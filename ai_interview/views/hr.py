import os
from django.http import HttpResponse
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from ..models import JobConfiguration, Candidate
from .utils import talent_profiles_for_config, mark_profile_completed_if_finished
from ..services.session_manager import SessionManager
from ..services.interview_types import DISCUSSION, INITIAL_INTERVIEW, normalize_interview_type, get_interview_type_label, can_analyze_report
from ..services.url_builder import build_interview_welcome_url
from ..services.assessment_groups import (
    assign_assessment_group,
    available_assessment_groups_for_config,
    switch_assessment_group,
)
from .hr_auth import HRAuthRequiredMixin


def _score_from_profile(profile, interview_type):
    if not profile:
        return 0

    profile_data = profile.profile_data if isinstance(profile.profile_data, dict) else {}
    if interview_type == DISCUSSION:
        analysis = profile_data.get('discussion_report_analysis') if isinstance(profile_data.get('discussion_report_analysis'), dict) else {}
        if analysis.get('score') is not None:
            try:
                return max(0, min(100, int(round(float(analysis.get('score'))))))
            except (TypeError, ValueError):
                pass

    analyses = profile_data.get('report_analysis') if isinstance(profile_data.get('report_analysis'), list) else []
    scores = []
    for item in analyses:
        if isinstance(item, dict) and item.get('score') is not None:
            try:
                scores.append(float(item.get('score')))
            except (TypeError, ValueError):
                pass
    if scores:
        return max(0, min(100, int(round(sum(scores) / len(scores)))))

    return max(0, min(100, int(round((profile.confidence_score or 0) * 100))))


def _latest_profile_for_config(config_id):
    profiles = [
        mark_profile_completed_if_finished(profile)
        for profile in talent_profiles_for_config(config_id).order_by('-updated_at')
    ]
    return profiles[0] if profiles else None, profiles


def _created_by_label(created_by, resume_data=None):
    value = str(created_by or '').strip()
    if not value:
        return '-'
    if value.startswith('feishu:'):
        resume_data = resume_data if isinstance(resume_data, dict) else {}
        creator_name = str(resume_data.get('feishu_creator_name') or '').strip()
        if not creator_name:
            feishu_id = value.split(':', 1)[1].strip()
            try:
                from ..services.feishu_integration import get_feishu_user_display_name
                creator_name = get_feishu_user_display_name(feishu_id)
            except Exception:
                creator_name = ''
        return f'飞书：{creator_name or "飞书用户"}'
    return value


def _calculate_position_match(config, latest_profile):
    resume_score = 0
    discussion_score = 0
    interview_score = 0
    has_discussion_score = False
    has_interview_score = False
    has_resume_score = False

    group = assign_assessment_group(config)
    related_configs = group.job_configs.all() if group else JobConfiguration.objects.filter(config_id=config.config_id)

    for related_config in related_configs:
        if related_config.job_match_score is not None and (related_config.job_match_status or '') == 'completed':
            has_resume_score = True
            resume_score = max(resume_score, related_config.job_match_score)
        related_profile, _ = _latest_profile_for_config(related_config.config_id)
        if related_config.interview_type == DISCUSSION:
            score = _score_from_profile(related_profile, DISCUSSION)
            if related_profile and related_profile.interview_completed:
                has_discussion_score = True
            discussion_score = max(discussion_score, score)
        else:
            score = _score_from_profile(related_profile, INITIAL_INTERVIEW)
            if related_profile and related_profile.interview_completed:
                has_interview_score = True
            interview_score = max(interview_score, score)

    if config.interview_type == DISCUSSION:
        discussion_score = max(discussion_score, _score_from_profile(latest_profile, DISCUSSION))
        if latest_profile and latest_profile.interview_completed:
            has_discussion_score = True
    else:
        interview_score = max(interview_score, _score_from_profile(latest_profile, INITIAL_INTERVIEW))
        if latest_profile and latest_profile.interview_completed:
            has_interview_score = True

    final_score = round(resume_score * 0.35 + discussion_score * 0.3 + interview_score * 0.35)

    return {
        'score': max(0, min(100, int(final_score))),
        'resume_score': resume_score,
        'discussion_score': discussion_score,
        'interview_score': interview_score,
        'has_resume_score': has_resume_score,
        'has_discussion_score': has_discussion_score,
        'has_interview_score': has_interview_score,
    }


class HRDashboardView(HRAuthRequiredMixin, APIView):
    login_redirect = True

    def get(self, request):
        template_path = os.path.join(os.path.dirname(__file__), '..', 'hr_dashboard.html')
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return HttpResponse(content, content_type='text/html')
        return HttpResponse("HR管理页面未找到", status=404)


