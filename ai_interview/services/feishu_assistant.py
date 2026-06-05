import json
import logging
import os
import re
from typing import Any, Callable, Dict, Tuple
from urllib.parse import quote

from django.conf import settings
from django.utils import timezone

from ..models import Candidate, JobConfiguration
from ..views.utils import mark_profile_completed_if_finished, talent_profiles_for_config
from .interview_types import DISCUSSION, INITIAL_INTERVIEW, get_interview_type_label, normalize_interview_type
from .token_utils import TokenRecorder


logger = logging.getLogger(__name__)

FEISHU_ASSISTANT_MODEL = os.getenv('FEISHU_ASSISTANT_MODEL', 'qwen3.7-plus')
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+')


def handle_text_message(
    data: Dict[str, Any],
    request_base: str,
    send_message: Callable[[str, Dict[str, Any]], Dict[str, Any]],
) -> Tuple[Dict[str, Any], int]:
    chat_id = _extract_chat_id(data)
    text = _extract_text(data)
    if not chat_id or not text:
        return {'code': 0, 'msg': 'ignored'}, 200

    command = _parse_by_rules(text)
    if not command:
        command = _parse_by_llm(text)

    intent = command.get('intent')
    if intent == 'show_feishu_id':
        send_message(chat_id, build_feishu_id_card(data))
        return {'code': 0, 'msg': 'success'}, 200
    if intent == 'query_interview_status':
        send_message(chat_id, build_query_result_card(command, request_base))
        return {'code': 0, 'msg': 'success'}, 200

    reply = str(command.get('reply') or '').strip() or '我现在可以帮你查询候选人的面试或面谈信息。你可以发送：查询 候选人邮箱 的面谈信息。'
    send_message(chat_id, build_text_reply_card('飞书助手', reply))
    return {'code': 0, 'msg': 'success'}, 200


def _parse_by_rules(text: str) -> Dict[str, Any]:
    compact = re.sub(r'\s+', '', text or '').strip()
    if compact in {'ID', 'id', '我的ID', '我的id', '飞书ID', '飞书id'}:
        return {'intent': 'show_feishu_id'}

    email_match = EMAIL_RE.search(text or '')
    if email_match and any(word in text for word in ('查', '查询', '查看', '状态', '信息', '报告', '面试', '面谈')):
        return {
            'intent': 'query_interview_status',
            'email': email_match.group(0),
            'interview_type': _infer_interview_type(text),
        }
    return {}


def _parse_by_llm(text: str) -> Dict[str, Any]:
    system_prompt = (
        '你是AI面试系统的飞书助手。你只负责理解HR在飞书里发来的文字，并输出JSON。'
        '系统当前支持：查询候选人的面试/面谈状态、查看飞书ID、普通问答回复。'
        '不要编造数据库结果；如果用户要执行删除、修改、发送邮件等未开放动作，intent=chat 并给出简短中文回复。'
        '只输出合法JSON，不要输出Markdown。'
    )
    user_prompt = f"""
用户消息：
{text}

请输出JSON：
{{
  "intent": "query_interview_status|show_feishu_id|chat",
  "email": "候选人邮箱，没有则为空",
  "candidate_name": "候选人姓名，没有则为空",
  "interview_type": "discussion|initial_interview|unknown",
  "reply": "当intent=chat或信息不足时，给用户的一句简短中文回复"
}}
"""
    try:
        raw = _call_qwen(system_prompt, user_prompt)
        TokenRecorder.record_feishu_assistant(system_prompt + user_prompt, raw, FEISHU_ASSISTANT_MODEL)
        data = _extract_json(raw)
        intent = str(data.get('intent') or 'chat').strip()
        if intent not in {'query_interview_status', 'show_feishu_id', 'chat'}:
            intent = 'chat'
        return {
            'intent': intent,
            'email': str(data.get('email') or '').strip(),
            'candidate_name': str(data.get('candidate_name') or '').strip(),
            'interview_type': normalize_interview_type(data.get('interview_type')) if data.get('interview_type') != 'unknown' else '',
            'reply': str(data.get('reply') or '').strip(),
        }
    except Exception as exc:
        logger.warning('Feishu assistant LLM parse failed: %s', exc)
        return {'intent': 'chat', 'reply': '我暂时没理解你的指令。可以发送“查询 候选人邮箱 的面谈信息”试试。'}


