import json
import re
import threading
from typing import Any, Dict

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from ..models import JobConfiguration
from .token_utils import TokenRecorder


JOB_MATCH_PENDING = 'pending'
JOB_MATCH_PROCESSING = 'processing'
JOB_MATCH_COMPLETED = 'completed'
JOB_MATCH_FAILED = 'failed'
JOB_MATCH_MODEL = 'qwen3.7-plus'


def should_analyze_job_match(job_config: JobConfiguration) -> bool:
    if not job_config or not job_config.resume_json:
        return False
    if job_config.resume_parse_status != 'completed':
        return False
    if job_config.job_match_status == JOB_MATCH_PROCESSING:
        return False
    return True


def enqueue_job_match_analysis(job_config_id: str, force: bool = False) -> None:
    thread = threading.Thread(
        target=analyze_job_match_for_job,
        args=(job_config_id, force),
        daemon=True,
        name=f'job-match-{job_config_id}',
    )
    thread.start()


def analyze_job_match_for_job(job_config_id: str, force: bool = False) -> None:
    close_old_connections()
    try:
        job_config = JobConfiguration.objects.filter(config_id=job_config_id).first()
        if not job_config:
            return
        if not force and not should_analyze_job_match(job_config):
            return
        if not force and job_config.job_match_status == JOB_MATCH_COMPLETED and job_config.job_match_score is not None:
            return

        JobConfiguration.objects.filter(config_id=job_config_id).update(
            job_match_status=JOB_MATCH_PROCESSING,
            job_match_error='',
            updated_at=timezone.now(),
        )

        result = run_job_match_analysis(job_config)
        JobConfiguration.objects.filter(config_id=job_config_id).update(
            job_match_status=JOB_MATCH_COMPLETED,
            job_match_score=result.get('score'),
            job_match_result=result,
            job_match_error='',
            job_match_analyzed_at=timezone.now(),
            updated_at=timezone.now(),
        )
    except Exception as exc:
        JobConfiguration.objects.filter(config_id=job_config_id).update(
            job_match_status=JOB_MATCH_FAILED,
            job_match_error=str(exc),
            updated_at=timezone.now(),
        )
    finally:
        close_old_connections()


def run_job_match_analysis(job_config: JobConfiguration) -> Dict[str, Any]:
    system_prompt, user_prompt = build_job_match_prompt(job_config)
    raw = call_qwen37(system_prompt, user_prompt)
    TokenRecorder.record_job_match(system_prompt + user_prompt, raw, JOB_MATCH_MODEL)
    parsed = extract_json(raw)
    score = normalize_score(parsed.get('score'))
    parsed['score'] = score
    parsed.setdefault('summary', '')
    parsed.setdefault('strengths', [])
    parsed.setdefault('risks', [])
    parsed.setdefault('suggestion', '')
    parsed['model'] = JOB_MATCH_MODEL
    parsed['thinking'] = False
    return parsed


def build_job_match_prompt(job_config: JobConfiguration):
    resume_json = job_config.resume_json or {}
    resume_text = json.dumps(resume_json, ensure_ascii=False, indent=2)
    job_name = job_config.job_name or job_config.target_position or ''
    job_level = job_config.job_level or ''
    job_description = job_config.job_description or ''
    system_prompt = (
        '你是资深招聘评估专家。请根据候选人的结构化简历、岗位名称、岗位JD和岗位职级，'
        '评估候选人胜任该岗位的匹配度。只输出合法JSON，不要输出Markdown。'
    )
    user_prompt = f"""
请进行简历匹配度分析。

岗位名称：
{job_name}

岗位职级：
{job_level}

岗位JD：
{job_description or '未提供'}

候选人结构化简历JSON：
{resume_text}

输出JSON格式：
{{
  "score": 0-100的整数,
  "summary": "一句话说明整体匹配度",
  "strengths": ["与岗位匹配的证据，最多4条"],
  "risks": ["不匹配或信息不足的风险，最多4条"],
  "suggestion": "HR后续判断建议"
}}

评分要求：
1. 重点看岗位名称、JD要求、职级要求与简历中的项目经验、技能、年限、职责深度是否匹配。
2. 不要因为简历写得长就高分，要基于岗位证据评分。
3. JD为空时，主要依据岗位名称和职级做保守评估。
4. 信息不足时降低分数，并在risks里说明。
"""
    return system_prompt, user_prompt


def call_qwen37(system_prompt: str, user_prompt: str) -> str:
    import dashscope
    from dashscope import MultiModalConversation

    api_key = getattr(settings, 'DASHSCOPE_API_KEY', '')
    if not api_key:
        raise RuntimeError('DASHSCOPE_API_KEY not configured')
    dashscope.base_http_api_url = getattr(
        settings,
        'DASHSCOPE_HTTP_API_URL',
        'https://dashscope.aliyuncs.com/api/v1',
    )

    response = MultiModalConversation.call(
        api_key=api_key,
        model=JOB_MATCH_MODEL,
        messages=[{
            'role': 'user',
            'content': [{'text': user_prompt}],
        }],
        system=system_prompt,
        temperature=0.1,
        max_tokens=1200,
        enable_thinking=False,
    )
    if response.status_code != 200:
        raise RuntimeError(response.message or 'qwen3.7-plus call failed')
    if hasattr(response.output, 'choices') and response.output.choices:
        content = response.output.choices[0].message.content
        if isinstance(content, list):
            return ''.join(str(item.get('text', '')) for item in content if isinstance(item, dict)).strip()
        return str(content or '').strip()
    raise RuntimeError('qwen3.7-plus returned empty content')


def extract_json(text: str) -> Dict[str, Any]:
    if not text:
        raise RuntimeError('empty job match response')
    cleaned = text.strip()
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    match = re.search(r'\{[\s\S]*\}', cleaned)
    if match:
        cleaned = match.group(0)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'invalid job match JSON: {exc}') from exc
    return data if isinstance(data, dict) else {}


def normalize_score(value: Any) -> int:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        score = 0
    return max(0, min(100, score))