class CandidateManagementView(HRAuthRequiredMixin, APIView):
    login_redirect = True

    def get(self, request):
        template_path = os.path.join(os.path.dirname(__file__), '..', 'candidate_management.html')
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return HttpResponse(content, content_type='text/html')
        return HttpResponse("候选人管理页面未找到", status=404)


class CandidateListView(HRAuthRequiredMixin, APIView):
    def get(self, request):
        try:
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 10))
            interview_type = normalize_interview_type(request.query_params.get('interview_type') or INITIAL_INTERVIEW)

            job_configs = JobConfiguration.objects.select_related('candidate').filter(interview_type=interview_type).order_by('-created_at')
            total_count = job_configs.count()

            start = (page - 1) * page_size
            end = start + page_size
            paginated_configs = list(job_configs[start:end])

            candidates = []
            for config in paginated_configs:
                resume_data = config.resume_json if config.resume_json else {}
                candidate_id = config.candidate.candidate_id if config.candidate else config.config_id
                latest_profile, profiles = _latest_profile_for_config(config.config_id)
                latest_profile = profiles[0] if profiles else None
                interview_completed = any(profile.interview_completed for profile in profiles)
                profile_data = latest_profile.profile_data if latest_profile and isinstance(latest_profile.profile_data, dict) else {}
                is_discussion = config.interview_type == DISCUSSION
                report_analyzed = bool(
                    profile_data.get('discussion_report_analysis') if is_discussion else profile_data.get('report_analysis')
                )
                match_score = config.job_match_score
                match_status = config.job_match_status or 'pending'
                if match_status == 'completed' and match_score is not None:
                    match_label = f'{match_score}%'
                elif match_status == 'processing':
                    match_label = '分析中'
                elif match_status == 'failed':
                    match_label = '分析失败'
                else:
                    match_label = '待分析'
                position_match = _calculate_position_match(config, latest_profile)
                assessment_group = assign_assessment_group(config)
                assessment_groups = available_assessment_groups_for_config(config)
                position_match_items = [
                    ('简历匹配度', position_match['has_resume_score'], position_match['resume_score']),
                    ('面谈得分', position_match['has_discussion_score'], position_match['discussion_score']),
                    ('面试得分', position_match['has_interview_score'], position_match['interview_score']),
                ]
                completed_items = [f'{name}{score}分' for name, done, score in position_match_items if done]
                missing_items = [name for name, done, _score in position_match_items if not done]
                candidate_info = {
                    'config_id': config.config_id,
                    'candidate_id': candidate_id,
                    'name': config.candidate.name if config.candidate else '',
                    'created_by': config.created_by or '',
                    'created_by_label': _created_by_label(config.created_by, resume_data),
                    'phone': config.candidate.phone if config.candidate else '',
                    'email': config.candidate.email if config.candidate else resume_data.get('email', ''),
                    'highest_education': resume_data.get('highest_education', '') or resume_data.get('degree', ''),
                    'work_years': resume_data.get('work_years', ''),
                    'job_name': config.job_name,
                    'interview_type': config.interview_type,
                    'interview_type_label': get_interview_type_label(config.interview_type),
                    'can_analyze_report': is_discussion or can_analyze_report(config.interview_type),
                    'recruitment_requirements': config.recruitment_requirements,
                    'summary': resume_data.get('summary', ''),
                    'interview_url': build_interview_welcome_url(request, config.config_id),
                    'interview_completed': interview_completed,
                    'report_analyzed': report_analyzed,
                    'job_match_status': match_status,
                    'job_match_score': match_score,
                    'job_match_label': match_label,
                    'job_match_summary': (config.job_match_result or {}).get('summary', '') or config.job_match_error,
                    'position_match_score': position_match['score'],
                    'position_match_summary': (
                        f"已完成：{('、'.join(completed_items) if completed_items else '暂无')}\n"
                        f"未完成：{('、'.join(missing_items) if missing_items else '无')}\n"
                        f"规则：简历匹配度×35% + 面谈得分×30% + 面试得分×35%；"
                        f"当前：{position_match['resume_score']}×35% + "
                        f"{position_match['discussion_score']}×30% + "
                        f"{position_match['interview_score']}×35% = {position_match['score']}分"
                    ),
                    'assessment_group_id': str(assessment_group.id) if assessment_group else '',
                    'assessment_group_label': (
                        '临时组'
                        if assessment_group and assessment_group.is_temporary
                        else (f'第{assessment_group.group_number}评估组' if assessment_group else '-')
                    ),
                    'assessment_groups': assessment_groups,
                    'interview_status': '已完成' if interview_completed else '未完成',
                    'report_url': (
                        f"{request.scheme}://{request.get_host()}/api/ai-interview/hr/candidates/interview-report/"
                        f"?candidate_id={candidate_id}&config_id={config.config_id}"
                    ) if interview_completed else '',
                    'analyze_report_url': (
                        f"{request.scheme}://{request.get_host()}/api/ai-interview/hr/candidates/interview-report/analyze/"
                    ) if interview_completed else '',
                    'created_at': config.created_at.isoformat() if config.created_at else None
                }
                candidates.append(candidate_info)

            total_pages = (total_count + page_size - 1) // page_size

            return Response({
                'candidates': candidates,
                'count': total_count,
                'page': page,
                'page_size': page_size,
                'total_pages': total_pages
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'获取候选人列表失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CandidateDeleteView(HRAuthRequiredMixin, APIView):
    def post(self, request):
        try:
            config_id = request.data.get('config_id', '').strip()
            candidate_id = request.data.get('candidate_id', '').strip()

            if not config_id:
                return Response(
                    {'error': 'config_id不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            with transaction.atomic():
                job_config = JobConfiguration.objects.select_related('candidate').filter(config_id=config_id).first()
                if not job_config:
                    return Response(
                        {'error': '未找到该候选人记录'},
                        status=status.HTTP_404_NOT_FOUND
                    )

                candidate = job_config.candidate
                profiles = list(talent_profiles_for_config(config_id))
                deleted_sessions = []
                for profile in profiles:
                    SessionManager.delete_session(profile.session_id)
                    deleted_sessions.append(profile.session_id)
                talent_profiles_for_config(config_id).delete()

                job_config.delete()

                if candidate and not JobConfiguration.objects.filter(candidate=candidate).exists():
                    candidate.delete()

            return Response({
                'success': True,
                'message': '删除成功',
                'deleted_sessions': deleted_sessions,
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'删除失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CandidateAssessmentGroupSwitchView(HRAuthRequiredMixin, APIView):
    def post(self, request):
        try:
            config_id = request.data.get('config_id', '').strip()
            assessment_group_id = request.data.get('assessment_group_id', '').strip()
            if not config_id or not assessment_group_id:
                return Response(
                    {'error': 'config_id和assessment_group_id不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            job_config = JobConfiguration.objects.select_related('candidate', 'assessment_group').filter(config_id=config_id).first()
            if not job_config:
                return Response(
                    {'error': '未找到该候选人记录'},
                    status=status.HTTP_404_NOT_FOUND
                )

            target_group = switch_assessment_group(job_config, assessment_group_id)
            return Response({
                'success': True,
                'message': '评估组已切换',
                'assessment_group_id': str(target_group.id),
                'assessment_group_label': '临时组' if target_group.is_temporary else f'第{target_group.group_number}评估组',
            }, status=status.HTTP_200_OK)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {'error': f'切换评估组失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CandidateUpdateView(HRAuthRequiredMixin, APIView):
    def post(self, request):
        try:
            config_id = request.data.get('config_id', '').strip()
            candidate_id = request.data.get('candidate_id', '').strip()
            name = request.data.get('name', '').strip()
            phone = request.data.get('phone', '').strip()
            email = request.data.get('email', '').strip()
            highest_education = request.data.get('highest_education', '').strip()
            work_years = request.data.get('work_years', '').strip()
            job_name = request.data.get('job_name', '').strip()
            summary = request.data.get('summary', '').strip()

            lookup_id = config_id or candidate_id
            if not lookup_id:
                return Response(
                    {'error': '候选人ID不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if email:
                try:
                    validate_email(email)
                except ValidationError:
                    return Response(
                        {'error': '邮箱格式不正确'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            job_configs = JobConfiguration.objects.select_related('candidate').filter(config_id=lookup_id)

            if not job_configs.exists():
                return Response(
                    {'error': '未找到该候选人'},
                    status=status.HTTP_404_NOT_FOUND
                )

            job_config = job_configs.first()

            if job_config.candidate:
                candidate = job_config.candidate
                if name:
                    candidate.name = name
                if phone:
                    candidate.phone = phone
                if email:
                    candidate.email = email
                if name or email:
                    candidate.candidate_id = f"{candidate.name}_{candidate.email}_{job_config.config_id}"
                candidate.interview_id = job_config.config_id
                candidate.save()

            if job_config.resume_json is None:
                job_config.resume_json = {}

            if name:
                job_config.resume_json['name'] = name
            if phone:
                job_config.resume_json['phone'] = phone
            if email:
                job_config.resume_json['email'] = email
            if highest_education:
                job_config.resume_json['highest_education'] = highest_education
            if work_years:
                job_config.resume_json['work_years'] = work_years
            if summary:
                job_config.resume_json['summary'] = summary

            job_config.save()

            return Response({
                'success': True,
                'message': '更新成功',
                'config_id': job_config.config_id,
                'candidate_id': job_config.candidate.candidate_id if job_config.candidate else '',
                'candidate_name': job_config.candidate.name if job_config.candidate else name,
                'candidate_email': job_config.candidate.email if job_config.candidate else email,
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'更新失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
