import json
import logging
import os
import smtplib
import hashlib
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections, transaction
from django.utils import timezone

from ..models import Candidate, JobConfiguration
from .assessment_groups import assign_assessment_group
from .interview_types import DISCUSSION, INITIAL_INTERVIEW, normalize_interview_type
from .resume_async import (
    RESUME_PARSE_PROCESSING,
    MAX_RESUME_BYTES,
    enqueue_resume_parse,
    resume_storage_dir,
    safe_filename,
)
from .url_builder import build_interview_welcome_url


logger = logging.getLogger(__name__)

FEISHU_API_BASE = 'https://open.feishu.cn'
FEISHU_FORM_CACHE_PREFIX = 'feishu_resume_file:'
FEISHU_CHAT_FILE_CACHE_PREFIX = 'feishu_latest_resume_file:'
FEISHU_GLOBAL_FILE_CACHE_KEY = 'feishu_latest_resume_file:global'
FEISHU_ACTION_LOCK_PREFIX = 'feishu_action_lock:'
FEISHU_USER_NAME_CACHE_PREFIX = 'feishu_user_name:'
FEISHU_INTERVIEW_CARD_CACHE_PREFIX = 'feishu_interview_card:'
SUPPORTED_RESUME_EXTENSIONS = {'.pdf', '.doc', '.docx'}


def handle_feishu_callback(data: Dict[str, Any], request) -> Tuple[Dict[str, Any], int]:
    event_type = _extract_event_type(data)
    if event_type == 'im.message.receive_v1':
        return handle_message_event(data, request)

    action = _extract_action(data)
    action_value = _extract_action_value(action)
    action_name = str(action_value.get('action') or '').strip()
    if not action_name and _is_interview_submit_action(action):
        action_name = 'feishu_create_interview'
    elif not action_name and _is_discussion_submit_action(action):
        action_name = 'feishu_create_discussion'
    elif not action_name and _is_form_submit_action(action):
        action_name = 'feishu_create_interview'
    if action_name == 'feishu_show_interview_form':
        return handle_show_form_action(data, action, INITIAL_INTERVIEW)
    if action_name == 'feishu_show_discussion_form':
        return handle_show_form_action(data, action, DISCUSSION)
    if action_name == 'feishu_create_interview':
        return handle_create_interview_action(data, action, request, INITIAL_INTERVIEW)
    if action_name == 'feishu_create_discussion':
        return handle_create_interview_action(data, action, request, DISCUSSION)
    if action_name == 'feishu_send_interview_email':
        return handle_send_email_action(data, action)
    if action_name == 'feishu_cancel_resume':
        return {'code': 0, 'msg': '已取消'}, 200

    if event_type == 'card.action.trigger' or action:
        logger.warning(
            'Unhandled Feishu card action. action_name=%s action_keys=%s action_value=%s form_value=%s',
            action_name,
            list(action.keys()) if isinstance(action, dict) else [],
            action_value,
            _extract_form_value(action),
        )
    return {'code': 0, 'msg': '成功'}, 200


def handle_message_event(data: Dict[str, Any], request=None) -> Tuple[Dict[str, Any], int]:
    event = data.get('event') if isinstance(data.get('event'), dict) else {}
    message = event.get('message') if isinstance(event.get('message'), dict) else {}
    message_type = str(message.get('message_type') or '').strip()
    if message_type == 'text':
        message_id = str(message.get('message_id') or '').strip()
        if message_id and not _acquire_action_lock('text_message', data, {'message_id': message_id}, ttl=60 * 60 * 24):
            return {'code': 0, 'msg': '已处理'}, 200
        from .feishu_assistant import handle_text_message

        request_base = _request_base_url(request) if request is not None else ''
        return handle_text_message(data, request_base, send_message)
    if message_type != 'file':
        return {'code': 0, 'msg': 'ignored'}, 200

    content = _json_loads(message.get('content')) or {}
    file_key = str(content.get('file_key') or '').strip()
    file_name = str(content.get('file_name') or content.get('name') or '').strip()
    file_ext = Path(file_name).suffix.lower()
    chat_id = str(message.get('chat_id') or '').strip()
    message_id = str(message.get('message_id') or '').strip()
    creator_name = _extract_creator_name(data)

    if not file_key or not message_id or not chat_id:
        logger.warning('Feishu file message missing required fields: %s', message)
        return {'code': 0, 'msg': '缺少文件字段'}, 200
    if file_ext not in SUPPORTED_RESUME_EXTENSIONS:
        logger.info('Ignored Feishu file with unsupported extension: %s', file_name)
        return {'code': 0, 'msg': '不支持的文件类型'}, 200

    file_ref = {
        'file_key': file_key,
        'file_name': file_name,
        'message_id': message_id,
        'chat_id': chat_id,
        'creator_name': creator_name,
    }
    cache.set(_file_cache_key(file_key), file_ref, 60 * 60 * 24)
    cache.set(_chat_file_cache_key(chat_id), file_ref, 60 * 60 * 24)
    cache.set(FEISHU_GLOBAL_FILE_CACHE_KEY, file_ref, 60 * 60 * 24)
    if not _acquire_action_lock('file_message', data, {'file_key': file_key, 'message_id': message_id, 'chat_id': chat_id}, ttl=60 * 60 * 24):
        return {'code': 0, 'msg': '已接收'}, 200
    try:
        sent_result = send_message(chat_id, build_resume_form_card(file_ref))
        resume_card_message_id = _extract_sent_message_id(sent_result)
        if resume_card_message_id:
            file_ref['resume_card_message_id'] = resume_card_message_id
            cache.set(_file_cache_key(file_key), file_ref, 60 * 60 * 24)
            cache.set(_chat_file_cache_key(chat_id), file_ref, 60 * 60 * 24)
            cache.set(FEISHU_GLOBAL_FILE_CACHE_KEY, file_ref, 60 * 60 * 24)
            logger.info('Cached Feishu resume card message id. file_key=%s message_id=%s', file_key, resume_card_message_id)
    except Exception:
        logger.exception('Failed to send Feishu resume form card.')
    return {'code': 0, 'msg': '成功'}, 200


