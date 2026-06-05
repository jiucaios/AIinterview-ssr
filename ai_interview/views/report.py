import json
import os
import re
from django.conf import settings
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from ..models import Candidate, JobConfiguration
from .utils import talent_profiles_for_config, mark_profile_completed_if_finished
from ..services.session_manager import SessionManager
from ..services.qwen_service import QwenService
from ..services.token_utils import TokenCalculator
from ..services.token_tracker import TokenTracker
from ..services.interview_result_policy import get_report_policy_for_profile
from ..services.interview_types import DISCUSSION
from .hr_auth import HRAuthRequiredMixin


DISCUSSION_ANALYSIS_MODEL = 'qwen-plus'


class CandidateInterviewReportView(HRAuthRequiredMixin, APIView):
    login_redirect = True

    def get(self, request):
        template_path = os.path.join(os.path.dirname(__file__), '..', 'candidate_interview_report.html')
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return HttpResponse(content, content_type='text/html')
        return HttpResponse("面试报告页面未找到", status=404)


def build_interview_report_analysis(profile, round_types):
    profile_data = profile.profile_data or {}
    qa_records = profile_data.get('qa_records') or SessionManager.build_qa_records(profile.dialogue_history)

    analyses = []
    report_input_tokens = 0
    report_output_tokens = 0
    for index, record in enumerate(qa_records):
        question = record.get('question', '')
        answer = record.get('answer', '')
        round_type = round_types[min(index, len(round_types) - 1)]
        quality = QwenService.validate_answer_quality(question, answer, round_type, record_token=False)
        token_prompt = quality.pop('_token_prompt', '')
        token_response = quality.pop('_token_response', '')
        if token_prompt or token_response:
            tokens = TokenCalculator.estimate_api_tokens(token_prompt, token_response, QwenService.get_text_model())
            report_input_tokens += tokens['input_tokens']
            report_output_tokens += tokens['output_tokens']
        confidence = float(quality.get('confidence', 0) or 0)
        score = round(confidence * 100)
        analyses.append({
            **record,
            'round': record.get('round') or index + 1,
            'round_type': round_type,
            'quality': quality,
            'score': score,
            'score_text': f"{score}分",
            'analysis_status': 'analyzed',
        })

    profile_data['qa_records'] = qa_records
    profile_data['report_analysis'] = analyses
    profile.profile_data = profile_data
    if analyses:
        profile.confidence_score = sum((item.get('score') or 0) for item in analyses) / len(analyses) / 100
        profile.save(update_fields=['profile_data', 'confidence_score', 'updated_at'])
    else:
        profile.save(update_fields=['profile_data', 'updated_at'])

    if report_input_tokens or report_output_tokens:
        TokenTracker.record_usage(
            category=TokenTracker.CATEGORY_ANSWER_ANALYSIS,
            input_tokens=report_input_tokens,
            output_tokens=report_output_tokens,
            model=QwenService.get_text_model(),
            metadata={
                'type': 'answer_analysis',
                'scope': 'interview_report',
                'qa_count': len(qa_records),
                'profile_id': str(profile.id),
            },
        )

    return qa_records, analyses


def _normalize_score(value):
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        score = 0
    return max(0, min(100, score))


def _extract_json_object(text):
    cleaned = (text or '').strip()
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    match = re.search(r'\{[\s\S]*\}', cleaned)
    if match:
        cleaned = match.group(0)
    return json.loads(cleaned)


def _build_discussion_context(profile):
    job_config_data = profile.job_config if isinstance(profile.job_config, dict) else {}
    config_id = job_config_data.get('config_id', '')
    job_config = JobConfiguration.objects.filter(config_id=config_id).first() if config_id else None

    return {
        'config_id': config_id,
        'job_name': (job_config.job_name if job_config else '') or job_config_data.get('job_name', '') or job_config_data.get('target_position', ''),
        'job_level': (job_config.job_level if job_config else '') or job_config_data.get('job_level', ''),
        'job_description': (job_config.job_description if job_config else '') or job_config_data.get('job_description', ''),
        'recruitment_requirements': (
            (job_config.recruitment_requirements if job_config else '')
            or job_config_data.get('recruitment_requirements', '')
        ),
    }


