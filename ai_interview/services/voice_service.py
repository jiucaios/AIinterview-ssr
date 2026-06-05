"""
语音服务模块
提供TTS（文字转语音）和ASR（语音转文字）功能
"""
import os
import base64
import tempfile
from typing import Optional
from django.conf import settings


class VoiceService:
    """语音服务类，处理TTS和ASR功能"""
    
    def __init__(self):
        self.api_key = getattr(settings, 'DASHSCOPE_API_KEY', '')
        if not self.api_key:
            from dotenv import load_dotenv
            load_dotenv()
            self.api_key = os.getenv('DASHSCOPE_API_KEY', '')
    
    def text_to_speech(self, text: str, voice: str = "longxiaochun", 
                      format: str = "mp3", sample_rate: int = 22050) -> Optional[bytes]:
        """
        将文字转换为语音
        
        Args:
            text: 要转换的文字
            voice: 语音角色，默认使用longxiaochun
            format: 输出格式，默认mp3
            sample_rate: 采样率，默认22050
            
        Returns:
            音频数据的字节流，失败返回None
        """
        try:
            import dashscope
            from dashscope.audio.tts_v2 import SpeechSynthesizer
            
            dashscope.api_key = self.api_key
            dashscope.base_url = self.base_url
            
            print(f"开始TTS合成: text='{text[:20]}...', model=cosyvoice-v1, voice={voice}")
            
            # 使用阿里云CosyVoice TTS API - 创建实例后调用
            synthesizer = SpeechSynthesizer(
                model='cosyvoice-v1',
                voice=voice  # 使用传入的音色参数
            )
            
            response = synthesizer.call(text)
            
            print(f"TTS响应类型: {type(response)}")
            
            if response is not None:
                # 获取音频数据
                if hasattr(response, 'get_audio_data'):
                    audio_data = response.get_audio_data()
                elif hasattr(response, 'audio'):
                    audio_data = response.audio
                else:
                    audio_data = response
                    
                if audio_data and len(audio_data) > 0:
                    print(f"TTS合成成功，音频大小: {len(audio_data)} bytes")
                    return audio_data
                else:
                    print("TTS合成失败: 音频数据为空")
                    return None
            else:
                print("TTS合成失败: 响应为None")
                return None
                
        except Exception as e:
            print(f"TTS合成异常: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def speech_to_text(self, audio_file_path: str, language: str = "zh-CN") -> Optional[str]:
        """
        将语音文件转换为文字（使用本地ASR或调用API）
        
        Args:
            audio_file_path: 音频文件路径
            language: 语言代码，默认中文
            
        Returns:
            识别出的文字，失败返回None
        """
        try:
            # 这里可以使用本地的语音识别库，如SpeechRecognition
            # 或者调用阿里云的ASR API
            import speech_recognition as sr
            
            recognizer = sr.Recognizer()
            
            with sr.AudioFile(audio_file_path) as source:
                audio_data = recognizer.record(source)
                
            # 使用Google Web Speech API进行识别（需要网络）
            # 也可以使用其他离线ASR引擎
            text = recognizer.recognize_google(audio_data, language=language)
            return text
            
        except Exception as e:
            print(f"ASR识别异常: {str(e)}")
            # 如果本地ASR失败，可以尝试调用阿里云ASR API
            return self._aliyun_asr(audio_file_path, language)
    
    def _aliyun_asr(self, audio_file_path: str, language: str = "zh-CN") -> Optional[str]:
        """
        使用阿里云ASR API进行语音识别
        
        Args:
            audio_file_path: 音频文件路径
            language: 语言代码
            
        Returns:
            识别出的文字，失败返回None
        """
        try:
            import dashscope
            from dashscope.audio.asr import Recognition
            
            dashscope.api_key = self.api_key
            dashscope.base_url = self.base_url
            
            # 读取音频文件
            with open(audio_file_path, 'rb') as f:
                audio_data = f.read()
            
            # 调用ASR API
            result = Recognition.call(
                model='paraformer-realtime-v1',
                audio=audio_data,
                format='wav',
                sample_rate=16000,
                language=language
            )
            
            if result.get('status_code') == 200:
                # 解析识别结果
                text = result.get('output', {}).get('text', '')
                return text
            else:
                print(f"ASR识别失败: {result.get('message', '未知错误')}")
                return None
                
        except Exception as e:
            print(f"阿里云ASR调用异常: {str(e)}")
            return None
    
    def save_audio_to_file(self, audio_data: bytes, format: str = "mp3") -> Optional[str]:
        """
        将音频数据保存到临时文件
        
        Args:
            audio_data: 音频数据字节流
            format: 文件格式
            
        Returns:
            临时文件路径，失败返回None
        """
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{format}') as temp_file:
                temp_file.write(audio_data)
                return temp_file.name
        except Exception as e:
            print(f"保存音频文件异常: {str(e)}")
            return None
    
    def encode_audio_to_base64(self, audio_data: bytes) -> str:
        """
        将音频数据编码为base64字符串
        
        Args:
            audio_data: 音频数据字节流
            
        Returns:
            base64编码的字符串
        """
        return base64.b64encode(audio_data).decode('utf-8')
    
    def decode_audio_from_base64(self, base64_string: str) -> bytes:
        """
        从base64字符串解码音频数据
        
        Args:
            base64_string: base64编码的字符串
            
        Returns:
            音频数据字节流
        """
        return base64.b64decode(base64_string)


# 全局语音服务实例
voice_service = VoiceService()
