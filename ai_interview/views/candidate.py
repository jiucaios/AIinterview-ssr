import os
from urllib.parse import quote
from datetime import timedelta
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.utils import timezone
from ..models import JobConfiguration, Candidate, TalentProfile
from .utils import talent_profiles_for_config, mark_profile_completed_if_finished
from ..services.session_manager import SessionManager
from ..services.external_ai_session import mark_external_session_in_progress
from ..services.interview_types import DISCUSSION, normalize_interview_type
from ..services.url_builder import build_interview_welcome_url, build_start_interview_url
from .hr_auth import HRAuthRequiredMixin
from .hr_auth import HR_AUTH_USERNAME_SESSION_KEY
from ..services.resume_async import (
    RESUME_PARSE_COMPLETED,
    RESUME_PARSE_FAILED,
    RESUME_PARSE_PROCESSING,
    enqueue_resume_parse,
    resume_is_ready,
    resume_is_waiting,
    save_uploaded_resume_file,
)
from ..services.job_match import enqueue_job_match_analysis
from ..services.assessment_groups import assign_assessment_group


class CandidateEntryView(APIView):
    def get(self, request):
        template_path = os.path.join(os.path.dirname(__file__), '..', 'candidate_entry.html')
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return HttpResponse(content, content_type='text/html')
        return HttpResponse("候选人入口页面未找到", status=404)


class CandidateWelcomeView(APIView):
    def get(self, request):
        template_path = os.path.join(os.path.dirname(__file__), '..', 'candidate_welcome.html')
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return HttpResponse(content, content_type='text/html')
        return HttpResponse("候选人面试欢迎页面未找到", status=404)