def _build_discussion_analysis_prompt(profile, qa_records):
    context = _build_discussion_context(profile)
    qa_text = json.dumps(qa_records, ensure_ascii=False, indent=2)
    system_prompt = (
        '你是资深招聘面谈评估专家。请基于面谈完整问答、岗位名称、岗位JD、岗位职级和HR提交的特殊要求，'
        '评估候选人在本次面谈中的综合匹配情况。必须只输出合法JSON，不要输出Markdown或额外说明。'
    )
    user_prompt = f"""
请分析这份面谈报告。评分重点如下：
1. 特殊要求匹配度是最高权重。优先判断候选人的回答是否回应、满足或明显偏离HR前端提交的特殊要求。
2. 综合考虑岗位名称、岗位JD和岗位职级，判断候选人回答与岗位真实要求是否一致。
3. 评估整场面谈的逻辑连贯性：回答前后是否一致、是否能围绕问题展开、是否存在明显矛盾或跳跃。
4. 评估语言逻辑性：表达是否清晰、有条理、有因果或层次。
5. 评估可信度真实性：是否包含具体事实、个人经历、可验证细节；空泛套话、回避、前后矛盾要扣分。

权重建议：
- 特殊要求匹配度：40%
- 逻辑连贯性和语言逻辑性：25%
- 可信度真实性：20%
- 岗位/JD/职级匹配度：15%

岗位名称：
{context['job_name'] or '未提供'}

岗位职级：
{context['job_level'] or '未提供'}

岗位JD：
{context['job_description'] or '未提供'}

HR前端提交的特殊要求：
{context['recruitment_requirements'] or '未提供'}

面谈问答记录JSON：
{qa_text}

请返回以下JSON结构，字段名必须一致：
{{
  "score": 0到100的整数,
  "summary": "2-4句话总结候选人与本次面谈要求的匹配情况",
  "decision": "推荐|谨慎推荐|不推荐|信息不足",
  "dimensions": [
    {{"name":"特殊要求匹配度","score":0到100的整数,"comment":"结合HR特殊要求说明命中、偏离或缺失点"}},
    {{"name":"逻辑连贯性","score":0到100的整数,"comment":"评价整场回答前后一致性和展开质量"}},
    {{"name":"语言逻辑性","score":0到100的整数,"comment":"评价表达结构、条理和可理解性"}},
    {{"name":"可信度真实性","score":0到100的整数,"comment":"评价事实细节、个人经历和可验证线索"}},
    {{"name":"岗位JD与职级匹配度","score":0到100的整数,"comment":"结合岗位名称、JD和职级评价匹配度"}}
  ],
  "strengths": ["最多4条优势，要具体对应回答证据"],
  "risks": ["最多4条风险或不足，要具体对应回答证据"],
  "suggestion": "给HR的一句话后续建议",
  "qa_evaluations": [
    {{
      "round": 1,
      "score": 0到100的整数,
      "comment": "这一轮回答对特殊要求、逻辑或真实性的具体点评",
      "matched_requirements": ["命中的特殊要求或岗位要求，最多3条"],
      "risks": ["这一轮暴露的问题，最多3条"]
    }}
  ]
}}
"""
    return system_prompt, user_prompt, context


def _call_qwen_plus(system_prompt, user_prompt):
    if not getattr(settings, 'DASHSCOPE_API_KEY', ''):
        raise RuntimeError('DASHSCOPE_API_KEY not configured')

    import dashscope
    from dashscope import Generation

    dashscope.api_key = getattr(settings, 'DASHSCOPE_API_KEY', '')
    dashscope.base_url = getattr(settings, 'DASHSCOPE_BASE_URL', 'https://dashscope.aliyuncs.com')

    response = Generation.call(
        model=DISCUSSION_ANALYSIS_MODEL,
        prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=0.1,
        max_tokens=1800,
    )
    if response.status_code != 200:
        raise RuntimeError(response.message or 'qwen-plus call failed')
    if hasattr(response.output, 'text') and response.output.text:
        return response.output.text
    if hasattr(response.output, 'choices') and response.output.choices:
        return response.output.choices[0].message.content
    raise RuntimeError('qwen-plus returned empty content')