def handle_show_form_action(data: Dict[str, Any], action: Dict[str, Any], interview_type: str) -> Tuple[Dict[str, Any], int]:
    action_value = _extract_action_value(action)
    chat_id = _extract_chat_id(data, action_value, {})
    file_ref = _resolve_file_ref(action_value, chat_id)
    if not chat_id:
        chat_id = _extract_chat_id(data, action_value, file_ref)
    if not file_ref.get('file_key') or not chat_id:
        return _toast_response('error', '未找到简历文件，请重新上传'), 200
    locked_card = build_resume_form_locked_card(file_ref, interview_type)
    original_file_message_id = str(file_ref.get('message_id') or action_value.get('message_id') or '').strip()
    resume_card_message_id = _valid_card_message_id(
        file_ref.get('resume_card_message_id'),
        original_file_message_id,
    ) or _valid_card_message_id(
        _extract_card_message_id(data, action),
        original_file_message_id,
    )
    if not _acquire_action_lock('show_form', data, action_value, file_ref, interview_type, ttl=8 * 60):
        logger.info('Ignored duplicate Feishu show-form action. chat_id=%s file_key=%s type=%s', chat_id, file_ref.get('file_key'), interview_type)
        if resume_card_message_id:
            update_message_card(resume_card_message_id, locked_card)
        return _card_update_response(locked_card, 'success', '创建表单已打开'), 200

    updated_ref = {
        **file_ref,
        'selected_interview_type': normalize_interview_type(interview_type),
    }
    if resume_card_message_id:
        updated_ref['resume_card_message_id'] = resume_card_message_id
    file_key = str(updated_ref.get('file_key') or '').strip()
    if file_key:
        cache.set(_file_cache_key(file_key), updated_ref, 60 * 60 * 24)
    cache.set(_chat_file_cache_key(chat_id), updated_ref, 60 * 60 * 24)
    cache.set(FEISHU_GLOBAL_FILE_CACHE_KEY, updated_ref, 60 * 60 * 24)

    if resume_card_message_id:
        if not update_message_card(resume_card_message_id, locked_card):
            logger.warning('Feishu selected-type card update via message API failed. message_id=%s file_key=%s type=%s', resume_card_message_id, file_ref.get('file_key'), interview_type)
    else:
        logger.warning('Feishu resume card message id missing; cannot update selected-type card. file_key=%s type=%s', file_ref.get('file_key'), interview_type)
    _run_async(send_create_form_message, chat_id, updated_ref, interview_type)
    return _card_update_response(locked_card, 'success', '创建表单已打开'), 200


def handle_create_interview_action(data: Dict[str, Any], action: Dict[str, Any], request, interview_type_override: str = '') -> Tuple[Dict[str, Any], int]:
    action_value = _extract_action_value(action)
    chat_id = _extract_chat_id(data, action_value, {})
    file_ref = _resolve_file_ref(action_value, chat_id)
    if not chat_id:
        chat_id = _extract_chat_id(data, action_value, file_ref)
    if not file_ref.get('file_key') or not chat_id:
        logger.warning(
            'Feishu create action missing file reference. chat_id=%s action_value=%s file_ref=%s',
            chat_id,
            action_value,
            file_ref,
        )
        return _toast_response('error', '未找到简历文件，请重新上传'), 200

    form_value = _extract_form_value(action)
    candidate_name = str(form_value.get('candidate_name') or '').strip()
    candidate_email = str(form_value.get('candidate_email') or '').strip()
    interview_type = str(interview_type_override or form_value.get('interview_type') or action_value.get('interview_type') or '').strip()
    job_payload = _extract_job_payload(form_value, action_value)
    file_ref = {**file_ref, 'creator_name': file_ref.get('creator_name') or _extract_creator_name(data)}
    if not _acquire_action_lock('create_interview', data, action_value, file_ref, interview_type, form_value, job_payload, ttl=15 * 60):
        logger.info('Ignored duplicate Feishu create action. chat_id=%s file_key=%s type=%s', chat_id, file_ref.get('file_key'), interview_type)
        return {'code': 0, 'msg': '已处理'}, 200

    request_base = _request_base_url(request)
    original_file_message_id = str(file_ref.get('message_id') or action_value.get('message_id') or '').strip()
    action_message_id = _valid_card_message_id(
        _extract_card_message_id(data, action),
        original_file_message_id,
    ) or _valid_card_message_id(
        file_ref.get('create_form_message_id'),
        original_file_message_id,
    )
    processing_card = build_create_processing_card(file_ref, interview_type)
    if action_message_id:
        _run_async(update_message_card, action_message_id, processing_card)
    else:
        logger.warning('Feishu create-form message id missing; cannot update processing card. file_key=%s type=%s', file_ref.get('file_key'), interview_type)
    _run_async(
        create_interview_from_feishu_file_async,
        file_ref,
        request_base,
        chat_id,
        candidate_name,
        candidate_email,
        interview_type,
        job_payload,
        _extract_creator_label(data),
        file_ref.get('creator_name') or _extract_creator_name(data),
        action_message_id,
    )
    return _card_update_response(processing_card, 'success', '正在创建任务，请稍候'), 200


