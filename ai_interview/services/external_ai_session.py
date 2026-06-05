import json
import mimetypes
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..models import Candidate, ExternalAISession, JobConfiguration, TalentProfile
from .interview_types import DISCUSSION, INITIAL_INTERVIEW, normalize_interview_type
from .url_builder import build_interview_welcome_url
from .resume_parser import ResumeParser
from .session_manager import SessionManager
from .resume_async import RESUME_PARSE_PROCESSING, enqueue_external_resume_parse
from .assessment_groups import assign_assessment_group


MAX_RESUME_BYTES = 50 * 1024 * 1024
_ACTIVE_CALLBACK_THREADS = set()
_ACTIVE_CALLBACK_THREADS_LOCK = threading.Lock()


def bearer_token_valid(request) -> bool:
    expected = (getattr(settings, 'EXTERNAL_AI_SESSION_TOKEN', '') or '').strip()
    auth_header = (request.headers.get('Authorization') or '').strip()
    if not expected:
        return False
    prefix = 'Bearer '
    if not auth_header.startswith(prefix):
        return False
    return auth_header[len(prefix):].strip() == expected


def error_response(error_code: str, error_message: str) -> Dict[str, Any]:
    return {
        'success': False,
        'error_code': error_code,
        'error_message': error_message,
    }


