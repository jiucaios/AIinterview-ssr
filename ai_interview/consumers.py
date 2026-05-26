import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .services.session_manager import SessionManager
from .services.dialogue_engine import DialogueEngine
from .services.speech_service import SpeechService, StreamingLLMService
from .services.prompts import INTERVIEWER_SYSTEM_PROMPT


class VoiceInterviewConsumer(AsyncWebsocketConsumer):
    """流式语音面试WebSocket消费者"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_id = None
        self.candidate_id = None
        self.is_recording = False
        self.audio_buffer = bytearray()
        self.asr_session = None
        self.tts_queue = asyncio.Queue()
        self.tts_task = None
    
    async def connect(self):
        await self.accept()
        await self.send(text_data=json.dumps({
            'type': 'connected',
            'message': 'WebSocket连接已建立'
        }))
    
    async def disconnect(self, close_code):
        if self.tts_task:
            self.tts_task.cancel()
        if self.asr_session:
            self.asr_session = None
    
    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get('type', '')
            
            if message_type == 'start_session':
                await self.handle_start_session(data)
            elif message_type == 'audio_chunk':
                await self.handle_audio_chunk(data)
            elif message_type == 'text_message':
                await self.handle_text_message(data)
            elif message_type == 'end_recording':
                await self.handle_end_recording()
            else:
                await self.send_error(f"未知消息类型: {message_type}")
        except Exception as e:
            await self.send_error(f"消息处理错误: {str(e)}")
    
    async def handle_start_session(self, data):
        try:
            self.session_id = data.get('session_id')
            self.candidate_id = data.get('candidate_id', 'unknown')
            
            await self.send(text_data=json.dumps({
                'type': 'session_started',
                'session_id': self.session_id,
                'message': '会话已开始'
            }))
        except Exception as e:
            await self.send_error(f"启动会话失败: {str(e)}")
    
    async def handle_audio_chunk(self, data):
        try:
            audio_data = data.get('audio', '')
            if audio_data:
                self.audio_buffer.extend(bytes.fromhex(audio_data))
            
            if len(self.audio_buffer) > 1024 * 1024:
                await self.process_audio()
        except Exception as e:
            await self.send_error(f"处理音频失败: {str(e)}")
    
    async def handle_text_message(self, data):
        try:
            text = data.get('text', '')
            if not text:
                return
            
            response = await self.generate_response(text)
            await self.send(text_data=json.dumps({
                'type': 'response',
                'text': response
            }))
        except Exception as e:
            await self.send_error(f"处理文本消息失败: {str(e)}")
    
    async def handle_end_recording(self):
        try:
            if len(self.audio_buffer) > 0:
                await self.process_audio()
            self.audio_buffer = bytearray()
        except Exception as e:
            await self.send_error(f"结束录音失败: {str(e)}")
    
    async def process_audio(self):
        try:
            audio_data = bytes(self.audio_buffer)
            self.audio_buffer = bytearray()
            
            text = await self.recognize_speech(audio_data)
            if text:
                await self.send(text_data=json.dumps({
                    'type': 'asr_result',
                    'text': text
                }))
                
                response = await self.generate_response(text)
                await self.send(text_data=json.dumps({
                    'type': 'response',
                    'text': response
                }))
                
                audio_bytes = await self.synthesize_speech(response)
                if audio_bytes:
                    await self.send(text_data=json.dumps({
                        'type': 'tts_audio',
                        'audio': audio_bytes.hex()
                    }))
        except Exception as e:
            await self.send_error(f"处理音频失败: {str(e)}")
    
    @database_sync_to_async
    def recognize_speech(self, audio_data):
        return SpeechService.speech_to_text(audio_data, 'wav')
    
    @database_sync_to_async
    def generate_response(self, text):
        try:
            engine = DialogueEngine(self.session_id)
            response = engine.generate_response(text)
            return response
        except Exception as e:
            return f"生成响应失败: {str(e)}"
    
    @database_sync_to_async
    def synthesize_speech(self, text):
        return SpeechService.text_to_speech(text)
    
    async def send_error(self, message):
        await self.send(text_data=json.dumps({
            'type': 'error',
            'message': message
        }))