def handle_send_email_action(data: Dict[str, Any], action: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    action_value = _extract_action_value(action)
    chat_id = _extract_chat_id(data, action_value, {})
    email_to = str(action_value.get('candidate_email') or '').strip()
    interview_url = str(action_value.get('interview_url') or '').strip()
    candidate_name = str(action_value.get('candidate_name') or '').strip()
    job_title = str(action_value.get('job_title') or '').strip()
    config_id = str(action_value.get('config_id') or '').strip()

    if not email_to or email_to.endswith('@resume.local'):
        if chat_id:
            send_message(chat_id, build_error_card('候选人邮箱为空，无法发送面试邮件'))
        return {'code': 0, 'msg': '缺少邮箱'}, 200
    if not _acquire_action_lock(
        'send_email',
        data,
        {
            'config_id': action_value.get('config_id'),
            'candidate_email': email_to,
            'interview_url': interview_url,
        },
        ttl=15 * 60,
    ):
        logger.info('Ignored duplicate Feishu email action. chat_id=%s email=%s url=%s', chat_id, email_to, interview_url)
        return {'code': 0, 'msg': '已处理'}, 200

    try:
        send_interview_email(email_to, candidate_name, job_title, interview_url)
        logger.info('Feishu-triggered interview email sent. email=%s config_id=%s', email_to, config_id)
        return _card_update_response(build_email_sent_card(email_to), 'success', '邮件已发送'), 200
    except Exception as exc:
        logger.exception('Failed to send Feishu-triggered interview email.')
        error_card = build_error_card(f'邮件发送失败：{_localize_error(exc)}')
        return _card_update_response(error_card, 'error', '邮件发送失败'), 200


def create_interview_from_feishu_file_async(
    file_ref: Dict[str, Any],
    request_base: str,
    chat_id: str,
    candidate_name: str,
    candidate_email: str,
    interview_type: str,
    job_payload: Optional[Dict[str, Any]] = None,
    creator_label: str = 'feishu',
    creator_name: str = '',
    action_message_id: str = '',
) -> None:
    close_old_connections()
    try:
        result = create_interview_from_feishu_file(
            file_ref,
            request_base,
            candidate_name,
            candidate_email,
            interview_type,
            job_payload,
            creator_label,
            creator_name,
        )
        if action_message_id:
            cache.set(_interview_card_cache_key(result.get('config_id')), action_message_id, 60 * 60 * 24 * 7)
        created_card = build_interview_created_card(result, action_message_id)
        if not update_message_card(action_message_id, created_card):
            sent_result = send_message(chat_id, build_interview_created_card(result))
            sent_message_id = _extract_sent_message_id(sent_result)
            if sent_message_id:
                cache.set(_interview_card_cache_key(result.get('config_id')), sent_message_id, 60 * 60 * 24 * 7)
                update_message_card(sent_message_id, build_interview_created_card(result, sent_message_id))
    except Exception as exc:
        logger.exception('Failed to create interview from Feishu file.')
        try:
            error_card = build_error_card(f'创建失败：{_localize_error(exc)}')
            if not update_message_card(action_message_id, error_card):
                send_message(chat_id, error_card)
        except Exception:
            logger.exception('Failed to send Feishu error card.')
    finally:
        close_old_connections()


def send_interview_email_async(
    chat_id: str,
    email_to: str,
    candidate_name: str,
    job_title: str,
    interview_url: str,
    action_message_id: str = '',
) -> None:
    close_old_connections()
    try:
        send_interview_email(email_to, candidate_name, job_title, interview_url)
        if chat_id:
            sent_card = build_email_sent_card(email_to)
            logger.info('Feishu-triggered interview email sent. email=%s message_id=%s', email_to, action_message_id)
            if action_message_id and update_message_card(action_message_id, sent_card):
                return
            if chat_id:
                send_message(chat_id, sent_card)
    except Exception as exc:
        logger.exception('Failed to send Feishu-triggered interview email.')
        if chat_id:
            try:
                error_card = build_error_card(f'邮件发送失败：{_localize_error(exc)}')
                if not update_message_card(action_message_id, error_card):
                    send_message(chat_id, error_card)
            except Exception:
                logger.exception('Failed to send Feishu email error card.')
    finally:
        close_old_connections()


def create_interview_from_feishu_file(
    file_ref: Dict[str, Any],
    request_or_base,
    candidate_name: str = '',
    candidate_email: str = '',
    interview_type: str = '',
    job_payload: Optional[Dict[str, Any]] = None,
    creator_label: str = 'feishu',
    creator_name: str = '',
) -> Dict[str, Any]:
    config_id = JobConfiguration.generate_config_id()
    file_path, file_name = download_feishu_file(file_ref, config_id)
    base_name = os.path.splitext(file_name)[0] or 'resume'
    auto_candidate_name = not candidate_name
    auto_candidate_email = not candidate_email
    if auto_candidate_name:
        candidate_name = f'Pending-{base_name}'
    if auto_candidate_email:
        candidate_email = f'pending_{config_id}@resume.local'

    normalized_interview_type = normalize_interview_type(interview_type)
    job_name = os.getenv('FEISHU_DEFAULT_JOB_NAME', 'AI应用工程师')
    job_description = os.getenv('FEISHU_DEFAULT_JOB_DESCRIPTION', '由飞书简历文件创建的面试任务')
    job_level = os.getenv('FEISHU_DEFAULT_JOB_LEVEL', '中级')
    days_valid = max(int(os.getenv('FEISHU_INTERVIEW_VALID_DAYS', '3') or 3), 1)
    job_payload = job_payload or {}
    job_external_id = ''
    job_name = str(job_payload.get('job_name') or os.getenv('FEISHU_DEFAULT_JOB_NAME', 'AI应用工程师')).strip()
    job_description = str(job_payload.get('job_description') or os.getenv('FEISHU_DEFAULT_JOB_DESCRIPTION', '由飞书简历文件创建的面试任务')).strip()
    job_level = str(job_payload.get('job_level') or os.getenv('FEISHU_DEFAULT_JOB_LEVEL', '中级')).strip()
    recruitment_requirements = str(job_payload.get('recruitment_requirements') or '').strip()
    days_valid = max(_safe_int(job_payload.get('days_valid'), days_valid), 1)
    expire_at = timezone.now() + timedelta(days=days_valid)

    with transaction.atomic():
        candidate_id = f'{candidate_name}_{candidate_email}_{config_id}'
        candidate = Candidate.objects.create(
            candidate_id=candidate_id,
            name=candidate_name,
            email=candidate_email,
            interview_id=config_id,
        )
        job_config = JobConfiguration.objects.create(
            config_id=config_id,
            job_name=job_name,
            job_description=job_description,
            job_level=job_level,
            target_position=job_name,
            interview_type=normalized_interview_type,
            recruitment_requirements=recruitment_requirements,
            hard_fields=[] if normalized_interview_type == DISCUSSION else [],
            custom_questions=[] if normalized_interview_type == DISCUSSION else {},
            max_interviews=1,
            expire_at=expire_at,
            created_by=creator_label or (f'feishu:{job_external_id}' if job_external_id else 'feishu'),
            candidate=candidate,
            resume_json={
                'feishu_creator_name': creator_name or file_ref.get('creator_name') or '',
                'feishu_creator_id': _extract_feishu_id_from_label(creator_label),
            },
            resume_parse_status=RESUME_PARSE_PROCESSING,
            resume_source_path=file_path,
        )
        if not (auto_candidate_name or auto_candidate_email):
            assign_assessment_group(job_config)

        extra_resume_data = {
            'name': candidate_name,
            'email': candidate_email,
            'file_name': file_name,
            'local_file_path': file_path,
            'feishu_file_key': file_ref.get('file_key'),
            'feishu_message_id': file_ref.get('message_id'),
            'feishu_job_name': job_name,
            'feishu_creator_name': creator_name or file_ref.get('creator_name') or '',
            'feishu_creator_id': _extract_feishu_id_from_label(creator_label),
            'recruitment_requirements': recruitment_requirements,
            '_auto_candidate_name': auto_candidate_name,
            '_auto_candidate_email': auto_candidate_email,
        }
        transaction.on_commit(lambda: enqueue_resume_parse(config_id, file_path, file_name, extra_resume_data))

    return {
        'config_id': config_id,
        'candidate_name': '' if auto_candidate_name else candidate_name,
        'candidate_email': '' if auto_candidate_email else candidate_email,
        'job_title': job_name,
        'interview_type': normalized_interview_type,
        'interview_url': build_feishu_interview_url(request_or_base, config_id),
        'file_name': file_name,
    }


def download_feishu_file(file_ref: Dict[str, Any], owner_key: str) -> Tuple[str, str]:
    token = get_tenant_access_token()
    message_id = str(file_ref.get('message_id') or '').strip()
    file_key = str(file_ref.get('file_key') or '').strip()
    file_name = safe_filename(str(file_ref.get('file_name') or 'resume'))
    if not message_id or not file_key:
        raise ValueError('missing Feishu message_id or file_key')

    url = (
        f'{FEISHU_API_BASE}/open-apis/im/v1/messages/'
        f'{urllib.parse.quote(message_id, safe="")}/resources/{urllib.parse.quote(file_key, safe="")}'
        f'?{urllib.parse.urlencode({"type": "file"})}'
    )
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json; charset=utf-8',
    }
    req = urllib.request.Request(url, headers=headers, method='GET')
    target_path = resume_storage_dir() / f'{safe_filename(owner_key)}_{int(time.time())}_{file_name}'
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            total = 0
            with target_path.open('wb') as fh:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_RESUME_BYTES:
                        raise ValueError('resume file exceeds 50MB')
                    fh.write(chunk)
    except urllib.error.HTTPError as exc:
        if target_path.exists():
            target_path.unlink()
        error_body = _read_http_error_body(exc)
        logger.warning(
            'Feishu resume download HTTP error. status=%s reason=%s message_id=%s file_key=%s body=%s',
            exc.code,
            exc.reason,
            message_id,
            file_key,
            error_body[:1000],
        )
        detail = f'HTTP {exc.code} {exc.reason}'
        if error_body:
            detail = f'{detail}: {error_body[:500]}'
        raise RuntimeError(f'Feishu resume download failed: {detail}') from exc
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as exc:
        if target_path.exists():
            target_path.unlink()
        raise RuntimeError(f'Feishu resume download failed: {exc}') from exc
    return str(target_path), file_name


