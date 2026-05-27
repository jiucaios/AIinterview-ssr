import uuid
import os
import time
import mimetypes
from html import escape
from django.http import HttpResponse, JsonResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from django.db import transaction
from django.db.models import F
from .services.session_manager import SessionManager
from .services.dialogue_engine import DialogueEngine
from .services.hard_field_detector import HardFieldDetector
from .services.resume_parser import ResumeParser
from .services.voice_service import voice_service
from .services.speech_service import SpeechService
from .models import TalentProfile, JobConfiguration, Candidate
from datetime import timedelta
from django.utils import timezone


class TestToolView(APIView):
    def get(self, request):
        template_path = os.path.join(os.path.dirname(__file__), 'test_tool.html')
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return HttpResponse(content, content_type='text/html')
        return HttpResponse("测试页面未找到", status=404)


class InterviewView(APIView):
    def get(self, request):
        template_path = os.path.join(os.path.dirname(__file__), 'interview.html')
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return HttpResponse(content, content_type='text/html')
        return HttpResponse("面试页面未找到", status=404)


class InterviewSessionView(APIView):

    def post(self, request):
        try:
            action = request.data.get('action', 'start')

            if action == 'start':
                return self._start_session(request)
            elif action == 'answer':
                return self._process_answer(request)
            elif action == 'resume':
                return self._resume_session(request)
            else:
                return Response(
                    {'error': f'Unknown action: {action}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except Exception as e:
            return Response(
                {'error': f'服务器错误: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _start_session(self, request):
        try:
            candidate_id = request.data.get('candidate_id')
            resume = request.data.get('resume', {})
            job_config = request.data.get('job_config', {})
            required_hard_fields = request.data.get('required_hard_fields', [])

            if not candidate_id:
                return Response(
                    {'error': 'candidate_id is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not resume:
                return Response(
                    {'error': 'resume is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            existing_session = TalentProfile.objects.filter(
                candidate_id=candidate_id,
                session_incomplete=True
            ).order_by('-created_at').first()

            if existing_session:
                session_data = SessionManager.get_session(existing_session.session_id)
                if session_data and session_data.get('state') != 'active':
                    pass
                else:
                    engine = DialogueEngine(existing_session.session_id)
                    if SessionManager.check_timeout(existing_session.session_id):
                        engine._finalize_session()
                    else:
                        current_round = engine.get_current_round()
                        if current_round > 0:
                            return Response({
                                'session_id': existing_session.session_id,
                                'message': '存在未完成的会话',
                                'resumable': True,
                                'current_round': current_round,
                            })

            custom_questions = request.data.get('custom_questions', {})
            session_id = SessionManager.create_session(
                candidate_id=candidate_id,
                resume=resume,
                job_config=job_config,
                required_hard_fields=required_hard_fields,
                custom_questions=custom_questions
            )

            engine = DialogueEngine(session_id)
            result = engine.start_session()

            if 'error' in result:
                return Response(result, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {'error': f'启动会话失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _process_answer(self, request):
        try:
            session_id = request.data.get('session_id')
            answer = request.data.get('answer', '')

            if not session_id:
                return Response(
                    {'error': 'session_id is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not answer:
                return Response(
                    {'error': 'answer is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            session_data = SessionManager.get_session(session_id)
            if not session_data:
                profile = TalentProfile.objects.filter(session_id=session_id).first()
                if profile:
                    return Response({
                        'session_id': session_id,
                        'message': '会话已结束',
                        'session_incomplete': profile.session_incomplete,
                        'already_finished': True,
                    })
                return Response(
                    {'error': 'Session not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            SessionManager.add_dialogue(session_id, 'user', answer)

            engine = DialogueEngine(session_id)
            result = engine.process_answer(answer)

            if 'error' in result:
                return Response(result, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {'error': f'处理回答失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _resume_session(self, request):
        try:
            candidate_id = request.data.get('candidate_id')

            if not candidate_id:
                return Response(
                    {'error': 'candidate_id is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            session_ids = SessionManager.get_sessions_by_candidate_id(candidate_id)

            if not session_ids:
                profile = TalentProfile.objects.filter(
                    candidate_id=candidate_id,
                    session_incomplete=True
                ).order_by('-created_at').first()

                if profile:
                    return Response({
                        'message': '会话已过期，但存在未完成的记录',
                        'candidate_id': candidate_id,
                        'session_id': profile.session_id,
                        'resumable': False,
                        'suggestion': '请创建新的面试会话',
                    })

                return Response(
                    {'error': '未找到该候选人的会话记录'},
                    status=status.HTTP_404_NOT_FOUND
                )

            session_data = None
            target_session_id = None

            for session_id in reversed(session_ids):
                data = SessionManager.get_session(session_id)
                if data:
                    session_data = data
                    target_session_id = session_id
                    break

            if not session_data:
                return Response({
                    'message': '会话数据已过期',
                    'candidate_id': candidate_id,
                    'resumable': False,
                    'suggestion': '请创建新的面试会话',
                })

            engine = DialogueEngine(target_session_id)
            result = engine.resume_session()

            if 'error' in result:
                return Response(result, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {'error': f'重新连接会话失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class InterviewSessionDetailView(APIView):

    def get(self, request, session_id):
        try:
            session_data = SessionManager.get_session(session_id)

            if session_data:
                # 从对话历史中获取最后一个问题
                dialogue_history = session_data.get('dialogue_history', [])
                question = ''
                for item in reversed(dialogue_history):
                    if item.get('role') == 'assistant':
                        question = item.get('content', '')
                        break

                return Response({
                    'session_id': session_id,
                    'candidate_id': session_data.get('candidate_id'),
                    'current_round': session_data.get('current_round', 0),
                    'round': session_data.get('current_round', 0) + 1,
                    'total_rounds': 6,
                    'state': session_data.get('state', 'active'),
                    'question': question,
                    'dialogue_history': dialogue_history,
                    'hard_fields_missing': session_data.get('hard_fields_missing', []),
                    'hard_fields_collected': session_data.get('hard_fields_collected', {}),
                    'project_roles_collected': session_data.get('project_roles_collected', {}),
                }, status=status.HTTP_200_OK)

            profile = TalentProfile.objects.filter(session_id=session_id).first()
            if not profile:
                return Response(
                    {'error': 'Session not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # 从对话历史中获取最后一个问题
            dialogue_history = profile.dialogue_history if profile.dialogue_history else []
            question = profile.last_question if profile.last_question else ''
            if not question and dialogue_history:
                for item in reversed(dialogue_history):
                    if item.get('role') == 'assistant':
                        question = item.get('content', '')
                        break

            return Response({
                'session_id': session_id,
                'candidate_id': profile.candidate_id,
                'current_round': profile.current_round,
                'round': profile.current_round + 1,
                'total_rounds': 6,
                'question': question,
                'session_incomplete': profile.session_incomplete,
                'hard_fields_results': profile.hard_fields_results,
                'project_role_results': profile.project_role_results,
                'confidence_score': profile.confidence_score,
                'profile_data': profile.profile_data,
                'incomplete_reasons': profile.incomplete_reasons,
                'created_at': profile.created_at.isoformat() if profile.created_at else None,
                'updated_at': profile.updated_at.isoformat() if profile.updated_at else None,
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {'error': f'获取会话详情失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def delete(self, request, session_id):
        try:
            SessionManager.delete_session(session_id)
            return Response(
                {'message': 'Session deleted'},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {'error': f'删除会话失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ResumeParserView(APIView):
    """简历解析API端点"""

    def post(self, request):
        try:
            import json
            if 'file' not in request.FILES:
                return Response(
                    {'error': '请上传简历文件', 'debug': {
                        'files_keys': list(request.FILES.keys()),
                        'data_keys': list(request.data.keys()),
                        'content_type': request.content_type
                    }},
                    status=status.HTTP_400_BAD_REQUEST
                )

            file = request.FILES['file']
            file_name = file.name
            save_to_db = request.data.get('save_to_db', False)

            import tempfile
            import datetime
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1]) as temp_file:
                for chunk in file.chunks():
                    temp_file.write(chunk)
                temp_file_path = temp_file.name

            try:
                result = ResumeParser.parse_resume(temp_file_path, file_name)

                if 'error' in result:
                    return Response(
                        {**result, 'debug_info': {
                            'file_name': file_name,
                            'file_size': file.size,
                            'temp_file_path': temp_file_path,
                            'file_extension': os.path.splitext(file_name)[1]
                        }},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                result['file_name'] = file_name
                result['parsed_at'] = datetime.datetime.now().isoformat()

                if save_to_db and result.get('name'):
                    candidate_id = result.get('phone') or result.get('email') or f"CAND_{uuid.uuid4().hex[:8]}"

                    profile = TalentProfile.objects.create(
                        candidate_id=candidate_id,
                        session_id=f"resume_{uuid.uuid4().hex}",
                        session_incomplete=False,
                        raw_resume=result,
                        job_config={},
                        hard_fields_results={},
                        project_role_results={},
                        confidence_score=0.8,
                        incomplete_reasons=[],
                    )
                    result['profile_id'] = str(profile.id)

                return Response(result, status=status.HTTP_200_OK)

            finally:
                os.unlink(temp_file_path)

        except Exception as e:
            return Response(
                {'error': f'服务器错误: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ResumeValidateView(APIView):
    """简历数据验证API端点"""

    def post(self, request):
        try:
            resume_data = request.data.get('resume_data', {})

            validation_result = ResumeParser.validate_resume_data(resume_data)

            return Response(validation_result, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'服务器错误: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class VoiceTTSView(APIView):
    """文字转语音API端点"""

    def post(self, request):
        try:
            text = request.data.get('text', '')
            voice = request.data.get('voice', 'longxiaochun')
            format_type = request.data.get('format', 'mp3')

            if not text:
                return Response(
                    {'error': '文本内容不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # 调用TTS服务
            audio_data = voice_service.text_to_speech(text, voice, format_type)

            if audio_data:
                # 将音频数据编码为base64返回
                base64_audio = voice_service.encode_audio_to_base64(audio_data)
                return Response({
                    'audio_data': base64_audio,
                    'format': format_type,
                    'voice': voice
                }, status=status.HTTP_200_OK)
            else:
                return Response(
                    {'error': '语音合成失败'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        except Exception as e:
            return Response(
                {'error': f'服务器错误: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class VoiceASRView(APIView):
    """语音转文字API端点"""

    def post(self, request):
        try:
            # 获取上传的音频文件
            if 'audio' not in request.FILES:
                return Response(
                    {'error': '请上传音频文件'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            audio_file = request.FILES['audio']
            language = request.data.get('language', 'zh-CN')

            # 保存临时文件
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_file:
                for chunk in audio_file.chunks():
                    temp_file.write(chunk)
                temp_file_path = temp_file.name

            try:
                # 调用ASR服务
                text = voice_service.speech_to_text(temp_file_path, language)

                if text:
                    return Response({
                        'text': text,
                        'language': language
                    }, status=status.HTTP_200_OK)
                else:
                    return Response(
                        {'error': '语音识别失败'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
            finally:
                # 删除临时文件
                os.unlink(temp_file_path)

        except Exception as e:
            return Response(
                {'error': f'服务器错误: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SpeechTTSView(APIView):
    """新的文字转语音API端点（使用speech_service）"""

    def post(self, request):
        try:
            text = request.data.get('text', '')

            if not text:
                return Response(
                    {'error': '文本内容不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            print(f"[DEBUG] TTS request received: {text[:50]}")
            print(f"[DEBUG] API Key configured: {len(settings.DASHSCOPE_API_KEY) > 0}")

            # 调用TTS服务
            audio_data = SpeechService.text_to_speech(text)

            if audio_data:
                print(f"[DEBUG] TTS succeeded, audio length: {len(audio_data)} bytes")
                # 将音频数据编码为base64返回
                import base64
                base64_audio = base64.b64encode(audio_data).decode('utf-8')
                return Response({
                    'audio_base64': base64_audio,
                    'format': 'wav',
                    'success': True
                }, status=status.HTTP_200_OK)
            else:
                print(f"[DEBUG] TTS failed: no audio data returned")
                return Response(
                    {'error': '语音合成失败'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        except Exception as e:
            print(f"[DEBUG] TTS exception: {type(e).__name__}: {str(e)}")
            import logging
            logging.error(f"TTS error: {str(e)}", exc_info=True)
            return Response(
                {'error': f'服务器错误: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SpeechASRView(APIView):
    """新的语音转文字API端点（使用speech_service）"""

    def post(self, request):
        try:
            # 获取上传的音频文件
            if 'audio' not in request.FILES:
                return Response(
                    {'error': '请上传音频文件'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            audio_file = request.FILES['audio']

            # 读取音频数据
            audio_data = audio_file.read()

            # 调用ASR服务
            text = SpeechService.speech_to_text(audio_data, 'wav')

            if text is not None:
                return Response({
                    'text': text
                }, status=status.HTTP_200_OK)
            else:
                return Response(
                    {'error': '语音识别失败'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        except Exception as e:
            import logging
            logging.error(f"ASR error: {str(e)}", exc_info=True)
            return Response(
                {'error': f'服务器错误: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class HRDashboardView(APIView):
    """HR管理页面"""

    def get(self, request):
        template_path = os.path.join(os.path.dirname(__file__), 'hr_dashboard.html')
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return HttpResponse(content, content_type='text/html')
        return HttpResponse("HR管理页面未找到", status=404)


class CandidateManagementView(APIView):
    """候选人管理页面"""

    def get(self, request):
        template_path = os.path.join(os.path.dirname(__file__), 'candidate_management.html')
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return HttpResponse(content, content_type='text/html')
        return HttpResponse("候选人管理页面未找到", status=404)


class CandidateListView(APIView):
    """获取候选人列表API（支持分页）"""

    def get(self, request):
        try:
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 10))

            job_configs = JobConfiguration.objects.select_related('candidate').order_by('-created_at')
            total_count = job_configs.count()

            start = (page - 1) * page_size
            end = start + page_size
            paginated_configs = list(job_configs[start:end])

            candidates = []
            for config in paginated_configs:
                resume_data = config.resume_json if config.resume_json else {}
                candidate_info = {
                    'candidate_id': config.candidate.candidate_id if config.candidate else config.config_id,
                    'name': config.candidate.name if config.candidate else '',
                    'phone': config.candidate.phone if config.candidate else '',
                    'email': resume_data.get('email', ''),
                    'highest_education': resume_data.get('highest_education', '') or resume_data.get('degree', ''),
                    'work_years': resume_data.get('work_years', ''),
                    'job_name': config.job_name,
                    'summary': resume_data.get('summary', ''),
                    'interview_url': f"{request.scheme}://{request.get_host()}/api/interview/entry/?config_id={config.config_id}",
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


class CandidateUpdateView(APIView):
    """更新候选人信息API"""

    def post(self, request):
        try:
            candidate_id = request.data.get('candidate_id', '')
            name = request.data.get('name', '').strip()
            phone = request.data.get('phone', '').strip()
            email = request.data.get('email', '').strip()
            highest_education = request.data.get('highest_education', '').strip()
            work_years = request.data.get('work_years', '').strip()
            job_name = request.data.get('job_name', '').strip()
            summary = request.data.get('summary', '').strip()

            if not candidate_id:
                return Response(
                    {'error': '候选人ID不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            job_configs = JobConfiguration.objects.select_related('candidate').filter(config_id=candidate_id)

            if not job_configs.exists():
                return Response(
                    {'error': '未找到该候选人'},
                    status=status.HTTP_404_NOT_FOUND
                )

            job_config = job_configs.first()

            if job_config.candidate:
                if name:
                    job_config.candidate.name = name
                if phone:
                    job_config.candidate.phone = phone
                job_config.candidate.save()

            if job_config.resume_json is None:
                job_config.resume_json = {}

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
                'message': '更新成功'
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'更新失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


EMAIL_LOGO_FILENAME = 'email-logo.jpg'
EMAIL_CONTACT = 'jiucaios@qq.com'
EMAIL_SUPPORT_PHONE = '17337075112'


def get_email_logo_path():
    return os.path.join(os.path.dirname(__file__), 'images', EMAIL_LOGO_FILENAME)


def build_interview_email_text(candidate_name, job_title, interview_url):
    name = candidate_name or '候选人'
    title = job_title or 'AI应用工程师'
    return (
        f"{name}，您好！\n\n"
        f"感谢您投递我司{title}职位，我们对您的简历印象深刻，现诚邀您参加AI面试\n"
        "请在收到邮件的三天内完成面试，完成AI面试后有机会进入下一阶段。\n\n"
        f"面试链接为：\n{interview_url}\n\n"
        "面试链接已绑定您的个人信息，请勿转发给他人！！！\n\n"
        f"·如果您还有其他疑问，请联系您的专属HR或发送邮件至{EMAIL_CONTACT}\n"
        f"·若遇在面试中遇到技术问题，请致电{EMAIL_SUPPORT_PHONE}以获得技术支持\n\n"
        "成就个体，共创未来"
    )


def build_logo_html(logo_cid, size):
    if logo_cid:
        return (
            f'<img src="cid:{logo_cid}" width="{size}" height="{size}" alt="未来世界 Logo" '
            f'style="display:block;width:{size}px;height:{size}px;object-fit:contain;border:0;">'
        )
    return f'<div style="width:{size}px;height:{size}px;background:#ffffff;"></div>'


def build_interview_email_html(candidate_name, job_title, interview_url, logo_cid=None):
    name = escape(candidate_name or '候选人')
    title = escape(job_title or 'AI应用工程师')
    url = (interview_url or '').strip()
    safe_url = escape(url, quote=True)
    link_html = (
        f'<a href="{safe_url}" target="_blank" '
        'style="color:#1266cc;font-weight:700;text-decoration:none;word-break:break-all;">'
        f'{safe_url}</a>'
        if safe_url else
        '<span style="color:#666666;">面试链接将在此显示</span>'
    )
    top_logo = build_logo_html(logo_cid, 76)
    footer_logo = build_logo_html(logo_cid, 56)

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI面试邀请</title>
</head>
<body style="margin:0;padding:0;background:#eeeeee;font-family:Arial,'Microsoft YaHei',sans-serif;color:#111111;">
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="background:#eeeeee;margin:0;padding:16px 0;">
        <tr>
            <td align="center">
                <table width="960" cellpadding="0" cellspacing="0" role="presentation" style="width:960px;max-width:960px;background:#ffffff;">
                    <tr>
                        <td style="height:132px;padding:28px 34px;background:#ffffff;background-image:linear-gradient(180deg,#e7e7e7 0%,#ffffff 78%);">
                            <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
                                <tr>
                                    <td align="left" valign="top">
                                        <div style="width:76px;height:76px;background:#ffffff;border:1px solid #eeeeee;">{top_logo}</div>
                                    </td>
                                    <td align="right" valign="top" style="padding-top:22px;color:#858585;font-size:34px;line-height:1;font-weight:800;letter-spacing:0;">
                                        未来世界
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <tr>
                        <td align="center" style="padding:28px 0 22px;">
                            <table width="760" cellpadding="0" cellspacing="0" role="presentation" style="width:760px;max-width:760px;">
                                <tr>
                                    <td style="font-size:18px;line-height:2.1;color:#111111;">
                                        <p style="margin:0 0 24px;font-size:21px;line-height:1.8;font-weight:700;">{name}，您好！</p>
                                        <p style="margin:0 0 12px;text-indent:2em;">感谢您投递我司{title}职位，我们对您的简历印象深刻，现诚邀您参加AI面试</p>
                                        <p style="margin:0 0 12px;">请在收到邮件的三天内完成面试，完成AI面试后有机会进入下一阶段。</p>
                                        <p style="margin:4px 0 12px;">面试链接为：</p>
                                        <p style="margin:0 0 12px;">{link_html}</p>
                                        <p style="margin:14px 0 12px;font-size:19px;line-height:1.7;font-weight:800;color:#000000;">面试链接已绑定您的个人信息，请勿转发给他人！！！</p>
                                        <p style="margin:0 0 12px;">·如果您还有其他疑问，请联系您的专属HR或发送邮件至{EMAIL_CONTACT}</p>
                                        <p style="margin:0 0 12px;">·若遇在面试中遇到技术问题，请致电{EMAIL_SUPPORT_PHONE}以获得技术支持</p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <tr>
                        <td align="center" style="padding:0 0 44px;">
                            <table width="760" cellpadding="0" cellspacing="0" role="presentation" style="width:760px;max-width:760px;border-top:1px solid #efefef;">
                                <tr>
                                    <td align="center" style="padding-top:28px;">
                                        <div style="width:56px;height:56px;background:#ffffff;border:1px solid #eeeeee;margin:0 auto 14px;">{footer_logo}</div>
                                        <div style="font-size:21px;color:#111111;line-height:1.5;margin-bottom:8px;">成就个体，共创未来</div>
                                        <div style="font-size:15px;line-height:1.5;color:#006fd6;">
                                            <a href="#" style="color:#006fd6;text-decoration:none;">隐私政策</a> · <a href="#" style="color:#006fd6;text-decoration:none;">保留所有权利</a>
                                        </div>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>'''


def send_message_via_smtp(smtplib, smtp_server, smtp_username, smtp_password, message):
    smtp_timeout = int(os.getenv('SMTP_TIMEOUT', '30'))
    smtp_test_mode = os.getenv('SMTP_TEST_MODE', 'false').strip().lower() in ('1', 'true', 'yes', 'on')

    if smtp_test_mode:
        log_dir = os.path.join(os.path.dirname(__file__), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"email_{time.strftime('%Y%m%d_%H%M%S')}.log")
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write(f"=== 模拟发送邮件 ===\n")
            f.write(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"收件人: {message['To']}\n")
            f.write(f"发件人: {message['From']}\n")
            f.write(f"主题: {message['Subject']}\n")
            f.write(f"\n邮件内容:\n")
            f.write(message.as_string())
        print(f"[测试模式] 邮件已记录到日志文件: {log_file}")
        return

    def send_with_starttls(port):
        server = smtplib.SMTP(smtp_server, port, timeout=smtp_timeout)
        try:
            server.ehlo()
            server.starttls()
            server.ehlo()
            try:
                server.login(smtp_username, smtp_password)
            except smtplib.SMTPAuthenticationError as auth_err:
                raise Exception(f'登录失败: {str(auth_err)}。请检查SMTP账户是否开启了POP3/SMTP服务，以及授权码是否正确。')
            server.sendmail(smtp_username, [message['To']], message.as_string())
            server.quit()
        except smtplib.SMTPServerDisconnected:
            raise Exception('SMTP连接被服务器断开。可能原因：1) 登录失败导致连接关闭 2) 服务器超时')
        except Exception:
            try:
                if server.sock is not None:
                    server.quit()
            except Exception:
                pass
            raise

    def send_with_ssl(port):
        server = smtplib.SMTP_SSL(smtp_server, port, timeout=smtp_timeout)
        try:
            try:
                server.login(smtp_username, smtp_password)
            except smtplib.SMTPAuthenticationError as auth_err:
                raise Exception(f'登录失败: {str(auth_err)}。请检查SMTP账户是否开启了POP3/SMTP服务，以及授权码是否正确。')
            server.sendmail(smtp_username, [message['To']], message.as_string())
            server.quit()
        except smtplib.SMTPServerDisconnected:
            raise Exception('SMTP连接被服务器断开。可能原因：1) 登录失败导致连接关闭 2) 服务器超时')
        except Exception:
            try:
                if server.sock is not None:
                    server.quit()
            except Exception:
                pass
            raise

    errors = []
    try:
        send_with_starttls(587)
        return
    except smtplib.SMTPAuthenticationError as e:
        raise e
    except (smtplib.SMTPException, TimeoutError, OSError) as e:
        errors.append(f'STARTTLS(587): {str(e)}')

    try:
        send_with_ssl(465)
        return
    except smtplib.SMTPAuthenticationError as e:
        raise e
    except (smtplib.SMTPException, TimeoutError, OSError) as e:
        errors.append(f'SSL(465): {str(e)}')

    raise Exception(f'SMTP连接失败: {", ".join(errors)}。可能原因：1) 网络防火墙阻止了SMTP连接 2) SMTP服务器地址或端口配置错误 3) 服务器暂时不可用。')


class SendEmailView(APIView):
    """发送邮件页面"""

    def get(self, request):
        template_path = os.path.join(os.path.dirname(__file__), 'send_email.html')
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return HttpResponse(content, content_type='text/html')
        return HttpResponse("发送邮件页面未找到", status=404)


class SendEmailImageView(APIView):
    """发送邮件页 logo 图片"""

    def get(self, request, filename):
        if filename != EMAIL_LOGO_FILENAME:
            return HttpResponse(status=404)

        image_path = get_email_logo_path()
        if not os.path.exists(image_path):
            return HttpResponse(status=404)

        content_type = mimetypes.guess_type(image_path)[0] or 'application/octet-stream'
        with open(image_path, 'rb') as image_file:
            return HttpResponse(image_file.read(), content_type=content_type)


class SendEmailAPIView(APIView):
    """发送邮件API"""

    def post(self, request):
        try:
            import smtplib
            from email.header import Header
            from email.mime.image import MIMEImage
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from email.utils import formataddr

            email_to = (request.data.get('email_to') or '').strip()
            candidate_name = (request.data.get('candidate_name') or '').strip()
            job_title = (request.data.get('job_title') or 'AI应用工程师').strip()
            subject = (request.data.get('subject') or 'AI面试邀请').strip() or 'AI面试邀请'
            interview_url = (request.data.get('interview_url') or '').strip()

            if not email_to:
                return Response(
                    {'error': '收件人邮箱不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not interview_url:
                return Response(
                    {'error': '面试链接不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            smtp_server = os.getenv('SMTP_SERVER', 'smtp.qq.com')
            smtp_username = os.getenv('SMTP_USERNAME', '2601413168@qq.com')
            smtp_password = os.getenv('SMTP_PASSWORD', 'vybtlcjfbrxrecbj')

            logo_path = get_email_logo_path()
            logo_cid = 'email-logo' if os.path.exists(logo_path) else None
            text_body = build_interview_email_text(candidate_name, job_title, interview_url)
            html_body = build_interview_email_html(candidate_name, job_title, interview_url, logo_cid)

            msg = MIMEMultipart('related')
            msg['From'] = formataddr((str(Header('AI面试系统', 'utf-8')), smtp_username))
            msg['To'] = email_to
            msg['Subject'] = Header(subject, 'utf-8')

            alternative = MIMEMultipart('alternative')
            alternative.attach(MIMEText(text_body, 'plain', 'utf-8'))
            alternative.attach(MIMEText(html_body, 'html', 'utf-8'))
            msg.attach(alternative)

            if logo_cid:
                with open(logo_path, 'rb') as logo_file:
                    logo = MIMEImage(logo_file.read())
                logo.add_header('Content-ID', f'<{logo_cid}>')
                logo.add_header('Content-Disposition', 'inline', filename=EMAIL_LOGO_FILENAME)
                msg.attach(logo)

            send_message_via_smtp(smtplib, smtp_server, smtp_username, smtp_password, msg)

            return Response({
                'success': True,
                'message': '邮件发送成功'
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'发送邮件失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CandidateEntryView(APIView):
    """候选人入口页面"""

    def get(self, request):
        template_path = os.path.join(os.path.dirname(__file__), 'candidate_entry.html')
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return HttpResponse(content, content_type='text/html')
        return HttpResponse("候选人入口页面未找到", status=404)


class HRCreateJobView(APIView):
    """接口A: HR创建岗位配置"""

    def post(self, request):
        try:
            # 获取配置信息
            job_name = request.data.get('job_name', '').strip()
            job_description = request.data.get('job_description', '').strip()
            job_level = request.data.get('job_level', '中级')
            hard_fields = request.data.get('hard_fields', [])
            custom_questions = request.data.get('custom_questions', {})
            max_interviews = request.data.get('max_interviews', 1)
            days_valid = request.data.get('days_valid', 30)
            candidate_name = request.data.get('candidate_name', '').strip()
            candidate_phone = request.data.get('candidate_phone', '').strip()
            candidate_email = request.data.get('candidate_email', '').strip()
            resume_json = request.data.get('resume_json', {})

            # 验证必填字段
            if not job_name:
                return Response(
                    {'error': '岗位名称不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

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

            # 生成唯一的config_id
            config_id = JobConfiguration.generate_config_id()

            # 计算过期时间
            expire_at = timezone.now() + timedelta(days=days_valid) if days_valid > 0 else None

            # 创建候选人记录（使用config_id作为面试ID）
            candidate_id = f"{candidate_name}_{candidate_email}"
            candidate, created = Candidate.objects.get_or_create(
                candidate_id=candidate_id,
                defaults={
                    'name': candidate_name,
                    'phone': candidate_phone,
                    'email': candidate_email,
                    'interview_id': config_id  # 将面试ID关联到候选人
                }
            )

            # 如果候选人已存在，更新面试ID
            if not created:
                candidate.interview_id = config_id
                candidate.save()

            # 创建岗位配置（使用config_id作为面试ID，存储完整简历JSON）
            job_config = JobConfiguration.objects.create(
                config_id=config_id,
                job_name=job_name,
                job_description=job_description,
                job_level=job_level,
                target_position=job_name,
                hard_fields=hard_fields,
                custom_questions=custom_questions,
                max_interviews=1,
                expire_at=expire_at,
                created_by=request.data.get('created_by', 'system'),
                candidate=candidate,
                resume_json=resume_json
            )

            # 构建面试链接
            host = request.get_host()
            protocol = 'https' if request.is_secure() else 'http'
            interview_url = f"{protocol}://{host}/api/interview/entry/?config_id={config_id}"

            return Response({
                'config_id': config_id,
                'job_name': job_name,
                'interview_url': interview_url,
                'expire_at': expire_at.isoformat() if expire_at else None,
                'max_interviews': max_interviews,
                'message': '岗位配置创建成功'
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {'error': f'创建岗位配置失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class JobInfoView(APIView):
    """接口B: 获取岗位信息（公开接口）"""

    def get(self, request):
        try:
            config_id = request.query_params.get('config_id', '')

            if not config_id:
                return Response(
                    {'error': 'config_id不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # 查找配置
            try:
                job_config = JobConfiguration.objects.get(config_id=config_id)
            except JobConfiguration.DoesNotExist:
                return Response(
                    {'error': '配置不存在'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # 入口页只判断链接本身是否可访问；人数上限和完成状态需要身份信息后再判断。
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

            # 返回简要信息（不包含敏感配置）
            return Response({
                'config_id': config_id,
                'job_name': job_config.job_name,
                'job_level': job_config.job_level,
                'target_position': job_config.target_position,
                'remaining_interviews': max(job_config.max_interviews - job_config.current_interviews, 0)
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'获取岗位信息失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class VerifyAndStartView(APIView):
    """接口C: 验证身份并开始面试（核心接口）"""

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

            try:
                job_config = JobConfiguration.objects.select_related('candidate').get(config_id=config_id)
            except JobConfiguration.DoesNotExist:
                return Response(
                    {'error': '面试链接无效'},
                    status=status.HTTP_404_NOT_FOUND
                )

            candidate_id = f"{name}_{email}"

            if not job_config.is_valid():
                return Response(
                    {'error': '配置已过期或已禁用'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if job_config.candidate:
                if job_config.candidate.name != name or job_config.candidate.email != email:
                    return Response(
                        {'error': '姓名或邮箱不匹配'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            job_config_dict = {
                'target_position': job_config.target_position,
                'job_level': job_config.job_level,
                'job_description': job_config.job_description,
                'special_requirements': []
            }

            resume_json = job_config.resume_json or {}
            if not resume_json:
                resume_json = {'summary': f'候选人: {name}', 'email': email, 'name': name}

            session_id = SessionManager.create_session(
                candidate_id=candidate_id,
                resume=resume_json,
                job_config=job_config_dict,
                required_hard_fields=job_config.hard_fields,
                custom_questions=job_config.custom_questions
            )

            job_config.increment_interview_count()

            engine = DialogueEngine(session_id)
            result = engine.start_session()

            result['candidate_id'] = candidate_id

            host = request.get_host()
            protocol = 'https' if request.is_secure() else 'http'
            interview_url = f"{protocol}://{host}/start-interview/?session_id={session_id}&candidate_id={candidate_id}&question={result.get('question', '')}"
            result['interview_url'] = interview_url

            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'开始面试失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class VerifyIdentityView(APIView):
    """验证候选人身份"""

    def post(self, request):
        try:
            config_id = request.data.get('config_id', '').strip()
            name = request.data.get('name', '').strip()
            email = request.data.get('email', '').strip()

            # 验证参数
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

            # 通过姓名和邮箱查找候选人
            candidate_id = f"{name}_{email}"
            try:
                candidate = Candidate.objects.get(candidate_id=candidate_id)
            except Candidate.DoesNotExist:
                return Response(
                    {'error': '未找到匹配的候选人信息'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # 验证面试ID是否匹配
            if candidate.interview_id != config_id:
                return Response(
                    {'error': '面试链接与候选人信息不匹配'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # 查找配置并检查有效性
            try:
                job_config = JobConfiguration.objects.get(config_id=config_id)
            except JobConfiguration.DoesNotExist:
                return Response(
                    {'error': '面试链接无效'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # 只校验有效期和状态；中断恢复不受 current_interviews 限制
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

            # 六轮完成后链接失效
            if TalentProfile.objects.filter(candidate_id=candidate_id, interview_completed=True).exists():
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
