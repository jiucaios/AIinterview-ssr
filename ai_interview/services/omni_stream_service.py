import asyncio
import json
import dashscope
from dashscope.audio.qwen_omni import (
    AudioFormat,
    MultiModality,
    OmniRealtimeCallback,
    OmniRealtimeConversation,
)
from django.conf import settings
from .token_utils import TokenRecorder

def get_realtime_model():
    return getattr(settings, 'QWEN_REALTIME_MODEL', 'qwen3.5-omni-plus-realtime')

def get_realtime_voice():
    return getattr(settings, 'QWEN_REALTIME_VOICE', 'Sunnybobi')

def get_realtime_url():
    return getattr(settings, 'QWEN_REALTIME_URL', 'wss://dashscope.aliyuncs.com/api-ws/v1/realtime')


class OmniStreamCallback(OmniRealtimeCallback):
    def __init__(self):
        self.transcript = ""
        self.text_delta = ""
        self.audio_chunks = []
        self.done = False
        self.error = None
        self.event = asyncio.Event()
        self.speech_started = False
        self.speech_stopped = False
        self.audio_committed = False
        self.response_created = False

    def on_open(self):
        pass

    def on_close(self, close_status_code, close_msg):
        self.done = True
        self.event.set()

    def on_error(self, error):
        self.error = str(error)
        self.done = True
        self.event.set()

    def on_event(self, message):
        event_type = message.get("type")
        
        # VAD模式事件处理
        if event_type == "input_audio_buffer.speech_started":
            self.speech_started = True
            self.speech_stopped = False
        elif event_type == "input_audio_buffer.speech_stopped":
            self.speech_stopped = True
        elif event_type == "input_audio_buffer.committed":
            self.audio_committed = True
        elif event_type == "response.created":
            self.response_created = True
        
        # 仅输出文本模式
        elif event_type == "response.text.delta":
            delta = message.get("delta", "")
            if delta:
                self.text_delta += delta
        elif event_type == "response.text.done":
            self.transcript = message.get("text", "")
        
        # 输出文本+音频模式
        elif event_type == "response.audio_transcript.delta":
            delta = message.get("delta", "")
            if delta:
                self.text_delta += delta
        elif event_type == "response.audio_transcript.done":
            self.transcript = message.get("transcript", "")
        elif event_type == "response.audio.delta":
            delta = message.get("delta")
            if delta:
                self.audio_chunks.append(delta)
        
        elif event_type == "response.done":
            if not self.transcript:
                self.transcript = self.text_delta
            self.done = True
            self.event.set()
        elif event_type == "error":
            self.error = message.get("message", str(message))
            self.done = True
            self.event.set()


class OmniStreamService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            cls._instance._session = None
            cls._instance._lock = asyncio.Lock()
        return cls._instance

    async def _ensure_session(self):
        if self._session is None or not self._initialized:
            async with self._lock:
                if self._session is None or not self._initialized:
                    await self._create_session()

    async def _create_session(self):
        api_key = getattr(settings, "DASHSCOPE_API_KEY", "")
        if not api_key:
            raise ValueError("DASHSCOPE_API_KEY is not configured")

        dashscope.api_key = api_key
        base_url = getattr(settings, "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com")
        dashscope.base_url = base_url
        model = get_realtime_model()
        url = get_realtime_url()
        voice = get_realtime_voice()
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        self._callback = OmniStreamCallback()
        self._session = OmniRealtimeConversation(
            model=model,
            callback=self._callback,
            url=url,
            headers=headers,
        )

        await asyncio.to_thread(self._session.connect)
        
        await asyncio.to_thread(
            self._session.update_session,
            output_modalities=[MultiModality.TEXT, MultiModality.AUDIO],
            voice=voice,
            input_audio_format=AudioFormat.PCM_16000HZ_MONO_16BIT,
            output_audio_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            enable_input_audio_transcription=True,
            enable_turn_detection=True,
            turn_detection_type="semantic_vad",
            turn_detection_threshold=0.2,
            turn_detection_silence_duration_ms=400,
        )
        
        self._initialized = True

    async def generate_text(self, system_prompt: str, user_message: str, dialogue_history=None):
        await self._ensure_session()
        
        # 重置回调状态
        self._callback.transcript = ""
        self._callback.text_delta = ""
        self._callback.audio_chunks = []
        self._callback.done = False
        self._callback.error = None
        self._callback.speech_started = False
        self._callback.speech_stopped = False
        self._callback.audio_committed = False
        self._callback.response_created = False
        self._callback.event.clear()

        instructions = f"{system_prompt}\n\n请用中文回答，保持简洁自然。"
        
        # 更新会话配置（必须包含voice参数）
        voice = get_realtime_voice()
        await asyncio.to_thread(
            self._session.update_session,
            output_modalities=[MultiModality.TEXT, MultiModality.AUDIO],
            voice=voice,
            instructions=instructions
        )
        
        # 创建消息项
        item = {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": user_message}],
        }
        await asyncio.to_thread(self._session.create_item, item)
        
        # 在VAD模式下，不需要手动调用create_response
        # 服务端会在检测到语音结束后自动生成响应
        # 但是对于文本输入，我们仍然需要手动触发响应
        await asyncio.to_thread(self._session.create_response, 
                               output_modalities=[MultiModality.TEXT, MultiModality.AUDIO])

        try:
            await asyncio.wait_for(self._callback.event.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            return {"text": "请求超时", "error": "Timeout"}

        if self._callback.error:
            return {"text": "", "error": self._callback.error}

        TokenRecorder.record_omni_interview(system_prompt + user_message, self._callback.transcript, get_realtime_model())
        
        return {"text": self._callback.transcript, "audio_chunks": self._callback.audio_chunks}

    async def close(self):
        if self._session:
            try:
                await asyncio.to_thread(self._session.close)
            except Exception:
                pass
            self._session = None
            self._initialized = False


async def generate_text_sync(system_prompt: str, user_message: str, dialogue_history=None):
    service = OmniStreamService()
    try:
        return await service.generate_text(system_prompt, user_message, dialogue_history)
    except Exception as e:
        return {"text": "", "error": str(e)}