def build_query_result_card(command: Dict[str, Any], request_base: str) -> Dict[str, Any]:
    email = str(command.get('email') or '').strip()
    candidate_name = str(command.get('candidate_name') or '').strip()
    interview_type = normalize_interview_type(command.get('interview_type')) if command.get('interview_type') else ''
    if not email and not candidate_name:
        return build_text_reply_card('需要更多信息', '请提供候选人邮箱，例如：查询 2601413168@qq.com 的面谈信息。')

    result = _find_interview(email, candidate_name, interview_type)
    if not result:
        target = email or candidate_name
        return build_text_reply_card('未找到记录', f'没有找到 {target} 对应的面试或面谈记录。')

    config = result['config']
    candidate = config.candidate
    profile = result['profile']
    status_label = _status_label(config, profile)
    report_url = _report_url(request_base, candidate.candidate_id if candidate else config.config_id, config.config_id)
    interview_url = _interview_url(request_base, config.config_id)
    report_analyzed = _report_analyzed(profile, config.interview_type)

    elements = [
        {'tag': 'markdown', 'content': (
            f"**候选人**：{candidate.name if candidate else '-'}\n"
            f"**邮箱**：{candidate.email if candidate else (email or '-')}\n"
            f"**任务类型**：{get_interview_type_label(config.interview_type)}\n"
            f"**状态**：{status_label}\n"
            f"**岗位**：{config.job_name or '-'}\n"
            f"**创建时间**：{timezone.localtime(config.created_at).strftime('%Y-%m-%d %H:%M') if config.created_at else '-'}\n"
            f"**报告分析**：{'已分析' if report_analyzed else '未分析'}"
        )},
        {'tag': 'hr'},
        {'tag': 'markdown', 'content': f'面试链接：[{interview_url}]({interview_url})'},
    ]
    if profile:
        elements.extend([
            _url_button('查看问答报告', report_url, 'primary'),
            _url_button('打开报告分析', report_url, 'default'),
        ])

    return {
        'schema': '2.0',
        'config': {'wide_screen_mode': True, 'update_multi': True},
        'header': {'title': {'content': '候选人面谈/面试信息', 'tag': 'plain_text'}, 'template': 'blue'},
        'body': {'elements': elements},
    }


def build_feishu_id_card(data: Dict[str, Any]) -> Dict[str, Any]:
    open_id = _extract_sender_open_id(data)
    name = _extract_sender_name(data) or '飞书用户'
    return build_text_reply_card('你的飞书ID', f'昵称：{name}\nOpen ID：{open_id or "未获取到"}')


def build_text_reply_card(title: str, content: str) -> Dict[str, Any]:
    return {
        'schema': '2.0',
        'config': {'wide_screen_mode': True, 'update_multi': True},
        'header': {'title': {'content': title, 'tag': 'plain_text'}, 'template': 'blue'},
        'body': {'elements': [{'tag': 'markdown', 'content': content}]},
    }


def _find_interview(email: str, candidate_name: str, interview_type: str):
    queryset = JobConfiguration.objects.select_related('candidate').all()
    if email:
        queryset = queryset.filter(candidate__email__iexact=email)
    if candidate_name:
        queryset = queryset.filter(candidate__name__icontains=candidate_name)
    if interview_type:
        queryset = queryset.filter(interview_type=interview_type)
    queryset = queryset.order_by('-created_at')
    for config in queryset[:10]:
        profiles = list(talent_profiles_for_config(config.config_id).order_by('-updated_at'))
        profile = mark_profile_completed_if_finished(profiles[0]) if profiles else None
        return {'config': config, 'profile': profile}
    return None


