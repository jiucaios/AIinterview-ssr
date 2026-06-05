import mimetypes
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from ..models import ExternalAISession, JobConfiguration
from .job_match import enqueue_job_match_analysis
from .assessment_groups import assign_assessment_group
from .resume_parser import ResumeParser


RESUME_PARSE_PENDING = 'pending'
RESUME_PARSE_PROCESSING = 'processing'
RESUME_PARSE_COMPLETED = 'completed'
RESUME_PARSE_FAILED = 'failed'
MAX_RESUME_BYTES = 50 * 1024 * 1024


def resume_is_ready(job_config: JobConfiguration) -> bool:
    return job_config.resume_parse_status == RESUME_PARSE_COMPLETED and bool(job_config.resume_json)


def resume_is_waiting(job_config: JobConfiguration) -> bool:
    return job_config.resume_parse_status in {RESUME_PARSE_PENDING, RESUME_PARSE_PROCESSING}


def safe_filename(file_name: str) -> str:
    name = os.path.basename(file_name or 'resume')
    name = re.sub(r'[\\/:*?"<>|\r\n]+', '_', name).strip(' .')
    return name or 'resume'


def resume_storage_dir() -> Path:
    storage_dir = Path(getattr(settings, 'EXTERNAL_RESUME_STORAGE_DIR', '') or 'external_resumes')
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


def save_uploaded_resume_file(uploaded_file, owner_key: str) -> Tuple[str, str]:
    file_name = safe_filename(getattr(uploaded_file, 'name', '') or 'resume')
    target_path = resume_storage_dir() / f"{safe_filename(owner_key)}_{int(time.time())}_{file_name}"
    total = 0
    with target_path.open('wb') as fh:
        for chunk in uploaded_file.chunks():
            total += len(chunk)
            if total > MAX_RESUME_BYTES:
                raise ValueError('resume file exceeds 50MB')
            fh.write(chunk)
    return str(target_path), file_name


def download_resume_file(request_id: str, resume: Dict[str, Any]) -> Tuple[str, str]:
    file_name = safe_filename(str(resume.get('file_name') or 'resume'))
    file_url = str(resume.get('file_url') or '').strip()
    suffix = Path(file_name).suffix
    if not suffix:
        guessed = mimetypes.guess_extension(mimetypes.guess_type(file_url)[0] or '')
        suffix = guessed or '.bin'
        file_name = f"{file_name}{suffix}"

    target_path = resume_storage_dir() / f"{safe_filename(request_id)}_{int(time.time())}_{file_name}"
    req = urllib.request.Request(file_url, headers={'User-Agent': 'AIInterviewService/1.0'})
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
    return str(target_path), file_name


def parse_resume_for_job(
    job_config_id: str,
    file_path: str,
    file_name: str,
    extra_resume_data: Optional[Dict[str, Any]] = None,
) -> None:
    close_old_connections()
    try:
        JobConfiguration.objects.filter(config_id=job_config_id).update(
            resume_parse_status=RESUME_PARSE_PROCESSING,
            resume_parse_error='',
            resume_source_path=file_path,
            updated_at=timezone.now(),
        )
        parsed = ResumeParser.parse_resume(file_path, file_name)
        if 'error' in parsed:
            raise RuntimeError(str(parsed.get('error')))
        extra_resume_data = extra_resume_data or {}
        auto_candidate_name = bool(extra_resume_data.pop('_auto_candidate_name', False))
        auto_candidate_email = bool(extra_resume_data.pop('_auto_candidate_email', False))
        for key, value in extra_resume_data.items():
            if key in ('name', 'phone', 'email') and (auto_candidate_name or auto_candidate_email):
                parsed.setdefault(key, value)
            else:
                parsed[key] = value

        job_config = JobConfiguration.objects.select_related('candidate').filter(config_id=job_config_id).first()
        if job_config and job_config.candidate:
            update_fields = []
            candidate = job_config.candidate
            candidate_still_pending_name = str(candidate.name or '').startswith('Pending-')
            candidate_still_pending_email = str(candidate.email or '') == f'pending_{job_config_id}@resume.local'
            if auto_candidate_name and candidate_still_pending_name and parsed.get('name'):
                candidate.name = parsed.get('name')
                update_fields.append('name')
            elif not candidate_still_pending_name:
                parsed['name'] = candidate.name
            if auto_candidate_email and candidate_still_pending_email and parsed.get('email'):
                candidate.email = parsed.get('email')
                update_fields.append('email')
            elif not candidate_still_pending_email:
                parsed['email'] = candidate.email
            if parsed.get('phone') and not candidate.phone:
                candidate.phone = parsed.get('phone')
                update_fields.append('phone')
            elif candidate.phone:
                parsed['phone'] = candidate.phone
            if update_fields and ('name' in update_fields or 'email' in update_fields):
                candidate.candidate_id = f"{candidate.name}_{candidate.email}_{job_config_id}"
                update_fields.append('candidate_id')
            if update_fields:
                candidate.save(update_fields=update_fields)

        JobConfiguration.objects.filter(config_id=job_config_id).update(
            resume_json=parsed,
            resume_parse_status=RESUME_PARSE_COMPLETED,
            resume_parse_error='',
            resume_source_path=file_path,
            updated_at=timezone.now(),
        )
        job_config = JobConfiguration.objects.select_related('candidate', 'assessment_group').filter(config_id=job_config_id).first()
        if job_config and not job_config.assessment_group_id:
            assign_assessment_group(job_config)
        enqueue_job_match_analysis(job_config_id)
    except Exception as exc:
        JobConfiguration.objects.filter(config_id=job_config_id).update(
            resume_parse_status=RESUME_PARSE_FAILED,
            resume_parse_error=str(exc),
            resume_source_path=file_path,
            updated_at=timezone.now(),
        )
    finally:
        close_old_connections()


