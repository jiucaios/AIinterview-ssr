import asyncio
import base64
from typing import Optional, Dict, Any, Generator
import dashscope
from dashscope.audio.qwen_omni import (
    AudioFormat,
    MultiModality,
    OmniRealtimeCallback,
    OmniRealtimeConversation,
)
from django.conf import settings

def get_realtime_model():
    return getattr(settings, 'QWEN_REALTIME_MODEL', 'qwen3.5-omni-plus-realtime')

def get_realtime_voice():
    return getattr(settings, 'QWEN_REALTIME_VOICE', 'Sunnybobi')

def get_realtime_url():
    return getattr(settings, 'QWEN_REALTIME_URL', 'wss://dashscope.aliyuncs.com/api-ws/v1/realtime')


class SpeechService:
    @classmethod
    def get_api_key(cls):
        return getattr(settings, 'DASHSCOPE_API_KEY', '')
    
    @classmethod
    def get_base_url(cls):
        return getattr(settings, 'DASHSCOPE_BASE_URL', 'https://dashscope.aliyuncs.com')

    @classmethod
    def initialize(cls):
        pass

    @classmethod
    def speech_to_text(cls, audio_data: bytes, format: str = 'wav') -> Optional[str]:
        return cls._streaming_asr(audio_data)

    @classmethod
    def _streaming_asr(cls, audio_data: bytes) -> Optional[str]:
        class ASRCallback(OmniRealtimeCallback):
            def __init__(self):
                self.transcript = ""
                self.done = False
                self.event = asyncio.Event()

            def on_open(self):
                pass

            def on_close(self, code, msg):
                self.done = True
                self.event.set()

            def on_event(self, message):
                event_type = message.get("type")
                if event_type == "conversation.item.input_audio_transcription.completed":
                    self.transcript = message.get("transcript", "")
                    self.done = True
                    self.event.set()
                elif event_type == "error":
                    self.done = True
                    self.event.set()

        try:
            api_key = cls.get_api_key()
            if not api_key:
                return None

            dashscope.api_key = api_key
            dashscope.base_url = cls.get_base_url()
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            callback = ASRCallback()
            conv = OmniRealtimeConversation(
                model=get_realtime_model(),
                callback=callback,
                url=get_realtime_url(),
                headers=headers,
            )

            conv.connect()
            conv.update_session(
                output_modalities=[MultiModality.TEXT],
                input_audio_format=AudioFormat.PCM_16000HZ_MONO_16BIT,
                enable_input_audio_transcription=True,
            )

            base64_audio = base64.b64encode(audio_data).decode('utf-8')
            conv.append_audio(base64_audio)
            conv.commit()

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(asyncio.wait_for(callback.event.wait(), timeout=15.0))
            loop.close()

            conv.close()
            return callback.transcript
        except Exception as e:
            return None

    @classmethod
    def text_to_speech(cls, text: str) -> Optional[bytes]:
        return cls._streaming_tts(text)

    @classmethod
    def _streaming_tts(cls, text: str) -> Optional[bytes]:
        class TTSCallback(OmniRealtimeCallback):
            def __init__(self):
                self.audio_chunks = []
                self.done = False
                self.event = asyncio.Event()

            def on_open(self):
                pass

            def on_close(self, code, msg):
                self.done = True
                self.event.set()

            def on_event(self, message):
                event_type = message.get("type")
                if event_type == "response.audio.delta":
                    delta = message.get("delta")
                    if delta:
                        self.audio_chunks.append(base64.b64decode(delta))
                elif event_type == "response.done":
                    self.done = True
                    self.event.set()
                elif event_type == "error":
                    self.done = True
                    self.event.set()

        try:
            api_key = cls.get_api_key()
            if not api_key:
                return None

            dashscope.api_key = api_key
            dashscope.base_url = cls.get_base_url()
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            callback = TTSCallback()
            conv = OmniRealtimeConversation(
                model=get_realtime_model(),
                callback=callback,
                url=get_realtime_url(),
                headers=headers,
            )

            conv.connect()
            conv.update_session(
                output_modalities=[MultiModality.AUDIO],
                voice=get_realtime_voice(),
                output_audio_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            )

            item = {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            }
            conv.create_item(item)
            conv.create_response(output_modalities=[MultiModality.AUDIO])

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(asyncio.wait_for(callback.event.wait(), timeout=15.0))
            loop.close()

            conv.close()
            return b''.join(callback.audio_chunks) if callback.audio_chunks else None
        except Exception as e:
            return None

    @classmethod
    def stream_tts(cls, text: str) -> Generator[bytes, None, None]:
        audio_data = cls.text_to_speech(text)
        if audio_data:
            chunk_size = 1024
            for i in range(0, len(audio_data), chunk_size):
                yield audio_data[i:i+chunk_size]


class StreamingLLMService:
    @classmethod
    def stream_generate(cls, system_prompt: str, user_prompt: str) -> Generator[str, None, None]:
        from .qwen_service import QwenService
        result = QwenService.generate_question(system_prompt, user_prompt)
        if result and not result.startswith('API调用') and not result.startswith('未配置'):
            yield result