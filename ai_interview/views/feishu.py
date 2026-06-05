import logging

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..services.feishu_integration import handle_feishu_callback


logger = logging.getLogger(__name__)


class FeishuEventCallbackView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({
            'success': True,
            'service': 'feishu_event_callback',
        })

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}

        challenge = data.get('challenge')
        if challenge and data.get('type') == 'url_verification':
            return Response({'challenge': challenge})

        if data.get('encrypt'):
            logger.warning('Feishu encrypted event received, but decrypt flow is not configured.')
            return Response(
                {
                    'code': 400,
                    'msg': 'Encrypted Feishu events are not configured. Disable encryption or configure Encrypt Key.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        app_id = _extract_app_id(data)
        expected_app_id = (getattr(settings, 'FEISHU_APP_ID', '') or '').strip()
        if expected_app_id and app_id and app_id != expected_app_id:
            logger.warning('Rejected Feishu event for unexpected app_id: %s', app_id)
            return Response(
                {'code': 403, 'msg': 'invalid app_id'},
                status=status.HTTP_403_FORBIDDEN,
            )

        event_type = _extract_event_type(data)
        if event_type:
            logger.info('Feishu event received: %s', event_type)
        else:
            logger.info('Feishu callback received without event_type.')

        response_data, http_status = handle_feishu_callback(data, request)
        return Response(response_data, status=http_status)


def _extract_app_id(data):
    header = data.get('header') if isinstance(data.get('header'), dict) else {}
    return str(header.get('app_id') or data.get('app_id') or '').strip()


def _extract_event_type(data):
    header = data.get('header') if isinstance(data.get('header'), dict) else {}
    event = data.get('event') if isinstance(data.get('event'), dict) else {}
    return str(
        header.get('event_type')
        or data.get('event_type')
        or event.get('type')
        or ''
    ).strip()