def enqueue_resume_parse(
    job_config_id: str,
    file_path: str,
    file_name: str,
    extra_resume_data: Optional[Dict[str, Any]] = None,
) -> None:
    thread = threading.Thread(
        target=parse_resume_for_job,
        args=(job_config_id, file_path, file_name, extra_resume_data),
        daemon=True,
        name=f'resume-parse-{job_config_id}',
    )
    thread.start()


def parse_external_resume_for_session(external_session_id: str) -> None:
    close_old_connections()
    try:
        external_session = ExternalAISession.objects.select_related('job_config').get(
            external_session_id=external_session_id
        )
        job_config = external_session.job_config
        if not job_config:
            return
        request_id = external_session.request_id
        resume_data = external_session.request_payload.get('resume') or {}
        file_path, file_name = download_resume_file(request_id, resume_data)
        ExternalAISession.objects.filter(pk=external_session.pk).update(
            downloaded_resume_path=file_path,
            resume_downloaded_at=timezone.now(),
            updated_at=timezone.now(),
        )
        parsed = ResumeParser.parse_resume(file_path, file_name)
        if 'error' in parsed:
            raise RuntimeError(str(parsed.get('error')))
        candidate = job_config.candidate
        parsed.setdefault('name', candidate.name if candidate else '')
        parsed.setdefault('phone', candidate.phone if candidate else '')
        parsed.setdefault('email', candidate.email if candidate else '')
        parsed['external_resume'] = {
            'file_name': resume_data.get('file_name'),
            'file_url': resume_data.get('file_url'),
            'local_file_path': file_path,
            'parsed_at': timezone.now().isoformat(),
        }
        JobConfiguration.objects.filter(pk=job_config.pk).update(
            resume_json=parsed,
            resume_parse_status=RESUME_PARSE_COMPLETED,
            resume_parse_error='',
            resume_source_path=file_path,
            updated_at=timezone.now(),
        )
        enqueue_job_match_analysis(job_config.config_id)
    except Exception as exc:
        ExternalAISession.objects.filter(external_session_id=external_session_id).update(
            status='failed',
            callback_last_error=str(exc),
            updated_at=timezone.now(),
        )
        external_session = ExternalAISession.objects.filter(external_session_id=external_session_id).first()
        if external_session and external_session.job_config_id:
            JobConfiguration.objects.filter(pk=external_session.job_config_id).update(
                resume_parse_status=RESUME_PARSE_FAILED,
                resume_parse_error=str(exc),
                updated_at=timezone.now(),
            )
    finally:
        close_old_connections()


def enqueue_external_resume_parse(external_session_id: str) -> None:
    thread = threading.Thread(
        target=parse_external_resume_for_session,
        args=(external_session_id,),
        daemon=True,
        name=f'external-resume-parse-{external_session_id}',
    )
    thread.start()