def _fallback_discussion_analysis(qa_records, error_message):
    answer_text = '\n'.join((record.get('answer') or '') for record in qa_records)
    base_score = 70 if len(answer_text) >= 120 else 55 if answer_text else 0
    dimensions = [
        {'name': '特殊要求匹配度', 'score': base_score, 'comment': '本地兜底无法完整理解特殊要求，建议配置API后重新分析。'},
        {'name': '逻辑连贯性', 'score': 70 if len(answer_text) >= 80 else base_score, 'comment': '根据回答长度和完整性做保守估计。'},
        {'name': '语言逻辑性', 'score': 70 if len(answer_text) >= 80 else base_score, 'comment': '根据表达完整度做保守估计。'},
        {'name': '可信度真实性', 'score': 65 if any(word in answer_text for word in ['我', '负责', '参与', '经历', '项目']) else 45, 'comment': '根据第一人称经历和行动词做保守估计。'},
        {'name': '岗位JD与职级匹配度', 'score': base_score, 'comment': '本地兜底无法完整结合岗位JD和职级。'},
    ]
    return {
        'score': base_score,
        'summary': f'AI面谈分析暂时不可用，已生成本地兜底评分。原因：{error_message}',
        'decision': '信息不足',
        'dimensions': dimensions,
        'strengths': ['候选人已完成面谈并留下可复核的问答记录'] if answer_text else [],
        'risks': ['AI分析未成功生成，建议重新分析或人工复核'],
        'suggestion': '建议配置或检查qwen-plus调用后重新生成面谈分析。',
        'qa_evaluations': [
            {
                'round': record.get('round') or index + 1,
                'score': base_score,
                'comment': '本地兜底仅保留问答记录，未做深度语义分析。',
                'matched_requirements': [],
                'risks': ['未完成AI语义分析'],
            }
            for index, record in enumerate(qa_records)
        ],
    }