class HRCreateJobView(HRAuthRequiredMixin, APIView):
    def post(self, request):
        try:
            job_name = request.data.get('job_name', '').strip()
            job_description = request.data.get('job_description', '').strip()
            job_level = request.data.get('job_level', '中级')
            hard_fields = request.data.get('hard_fields', [])
            custom_questions = request.data.get('custom_questions', {})
            if hasattr(request.data, 'getlist'):
                hard_fields = request.data.getlist('hard_fields') or hard_fields
                custom_questions = request.data.getlist('custom_questions') or custom_questions
            interview_type = normalize_interview_type(request.data.get('interview_type'))
            recruitment_requirements = request.data.get('recruitment_requirements', '').strip()
            max_interviews = request.data.get('max_interviews', 1)
            try:
                days_valid = int(request.data.get('days_valid') or 3)
            except (TypeError, ValueError):
                days_valid = 3
            days_valid = max(days_valid, 1)
            candidate_name = request.data.get('candidate_name', '').strip()
            candidate_phone = request.data.get('candidate_phone', '').strip()
            candidate_email = request.data.get('candidate_email', '').strip()
            resume_json = request.data.get('resume_json', {})
            resume_file = request.FILES.get('resume_file') or request.FILES.get('file')
            allow_pending_candidate = str(request.data.get('allow_pending_candidate', '')).strip().lower() in ('1', 'true', 'yes', 'on')
            resume_file_path = ''
            resume_file_name = ''
            resume_parse_status = RESUME_PARSE_COMPLETED

            if not job_name:
                return Response(
                    {'error': '岗位名称不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            config_id = JobConfiguration.generate_config_id()
            pending_resume_identity = bool(resume_file and not resume_json and allow_pending_candidate)
            auto_candidate_name = False
            auto_candidate_email = False
            if pending_resume_identity and not candidate_name:
                base_name = os.path.splitext(getattr(resume_file, 'name', '') or 'resume')[0]
                candidate_name = f'Pending-{base_name}'
                auto_candidate_name = True
            if pending_resume_identity and not candidate_email:
                candidate_email = f'pending_{config_id}@resume.local'
                auto_candidate_email = True

            if not candidate_name:
                return Response(
                    {'error': '候选人姓名不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not candidate_email:
                return Response(
                    {'error': '候选人邮箱不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if interview_type == DISCUSSION:
                hard_fields = []
                custom_questions = []

            if resume_file and not resume_json:
                try:
                    resume_file_path, resume_file_name = save_uploaded_resume_file(resume_file, config_id)
                    resume_parse_status = RESUME_PARSE_PROCESSING
                except ValueError as exc:
                    return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

            expire_at = timezone.now() + timedelta(days=days_valid) if days_valid > 0 else None

            candidate_id = f"{candidate_name}_{candidate_email}"
            candidate, created = Candidate.objects.get_or_create(
                candidate_id=candidate_id,
                defaults={
                    'name': candidate_name,
                    'phone': candidate_phone,
                    'email': candidate_email,
                    'interview_id': config_id
                }
            )

            if not created:
                candidate.interview_id = config_id
                candidate.save()

            job_config = JobConfiguration.objects.create(
                config_id=config_id,
                job_name=job_name,
                job_description=job_description,
                job_level=job_level,
                target_position=job_name,
                interview_type=interview_type,
                recruitment_requirements=recruitment_requirements,
                hard_fields=hard_fields,
                custom_questions=custom_questions,
                max_interviews=1,
                expire_at=expire_at,
                created_by=request.data.get('created_by') or request.session.get(HR_AUTH_USERNAME_SESSION_KEY) or 'system',
                candidate=candidate,
                resume_json=resume_json,
                resume_parse_status=resume_parse_status,
                resume_source_path=resume_file_path
            )
            assessment_group = None
            if not (auto_candidate_name or auto_candidate_email):
                assessment_group = assign_assessment_group(job_config)

            if resume_file_path:
                extra_resume_data = {
                    'name': candidate_name,
                    'phone': candidate_phone,
                    'email': candidate_email,
                    'file_name': resume_file_name,
                    'local_file_path': resume_file_path,
                    '_auto_candidate_name': auto_candidate_name,
                    '_auto_candidate_email': auto_candidate_email,
                }
                transaction.on_commit(
                    lambda: enqueue_resume_parse(config_id, resume_file_path, resume_file_name, extra_resume_data)
                )
            elif resume_json:
                transaction.on_commit(lambda: enqueue_job_match_analysis(config_id))

            interview_url = build_interview_welcome_url(request, config_id)

            return Response({
                'config_id': config_id,
                'job_name': job_name,
                'interview_url': interview_url,
                'expire_at': expire_at.isoformat() if expire_at else None,
                'max_interviews': max_interviews,
                'resume_parse_status': resume_parse_status,
                'assessment_group_id': str(assessment_group.id) if assessment_group else '',
                'assessment_group_label': (
                    '临时组'
                    if assessment_group and assessment_group.is_temporary
                    else (f'第{assessment_group.group_number}评估组' if assessment_group else '')
                ),
                'candidate_name': '' if auto_candidate_name else candidate_name,
                'candidate_email': '' if auto_candidate_email else candidate_email,
                'message': '岗位配置创建成功'
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {'error': f'创建岗位配置失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class JobInfoView(APIView):
    def get(self, request):
        try:
            config_id = request.query_params.get('config_id', '')

            if not config_id:
                return Response(
                    {'error': 'config_id不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                job_config = JobConfiguration.objects.get(config_id=config_id)
            except JobConfiguration.DoesNotExist:
                return Response(
                    {'error': '配置不存在'},
                    status=status.HTTP_404_NOT_FOUND
                )

            if job_config.status != 'active':
                return Response(
                    {'error': '面试链接已关闭'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if job_config.expire_at and job_config.expire_at < timezone.now():
                return Response(
                    {'error': '面试链接已过期'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            job_level = (job_config.job_level or '').strip() or '中级'

            return Response({
                'config_id': config_id,
                'job_name': job_config.job_name,
                'job_level': job_level,
                'interview_type': job_config.interview_type,
                'target_position': job_config.target_position,
                'identity_verification_required': job_config.created_by != 'external',
                'resume_parse_status': job_config.resume_parse_status,
                'resume_ready': resume_is_ready(job_config),
                'resume_parse_error': job_config.resume_parse_error if job_config.resume_parse_status == RESUME_PARSE_FAILED else '',
                'candidate_name': job_config.candidate.name if job_config.candidate else '',
                'candidate_email': job_config.candidate.email if job_config.candidate else '',
                'remaining_interviews': max(job_config.max_interviews - job_config.current_interviews, 0)
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'获取岗位信息失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class VerifyAndStartView(APIView):
    def post(self, request):
        acquired_lock_config_id = None
        try:
            config_id = request.data.get('config_id', '').strip()
            name = request.data.get('name', '').strip()
            email = request.data.get('email', '').strip()

            if not config_id:
                return Response(
                    {'error': 'config_id不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                job_config = JobConfiguration.objects.select_related('candidate').get(config_id=config_id)
            except JobConfiguration.DoesNotExist:
                return Response(
                    {'error': '面试链接无效'},
                    status=status.HTTP_404_NOT_FOUND
                )

            if job_config.created_by == 'external' and job_config.candidate:
                name = name or job_config.candidate.name
                email = email or job_config.candidate.email

            candidate_id = f"{name}_{email}"

            if not name:
                return Response(
                    {'error': '姓名不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not email:
                return Response(
                    {'error': '邮箱不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if job_config.status != 'active':
                return Response(
                    {'error': '面试链接已关闭'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if job_config.expire_at and job_config.expire_at < timezone.now():
                return Response(
                    {'error': '面试链接已过期'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if resume_is_waiting(job_config):
                return Response(
                    {
                        'resume_ready': False,
                        'resume_parse_status': job_config.resume_parse_status,
                        'message': '面试正在准备中，请稍等。'
                    },
                    status=status.HTTP_202_ACCEPTED
                )

            if job_config.resume_parse_status == RESUME_PARSE_FAILED:
                return Response(
                    {
                        'error': job_config.resume_parse_error or '简历解析失败，请联系 HR 重新生成面试链接',
                        'resume_ready': False,
                        'resume_parse_status': job_config.resume_parse_status
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            if job_config.candidate and job_config.created_by != 'external':
                if job_config.candidate.name != name or job_config.candidate.email != email:
                    return Response(
                        {'error': '姓名或邮箱不匹配'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            profiles = [
                mark_profile_completed_if_finished(profile)
                for profile in talent_profiles_for_config(config_id).order_by('-updated_at')
            ]
            completed_profile = next(
                (profile for profile in profiles if profile.interview_completed),
                None
            )
            if completed_profile:
                return Response(
                    {'error': '面试已完成，不能继续作答', 'interview_completed': True},
                    status=status.HTTP_400_BAD_REQUEST
                )

            with transaction.atomic():
                locked_job_config = JobConfiguration.objects.select_for_update().get(config_id=config_id)
                if locked_job_config.is_locked:
                    return Response(
                        {'error': '该面试链接正在使用中，请稍后重试'},
                        status=status.HTTP_423_LOCKED
                    )
                locked_job_config.is_locked = True
                locked_job_config.save(update_fields=['is_locked', 'updated_at'])
                acquired_lock_config_id = config_id
                job_config = locked_job_config

            job_config_dict = {
                'config_id': job_config.config_id,
                'target_position': job_config.target_position,
                'job_level': (job_config.job_level or '').strip() or '中级',
                'job_description': job_config.job_description,
                'interview_type': job_config.interview_type,
                'recruitment_requirements': job_config.recruitment_requirements,
                'special_requirements': [],
                'hard_fields': job_config.hard_fields or [],
                'custom_questions': job_config.custom_questions or {},
            }

            resume_json = job_config.resume_json or {}
            if not resume_json:
                resume_json = {'summary': f'候选人: {name}', 'email': email, 'name': name}

            existing_profile = talent_profiles_for_config(config_id).filter(
                session_incomplete=True,
                interview_completed=False
            ).order_by('-updated_at').first()

            session_id = None
            result = {}

            if existing_profile:
                session_id = SessionManager.restore_session_from_profile(existing_profile)
            else:
                session_id = SessionManager.create_session(
                    candidate_id=candidate_id,
                    resume=resume_json,
                    job_config=job_config_dict,
                    required_hard_fields=job_config.hard_fields,
                    custom_questions=job_config.custom_questions
                )

                job_config.increment_interview_count()

            mark_external_session_in_progress(config_id)

            result['session_id'] = session_id
            result['candidate_id'] = candidate_id
            result['question'] = ''
            result['round_number'] = 0

            interview_url = build_start_interview_url(request, session_id, candidate_id, config_id)
            result['interview_url'] = interview_url

            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            if acquired_lock_config_id:
                SessionManager.release_job_lock(acquired_lock_config_id)
            return Response(
                {'error': f'开始面试失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ReleaseInterviewLockView(APIView):
    def post(self, request):
        try:
            session_id = request.data.get('session_id', '').strip()
            config_id = request.data.get('config_id', '').strip()

            if session_id:
                profile = TalentProfile.objects.filter(session_id=session_id).first()
                if profile and profile.interview_completed:
                    return Response({'success': True, 'interview_completed': True}, status=status.HTTP_200_OK)

                session_data = SessionManager.get_session(session_id)
                if session_data:
                    SessionManager.end_session(session_id, 'exited')
                    return Response({'success': True}, status=status.HTTP_200_OK)

                if profile:
                    config_id = config_id or (profile.job_config or {}).get('config_id', '')

            if config_id:
                SessionManager.release_job_lock(config_id)
                return Response({'success': True}, status=status.HTTP_200_OK)

            return Response(
                {'error': 'session_id or config_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'error': f'释放面试锁失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class VerifyIdentityView(APIView):
    def post(self, request):
        try:
            config_id = request.data.get('config_id', '').strip()
            name = request.data.get('name', '').strip()
            email = request.data.get('email', '').strip()

            if not config_id:
                return Response(
                    {'error': 'config_id不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not name:
                return Response(
                    {'error': '姓名不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not email:
                return Response(
                    {'error': '邮箱不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            candidate_id = f"{name}_{email}"
            try:
                candidate = Candidate.objects.get(candidate_id=candidate_id)
            except Candidate.DoesNotExist:
                return Response(
                    {'error': '未找到匹配的候选人信息'},
                    status=status.HTTP_404_NOT_FOUND
                )

            try:
                job_config = JobConfiguration.objects.get(config_id=config_id)
            except JobConfiguration.DoesNotExist:
                return Response(
                    {'error': '面试链接无效'},
                    status=status.HTTP_404_NOT_FOUND
                )

            if job_config.status != 'active':
                return Response(
                    {'error': '面试链接已关闭'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if job_config.expire_at and job_config.expire_at < timezone.now():
                return Response(
                    {'error': '面试链接已过期'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            profiles = [
                mark_profile_completed_if_finished(profile)
                for profile in talent_profiles_for_config(config_id).order_by('-updated_at')
            ]
            if any(profile.interview_completed for profile in profiles):
                return Response(
                    {'error': '面试已完成，无法重新进入'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            return Response({
                'message': '身份验证成功',
                'candidate_id': candidate.candidate_id,
                'interview_id': config_id
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'身份验证失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