def _read_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode('utf-8', errors='replace').strip()
    except Exception:
        return ''


def send_interview_email(email_to: str, candidate_name: str, job_title: str, interview_url: str) -> None:
    from email.header import Header
    from email.mime.image import MIMEImage
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.utils import formataddr
    from ..views.email import (
        EMAIL_LOGO_FILENAME,
        build_interview_email_html,
        build_interview_email_text,
        get_email_logo_path,
        send_message_via_smtp,
    )

    smtp_server = os.getenv('SMTP_SERVER', 'smtp.qq.com')
    smtp_username = os.getenv('SMTP_USERNAME', '2601413168@qq.com')
    smtp_password = os.getenv('SMTP_PASSWORD', 'vybtlcjfbrxrecbj')
    logo_path = get_email_logo_path()
    logo_cid = 'email-logo' if os.path.exists(logo_path) else None

    msg = MIMEMultipart('related')
    msg['From'] = formataddr((str(Header('AI面试系统', 'utf-8')), smtp_username))
    msg['To'] = email_to
    msg['Subject'] = Header('AI面试邀请', 'utf-8')

    alternative = MIMEMultipart('alternative')
    alternative.attach(MIMEText(build_interview_email_text(candidate_name, job_title, interview_url), 'plain', 'utf-8'))
    alternative.attach(MIMEText(build_interview_email_html(candidate_name, job_title, interview_url, logo_cid), 'html', 'utf-8'))
    msg.attach(alternative)

    if logo_cid:
        with open(logo_path, 'rb') as logo_file:
            logo = MIMEImage(logo_file.read())
        logo.add_header('Content-ID', f'<{logo_cid}>')
        logo.add_header('Content-Disposition', 'inline', filename=EMAIL_LOGO_FILENAME)
        msg.attach(logo)

    send_message_via_smtp(smtplib, smtp_server, smtp_username, smtp_password, msg)


def build_resume_form_card(file_ref: Dict[str, Any]) -> Dict[str, Any]:
    file_name = file_ref.get('file_name') or '简历文件'
    action_value = {
        'file_key': file_ref.get('file_key'),
        'file_name': file_name,
        'message_id': file_ref.get('message_id'),
        'chat_id': file_ref.get('chat_id'),
    }
    return {
        'schema': '2.0',
        'config': {'wide_screen_mode': True, 'update_multi': True},
        'header': {
            'title': {'content': '简历接收确认', 'tag': 'plain_text'},
            'template': 'blue',
        },
        'body': {
            'elements': [
                {'tag': 'markdown', 'content': f'已收到文件：**{file_name}**\n请选择要创建的任务类型。'},
                {
                    'tag': 'button',
                    'text': {'content': '创建面试', 'tag': 'plain_text'},
                    'type': 'primary',
                    'value': {**action_value, 'action': 'feishu_show_interview_form'},
                },
                {
                    'tag': 'button',
                    'text': {'content': '创建面谈', 'tag': 'plain_text'},
                    'type': 'default',
                    'value': {**action_value, 'action': 'feishu_show_discussion_form'},
                },
            ],
        },
    }