def build_discussion_report_analysis(profile):
    profile_data = profile.profile_data or {}
    qa_records = profile_data.get('qa_records') or SessionManager.build_qa_records(profile.dialogue_history)
    system_prompt, user_prompt, context = _build_discussion_analysis_prompt(profile, qa_records)
    token_response = ''

    try:
        token_response = _call_qwen_plus(system_prompt, user_prompt)
        analysis = _extract_json_object(token_response)
        if not isinstance(analysis, dict):
            raise RuntimeError('qwen-plus returned non-object JSON')
    except Exception as exc:
        analysis = _fallback_discussion_analysis(qa_records, str(exc))

    score = _normalize_score(analysis.get('score'))
    analysis['score'] = score
    analysis['score_text'] = f'{score}分'
    analysis['model'] = DISCUSSION_ANALYSIS_MODEL
    analysis['job_context'] = context
    analysis['analysis_status'] = 'analyzed'
    analysis.setdefault('summary', '')
    analysis.setdefault('decision', '信息不足')
    analysis.setdefault('dimensions', [])
    analysis.setdefault('strengths', [])
    analysis.setdefault('risks', [])
    analysis.setdefault('suggestion', '')

    evaluations = analysis.get('qa_evaluations') if isinstance(analysis.get('qa_evaluations'), list) else []
    evaluations_by_round = {
        str(item.get('round') or index + 1): item
        for index, item in enumerate(evaluations)
        if isinstance(item, dict)
    }
    analyzed_records = []
    for index, record in enumerate(qa_records):
        round_number = record.get('round') or index + 1
        evaluation = evaluations_by_round.get(str(round_number), {})
        item_score = _normalize_score(evaluation.get('score', score))
        analyzed_records.append({
            **record,
            'round': round_number,
            'round_type': 'discussion',
            'score': item_score,
            'score_text': f'{item_score}分',
            'analysis_status': 'analyzed',
            'quality': {
                'valid': item_score >= 60,
                'reason': evaluation.get('comment') or analysis.get('summary', ''),
                'dimensions': [],
                'strengths': evaluation.get('matched_requirements') if isinstance(evaluation.get('matched_requirements'), list) else [],
                'risks': evaluation.get('risks') if isinstance(evaluation.get('risks'), list) else [],
                'suggestion': analysis.get('suggestion', ''),
                'issues': evaluation.get('risks') if isinstance(evaluation.get('risks'), list) else [],
            },
        })

    profile_data['qa_records'] = qa_records
    profile_data['discussion_report_analysis'] = analysis
    profile_data['discussion_report_records'] = analyzed_records
    profile.profile_data = profile_data
    profile.confidence_score = score / 100
    profile.save(update_fields=['profile_data', 'confidence_score', 'updated_at'])

    if token_response:
        tokens = TokenCalculator.estimate_api_tokens(system_prompt + user_prompt, token_response, DISCUSSION_ANALYSIS_MODEL)
        TokenTracker.record_usage(
            category=TokenTracker.CATEGORY_ANSWER_ANALYSIS,
            input_tokens=tokens['input_tokens'],
            output_tokens=tokens['output_tokens'],
            model=DISCUSSION_ANALYSIS_MODEL,
            metadata={
                'type': 'discussion_report_analysis',
                'scope': 'interview_report',
                'qa_count': len(qa_records),
                'profile_id': str(profile.id),
            },
        )

    return qa_records, analyzed_records, analysis