def _status_label(config: JobConfiguration, profile) -> str:
    if profile and profile.interview_completed:
        return '已完成'
    if config.expire_at and config.expire_at < timezone.now():
        return '已过期'
    if config.is_locked or config.current_interviews > 0:
        return '进行中'
    return '未开始'


def _report_analyzed(profile, interview_type: str) -> bool:
    if not profile or not isinstance(profile.profile_data, dict):
        return False
    data = profile.profile_data
    if normalize_interview_type(interview_type) == DISCUSSION:
        return bool(data.get('discussion_report_analysis'))
    return bool(data.get('report_analysis'))


def _infer_interview_type(text: str) -> str:
    if '面谈' in text:
        return DISCUSSION
    if '面试' in text:
        return INITIAL_INTERVIEW
    return ''


def _call_qwen(system_prompt: str, user_prompt: str) -> str:
    import dashscope
    from dashscope import MultiModalConversation

    api_key = getattr(settings, 'DASHSCOPE_API_KEY', '')
    if not api_key:
        raise RuntimeError('DASHSCOPE_API_KEY not configured')
    dashscope.base_http_api_url = getattr(settings, 'DASHSCOPE_HTTP_API_URL', 'https://dashscope.aliyuncs.com/api/v1')
    response = MultiModalConversation.call(
        api_key=api_key,
        model=FEISHU_ASSISTANT_MODEL,
        messages=[{'role': 'user', 'content': [{'text': user_prompt}]}],
        system=system_prompt,
        temperature=0.1,
        max_tokens=600,
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


def _extract_json(text: str) -> Dict[str, Any]:
    cleaned = (text or '').strip()
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    match = re.search(r'\{[\s\S]*\}', cleaned)
    if match:
        cleaned = match.group(0)
    parsed = json.loads(cleaned)
    return parsed if isinstance(parsed, dict) else {}


def _extract_text(data: Dict[str, Any]) -> str:
    event = data.get('event') if isinstance(data.get('event'), dict) else {}
    message = event.get('message') if isinstance(event.get('message'), dict) else {}
    content = message.get('content')
    if isinstance(content, dict):
        return str(content.get('text') or '').strip()
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return str(parsed.get('text') or '').strip()
        except json.JSONDecodeError:
            return content.strip()
    return ''


def _extract_chat_id(data: Dict[str, Any]) -> str:
    event = data.get('event') if isinstance(data.get('event'), dict) else {}
    message = event.get('message') if isinstance(event.get('message'), dict) else {}
    return str(message.get('chat_id') or event.get('open_chat_id') or '').strip()


def _extract_sender_open_id(data: Dict[str, Any]) -> str:
    event = data.get('event') if isinstance(data.get('event'), dict) else {}
    sender = event.get('sender') if isinstance(event.get('sender'), dict) else {}
    sender_id = sender.get('sender_id') if isinstance(sender.get('sender_id'), dict) else {}
    return str(sender_id.get('open_id') or sender.get('open_id') or event.get('open_id') or '').strip()


def _extract_sender_name(data: Dict[str, Any]) -> str:
    event = data.get('event') if isinstance(data.get('event'), dict) else {}
    sender = event.get('sender') if isinstance(event.get('sender'), dict) else {}
    return str(sender.get('sender_name') or sender.get('name') or event.get('sender_name') or '').strip()


def _report_url(request_base: str, candidate_id: str, config_id: str) -> str:
    return (
        f'{request_base.rstrip("/")}/api/ai-interview/hr/candidates/interview-report/'
        f'?candidate_id={quote(str(candidate_id))}&config_id={quote(str(config_id))}'
    )


def _interview_url(request_base: str, config_id: str) -> str:
    return f'{request_base.rstrip("/")}/api/ai-interview/interview/welcome/?config_id={quote(str(config_id))}'


def _url_button(text: str, url: str, button_type: str) -> Dict[str, Any]:
    return {
        'tag': 'button',
        'text': {'content': text, 'tag': 'plain_text'},
        'type': button_type,
        'behaviors': [{'type': 'open_url', 'default_url': url, 'pc_url': url, 'ios_url': url, 'android_url': url}],
    }
