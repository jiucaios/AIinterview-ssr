import os
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from ..services.session_manager import SessionManager
from ..services.dialogue_engine import DialogueEngine
from ..services.qwen_service import QwenService
from ..models import TalentProfile


class InterviewView(APIView):
    def get(self, request):
        template_path = os.path.join(os.path.dirname(__file__), '..', 'interview.html')
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
            elif action == 'answer_intent':
                return self._classify_answer_intent(request)
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

            profile = TalentProfile.objects.filter(session_id=session_id).first()
            if profile and profile.interview_completed:
                return Response(
                    {'error': '闈㈣瘯宸插畬鎴愶紝涓嶈兘缁х画浣滅瓟', 'interview_completed': True},
                    status=status.HTTP_400_BAD_REQUEST
                )

            session_data = SessionManager.get_session(session_id)
            if not session_data and profile and profile.session_incomplete:
                SessionManager.restore_session_from_profile(profile)
                session_data = SessionManager.get_session(session_id)

            if not session_data:
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

    def _classify_answer_intent(self, request):
        try:
            session_id = request.data.get('session_id')
            utterance = (request.data.get('utterance') or request.data.get('answer') or '').strip()
            question = (request.data.get('question') or '').strip()

            if not session_id:
                return Response(
                    {'error': 'session_id is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not utterance:
                return Response({
                    'intent': 'chat',
                    'should_submit': False,
                    'confidence': 1.0,
                    'reason': 'empty utterance',
                }, status=status.HTTP_200_OK)

            session_data = SessionManager.get_session(session_id)
            dialogue_history = []
            round_name = ''
            if session_data:
                dialogue_history = session_data.get('dialogue_history', [])
                round_index = max(int(session_data.get('current_round', 0)), 0)
                if round_index < len(DialogueEngine.ROUND_CONFIG):
                    round_name = DialogueEngine.ROUND_CONFIG[round_index].get('name', '')
                if not question:
                    for item in reversed(dialogue_history):
                        if item.get('role') == 'assistant' and item.get('content'):
                            question = item.get('content')
                            break

            result = QwenService.classify_interview_utterance(
                question=question,
                utterance=utterance,
                dialogue_history=dialogue_history[-8:],
                round_name=round_name,
            )
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {'error': f'判断回答意图失败: {str(e)}'},
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
                    'round_name': DialogueEngine.ROUND_CONFIG[min(session_data.get('current_round', 0), 5)].get('name'),
                    'round_display_name': DialogueEngine.ROUND_CONFIG[min(session_data.get('current_round', 0), 5)].get('display_name'),
                    'round_objective': DialogueEngine.ROUND_CONFIG[min(session_data.get('current_round', 0), 5)].get('objective'),
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
                'round_name': DialogueEngine.ROUND_CONFIG[min(profile.current_round or 0, 5)].get('name'),
                'round_display_name': DialogueEngine.ROUND_CONFIG[min(profile.current_round or 0, 5)].get('display_name'),
                'round_objective': DialogueEngine.ROUND_CONFIG[min(profile.current_round or 0, 5)].get('objective'),
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