class CandidateInterviewReportDataView(HRAuthRequiredMixin, APIView):
    ROUND_TYPES = [
        'hard_field',
        'role_verification',
        'role_depth',
        'skill_deviation',
        'language_logic',
        'special_requirement',
    ]

    def get(self, request):
        try:
            candidate_id = request.query_params.get('candidate_id', '').strip()
            config_id = request.query_params.get('config_id', '').strip()

            if not config_id:
                return Response(
                    {'error': 'candidate_id不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            profiles = list(talent_profiles_for_config(config_id).order_by('-updated_at'))
            profile = mark_profile_completed_if_finished(profiles[0]) if profiles else None
            if profile:
                candidate_id = candidate_id or profile.candidate_id
            if not profile:
                return Response(
                    {'error': '未找到面试记录'},
                    status=status.HTTP_404_NOT_FOUND
                )

            profile_data = profile.profile_data or {}
            policy = get_report_policy_for_profile(profile)
            qa_records = profile_data.get('qa_records') or SessionManager.build_qa_records(profile.dialogue_history)
            is_discussion = policy.get('interview_type') == DISCUSSION
            discussion_analysis = profile_data.get('discussion_report_analysis') if is_discussion else None
            discussion_records = profile_data.get('discussion_report_records') if is_discussion else []
            has_discussion_analysis = bool(isinstance(discussion_analysis, dict) and discussion_analysis)
            stored_analyses = (
                discussion_records
                if has_discussion_analysis
                else ([] if policy['qa_only'] else (profile_data.get('report_analysis') or []))
            )
            analyzed_by_round = {
                str(item.get('round') or index + 1): item
                for index, item in enumerate(stored_analyses)
                if isinstance(item, dict)
            }

            records = []
            for index, record in enumerate(qa_records):
                round_type = self.ROUND_TYPES[min(index, len(self.ROUND_TYPES) - 1)]
                round_number = record.get('round') or index + 1
                analyzed_record = analyzed_by_round.get(str(round_number))
                if analyzed_record:
                    records.append(analyzed_record)
                else:
                    records.append({
                        **record,
                        'round': round_number,
                        'round_type': round_type,
                        'analysis_status': 'qa_only' if policy['qa_only'] and not has_discussion_analysis else 'not_analyzed',
                    })

            if not profile_data.get('qa_records'):
                profile_data['qa_records'] = qa_records
                profile.profile_data = profile_data
                profile.save(update_fields=['profile_data', 'updated_at'])

            candidate = Candidate.objects.filter(candidate_id=candidate_id).first()

            return Response({
                'candidate_id': candidate_id,
                'candidate_name': candidate.name if candidate else candidate_id,
                'interview_completed': profile.interview_completed,
                'confidence_score': profile.confidence_score,
                'report_analyzed': has_discussion_analysis or bool(stored_analyses),
                'discussion_analysis': discussion_analysis if has_discussion_analysis else None,
                **policy,
                'updated_at': profile.updated_at.isoformat() if profile.updated_at else None,
                'qa_records': records,
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'获取面试报告失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CandidateInterviewReportAnalyzeView(HRAuthRequiredMixin, APIView):
    ROUND_TYPES = CandidateInterviewReportDataView.ROUND_TYPES

    def post(self, request):
        try:
            candidate_id = request.data.get('candidate_id', '').strip()
            config_id = request.data.get('config_id', '').strip()

            if not config_id:
                return Response(
                    {'error': 'config_id不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            profiles = list(talent_profiles_for_config(config_id).order_by('-updated_at'))
            profile = mark_profile_completed_if_finished(profiles[0]) if profiles else None
            if profile:
                candidate_id = candidate_id or profile.candidate_id
            if not profile:
                return Response(
                    {'error': '未找到面试记录'},
                    status=status.HTTP_404_NOT_FOUND
                )

            policy = get_report_policy_for_profile(profile)
            if policy.get('interview_type') == DISCUSSION:
                qa_records, analyses, discussion_analysis = build_discussion_report_analysis(profile)
                candidate = Candidate.objects.filter(candidate_id=candidate_id).first()

                return Response({
                    'success': True,
                    'message': '面谈报告分析完成',
                    'candidate_id': candidate_id,
                    'candidate_name': candidate.name if candidate else candidate_id,
                    'interview_completed': profile.interview_completed,
                    'confidence_score': profile.confidence_score,
                    'report_analyzed': True,
                    'discussion_analysis': discussion_analysis,
                    **policy,
                    'updated_at': profile.updated_at.isoformat() if profile.updated_at else None,
                    'qa_records': analyses,
                    'qa_count': len(qa_records),
                }, status=status.HTTP_200_OK)

            if not policy['can_analyze_report']:
                profile_data = profile.profile_data or {}
                qa_records = profile_data.get('qa_records') or SessionManager.build_qa_records(profile.dialogue_history)
                if not profile_data.get('qa_records'):
                    profile_data['qa_records'] = qa_records
                    profile.profile_data = profile_data
                    profile.save(update_fields=['profile_data', 'updated_at'])
                return Response({
                    'success': True,
                    'message': '面谈仅保留问答记录，不执行回答分析',
                    'candidate_id': candidate_id,
                    'interview_completed': profile.interview_completed,
                    'report_analyzed': False,
                    **policy,
                    'qa_records': qa_records,
                    'qa_count': len(qa_records),
                }, status=status.HTTP_200_OK)

            qa_records, analyses = build_interview_report_analysis(profile, self.ROUND_TYPES)
            candidate = Candidate.objects.filter(candidate_id=candidate_id).first()

            return Response({
                'success': True,
                'message': '问答报告分析完成',
                'candidate_id': candidate_id,
                'candidate_name': candidate.name if candidate else candidate_id,
                'interview_completed': profile.interview_completed,
                'confidence_score': profile.confidence_score,
                'report_analyzed': True,
                'updated_at': profile.updated_at.isoformat() if profile.updated_at else None,
                'qa_records': analyses,
                'qa_count': len(qa_records),
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'分析问答报告失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
