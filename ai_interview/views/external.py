from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import ExternalAISession
from ..services.external_ai_session import (
    bearer_token_valid,
    create_external_session,
    error_response,
)
from ..services.session_manager import SessionManager


class ExternalAISessionCreateView(APIView):
    def post(self, request):
        if not bearer_token_valid(request):
            return Response(
                error_response('UNAUTHORIZED', '鉴权失败'),
                status=status.HTTP_401_UNAUTHORIZED,
            )

        response_data, http_status = create_external_session(request.data, request)
        return Response(response_data, status=http_status)


class ExternalAISessionTranscriptView(APIView):
    def get(self, request, external_session_id):
        if not bearer_token_valid(request):
            return Response(
                {'error_code': 'UNAUTHORIZED', 'error_message': '鉴权失败'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        external_session = ExternalAISession.objects.filter(
            external_session_id=external_session_id
        ).select_related('job_config').first()
        if not external_session or not external_session.job_config:
            return Response(
                {'error_code': 'INVALID_SESSION', 'error_message': 'external_session_id不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )

        profile = _latest_profile_for_external_session(external_session)
        if not profile:
            return Response(
                {'error_code': 'INVALID_SESSION', 'error_message': '面试记录不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({
            'request_id': external_session.request_id,
            'external_session_id': external_session.external_session_id,
            'dialogue_history': profile.dialogue_history or [],
            'qa_records': (profile.profile_data or {}).get('qa_records') or SessionManager.build_qa_records(profile.dialogue_history or []),
        })


class ExternalAISessionReportView(APIView):
    def get(self, request, external_session_id):
        if not bearer_token_valid(request):
            return Response(
                {'error_code': 'UNAUTHORIZED', 'error_message': '鉴权失败'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        external_session = ExternalAISession.objects.filter(
            external_session_id=external_session_id
        ).select_related('job_config').first()
        if not external_session:
            return Response(
                {'error_code': 'INVALID_SESSION', 'error_message': 'external_session_id不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            external_session.result_payload or {
                'request_id': external_session.request_id,
                'external_session_id': external_session.external_session_id,
                'status': external_session.status,
                'result': {},
            }
        )


def _latest_profile_for_external_session(external_session):
    config_id = external_session.job_config.config_id if external_session.job_config else ''
    if not config_id:
        return None
    from .utils import talent_profiles_for_config, mark_profile_completed_if_finished

    profile = talent_profiles_for_config(config_id).order_by('-updated_at').first()
    return mark_profile_completed_if_finished(profile) if profile else None
