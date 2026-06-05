import asyncio
import re
from typing import Optional, List, Dict, Any
import json
from django.conf import settings
from .prompts import get_prompt
from .omni_stream_service import generate_text_sync
from .token_utils import TokenRecorder


class QwenService:

    @classmethod
    def get_api_key(cls):
        return getattr(settings, 'DASHSCOPE_API_KEY', '')

    @classmethod
    def get_model(cls, use_advanced: bool = True):
        return 'qwen3.5-omni-plus-realtime'

    @classmethod
    def get_text_model(cls):
        return getattr(settings, 'QWEN_TEXT_MODEL', 'qwen3.6-flash')

    @classmethod
    def initialize(cls):
        pass

    @classmethod
    def _generate_streaming(cls, system_prompt: str, user_message: str, dialogue_history=None):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(
                generate_text_sync(system_prompt, user_message, dialogue_history)
            )
            loop.close()
            return result
        except Exception as e:
            return {"text": "", "error": str(e)}

    @classmethod
    def _generate_text_model(cls, system_prompt: str, user_message: str, temperature=0.1, max_tokens=2000):
        try:
            import dashscope
            from dashscope import Generation
            
            api_key = cls.get_api_key()
            if not api_key:
                return {"text": "", "error": "API key not configured"}
            
            base_url = getattr(settings, 'DASHSCOPE_BASE_URL', 'https://dashscope.aliyuncs.com')
            dashscope.api_key = api_key
            dashscope.base_url = base_url
            
            model = cls.get_text_model()
            
            response = Generation.call(
                model=model,
                prompt=user_message,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            
            # 处理两种不同的响应格式
            if response.status_code == 200:
                # qwen-plus等模型使用 output.text
                if hasattr(response.output, 'text') and response.output.text:
                    return {"text": response.output.text, "error": ""}
                # qwen3.5-plus等模型使用 output.choices[0].message.content
                elif hasattr(response.output, 'choices') and response.output.choices:
                    return {"text": response.output.choices[0].message.content, "error": ""}
                # 其他情况
                else:
                    error_msg = f"API返回内容为空或格式异常: {response.output}"
                    return {"text": "", "error": error_msg}
            else:
                error_msg = f"API error: {response.message}" if response.message else "Unknown error"
                return {"text": "", "error": error_msg}
        except Exception as e:
            return {"text": "", "error": str(e)}

    @classmethod
    def generate_question(
        cls,
        system_prompt: str,
        user_message: str,
        dialogue_history: List[Dict[str, str]] = None,
        temperature: float = 0.1,
        max_tokens: int = 500,
        use_advanced_model: bool = True,
        enable_thinking: Optional[bool] = None
    ) -> Optional[str]:
        api_key = cls.get_api_key()
        if not api_key:
            return "未配置API密钥，请检查.env文件中的DASHSCOPE_API_KEY"

        if use_advanced_model:
            result = cls._generate_streaming(system_prompt, user_message, dialogue_history)
        else:
            result = cls._generate_text_model(system_prompt, user_message, temperature, max_tokens)
        
        if result.get("error"):
            return f"API调用失败: {result['error']}"
        
        text = result.get("text", "")
        if text:
            return cls._clean_response(text)
        else:
            return "API返回内容为空"

    @classmethod
    def _clean_response(cls, content: str) -> str:
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
        if not job_description or not isinstance(job_description, str):
            return ''
        
        if len(job_description) <= 200:
            return job_description[:200]

        if not getattr(settings, 'JD_SUMMARY_ENABLED', False):
            return job_description[:200]
        
        system_prompt = "你是一位资深的HR专家，擅长提炼岗位核心要求。"
        prompt_template = get_prompt('jd_summarize')
        user_prompt = prompt_template.format(job_description=job_description)
        
        summary = cls.generate_question(system_prompt, user_prompt, use_advanced_model=False)
        
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
        project_focus = project_info or {}
        project_focus_text = json.dumps(project_focus, ensure_ascii=False) if project_focus else '无指定项目，请基于简历综合推断'
        all_projects_text = json.dumps(resume.get('projects', []), ensure_ascii=False)
        
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
                'projects': project_focus_text
            },
            'role_depth': {
                'target_position': target_position,
                'job_level': job_level,
                'job_requirement': job_requirement,
                'projects': project_focus_text
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
        dialogue_history = context.get('dialogue_history') or []
        previous_questions = [
            item.get('content', '').strip()
            for item in dialogue_history
            if item.get('role') == 'assistant' and item.get('content')
        ]
        previous_questions_text = '\n'.join(f"- {question}" for question in previous_questions[-5:]) or '无'
        
        round_focus = {
            'hard_field': '硬性指标补全 - 确认基本背景信息（如学历、工作年限、技术栈匹配度）',
            'role_verification': '项目角色真实性 - 验证候选人是否真正参与了该项目并担任所描述的角色',
            'role_depth': '项目角色深度 - 考察候选人在项目中的实际贡献深度和技术决策能力',
            'skill_deviation': '技能偏差 - 验证候选人技能描述的真实性，特别是简历中提到的技术栈',
            'language_logic': '语言逻辑 - 评估候选人的表达逻辑性和条理性',
            'special_requirement': '岗位特殊要求 - 针对岗位描述中的特定要求进行提问'
        }
        
        round_order = {
            'hard_field': (1, '硬性指标补全', '确认基本背景信息'),
            'role_verification': (2, '项目角色真实性', '验证项目经历真实性'),
            'role_depth': (3, '项目角色深度', '考察实际贡献深度'),
            'skill_deviation': (4, '技能偏差', '验证技能掌握程度'),
            'language_logic': (5, '语言逻辑', '评估表达能力'),
            'special_requirement': (6, '岗位特殊要求', '针对特定要求提问'),
        }
        round_num, round_display_name, round_objective = round_order.get(round_type, (0, round_type, ''))

        user_prompt += f"""
当前是第 {round_num}/6 轮：{round_display_name}
本轮目标：{round_objective}

当前轮次：{round_type}
轮次考察重点：{round_focus.get(round_type, '未知轮次')}

输出风格额外要求：
- 这不是笔试题，也不是题库播报；请生成一句适合语音聊天场景的自然面试提问。
- 当前是在生成一个新的结构化轮次问题，不是对上一题继续追问。
- **重要**：每一轮必须围绕当前轮次的考察重点提问，不能重复之前的提问角度。
- 不要沿着上一题继续深挖，不要重复已问过的问题；请围绕当前轮次要求，结合简历和岗位信息重新选择提问角度。
- 每一轮必须符合六轮结构中的当前轮次侧重点，不能把上一轮的考察点带到下一轮。
- 如果当前轮次给出了指定项目，请优先围绕指定项目提问；如果指定项目和已问问题涉及的项目不同，必须切换到指定项目。
- 如果简历有多个项目，项目真实性和项目深度两轮尽量选择不同项目、不同能力侧重点；只有一个项目或没有项目时，才基于同一项目或简历整体推断。
- 问题要像面试官基于候选人简历顺势聊出来的，可以有轻微承接，但不要寒暄过多。
- 保持原考察维度和事实约束不变，不要添加简历或岗位要求中没有的信息。
- 不要使用"请你回答""本题""第几题""请说明以下问题"等机械表达。
- 只输出最终要说给候选人的一句话或两句话，不要输出分析过程。
- **关键**：必须生成与之前轮次完全不同的问题，不要重复任何一个已问过的问题。

指定项目焦点：{project_focus_text}
简历全部项目：{all_projects_text}
已问过的问题（必须避免重复）：
{previous_questions_text}
"""

        return cls.generate_question(system_prompt, user_prompt, None)

    @classmethod
    def classify_interview_utterance(
        cls,
        question: str,
        utterance: str,
        dialogue_history: List[Dict[str, str]] = None,
        round_name: str = ''
    ) -> Dict[str, Any]:
        text = (utterance or '').strip()
        if not text:
            return {
                'intent': 'chat',
                'should_submit': False,
                'should_advance': False,
                'confidence': 1.0,
                'reason': 'empty utterance',
            }

        compact_text = re.sub(r'[\s，。！？,.!?、]', '', text.lower())
        if re.search(r'不会|不懂|不知道|不清楚|没做过|没有接触|答不上来|不会答|不了解', compact_text):
            return {
                'intent': 'give_up',
                'should_submit': False,
                'should_advance': True,
                'confidence': 0.95,
                'reason': '候选人明确表示不会或不了解',
                'model': cls.get_model(use_advanced=True),
            }

        system_prompt = (
            "你是实时语音面试中的回答完成度裁判。"
            "请判断候选人刚刚这句话是否已经基本构成本轮问题的答案。"
            "你只做分类，不评价优劣，不生成追问。"
        )
        user_prompt = f"""
当前本轮考察目标或问题：
{question}

候选人刚刚说的话：
{text}

判断标准：
1. intent=answer：内容在尝试回答本轮问题，包含可记录的信息，即使不完美、较短或需要后续追问，也算答案。
2. intent=chat：明显不是答案，例如“等一下”“稍等”“我想一下”“再说一遍”“没听清”“这题什么意思”“可以解释一下吗”“好的”等流程性、澄清性、等待性话语。
3. intent=unclear：太短或语义不完整，暂时不能判断为答案，也不能明确算普通插话。
4. 只有 intent=answer 时 should_submit 才为 true。
5. 不要因为答案质量一般就判为 chat；质量由后续流程处理。这里仅判断“是不是答案”。

请只输出 JSON，不要输出 Markdown：
{{"intent":"answer|chat|unclear","should_submit":true|false,"confidence":0到1,"reason":"一句简短中文原因"}}
"""
        raw = cls.generate_question(
            system_prompt,
            user_prompt,
            dialogue_history=dialogue_history or [],
            temperature=0,
            max_tokens=160,
            use_advanced_model=True,
            enable_thinking=False,
        )
        
        TokenRecorder.record_answer_analysis(system_prompt + user_prompt, raw or '', cls.get_model(use_advanced=True))

        try:
            cleaned = (raw or '').strip()
            if cleaned.startswith('```'):
                cleaned = cleaned.strip('`')
                cleaned = cleaned.replace('json', '', 1).strip()
            result = json.loads(cleaned)
        except Exception:
            normalized = text.replace('，', '').replace('。', '').replace('？', '').replace('?', '').strip()
            non_answer_phrases = [
                '等一下', '稍等', '等会', '我想一下', '让我想想',
                '再说一遍', '重复一下', '没听清', '没听见',
                '什么意思', '没听懂', '不太懂', '解释一下',
                '好的', '嗯', '啊', '可以'
            ]
            is_chat = len(normalized) < 5 or any(phrase in normalized for phrase in non_answer_phrases)
            result = {
                'intent': 'chat' if is_chat else 'answer',
                'should_submit': not is_chat,
                'confidence': 0.35,
                'reason': 'model parse fallback',
            }

        intent = result.get('intent', 'unclear')
        if intent not in {'answer', 'chat', 'unclear', 'wait', 'repeat', 'clarify', 'give_up'}:
            intent = 'unclear'
        should_submit = bool(result.get('should_submit')) and intent == 'answer'
        should_advance = bool(result.get('should_advance')) or intent == 'give_up'
        return {
            'intent': intent,
            'should_submit': should_submit,
            'should_advance': should_advance,
            'confidence': float(result.get('confidence') or 0),
            'reason': str(result.get('reason') or ''),
            'model': cls.get_model(use_advanced=True),
        }

    @classmethod
    def evaluate_answer_relevance(cls, question: str, answer: str, record_token: bool = True) -> dict:
        question = (question or '').strip()
        answer = (answer or '').strip()

        if not answer:
            return {'score': 0, 'reason': 'empty answer'}

        if not cls.get_api_key():
            question_tokens = set(re.findall(r'[\w\u4e00-\u9fff]+', question.lower()))
            answer_tokens = set(re.findall(r'[\w\u4e00-\u9fff]+', answer.lower()))
            overlap = len(question_tokens & answer_tokens)
            base = 55 if len(answer) >= 10 else 25
            score = min(100, base + overlap * 8)
            return {'score': score, 'reason': 'API not configured; used local fallback'}

        system_prompt = '你是一个专业的面试官。请根据用户的问题，评估候选人的回答是否切题。忽略语法错误，重点关注语义相关性。请直接返回一个0到100之间的数字，不要包含其他文字。'
        user_prompt = f'问题：{question}\n回答：{answer}'
        raw = cls.generate_question(
            system_prompt,
            user_prompt,
            temperature=0,
            max_tokens=20,
            use_advanced_model=False,
        )
        
        if record_token:
            TokenRecorder.record_answer_analysis(system_prompt + user_prompt, raw or '', cls.get_text_model())
        
        match = re.search(r'\d+(?:\.\d+)?', raw or '')
        if not match:
            return {'score': 50, 'reason': f'unparseable model score: {raw}'}

        score = int(round(float(match.group(0))))
        score = max(0, min(100, score))
        return {'score': score, 'reason': 'model relevance score'}

    @classmethod
    def validate_answer_quality(cls, question: str, answer: str, round_type: str, record_token: bool = True) -> dict:
        question = (question or '').strip()
        answer = (answer or '').strip()
        round_type = (round_type or '').strip()

        if not answer:
            return {
                'valid': False,
                'reason': '候选人没有提供可评估的回答。',
                'confidence': 0,
                'score': 0,
                'dimensions': [
                    {'name': '问题相关性', 'score': 0, 'comment': '没有回答，无法判断是否切题。'},
                    {'name': '具体性与证据', 'score': 0, 'comment': '没有项目细节、数据或例子。'},
                    {'name': '岗位匹配度', 'score': 0, 'comment': '没有体现与岗位要求相关的能力。'},
                    {'name': '逻辑表达', 'score': 0, 'comment': '没有形成完整表达。'},
                    {'name': '真实性线索', 'score': 0, 'comment': '没有第一人称经历或可追问线索。'},
                ],
                'strengths': [],
                'risks': ['未回答问题'],
                'suggestion': '建议继续追问候选人，让其补充具体经历、个人职责和结果数据。',
                'issues': ['未回答问题'],
            }

        if not cls.get_api_key():
            score_result = cls.evaluate_answer_relevance(question, answer, record_token=record_token)
            score = int(score_result.get('score', 0) or 0)
            issues = []
            if len(answer) < 20:
                issues.append('回答偏短')
            if not any(word in answer for word in ['我', '本人', '负责', '参与', '主导', '实现', '优化', '设计']):
                issues.append('缺少个人贡献描述')
            return {
                'valid': score >= 60,
                'reason': '未配置API，使用本地规则做基础评分。',
                'confidence': score / 100,
                'score': score,
                'dimensions': [
                    {'name': '问题相关性', 'score': score, 'comment': score_result.get('reason', '本地相关性评分')},
                    {'name': '具体性与证据', 'score': 65 if len(answer) >= 50 else 35, 'comment': '根据回答长度和细节密度估算。'},
                    {'name': '岗位匹配度', 'score': 60, 'comment': '本地模式无法完整结合岗位要求。'},
                    {'name': '逻辑表达', 'score': 70 if len(answer) >= 30 else 45, 'comment': '根据表达完整度估算。'},
                    {'name': '真实性线索', 'score': 70 if any(word in answer for word in ['我', '负责', '参与', '主导']) else 40, 'comment': '根据第一人称和行动词估算。'},
                ],
                'strengths': ['回答已被记录，可作为后续追问基础'] if score >= 60 else [],
                'risks': issues,
                'suggestion': '配置API后可获得更细致的模型评分。',
                'issues': issues,
            }

        round_names = {
            'hard_field': '硬性指标补全',
            'role_verification': '项目角色真实性验证',
            'role_depth': '项目角色深度考察',
            'skill_deviation': '技能偏差验证',
            'language_logic': '语言逻辑能力',
            'special_requirement': '岗位特殊要求',
        }
        round_name = round_names.get(round_type, round_type or '未知轮次')

        system_prompt = (
            '你是资深技术面试官和招聘评估专家。'
            '你需要根据面试官问题、候选人回答和当前考察轮次，对回答质量做细致、可解释、可复核的评分。'
            '评分要严格但公平，不要因为回答长就给高分，重点看是否切题、是否有个人贡献、是否有事实细节、是否能支撑岗位判断。'
            '只输出JSON，不要输出Markdown或额外说明。'
        )
        user_prompt = f"""
当前考察轮次：{round_name}
轮次标识：{round_type}

面试官问题：
{question}

候选人回答：
{answer}

请按以下维度分别给0-100分，并给一句具体中文点评：
1. 问题相关性：是否正面回答问题，是否跑题。
2. 具体性与证据：是否有项目背景、技术细节、数据、例子、结果。
3. 岗位匹配度：回答体现的经验是否匹配本轮考察目标和岗位能力。
4. 逻辑表达：结构是否清晰，因果是否明确，表达是否可理解。
5. 真实性线索：是否体现第一人称职责、真实决策过程、可验证细节；空泛套话要低分。

综合评分规则：
- 90-100：高度切题，细节充分，有明确个人贡献、技术过程和结果。
- 80-89：切题且较完整，有一定细节，但仍可补充数据或深度。
- 70-79：基本可用，但细节、逻辑或岗位匹配有明显缺口。
- 60-69：勉强相关，回答偏泛，难以支撑强判断。
- 40-59：部分相关但空泛、缺少事实或明显答非所问。
- 0-39：未回答、严重跑题、无法评估或明显敷衍。

请返回这个JSON结构，字段名必须一致：
{{
  "score": 0到100的整数,
  "valid": true或false,
  "reason": "2-4句综合评价，说明为什么给这个分",
  "dimensions": [
    {{"name":"问题相关性","score":0到100的整数,"comment":"一句具体点评"}},
    {{"name":"具体性与证据","score":0到100的整数,"comment":"一句具体点评"}},
    {{"name":"岗位匹配度","score":0到100的整数,"comment":"一句具体点评"}},
    {{"name":"逻辑表达","score":0到100的整数,"comment":"一句具体点评"}},
    {{"name":"真实性线索","score":0到100的整数,"comment":"一句具体点评"}}
  ],
  "strengths": ["最多3条优势"],
  "risks": ["最多3条风险或不足"],
  "suggestion": "给HR或下一轮面试官的一句追问建议",
  "issues": ["需要重点关注的问题标签，最多4条"]
}}
"""
        raw = cls.generate_question(
            system_prompt,
            user_prompt,
            temperature=0,
            max_tokens=1200,
            use_advanced_model=False,
        )
        
        token_prompt = system_prompt + user_prompt
        token_response = raw or ''
        if record_token:
            TokenRecorder.record_answer_analysis(token_prompt, token_response, cls.get_text_model())

        try:
            cleaned = (raw or '').strip()
            if cleaned.startswith('```'):
                cleaned = cleaned.strip('`')
                cleaned = cleaned.replace('json', '', 1).strip()
            match = re.search(r'\{.*\}', cleaned, re.S)
            result = json.loads(match.group(0) if match else cleaned)
        except Exception:
            score_result = cls.evaluate_answer_relevance(question, answer, record_token=record_token)
            score = int(score_result.get('score', 50) or 50)
            fallback_payload = {
                'valid': score >= 60,
                'reason': f"AI评分解析失败，已回退到相关性评分。原始返回：{(raw or '')[:160]}",
                'confidence': score / 100,
                'score': score,
                'dimensions': [
                    {'name': '问题相关性', 'score': score, 'comment': score_result.get('reason', '回退评分')},
                ],
                'strengths': [],
                'risks': ['AI评分结果解析失败'],
                'suggestion': '建议重新生成报告或人工复核该轮回答。',
                'issues': ['AI评分解析失败'],
            }
            if not record_token:
                fallback_payload['_token_prompt'] = token_prompt
                fallback_payload['_token_response'] = token_response
            return fallback_payload

        score = int(round(float(result.get('score') or 0)))
        score = max(0, min(100, score))
        dimensions = result.get('dimensions') if isinstance(result.get('dimensions'), list) else []
        valid_value = result.get('valid', score >= 60)
        if isinstance(valid_value, str):
            valid = valid_value.strip().lower() in {'true', '1', 'yes', '是', '有效'}
        else:
            valid = bool(valid_value)
        payload = {
            'valid': valid,
            'reason': str(result.get('reason') or ''),
            'confidence': score / 100,
            'score': score,
            'dimensions': dimensions,
            'strengths': result.get('strengths') if isinstance(result.get('strengths'), list) else [],
            'risks': result.get('risks') if isinstance(result.get('risks'), list) else [],
            'suggestion': str(result.get('suggestion') or ''),
            'issues': result.get('issues') if isinstance(result.get('issues'), list) else [],
        }
        if not record_token:
            payload['_token_prompt'] = token_prompt
            payload['_token_response'] = token_response
        return payload

    @classmethod
    def validate_answer_quality_legacy(cls, question: str, answer: str, round_type: str) -> dict:
        if not getattr(settings, 'ANSWER_EVALUATION_ENABLED', False):
            return {'valid': True, 'reason': 'answer evaluation disabled', 'confidence': 1.0, 'issues': []}

        if not cls.get_api_key():
            return {'valid': True, 'reason': 'API not configured', 'confidence': 1.0}

        issues = []
        confidence = 1.0

        if len(answer.strip()) < 10:
            issues.append('回答过短')
            confidence *= 0.5

        first_person_indicators = ['我', '本人', '我自己']
        has_first_person = any(indicator in answer for indicator in first_person_indicators)
        if not has_first_person:
            issues.append('缺少第一人称')
            confidence *= 0.7

        typical_patterns = [
            r'负责', r'参与', r'主导', r'完成', r'实现', r'开发', r'设计', r'使用', r'做了', r'进行了'
        ]
        pattern_count = sum(1 for p in typical_patterns if p in answer)
        if pattern_count < 1:
            issues.append('缺少典型表述')
            confidence *= 0.6

        if len(answer) > 100 and answer.count('。') < 2:
            issues.append('长回答逻辑性存疑')
            confidence *= 0.7

        if len(answer) > 300:
            issues.append('回答过长')
            confidence *= 0.8

        is_valid = len(issues) == 0 or confidence > 0.5

        return {
            'valid': is_valid,
            'reason': '; '.join(issues) if issues else '回答有效',
            'confidence': confidence,
            'issues': issues
        }
