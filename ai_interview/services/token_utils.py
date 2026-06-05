import re
from typing import Optional
from .token_tracker import TokenTracker


class TokenCalculator:
    """Token计算工具类，基于Qwen模型的token编码规则"""
    
    @classmethod
    def count_tokens(cls, text: str, model: str = 'qwen') -> int:
        """
        估算文本的token数量
        
        Qwen模型使用Byte Pair Encoding (BPE)，中文每个字符约为1-2个token
        这里采用简化的估算方法：
        - 中文字符：每个按1.5个token估算
        - 英文字符：每个按0.5个token估算（因为BPE会合并）
        - 数字和标点：每个按0.5个token估算
        """
        if not text or not isinstance(text, str):
            return 0
        
        text = str(text)
        token_count = 0
        
        for char in text:
            if '\u4e00' <= char <= '\u9fff':
                token_count += 2
            elif char.isalpha():
                token_count += 1
            elif char.isdigit():
                token_count += 1
            elif char.isspace():
                continue
            else:
                token_count += 1
        
        return max(1, (token_count + 1) // 2)

    @classmethod
    def estimate_api_tokens(cls, prompt: str, response: str = '', model: str = 'qwen3.6-flash') -> dict:
        """
        估算API调用的token消耗
        """
        input_tokens = cls.count_tokens(prompt)
        output_tokens = cls.count_tokens(response)
        
        return {
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': input_tokens + output_tokens
        }


class TokenRecorder:
    """Token记录器，用于在各个服务中记录token消耗"""
    
    @classmethod
    def record_resume_parsing(cls, prompt: str, response: str, model: str = 'qwen3.6-flash') -> bool:
        """记录简历解析的token消耗"""
        tokens = TokenCalculator.estimate_api_tokens(prompt, response, model)
        return TokenTracker.record_usage(
            category=TokenTracker.CATEGORY_RESUME_PARSING,
            input_tokens=tokens['input_tokens'],
            output_tokens=tokens['output_tokens'],
            model=model,
            metadata={'type': 'resume_parsing'}
        )

    @classmethod
    def record_job_match(cls, prompt: str, response: str, model: str = 'qwen3.7-plus') -> bool:
        """Record token usage for resume-to-job match analysis."""
        tokens = TokenCalculator.estimate_api_tokens(prompt, response, model)
        return TokenTracker.record_usage(
            category=TokenTracker.CATEGORY_JOB_MATCH,
            input_tokens=tokens['input_tokens'],
            output_tokens=tokens['output_tokens'],
            model=model,
            metadata={'type': 'job_match', 'thinking': False}
        )
    
    @classmethod
    def record_omni_interview(
        cls,
        prompt: str,
        response: str,
        model: str = 'qwen3.5-omni-plus-realtime',
        metadata: dict = None,
    ) -> bool:
        """记录Omni语音面试的token消耗"""
        tokens = TokenCalculator.estimate_api_tokens(prompt, response, model)
        record_metadata = {
            'type': 'omni_interview',
            'input_modality': 'audio',
            'output_modality': 'text_audio',
            'input_rate_per_million': 80,
            'output_rate_per_million': 300,
        }
        if metadata:
            record_metadata.update(metadata)
        return TokenTracker.record_usage(
            category=TokenTracker.CATEGORY_OMNI_INTERVIEW,
            input_tokens=tokens['input_tokens'],
            output_tokens=tokens['output_tokens'],
            model=model,
            metadata=record_metadata
        )
    
    @classmethod
    def record_answer_analysis(cls, prompt: str, response: str, model: str = 'qwen3.6-flash') -> bool:
        """记录回答分析的token消耗"""
        tokens = TokenCalculator.estimate_api_tokens(prompt, response, model)
        return TokenTracker.record_usage(
            category=TokenTracker.CATEGORY_ANSWER_ANALYSIS,
            input_tokens=tokens['input_tokens'],
            output_tokens=tokens['output_tokens'],
            model=model,
            metadata={'type': 'answer_analysis'}
        )

    @classmethod
    def record_feishu_assistant(cls, prompt: str, response: str, model: str = 'qwen3.7-plus') -> bool:
        """记录飞书助手的token消耗"""
        tokens = TokenCalculator.estimate_api_tokens(prompt, response, model)
        return TokenTracker.record_usage(
            category=TokenTracker.CATEGORY_FEISHU_ASSISTANT,
            input_tokens=tokens['input_tokens'],
            output_tokens=tokens['output_tokens'],
            model=model,
            metadata={'type': 'feishu_assistant', 'thinking': False}
        )
    
    @classmethod
    def record_with_category(cls, category: str, prompt: str, response: str, model: str = '') -> bool:
        """通用记录方法，按类别记录token消耗"""
        tokens = TokenCalculator.estimate_api_tokens(prompt, response, model)
        return TokenTracker.record_usage(
            category=category,
            input_tokens=tokens['input_tokens'],
            output_tokens=tokens['output_tokens'],
            model=model,
            metadata={'type': category}
        )


def token_decorator(category: str, model: str = ''):
    """
    装饰器：用于自动记录函数调用的token消耗
    
    使用示例：
    @token_decorator(category=TokenTracker.CATEGORY_RESUME_PARSING, model='qwen3.6-flash')
    def parse_resume(text):
        result = call_api(text)
        return result
    
    注意：装饰器会尝试从函数参数中提取prompt和response
    期望函数返回字典包含 'text' 或 'response' 字段，或者直接返回字符串
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            prompt = ""
            
            for arg in args:
                if isinstance(arg, str):
                    prompt += str(arg) + " "
            
            for key, value in kwargs.items():
                if isinstance(value, str):
                    prompt += str(value) + " "
            
            result = func(*args, **kwargs)
            
            response = ""
            if isinstance(result, dict):
                response = str(result.get('text', '') or result.get('response', '') or result.get('result', ''))
            elif isinstance(result, str):
                response = result
            
            try:
                TokenRecorder.record_with_category(category, prompt, response, model)
            except Exception as e:
                pass
            
            return result
        return wrapper
    return decorator