def build_resume_form_locked_card(file_ref: Dict[str, Any], interview_type: str) -> Dict[str, Any]:
    file_name = file_ref.get('file_name') or '简历文件'
    is_discussion = normalize_interview_type(interview_type) == DISCUSSION
    task_label = '面谈' if is_discussion else '面试'
    return {
        'schema': '2.0',
        'config': {'wide_screen_mode': True, 'update_multi': True},
        'header': {
            'title': {'content': '已选择任务类型', 'tag': 'plain_text'},
            'template': 'green',
        },
        'body': {
            'elements': [
                {'tag': 'markdown', 'content': f'已收到文件：**{file_name}**\n已选择创建{task_label}，请在新表单中填写信息。'},
            ],
        },
    }


def build_create_form_card(file_ref: Dict[str, Any], interview_type: str) -> Dict[str, Any]:
    normalized_type = normalize_interview_type(interview_type)
    is_discussion = normalized_type == DISCUSSION
    file_name = file_ref.get('file_name') or '简历文件'
    action_value = {
        'action': 'feishu_create_discussion' if is_discussion else 'feishu_create_interview',
        'interview_type': normalized_type,
        'file_key': file_ref.get('file_key'),
        'file_name': file_name,
        'message_id': file_ref.get('message_id'),
        'chat_id': file_ref.get('chat_id'),
    }
    fields = [
        ('姓名', 'candidate_name', '可选'),
        ('邮箱', 'candidate_email', '可选'),
        ('岗位名称', 'job_name', '例如 AI应用工程师 / 半导体销售'),
        ('职级', 'job_level', '例如 初级 / 中级 / 高级'),
        ('岗位JD', 'job_description', '请输入岗位描述或 JD'),
    ]
    if is_discussion:
        fields.append(('面谈特殊需求', 'recruitment_requirements', '请输入面谈关注点或特殊要求'))

    form_elements = []
    for label, name, placeholder in fields:
        form_elements.append({'tag': 'markdown', 'content': f'**{label}**'})
        form_elements.append({
            'tag': 'input',
            'name': name,
            'placeholder': {'tag': 'plain_text', 'content': placeholder},
            'required': False,
        })
    form_elements.append({
        'tag': 'button',
        'name': 'discussion_submit' if is_discussion else 'interview_submit',
        'form_action_type': 'submit',
        'text': {'content': '创建面谈' if is_discussion else '创建面试', 'tag': 'plain_text'},
        'type': 'primary',
        'value': action_value,
    })

    return {
        'schema': '2.0',
        'config': {'wide_screen_mode': True, 'update_multi': True},
        'header': {
            'title': {'content': '创建面谈' if is_discussion else '创建面试', 'tag': 'plain_text'},
            'template': 'purple' if is_discussion else 'blue',
        },
        'body': {
            'elements': [
                {'tag': 'markdown', 'content': f'简历文件：**{file_name}**'},
                {'tag': 'form', 'name': 'feishu_create_form', 'elements': form_elements},
            ],
        },
    }


def build_create_processing_card(file_ref: Dict[str, Any], interview_type: str) -> Dict[str, Any]:
    normalized_type = normalize_interview_type(interview_type)
    is_discussion = normalized_type == DISCUSSION
    file_name = file_ref.get('file_name') or '简历文件'
    return {
        'schema': '2.0',
        'config': {'wide_screen_mode': True, 'update_multi': True},
        'header': {
            'title': {'content': '正在创建面谈' if is_discussion else '正在创建面试', 'tag': 'plain_text'},
            'template': 'yellow',
        },
        'body': {
            'elements': [
                {'tag': 'markdown', 'content': f'简历文件：**{file_name}**\n任务已提交，系统正在下载并解析简历，请稍候。'},
            ],
        },
    }


def build_interview_created_card(result: Dict[str, Any], card_message_id: str = '') -> Dict[str, Any]:
    interview_url = result.get('interview_url') or ''
    candidate_email = result.get('candidate_email') or ''
    action_value = {
        'action': 'feishu_send_interview_email',
        'config_id': result.get('config_id'),
        'candidate_name': result.get('candidate_name') or '',
        'candidate_email': candidate_email,
        'job_title': result.get('job_title') or '',
        'interview_url': interview_url,
    }
    if card_message_id:
        action_value['card_message_id'] = card_message_id
    return {
        'schema': '2.0',
        'config': {'wide_screen_mode': True, 'update_multi': True},
        'header': {
            'title': {'content': '面试链接已创建', 'tag': 'plain_text'},
            'template': 'green',
        },
        'body': {'elements': [
            {'tag': 'markdown', 'content': f'面试链接：[{interview_url}]({interview_url})\n邮箱：{candidate_email or "未填写"}'},
            {
                'tag': 'button',
                'text': {'content': '点我发送面试邮件', 'tag': 'plain_text'},
                'type': 'primary',
                'value': action_value,
            },
        ]},
    }


def build_email_sent_card(email_to: str) -> Dict[str, Any]:
    return {
        'schema': '2.0',
        'config': {'wide_screen_mode': True, 'update_multi': True},
        'header': {'title': {'content': '邮件已发送', 'tag': 'plain_text'}, 'template': 'green'},
        'body': {'elements': [{'tag': 'markdown', 'content': f'面试邀请已发送至：{email_to}'}]},
    }


def build_email_sending_card(email_to: str, interview_url: str) -> Dict[str, Any]:
    return {
        'schema': '2.0',
        'config': {'wide_screen_mode': True, 'update_multi': True},
        'header': {'title': {'content': '正在发送邮件', 'tag': 'plain_text'}, 'template': 'yellow'},
        'body': {'elements': [{'tag': 'markdown', 'content': f'正在向 **{email_to}** 发送面试邀请。\n面试链接：[{interview_url}]({interview_url})'}]},
    }


