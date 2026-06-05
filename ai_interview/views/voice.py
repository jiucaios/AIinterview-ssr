import os
import base64
import tempfile
import logging
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from ..services.voice_service import voice_service
from ..services.speech_service import SpeechService


class VoiceTTSView(APIView):
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

            audio_data = voice_service.text_to_speech(text, voice, format_type)

            if audio_data:
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
    def post(self, request):
        try:
            if 'audio' not in request.FILES:
                return Response(
                    {'error': '请上传音频文件'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            audio_file = request.FILES['audio']
            language = request.data.get('language', 'zh-CN')

            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_file:
                for chunk in audio_file.chunks():
                    temp_file.write(chunk)
                temp_file_path = temp_file.name

            try:
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
                os.unlink(temp_file_path)

        except Exception as e:
            return Response(
                {'error': f'服务器错误: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SpeechTTSView(APIView):
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

            audio_data = SpeechService.text_to_speech(text)

            if audio_data:
                print(f"[DEBUG] TTS succeeded, audio length: {len(audio_data)} bytes")
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
            logging.error(f"TTS error: {str(e)}", exc_info=True)
            return Response(
                {'error': f'服务器错误: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SpeechASRView(APIView):
    def post(self, request):
        try:
            if 'audio' not in request.FILES:
                return Response(
                    {'error': '请上传音频文件'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            audio_file = request.FILES['audio']
            audio_data = audio_file.read()

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
            logging.error(f"ASR error: {str(e)}", exc_info=True)
            return Response(
                {'error': f'服务器错误: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )