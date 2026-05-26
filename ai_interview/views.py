import uuid
import os
import time
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
            
            if not candidate_phone:
                return Response(
                    {'error': '候选人手机号不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 生成唯一的config_id
            config_id = JobConfiguration.generate_config_id()
            
            # 计算过期时间
            expire_at = timezone.now() + timedelta(days=days_valid) if days_valid > 0 else None
            
            # 创建候选人记录（使用config_id作为面试ID）
            candidate_id = f"{candidate_name}_{candidate_phone}"
            candidate, created = Candidate.objects.get_or_create(
                candidate_id=candidate_id,
                defaults={
                    'name': candidate_name,
                    'phone': candidate_phone,
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
            phone = request.data.get('phone', '').strip()
            
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
            
            if not phone:
                return Response(
                    {'error': '手机号不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                job_config = JobConfiguration.objects.select_related('candidate').get(config_id=config_id)
            except JobConfiguration.DoesNotExist:
                return Response(
                    {'error': '面试链接无效'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            candidate_id = f"{name}_{phone}"
            
            if not job_config.is_valid():
                return Response(
                    {'error': '配置已过期或已禁用'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if job_config.candidate:
                if job_config.candidate.name != name or job_config.candidate.phone != phone:
                    return Response(
                        {'error': '姓名或手机号不匹配'},
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
                resume_json = {'summary': f'候选人: {name}', 'phone': phone, 'name': name}
            
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
            phone = request.data.get('phone', '').strip()
            
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
            
            if not phone:
                return Response(
                    {'error': '手机号不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 首先通过姓名和手机号查找候选人
            candidate_id = f"{name}_{phone}"
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