def validate_create_payload(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    request_id = str(data.get('request_id') or '').strip()
    scene = str(data.get('scene') or '').strip()
    candidate = data.get('candidate') if isinstance(data.get('candidate'), dict) else {}
    job = data.get('job') if isinstance(data.get('job'), dict) else {}
    resume = data.get('resume') if isinstance(data.get('resume'), dict) else {}
    callback_url = str(data.get('callback_url') or '').strip()

    if not request_id:
        return error_response('INVALID_PARAM', 'request_id不能为空')
    if scene != 'ai_interview':
        return error_response('INVALID_PARAM', 'scene必须为ai_interview')
    if not candidate:
        return error_response('CANDIDATE_INFO_INVALID', 'candidate不能为空')
    if candidate.get('id') in (None, ''):
        return error_response('CANDIDATE_INFO_INVALID', 'candidate.id不能为空')
    if not str(candidate.get('name') or '').strip():
        return error_response('CANDIDATE_INFO_INVALID', 'candidate.name不能为空')
    if not str(candidate.get('email') or '').strip():
        return error_response('CANDIDATE_INFO_INVALID', 'candidate.email不能为空')
    if not job:
        return error_response('JOB_INFO_INVALID', 'job不能为空')
    if job.get('id') in (None, ''):
        return error_response('JOB_INFO_INVALID', 'job.id不能为空')
    if not str(job.get('title') or '').strip():
        return error_response('JOB_INFO_INVALID', 'job.title不能为空')
    if not str(job.get('description') or '').strip():
        return error_response('JOB_INFO_INVALID', 'job.description不能为空')
    raw_interview_type = data.get('interview_type') or job.get('interview_type')
    if raw_interview_type not in (None, '') and str(raw_interview_type).strip() not in {
        INITIAL_INTERVIEW,
        DISCUSSION,
        'discussion_interview',
        'talk',
        'meeting',
        '面谈',
    }:
        return error_response('INVALID_PARAM', 'interview_type无效')
    if not resume:
        return error_response('INVALID_PARAM', 'resume不能为空')
    if not str(resume.get('file_name') or '').strip():
        return error_response('INVALID_PARAM', 'resume.file_name不能为空')
    if not str(resume.get('file_url') or '').strip():
        return error_response('INVALID_PARAM', 'resume.file_url不能为空')
    if not _valid_http_url(str(resume.get('file_url') or '')):
        return error_response('INVALID_PARAM', 'resume.file_url必须为http或https地址')
    if not callback_url:
        return error_response('INVALID_PARAM', 'callback_url不能为空')
    if not _valid_http_url(callback_url):
        return error_response('INVALID_PARAM', 'callback_url必须为http或https地址')
    return None


def _valid_http_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme in ('http', 'https') and bool(parsed.netloc)


def _safe_filename(file_name: str) -> str:
    name = os.path.basename(file_name or 'resume')
    name = re.sub(r'[\\/:*?"<>|\r\n]+', '_', name).strip(' .')
    return name or 'resume'


def download_and_parse_resume(request_id: str, resume: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    file_name = _safe_filename(str(resume.get('file_name') or 'resume'))
    file_url = str(resume.get('file_url') or '').strip()
    suffix = Path(file_name).suffix
    if not suffix:
        guessed = mimetypes.guess_extension(mimetypes.guess_type(file_url)[0] or '')
        suffix = guessed or '.bin'
        file_name = f"{file_name}{suffix}"

    storage_dir = Path(getattr(settings, 'EXTERNAL_RESUME_STORAGE_DIR', '') or 'external_resumes')
    storage_dir.mkdir(parents=True, exist_ok=True)
    target_path = storage_dir / f"{_safe_filename(request_id)}_{int(time.time())}_{file_name}"

    req = urllib.request.Request(
        file_url,
        headers={
            'User-Agent': 'AIInterviewService/1.0',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
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
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as exc:
        if target_path.exists():
            target_path.unlink()
        raise RuntimeError(f'简历文件无法访问或下载失败: {exc}') from exc

    parsed = ResumeParser.parse_resume(str(target_path), file_name)
    if 'error' in parsed:
        raise RuntimeError(f"简历解析失败: {parsed.get('error')}")

    parsed['file_name'] = file_name
    parsed['file_url'] = file_url
    parsed['local_file_path'] = str(target_path)
    parsed['parsed_at'] = timezone.now().isoformat()
    return parsed, str(target_path)


def create_external_session(data: Dict[str, Any], request) -> Tuple[Dict[str, Any], int]:
    validation_error = validate_create_payload(data)
    if validation_error:
        return validation_error, 400

    request_id = str(data.get('request_id')).strip()
    existing = ExternalAISession.objects.filter(request_id=request_id).first()
    if existing:
        return existing.create_response or build_create_response(existing, request), 200

    candidate_data = data['candidate']
    job_data = data['job']
    resume_data = data['resume']
    interview_type = normalize_interview_type(data.get('interview_type') or job_data.get('interview_type'))
    job_level = str(job_data.get('level') or job_data.get('job_level') or '中级').strip() or '中级'
    recruitment_requirements = str(
        job_data.get('recruitment_requirements')
        or data.get('recruitment_requirements')
        or ''
    ).strip()

    candidate_name = str(candidate_data.get('name') or '').strip()
    candidate_email = str(candidate_data.get('email') or '').strip()
    candidate_phone = str(candidate_data.get('phone') or '').strip()
    candidate_id = f"{candidate_name}_{candidate_email}"

    expire_at = timezone.now() + timedelta(
        days=max(int(getattr(settings, 'EXTERNAL_AI_SESSION_EXPIRE_DAYS', 7) or 7), 1)
    )

    with transaction.atomic():
        config_id = JobConfiguration.generate_config_id()
        candidate, created = Candidate.objects.get_or_create(
            candidate_id=candidate_id,
            defaults={
                'name': candidate_name,
                'phone': candidate_phone,
                'email': candidate_email,
                'interview_id': config_id,
            },
        )
        if not created:
            candidate.name = candidate_name
            candidate.phone = candidate_phone
            candidate.email = candidate_email
            candidate.interview_id = config_id
            candidate.save(update_fields=['name', 'phone', 'email', 'interview_id'])

        resume_json = {
            'name': candidate_name,
            'phone': candidate_phone,
            'email': candidate_email,
            'external_resume': {
                'file_name': resume_data.get('file_name'),
                'file_url': resume_data.get('file_url'),
            }
        }

        job_config = JobConfiguration.objects.create(
            config_id=config_id,
            job_name=str(job_data.get('title') or '').strip(),
            job_description=str(job_data.get('description') or '').strip(),
            job_level=job_level,
            target_position=str(job_data.get('title') or '').strip(),
            interview_type=interview_type,
            recruitment_requirements=recruitment_requirements,
            hard_fields=[],
            custom_questions={},
            max_interviews=1,
            expire_at=expire_at,
            created_by='external',
            candidate=candidate,
            resume_json=resume_json,
            resume_parse_status=RESUME_PARSE_PROCESSING,
        )
        assign_assessment_group(job_config)

        external_session = ExternalAISession.objects.create(
            request_id=request_id,
            external_session_id=f"ai_{config_id}",
            scene='ai_interview',
            status='pending',
            external_candidate_id=str(candidate_data.get('id')),
            external_job_id=str(job_data.get('id')),
            callback_url=str(data.get('callback_url')).strip(),
            candidate=candidate,
            job_config=job_config,
            request_payload=data,
        )
        response = build_create_response(external_session, request)
        external_session.create_response = response
        external_session.save(update_fields=['create_response', 'updated_at'])
        transaction.on_commit(lambda: enqueue_external_resume_parse(external_session.external_session_id))

    return response, 201


def build_create_response(external_session: ExternalAISession, request) -> Dict[str, Any]:
    job_config = external_session.job_config
    if job_config:
        config_id = job_config.config_id
        expires_at = job_config.expire_at.isoformat() if job_config.expire_at else None
    else:
        config_id = (external_session.external_session_id or '').replace('ai_', '', 1)
        expires_at = None

    return {
        'success': True,
        'external_session_id': external_session.external_session_id,
        'session_url': build_interview_welcome_url(request, config_id),
        'expires_at': expires_at,
    }


def mark_external_session_in_progress(config_id: str) -> None:
    ExternalAISession.objects.filter(
        job_config__config_id=config_id,
        status='pending',
    ).update(status='in_progress', updated_at=timezone.now())


def trigger_completion_callback_for_profile(profile: TalentProfile) -> None:
    if not profile or not isinstance(profile.job_config, dict):
        return
    config_id = profile.job_config.get('config_id')
    if not config_id:
        return
    external_session = ExternalAISession.objects.filter(job_config__config_id=config_id).first()
    if not external_session or external_session.callback_received:
        return

    payload = build_result_payload(external_session, profile)
    external_session.status = payload.get('status') or 'completed'
    external_session.completed_at = timezone.now()
    external_session.result_payload = payload
    external_session.save(update_fields=['status', 'completed_at', 'result_payload', 'updated_at'])
    send_callback_async(external_session.id)


def build_result_payload(external_session: ExternalAISession, profile: TalentProfile) -> Dict[str, Any]:
    profile_data = profile.profile_data or {}
    qa_records = profile_data.get('qa_records') or SessionManager.build_qa_records(profile.dialogue_history or [])
    analyses = profile_data.get('report_analysis') or []

    score_values = [
        int(item.get('score') or 0)
        for item in analyses
        if isinstance(item, dict) and item.get('score') is not None
    ]
    score = round(sum(score_values) / len(score_values)) if score_values else round((profile.confidence_score or 0) * 100)
    score = max(0, min(100, int(score or 0)))

    dimensions = []
    for index, item in enumerate(analyses):
        if not isinstance(item, dict):
            continue
        quality = item.get('quality') if isinstance(item.get('quality'), dict) else {}
        detail_dimensions = quality.get('dimensions') if isinstance(quality.get('dimensions'), list) else []
        if detail_dimensions:
            for dim in detail_dimensions:
                if isinstance(dim, dict):
                    dimensions.append({
                        'name': str(dim.get('name') or item.get('round_type') or f"维度{index + 1}"),
                        'score': int(dim.get('score') or item.get('score') or 0),
                        'comment': str(dim.get('comment') or quality.get('reason') or ''),
                    })
        else:
            dimensions.append({
                'name': str(item.get('round_type') or f"第{item.get('round') or index + 1}轮"),
                'score': int(item.get('score') or 0),
                'comment': str(quality.get('reason') or item.get('answer') or ''),
            })

    if not dimensions:
        dimensions = [{
            'name': '综合表现',
            'score': score,
            'comment': '系统已完成面试记录，未生成逐维度分析。',
        }]

    summary_for_hr = _summary_for_hr(score, qa_records, analyses)
    summary_for_candidate = _summary_for_candidate(score)
    external_id = external_session.external_session_id
    transcript_url = _public_url(f"/api/external/ai-session/{external_id}/transcript/")
    report_url = _public_url(f"/api/external/ai-session/{external_id}/report/")
    return {
        'request_id': external_session.request_id,
        'external_session_id': external_id,
        'status': 'completed',
        'completed_at': timezone.now().isoformat(),
        'result': {
            'score': score,
            'summary_for_hr': summary_for_hr,
            'summary_for_candidate': summary_for_candidate,
            'dimensions': dimensions,
            'transcript_url': transcript_url,
            'report_url': report_url,
        },
    }


def _public_url(path: str) -> str:
    base_url = getattr(settings, 'EXTERNAL_PUBLIC_BASE_URL', '') or ''
    return f"{base_url}{path}" if base_url else path


def _summary_for_hr(score: int, qa_records: list, analyses: list) -> str:
    if analyses:
        reasons = []
        for item in analyses[:3]:
            quality = item.get('quality') if isinstance(item, dict) else {}
            reason = quality.get('reason') if isinstance(quality, dict) else ''
            if reason:
                reasons.append(str(reason))
        if reasons:
            return f"候选人综合得分{score}分。" + "；".join(reasons)
    return f"候选人已完成AI面试，共记录{len(qa_records or [])}轮问答，综合得分{score}分。"


def _summary_for_candidate(score: int) -> str:
    if score >= 80:
        return '你在本次AI面试中整体表现较好，建议继续补充更具体的项目结果和量化指标。'
    if score >= 60:
        return '你已完成本次AI面试，部分回答仍可进一步补充具体案例、职责和结果。'
    return '你已完成本次AI面试，建议后续回答时加强问题相关性、具体案例和结构化表达。'


def send_callback_async(external_session_id) -> None:
    session_key = str(external_session_id)
    with _ACTIVE_CALLBACK_THREADS_LOCK:
        if session_key in _ACTIVE_CALLBACK_THREADS:
            return
        _ACTIVE_CALLBACK_THREADS.add(session_key)

    thread = threading.Thread(
        target=_callback_retry_loop,
        args=(session_key,),
        daemon=True,
    )
    thread.start()


def _callback_retry_loop(external_session_pk: str) -> None:
    try:
        while True:
            external_session = ExternalAISession.objects.filter(id=external_session_pk).first()
            if not external_session or external_session.callback_received:
                return
            payload = external_session.result_payload
            if not payload:
                return

            received, error = _post_callback(external_session.callback_url, payload)
            external_session.callback_attempts += 1
            external_session.callback_last_at = timezone.now()
            external_session.callback_received = received
            external_session.callback_last_error = '' if received else error
            external_session.save(update_fields=[
                'callback_attempts',
                'callback_last_at',
                'callback_received',
                'callback_last_error',
                'updated_at',
            ])
            if received:
                return
            time.sleep(5)
    finally:
        with _ACTIVE_CALLBACK_THREADS_LOCK:
            _ACTIVE_CALLBACK_THREADS.discard(external_session_pk)


def _post_callback(callback_url: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        callback_url,
        data=body,
        headers={
            'Content-Type': 'application/json',
            'User-Agent': 'AIInterviewService/1.0',
        },
        method='POST',
    )
    timeout = float(getattr(settings, 'EXTERNAL_CALLBACK_TIMEOUT_SECONDS', 0.5) or 0.5)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read(1024 * 1024).decode('utf-8', errors='ignore')
            data = json.loads(raw) if raw else {}
            return bool(data.get('received') is True), '' if data.get('received') is True else raw
    except Exception as exc:
        return False, str(exc)
