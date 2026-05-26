from typing import Optional, Dict, Any, Generator, AsyncGenerator
import dashscope
from dashscope.audio.asr import Transcription
from dashscope.audio.tts import SpeechSynthesizer
from dashscope import Generation
from django.conf import settings


class SpeechService:
    @classmethod
    def get_api_key(cls):
        """动态获取API密钥"""
        return getattr(settings, 'DASHSCOPE_API_KEY', '')

    @classmethod
    def initialize(cls):
        """初始化API密钥"""
        api_key = cls.get_api_key()
        if api_key:
            dashscope.api_key = api_key

    @classmethod
    def speech_to_text(cls, audio_data: bytes, format: str = 'wav') -> Optional[str]:
        """
        使用paraformer-realtime-v1将语音转换为文字
        
        Args:
            audio_data: 音频数据（字节）
            format: 音频格式（wav, mp3, ogg等）
        
        Returns:
            识别出的文字，失败返回None
        """
        import logging
        logger = logging.getLogger(__name__)
        
        cls.initialize()
        api_key = cls.get_api_key()
        if not api_key:
            logger.error("DASHSCOPE_API_KEY not configured")
            return None

        if not audio_data or len(audio_data) == 0:
            logger.error("Empty audio data received")
            return None

        try:
            logger.info(f"Calling ASR with format: {format}, data size: {len(audio_data)} bytes")
            
            response = Transcription.call(
                model='paraformer-realtime-v1',
                file_urls=['data:audio/wav;base64,' + audio_data.hex()],
                format=format,
                sample_rate=16000,
                language='zh'
            )

            logger.info(f"ASR response status: {response.status_code}")
            
            if response.status_code == 200:
                if hasattr(response, 'output') and response.output:
                    if hasattr(response.output, 'result') and response.output.result:
                        text = response.output.result.get('text', '')
                        logger.info(f"ASR recognized text: {text[:50]}...")
                        return text
                    else:
                        logger.warning("ASR response result is None")
                        return ''
                else:
                    logger.warning("ASR response output is None")
                    return ''
            else:
                logger.error(f"ASR API returned status {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"ASR error: {str(e)}", exc_info=True)
            return None

    @classmethod
    def text_to_speech(cls, text: str) -> Optional[bytes]:
        """
        使用cosyvoice-v1将文字转换为语音（使用longxiaochun音色）
        
        Args:
            text: 要合成的文字
        
        Returns:
            音频数据（字节），失败返回None
        """
        import logging
        logger = logging.getLogger(__name__)
        
        cls.initialize()
        api_key = cls.get_api_key()
        if not api_key:
            logger.error("DASHSCOPE_API_KEY not configured")
            return None

        try:
            logger.info(f"Calling TTS with text: {text[:30]}...")
            
            from dashscope.audio.tts_v2 import SpeechSynthesizer
            
            synthesizer = SpeechSynthesizer(
                model='cosyvoice-v1',
                voice='longxiaochun'
            )
            response = synthesizer.call(text)

            if isinstance(response, bytes):
                audio_data = response
            elif hasattr(response, 'get_audio_data'):
                audio_data = response.get_audio_data()
            elif hasattr(response, 'audio'):
                audio_data = response.audio
            else:
                audio_data = None
                
            if audio_data and len(audio_data) > 0:
                logger.info(f"TTS succeeded, audio length: {len(audio_data)} bytes")
                return audio_data
            else:
                logger.error("TTS API returned no audio data")
                return None
        except Exception as e:
            logger.error(f"TTS error: {str(e)}", exc_info=True)
            return None

    

    @classmethod
    def stream_tts(cls, text: str) -> Generator[bytes, None, None]:
        """
        流式文字转语音
        
        Args:
            text: 要合成的文字
        
        Returns:
            音频数据片段生成器
        """
        import logging
        logger = logging.getLogger(__name__)
        
        cls.initialize()
        api_key = cls.get_api_key()
        if not api_key:
            logger.error("DASHSCOPE_API_KEY not configured")
            return

        try:
            synthesizer = SpeechSynthesizer(
                model='sambert-zhide-v1',
                voice='zhide',
                format='wav',
                sample_rate=16000,
                stream=True
            )
            responses = synthesizer.call(text)

            for response in responses:
                if hasattr(response, 'output') and hasattr(response.output, 'audio'):
                    yield response.output.audio
        except Exception as e:
            logger.error(f"Stream TTS error: {str(e)}", exc_info=True)
            return


class StreamingLLMService:
    """流式LLM服务"""
    
    @classmethod
    def stream_generate(cls, system_prompt: str, user_prompt: str) -> Generator[str, None, None]:
        """
        流式生成回答
        
        Args:
            system_prompt: 系统提示
            user_prompt: 用户输入
        
        Returns:
            文本片段生成器
        """
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            SpeechService.initialize()
            
            # 使用配置中的模型名称
            from django.conf import settings
            model_name = getattr(settings, 'QWEN_MODEL', 'qwen-plus')
            
            responses = Generation.call(
                model=model_name,
                prompt=user_prompt,
                system_prompt=system_prompt,
                stream=True
            )
            
            for response in responses:
                if hasattr(response, 'output') and response.output:
                    if hasattr(response.output, 'text') and response.output.text:
                        yield response.output.text
        except Exception as e:
            logger.error(f"Streaming LLM error: {str(e)}", exc_info=True)
            return