def build_error_card(message: str) -> Dict[str, Any]:
    return {
        'schema': '2.0',
        'config': {'wide_screen_mode': True, 'update_multi': True},
        'header': {'title': {'content': '处理失败', 'tag': 'plain_text'}, 'template': 'red'},
        'body': {'elements': [{'tag': 'markdown', 'content': message}]},
    }

def send_message(chat_id: str, card: Dict[str, Any]) -> Dict[str, Any]:
    token = get_tenant_access_token()
    payload = {
        'receive_id': chat_id,
        'msg_type': 'interactive',
        'content': json.dumps(card, ensure_ascii=False),
    }
    return feishu_request(
        'POST',
        '/open-apis/im/v1/messages?receive_id_type=chat_id',
        payload,
        token,
    )


def send_create_form_message(chat_id: str, file_ref: Dict[str, Any], interview_type: str) -> None:
    try:
        sent_result = send_message(chat_id, build_create_form_card(file_ref, interview_type))
        create_form_message_id = _extract_sent_message_id(sent_result)
        file_key = str(file_ref.get('file_key') or '').strip()
        if create_form_message_id and file_key:
            updated_ref = {**file_ref, 'create_form_message_id': create_form_message_id}
            cache.set(_file_cache_key(file_key), updated_ref, 60 * 60 * 24)
            cache.set(_chat_file_cache_key(chat_id), updated_ref, 60 * 60 * 24)
            cache.set(FEISHU_GLOBAL_FILE_CACHE_KEY, updated_ref, 60 * 60 * 24)
            logger.info('Cached Feishu create-form card message id. file_key=%s message_id=%s', file_key, create_form_message_id)
    except Exception:
        logger.exception('Failed to send Feishu create form card.')


def update_message_card(message_id: str, card: Dict[str, Any]) -> bool:
    message_id = str(message_id or '').strip()
    if not message_id:
        return False
    try:
        token = get_tenant_access_token()
        feishu_request(
            'PATCH',
            f'/open-apis/im/v1/messages/{urllib.parse.quote(message_id, safe="")}',
            {
                'msg_type': 'interactive',
                'content': json.dumps(card, ensure_ascii=False),
            },
            token,
        )
        return True
    except Exception:
        logger.exception('Failed to update Feishu card. message_id=%s', message_id)
        return False


