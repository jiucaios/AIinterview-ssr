from typing import Optional, List, Dict, Any
import dashscope
from dashscope import Generation
try:
    from dashscope import MultiModalConversation
except ImportError:
    MultiModalConversation = None
from django.conf import settings
from .prompts import get_prompt


class QwenService:

    @classmethod
    def get_api_key(cls):
        """动态获取API密钥"""
        return getattr(settings, 'DASHSCOPE_API_KEY', '')

    @classmethod
    def get_model(cls, use_advanced: bool = True):
        """动态获取模型名称
        
        Args:
            use_advanced: 是否使用高级模型，True返回QWEN_MODEL，False返回QWEN_MODEL_BASE
        """
        if use_advanced:
            return getattr(settings, 'QWEN_MODEL', 'qwen-plus')
        else:
            return getattr(settings, 'QWEN_MODEL_BASE', 'qwen-plus')

    @classmethod
    def initialize(cls):
        """初始化API密钥"""
        api_key = cls.get_api_key()
        if api_key:
            dashscope.api_key = api_key

    @classmethod
    def generate_question(
        cls,
        system_prompt: str,
        user_message: str,
        dialogue_history: List[Dict[str, str]] = None,
        temperature: float = 0.1,
        max_tokens: int = 500,
        use_advanced_model: bool = True
    ) -> Optional[str]:
        """生成问题或回答
        
        Args:
            system_prompt: 系统提示词
            user_message: 用户消息
            dialogue_history: 对话历史
            temperature: 温度参数
            max_tokens: 最大token数
            use_advanced_model: 是否使用高级模型，默认True
        """
        cls.initialize()
        api_key = cls.get_api_key()
        if not api_key:
            return "未配置API密钥，请检查.env文件中的DASHSCOPE_API_KEY"

        messages = [{'role': 'system', 'content': system_prompt}]
        if dialogue_history:
            for item in dialogue_history:
                messages.append({'role': item.get('role', 'user'), 'content': item.get('content', '')})
        messages.append({'role': 'user', 'content': user_message})

        try:
            model = cls.get_model(use_advanced=use_advanced_model)
            
            # 判断是否是新架构模型（qwen3.x系列都需要使用MultiModalConversation API）
            # 根据阿里云文档，qwen3.6-plus 必须使用 MultiModalConversation API
            is_new_architecture = model.startswith('qwen3')
            
            if is_new_architecture and MultiModalConversation:
                # 使用新架构的MultiModalConversation API
                response = MultiModalConversation.call(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
            else:
                # 使用旧版Generation API
                response = Generation.call(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    result_format='message'
                )
            
            if hasattr(response, 'status_code') and response.status_code == 200:
                if response.output and response.output.choices:
                    content = response.output.choices[0].message.content
                    if content:
                        # 处理多模态API返回的列表类型内容
                        if isinstance(content, list):
                            # 从列表中提取文本内容
                            text_parts = []
                            for item in content:
                                if isinstance(item, dict):
                                    text_parts.append(str(item.get('text', '')))
                                elif isinstance(item, str):
                                    text_parts.append(item)
                                else:
                                    text_parts.append(str(item))
                            content = '\n'.join(text_parts)
                        
                        return cls._clean_response(content)
                    else:
                        return f"API返回内容为空 (模型: {model})"
                else:
                    return f"API返回格式异常，缺少choices"
            elif hasattr(response, 'status_code'):
                error_msg = f"API调用失败，状态码: {response.status_code}"
                if hasattr(response, 'message'):
                    error_msg += f"，错误信息: {response.message}"
                elif hasattr(response, 'code'):
                    error_msg += f"，错误码: {response.code}"
                return error_msg
            else:
                return f"API响应格式异常，无法解析"
                
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            return f"API调用异常: {str(e)}\n{error_trace}"

    @classmethod
    def _clean_response(cls, content: str) -> str:
        """清理响应内容，移除思考过程和多余格式"""
        if not content:
            return content
        
        lines = content.split('\n')
        cleaned_lines = []
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith('**') and stripped.endswith('**'):
                cleaned_lines.append(stripped.strip('*'))
            elif any(prefix in stripped for prefix in ['好的，', '明白了。', '好的，明白了', '我需要', '让我', '首先']):
                continue
            else:
                cleaned_lines.append(stripped)
        
        return '\n'.join(cleaned_lines).strip()

    @classmethod
    def summarize_jd(cls, job_description: str) -> str:
        """对岗位描述(JD)进行精炼摘要"""
        if not job_description or not isinstance(job_description, str):
            return ''
        
        if len(job_description) <= 200:
            return job_description[:200]
        
        system_prompt = "你是一位资深的HR专家，擅长提炼岗位核心要求。"
        prompt_template = get_prompt('jd_summarize')
        user_prompt = prompt_template.format(job_description=job_description)
        
        summary = cls.generate_question(system_prompt, user_prompt, use_advanced_model=False)  # JD摘要使用基础模型
        
        if summary and not summary.startswith('未配置API密钥') and not summary.startswith('API调用'):
            return summary
        
        return job_description[:200]

    @classmethod
    def generate_interview_question(
        cls,
        round_type: str,
        context: dict,
        missing_fields: List[str] = None,
        project_info: dict = None
    ) -> Optional[str]:
        resume = context.get('resume', {})
        
        job_config = context.get('job_config', {})
        target_position = job_config.get('target_position', '') or job_config.get('position', '') or job_config.get('job_title', '')
        job_level = job_config.get('job_level', '') or job_config.get('level', '') or job_config.get('grade', '') or '中级'
        job_description = job_config.get('job_description', '') or job_config.get('requirements', '')
        job_requirement = cls.summarize_jd(job_description)
        
        prompt_params = {
            'hard_field': {
                'target_position': target_position,
                'job_level': job_level,
                'job_requirement': job_requirement,
                'resume_summary': resume.get('summary', '未提供'),
                'missing_fields': '、'.join(missing_fields) if missing_fields else '无'
            },
            'role_verification': {
                'target_position': target_position,
                'job_level': job_level,
                'job_requirement': job_requirement,
                'projects': str(resume.get('projects', []))
            },
            'role_depth': {
                'target_position': target_position,
                'job_level': job_level,
                'job_requirement': job_requirement,
                'projects': str(resume.get('projects', []))
            },
            'skill_deviation': {
                'target_position': target_position,
                'job_level': job_level,
                'job_requirement': job_requirement,
                'skills': str(resume.get('skills', []))
            },
            'language_logic': {
                'target_position': target_position,
                'job_level': job_level,
                'job_requirement': job_requirement,
                'summary': resume.get('summary', '')
            },
            'special_requirement': {
                'target_position': target_position,
                'job_level': job_level,
                'job_requirement': job_requirement,
                'special_reqs': str(job_config.get('special_requirements', []))
            },
        }

        system_prompt = get_prompt('interviewer_system')
        prompt_template = get_prompt(round_type)
        
        if not prompt_template:
            prompt_template = get_prompt('hard_field')
            params = prompt_params.get('hard_field', {})
        else:
            params = prompt_params.get(round_type, {})
        
        user_prompt = prompt_template.format(**params)

        return cls.generate_question(system_prompt, user_prompt, context.get('dialogue_history'))

    @classmethod
    def validate_answer_quality(cls, question: str, answer: str, round_type: str) -> dict:
        if not cls.get_api_key():
            return {'valid': True, 'reason': 'API not configured', 'confidence': 1.0}

        issues = []
        confidence = 1.0

        if len(answer.strip()) < 5:
            issues.append('回答过短')
            confidence *= 0.5

        first_person_indicators = ['我', '本人', '我自己']
        has_first_person = any(indicator in answer for indicator in first_person_indicators)
        if not has_first_person:
            issues.append('缺少第一人称')
            confidence *= 0.9

        typical_patterns = [
            r'负责', r'参与', r'主导', r'完成', r'实现', r'开发', r'设计'
        ]
        pattern_count = sum(1 for p in typical_patterns if p in answer)
        if pattern_count < 1:
            issues.append('缺少典型表述')
            confidence *= 0.95

        if len(answer) > 50 and answer.count('。') < 2:
            issues.append('长回答逻辑性存疑')
            confidence *= 0.95

        is_valid = len(issues) == 0 or confidence > 0.3

        return {
            'valid': is_valid,
            'reason': '; '.join(issues) if issues else '回答有效',
            'confidence': confidence,
            'issues': issues
        }