def _extract_sent_message_id(result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return ''
    data = result.get('data') if isinstance(result.get('data'), dict) else {}
    candidates = [
        data.get('message_id'),
        data.get('open_message_id'),
        data.get('msg_id'),
        result.get('message_id'),
        result.get('open_message_id'),
        result.get('msg_id'),
    ]
    for value in candidates:
        message_id = str(value or '').strip()
        if message_id:
            return message_id
    return _find_first_nested_value(result, {'open_message_id', 'message_id', 'msg_id'})


def get_tenant_access_token() -> str:
    cached = cache.get('feishu_tenant_access_token')
    if cached:
        return cached
    app_id = (getattr(settings, 'FEISHU_APP_ID', '') or '').strip()
    app_secret = (getattr(settings, 'FEISHU_APP_SECRET', '') or '').strip()
    if not app_id or not app_secret:
        raise RuntimeError('FEISHU_APP_ID or FEISHU_APP_SECRET is not configured')
    result = feishu_request(
        'POST',
        '/open-apis/auth/v3/tenant_access_token/internal',
        {'app_id': app_id, 'app_secret': app_secret},
        token='',
    )
    token = result.get('tenant_access_token')
    if not token:
        raise RuntimeError(f'Feishu tenant_access_token missing: {result}')
    expire = int(result.get('expire') or 7200)
    cache.set('feishu_tenant_access_token', token, max(expire - 300, 60))
    return token


def feishu_request(method: str, path: str, payload: Optional[Dict[str, Any]], token: str) -> Dict[str, Any]:
    url = f'{FEISHU_API_BASE}{path}'
    body = json.dumps(payload or {}, ensure_ascii=False).encode('utf-8') if payload is not None else None
    headers = {'Content-Type': 'application/json; charset=utf-8'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            response_body = response.read().decode('utf-8')
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'Feishu API HTTP {exc.code}: {error_body}') from exc
    result = _json_loads(response_body) or {}
    if not result and response_body.strip():
        raise RuntimeError(f'Feishu API returned non-JSON response: {response_body[:500]}')
    code = result.get('code', 0)
    if code not in (0, None):
        raise RuntimeError(f'Feishu API error: {result}')
    return result


def get_feishu_user_display_name(open_id: str) -> str:
    open_id = str(open_id or '').strip()
    if not open_id:
        return ''
    cache_key = f'{FEISHU_USER_NAME_CACHE_PREFIX}{open_id}'
    cached = cache.get(cache_key)
    if cached is not None:
        return str(cached or '')
    try:
        token = get_tenant_access_token()
        result = feishu_request(
            'POST',
            '/open-apis/contact/v3/users/basic_batch?user_id_type=open_id',
            {'user_ids': [open_id]},
            token,
        )
        user = result.get('data') if isinstance(result.get('data'), dict) else {}
        users = user.get('users') if isinstance(user.get('users'), list) else []
        user_info = users[0] if users and isinstance(users[0], dict) else {}
        name = _normalize_feishu_name(user_info.get('i18n_name')) or str(user_info.get('name') or '').strip()
        cache.set(cache_key, name, 60 * 60 * 24)
        return name
    except Exception as exc:
        logger.warning('Failed to fetch Feishu user display name. open_id=%s error=%s', open_id, exc)
        cache.set(cache_key, '', 60 * 10)
        return ''


def _extract_event_type(data: Dict[str, Any]) -> str:
    header = data.get('header') if isinstance(data.get('header'), dict) else {}
    event = data.get('event') if isinstance(data.get('event'), dict) else {}
    return str(header.get('event_type') or data.get('event_type') or event.get('type') or '').strip()


def _extract_action(data: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(data.get('action'), dict):
        return data['action']
    event = data.get('event') if isinstance(data.get('event'), dict) else {}
    if isinstance(event.get('action'), dict):
        return event['action']
    if isinstance(data.get('card'), dict):
        card_action = data['card'].get('action')
        if isinstance(card_action, dict):
            return card_action
    return {}


def _extract_action_value(action: Dict[str, Any]) -> Dict[str, Any]:
    value = action.get('value')
    value_dict = _ensure_dict(value)
    if value_dict:
        return value_dict
    option = action.get('option')
    option_dict = _ensure_dict(option)
    if option_dict:
        return option_dict
    return {}


def _extract_form_value(action: Dict[str, Any]) -> Dict[str, Any]:
    form_value = action.get('form_value')
    if isinstance(form_value, dict):
        return form_value
    input_values = action.get('input_values')
    if isinstance(input_values, dict):
        return input_values
    form_value = action.get('formValues')
    if isinstance(form_value, dict):
        return form_value
    input_values = action.get('inputValues')
    if isinstance(input_values, dict):
        return input_values
    value = action.get('value')
    value_dict = _ensure_dict(value)
    if value_dict:
        nested = value_dict.get('form_value')
        if isinstance(nested, dict):
            return nested
        nested = value_dict.get('input_values')
        if isinstance(nested, dict):
            return nested
        nested = value_dict.get('formValues')
        if isinstance(nested, dict):
            return nested
        nested = value_dict.get('inputValues')
        if isinstance(nested, dict):
            return nested
    return {}


def _extract_chat_id(data: Dict[str, Any], action_value: Dict[str, Any], file_ref: Dict[str, Any]) -> str:
    if action_value.get('chat_id'):
        return str(action_value.get('chat_id')).strip()
    if file_ref.get('chat_id'):
        return str(file_ref.get('chat_id')).strip()
    event = data.get('event') if isinstance(data.get('event'), dict) else {}
    context = data.get('context') if isinstance(data.get('context'), dict) else {}
    if context.get('open_chat_id'):
        return str(context.get('open_chat_id')).strip()
    if context.get('chat_id'):
        return str(context.get('chat_id')).strip()
    if event.get('open_chat_id'):
        return str(event.get('open_chat_id')).strip()
    if event.get('chat_id'):
        return str(event.get('chat_id')).strip()
    operator = event.get('operator') if isinstance(event.get('operator'), dict) else {}
    if operator.get('open_chat_id'):
        return str(operator.get('open_chat_id')).strip()
    return ''


def _extract_card_message_id(data: Dict[str, Any], action: Dict[str, Any]) -> str:
    candidates = []
    event = data.get('event') if isinstance(data.get('event'), dict) else {}
    context = data.get('context') if isinstance(data.get('context'), dict) else {}
    event_context = event.get('context') if isinstance(event.get('context'), dict) else {}
    action = action if isinstance(action, dict) else {}
    candidates.extend([
        data.get('open_message_id'),
        data.get('message_id'),
        data.get('msg_id'),
        event.get('open_message_id'),
        event.get('message_id'),
        event.get('msg_id'),
        context.get('open_message_id'),
        context.get('message_id'),
        context.get('msg_id'),
        event_context.get('open_message_id'),
        event_context.get('message_id'),
        event_context.get('msg_id'),
        action.get('open_message_id'),
        action.get('message_id'),
        action.get('msg_id'),
    ])
    for value in candidates:
        message_id = str(value or '').strip()
        if message_id:
            return message_id
    return ''


def _valid_card_message_id(value: Any, *invalid_values: Any) -> str:
    message_id = str(value or '').strip()
    if not message_id:
        return ''
    invalid_ids = {str(item or '').strip() for item in invalid_values if str(item or '').strip()}
    return '' if message_id in invalid_ids else message_id


def _find_first_nested_value(value: Any, keys: set) -> str:
    if isinstance(value, dict):
        for key in keys:
            found = str(value.get(key) or '').strip()
            if found:
                return found
        for item in value.values():
            found = _find_first_nested_value(item, keys)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_first_nested_value(item, keys)
            if found:
                return found
    return ''


def _file_cache_key(file_key: str) -> str:
    return f'{FEISHU_FORM_CACHE_PREFIX}{file_key}'


def _chat_file_cache_key(chat_id: str) -> str:
    return f'{FEISHU_CHAT_FILE_CACHE_PREFIX}{chat_id}'


def _interview_card_cache_key(config_id: Any) -> str:
    return f'{FEISHU_INTERVIEW_CARD_CACHE_PREFIX}{str(config_id or "").strip()}'


def _resolve_file_ref(action_value: Dict[str, Any], chat_id: str) -> Dict[str, Any]:
    file_key = str(action_value.get('file_key') or '').strip()
    file_ref = (cache.get(_file_cache_key(file_key)) if file_key else None) or action_value
    if (not file_ref or not file_ref.get('file_key')) and chat_id:
        file_ref = cache.get(_chat_file_cache_key(chat_id)) or {}
    if not file_ref or not file_ref.get('file_key'):
        file_ref = cache.get(FEISHU_GLOBAL_FILE_CACHE_KEY) or {}
    return file_ref or {}


def _is_interview_submit_action(action: Dict[str, Any]) -> bool:
    return isinstance(action, dict) and str(action.get('name') or '').strip() == 'interview_submit'


def _is_discussion_submit_action(action: Dict[str, Any]) -> bool:
    return isinstance(action, dict) and str(action.get('name') or '').strip() == 'discussion_submit'


def _is_form_submit_action(action: Dict[str, Any]) -> bool:
    if not isinstance(action, dict):
        return False
    name = str(action.get('name') or '').strip()
    tag = str(action.get('tag') or '').strip()
    return name == 'submit' or tag == 'button' and bool(_extract_form_value(action))


def _extract_job_payload(form_value: Dict[str, Any], action_value: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'job_id': '',
        'job_name': str(
            form_value.get('job_name')
            or action_value.get('job_name')
            or form_value.get('job_id')
            or action_value.get('job_id')
            or ''
        ).strip(),
        'job_description': str(form_value.get('job_description') or action_value.get('job_description') or '').strip(),
        'job_level': str(form_value.get('job_level') or action_value.get('job_level') or '').strip(),
        'days_valid': str(form_value.get('days_valid') or action_value.get('days_valid') or '').strip(),
        'recruitment_requirements': str(
            form_value.get('recruitment_requirements')
            or action_value.get('recruitment_requirements')
            or ''
        ).strip(),
    }


def _acquire_action_lock(action_name: str, data: Dict[str, Any], *parts: Any, ttl: int = 600) -> bool:
    del data
    key_payload = {
        'action': action_name,
        'parts': _stable_lock_parts(parts),
    }
    key_source = json.dumps(key_payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(key_source.encode('utf-8')).hexdigest()
    return cache.add(f'{FEISHU_ACTION_LOCK_PREFIX}{action_name}:{digest}', 1, ttl)


def _stable_lock_parts(value: Any) -> Any:
    if isinstance(value, dict):
        stable = {}
        for key, item in value.items():
            if key in {'creator_name'}:
                continue
            if key in {
                'file_key',
                'file_name',
                'message_id',
                'chat_id',
                'interview_type',
                'candidate_name',
                'candidate_email',
                'job_name',
                'job_description',
                'job_level',
                'days_valid',
                'recruitment_requirements',
                'config_id',
                'interview_url',
            }:
                stable[key] = _stable_lock_parts(item)
        if stable:
            return stable
        return {key: _stable_lock_parts(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_stable_lock_parts(item) for item in value]
    return str(value or '').strip()


def _extract_event_id(data: Dict[str, Any]) -> str:
    header = data.get('header') if isinstance(data.get('header'), dict) else {}
    event = data.get('event') if isinstance(data.get('event'), dict) else {}
    return str(
        header.get('event_id')
        or header.get('event_uuid')
        or data.get('uuid')
        or data.get('event_id')
        or event.get('event_id')
        or ''
    ).strip()


def _extract_feishu_id_from_label(value: str) -> str:
    value = str(value or '').strip()
    if value.startswith('feishu:'):
        return value.split(':', 1)[1].strip()
    return ''


def _extract_creator_name(data: Dict[str, Any]) -> str:
    event = data.get('event') if isinstance(data.get('event'), dict) else {}
    operator = event.get('operator') if isinstance(event.get('operator'), dict) else {}
    sender = event.get('sender') if isinstance(event.get('sender'), dict) else {}
    context = data.get('context') if isinstance(data.get('context'), dict) else {}
    candidates = [
        operator.get('name'),
        operator.get('nickname'),
        operator.get('user_name'),
        event.get('operator_name'),
        event.get('user_name'),
        sender.get('sender_name'),
        sender.get('name'),
        context.get('operator_name'),
        context.get('user_name'),
    ]
    for value in candidates:
        name = _normalize_feishu_name(value)
        if name:
            return name
    return get_feishu_user_display_name(_extract_creator_open_id(data))


def _extract_creator_open_id(data: Dict[str, Any]) -> str:
    event = data.get('event') if isinstance(data.get('event'), dict) else {}
    operator = event.get('operator') if isinstance(event.get('operator'), dict) else {}
    operator_id = operator.get('operator_id') if isinstance(operator.get('operator_id'), dict) else {}
    sender = event.get('sender') if isinstance(event.get('sender'), dict) else {}
    sender_id = sender.get('sender_id') if isinstance(sender.get('sender_id'), dict) else {}
    candidates = [
        operator_id.get('open_id'),
        operator.get('open_id'),
        sender_id.get('open_id'),
        sender.get('open_id'),
        event.get('open_id'),
        data.get('open_id'),
    ]
    for value in candidates:
        open_id = str(value or '').strip()
        if open_id:
            return open_id
    return ''


def _normalize_feishu_name(value: Any) -> str:
    if isinstance(value, dict):
        for key in ('zh_cn', 'name', 'cn', 'en_us', 'en'):
            name = str(value.get(key) or '').strip()
            if name:
                return name
        return ''
    return str(value or '').strip()


def _localize_error(exc: Exception) -> str:
    message = str(exc)
    replacements = {
        'Feishu resume download failed': '飞书简历下载失败',
        'missing Feishu message_id or file_key': '缺少飞书文件标识',
        'resume file exceeds 50MB': '简历文件超过 50MB',
        'FEISHU_APP_ID or FEISHU_APP_SECRET is not configured': '飞书应用配置不完整',
        'Feishu tenant_access_token missing': '飞书访问令牌获取失败',
        'Feishu API HTTP': '飞书接口请求失败',
        'Feishu API error': '飞书接口返回错误',
    }
    for source, target in replacements.items():
        message = message.replace(source, target)
    return message


def _extract_creator_label(data: Dict[str, Any]) -> str:
    open_id = _extract_creator_open_id(data)
    return f'feishu:{open_id}' if open_id else 'feishu'


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _json_loads(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _ensure_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return _json_loads(value)
    return {}


def build_feishu_interview_url(request_or_base, config_id: str) -> str:
    if isinstance(request_or_base, str):
        return f'{request_or_base}/api/ai-interview/interview/welcome/?config_id={urllib.parse.quote(config_id)}'
    return build_interview_welcome_url(request_or_base, config_id)


def _request_base_url(request) -> str:
    public_base = (
        getattr(settings, 'AI_INTERVIEW_PUBLIC_BASE_URL', '')
        or getattr(settings, 'EXTERNAL_PUBLIC_BASE_URL', '')
        or ''
    ).strip().rstrip('/')
    if public_base:
        return public_base
    return f'{request.scheme}://{request.get_host()}'.rstrip('/')


def _run_async(target, *args) -> None:
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()


def _toast_response(toast_type: str, content: str) -> Dict[str, Any]:
    return {'toast': {'type': toast_type, 'content': content}}


def _card_update_response(card: Dict[str, Any], toast_type: str = 'success', content: str = '') -> Dict[str, Any]:
    response = {'card': {'type': 'raw', 'data': card}}
    if content:
        response['toast'] = {'type': toast_type, 'content': content}
    return response




