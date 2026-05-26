import time
from typing import Dict, Any, Optional, List, Tuple
from django.conf import settings
from .session_manager import SessionManager
from .qwen_service import QwenService
from .embedding_service import EmbeddingService
from .hard_field_detector import HardFieldDetector
from ..models import TalentProfile


class DialogueEngine:
    ROUND_CONFIG = [
        {
            'name': 'hard_field',
            'description': '硬性指标补全',
            'priority': 1,
        },
        {
            'name': 'role_verification',
            'description': '项目角色真实性',
            'priority': 2,
        },
        {
            'name': 'role_depth',
            'description': '项目角色深度',
            'priority': 3,
        },
        {
            'name': 'skill_deviation',
            'description': '技能偏差',
            'priority': 4,
        },
        {
            'name': 'language_logic',
            'description': '语言逻辑',
            'priority': 5,
        },
        {
            'name': 'special_requirement',
            'description': '岗位特殊要求',
            'priority': 6,
        },
    ]

    SHORT_ANSWER_THRESHOLD = 5
    SIMILARITY_THRESHOLD = 0.15
    MAX_INVALID_ATTEMPTS = 1
    WAIT_TIMEOUT_SECONDS = 10

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.session_data = SessionManager.get_session(session_id)
        self._is_processing = False

    def get_current_round(self) -> int:
        if not self.session_data:
            return 0
        return self.session_data.get('current_round', 0)

    def is_session_timeout(self) -> bool:
        if not self.session_data:
            return True
        elapsed = time.time() - self.session_data.get('last_question_time', 0)
        base_timeout = getattr(settings, 'SESSION_TIMEOUT', 120)
        return elapsed > (base_timeout + self.WAIT_TIMEOUT_SECONDS)

    def process_answer(self, answer: str) -> Dict[str, Any]:
        if self.is_session_timeout():
            return self._handle_session_timeout()

        session_data = SessionManager.get_session(self.session_id)
        if not session_data:
            return self._build_error_response('Session not found')

        if session_data.get('is_processing', False):
            return self._build_error_response('请求正在处理中，请稍候')

        SessionManager.set_processing(self.session_id, True)

        try:
            current_round = self.get_current_round()
            if current_round >= len(self.ROUND_CONFIG):
                return self._finalize_session()

            round_config = self.ROUND_CONFIG[current_round]
            round_name = round_config['name']

            SessionManager.add_dialogue(self.session_id, 'user', answer)

            if round_name == 'special_requirement':
                return self._handle_special_answer(answer)

            quality_result = QwenService.validate_answer_quality(
                question=self._get_last_question(),
                answer=answer,
                round_type=round_name
            )

            if not quality_result['valid']:
                invalid_count = SessionManager.increment_invalid_count(self.session_id, round_name)

                if invalid_count >= self.MAX_INVALID_ATTEMPTS:
                    self._skip_dimension(round_name)
                    SessionManager.advance_round(self.session_id)
                    return self._generate_next_question()

                similarity, is_similar = EmbeddingService.compute_text_similarity_with_question(
                    question=self._get_last_question(),
                    answer=answer,
                    threshold=self.SIMILARITY_THRESHOLD
                )

                if not is_similar:
                    result = self._rephrase_question(round_name)
                    return result

            self._store_round_result(round_name, answer, quality_result)
            SessionManager.advance_round(self.session_id)

            return self._generate_next_question()
        finally:
            SessionManager.set_processing(self.session_id, False)

    def _handle_special_answer(self, answer: str) -> Dict[str, Any]:
        session_data = SessionManager.get_session(self.session_id)
        if not session_data:
            return self._build_error_response('Session not found')

        last_question = self._get_last_question()
        custom_questions_answered = session_data.get('custom_questions_answered', {})

        for key, question in session_data.get('custom_questions', {}).items():
            if question == last_question and key not in custom_questions_answered:
                custom_questions_answered[key] = {
                    'question': question,
                    'answer': answer,
                    'confidence': 1.0
                }
                SessionManager.update_session(self.session_id, {
                    'custom_questions_answered': custom_questions_answered
                })
                break

        return self._generate_next_question()

    def resume_session(self) -> Dict[str, Any]:
        """重新接入已存在的会话"""
        if not self.session_data:
            return self._build_error_response('Session not found')

        SessionManager.resume_session(self.session_id)
        
        self.session_data = SessionManager.get_session(self.session_id)
        if not self.session_data:
            return self._build_error_response('Failed to resume session')

        current_round = self.get_current_round()
        
        if current_round >= len(self.ROUND_CONFIG):
            return self._finalize_session()

        dialogue_history = self.session_data.get('dialogue_history', [])
        last_question = self._get_last_question()
        
        if last_question:
            has_unanswered_question = False
            if len(dialogue_history) >= 1:
                last_msg = dialogue_history[-1]
                has_unanswered_question = last_msg.get('role') == 'assistant'
            
            if has_unanswered_question:
                round_config = self.ROUND_CONFIG[current_round - 1] if current_round > 0 else self.ROUND_CONFIG[0]
                return {
                    'session_id': self.session_id,
                    'question': last_question,
                    'round': current_round,
                    'round_name': round_config['name'],
                    'total_rounds': len(self.ROUND_CONFIG),
                    'resumed': True,
                    'dialogue_history': dialogue_history,
                    'message': '会话已重新连接'
                }
        
        return self._generate_next_question()

    def _get_last_question(self) -> str:
        history = self.session_data.get('dialogue_history', [])
        for item in reversed(history):
            if item.get('role') == 'assistant':
                return item.get('content', '')
        return ''

    def _handle_session_timeout(self) -> Dict[str, Any]:
        SessionManager.end_session(self.session_id, 'timeout')
        return self._build_final_response(incomplete=True, reason='会话超时')

    def _rephrase_question(self, round_name: str) -> Dict[str, Any]:
        original_question = self._get_last_question()
        if not original_question:
            SessionManager.advance_round(self.session_id)
            return self._generate_next_question()

        session_data = SessionManager.get_session(self.session_id)
        dialogue_history = session_data.get('dialogue_history', [])
        
        last_answer = ''
        for item in reversed(dialogue_history):
            if item.get('role') == 'user':
                last_answer = item.get('content', '')
                break

        job_config = session_data.get('job_config', {})
        target_position = job_config.get('target_position', '') or job_config.get('position', '') or ''
        job_description = job_config.get('job_description', '') or job_config.get('requirements', '')
        resume = session_data.get('resume', {})

        context_info = f"""
目标岗位：{target_position}

岗位要求摘要：{job_description[:100]}...

候选人简历摘要：{resume.get('summary', '')[:100]}...

原问题：{original_question}

候选人回答：{last_answer}
"""

        rephrase_prompt = f"""请作为一位资深面试官，基于以下对话上下文，生成一个追问问题。

{context_info}

分析要求：
1. 仔细分析候选人的回答，识别哪些部分回答了原问题，哪些部分没有回答
2. 如果候选人回答太笼统或不完整，请针对未回答的部分进行追问
3. 如果候选人部分回答了问题，请针对未回答的具体点进行追问
4. 追问问题应该简洁明了，聚焦于具体缺失的信息
5. 不要重复原问题，而是基于候选人的回答进行引导

输出要求：
- 只输出追问问题本身
- 使用第一人称"我"进行提问
- 语言正式、简洁

追问问题："""

        system_prompt = "你是一个专业、经验丰富的面试官，擅长根据候选人的回答进行有针对性的追问。"
        new_question = QwenService.generate_question(system_prompt, rephrase_prompt)

        if not new_question or new_question.strip() == '' or 'API' in new_question:
            fallback_question = f"请具体描述一下相关情况以及您在其中的主要职责。"
            new_question = fallback_question

        if new_question and new_question.strip() != original_question.strip():
            SessionManager.add_dialogue(self.session_id, 'assistant', new_question)
            SessionManager.set_reasked(self.session_id, True)
            return {
                'session_id': self.session_id,
                'question': new_question,
                'round': self.get_current_round(),
                'round_name': round_name,
                'reasked': True,
            }

        invalid_count = SessionManager.increment_invalid_count(self.session_id, round_name)
        if invalid_count >= self.MAX_INVALID_ATTEMPTS:
            self._skip_dimension(round_name)
            SessionManager.advance_round(self.session_id)
        
        return self._generate_next_question()

    def _skip_dimension(self, dimension: str) -> None:
        session_data = SessionManager.get_session(self.session_id)
        if session_data:
            incomplete_reasons = session_data.get('incomplete_reasons', [])
            incomplete_reasons.append(f'维度"{dimension}"因连续无效回答被跳过')
            SessionManager.update_session(self.session_id, {'incomplete_reasons': incomplete_reasons})

    def _store_round_result(self, round_name: str, answer: str, quality_result: dict) -> None:
        if round_name == 'hard_field':
            self._process_hard_field_answer(answer)
        elif round_name in ['role_verification', 'role_depth']:
            self._process_role_answer(round_name, answer, quality_result)

    def _process_hard_field_answer(self, answer: str) -> None:
        session_data = SessionManager.get_session(self.session_id)
        missing_fields = session_data.get('hard_fields_missing', [])

        hard_fields_results = {}
        for field in missing_fields:
            field_value = HardFieldDetector.extract_field_value(field, {'text': answer})
            if field_value:
                hard_fields_results[field] = {
                    'value': field_value,
                    'verified': True,
                    'source': 'interview'
                }

        if hard_fields_results:
            SessionManager.update_session(
                self.session_id,
                {'hard_fields_collected': hard_fields_results}
            )

    def _process_role_answer(self, round_name: str, answer: str, quality_result: dict) -> None:
        session_data = SessionManager.get_session(self.session_id)
        project_roles = session_data.get('project_roles_collected', {})

        confidence = quality_result.get('confidence', 0.5)

        if round_name == 'role_verification':
            role_level = self._determine_role_level(answer)
            project_roles['role_verification'] = {
                'level': role_level,
                'confidence': confidence,
                'answer': answer
            }
        elif round_name == 'role_depth':
            project_roles['role_depth'] = {
                'depth_info': self._analyze_role_depth(answer),
                'confidence': confidence,
                'answer': answer
            }

        SessionManager.update_session(self.session_id, {'project_roles_collected': project_roles})

    def _determine_role_level(self, answer: str) -> str:
        leading_indicators = ['主导', '负责', '统筹', '整体', '核心', '发起', '创建']
        participating_indicators = ['参与', '配合', '协助', '支持', '协作', '合作']
        peripheral_indicators = ['了解', '接触', '见过', '知道', '听说过']

        answer_lower = answer.lower()

        leading_score = sum(1 for ind in leading_indicators if ind in answer)
        participating_score = sum(1 for ind in participating_indicators if ind in answer)
        peripheral_score = sum(1 for ind in peripheral_indicators if ind in answer)

        if leading_score > participating_score and leading_score > peripheral_score:
            return 'leading'
        elif participating_score > peripheral_score:
            return 'participating'
        return 'peripheral'

    def _analyze_role_depth(self, answer: str) -> Dict[str, Any]:
        return {
            'technical_contributions': self._extract_technical_parts(answer),
            'complexity_level': self._estimate_complexity(answer),
            'team_size_mentioned': self._extract_team_size(answer),
        }

    def _extract_technical_parts(self, answer: str) -> List[str]:
        technical_keywords = [
            '架构', '设计', '开发', '优化', '重构', '部署', '测试',
            '算法', '模型', '数据', '性能', '安全', 'api', '接口'
        ]
        found = [kw for kw in technical_keywords if kw in answer.lower()]
        return found[:5]

    def _estimate_complexity(self, answer: str) -> str:
        complexity_indicators = {
            'high': ['复杂', '大型', '高并发', '分布式', '微服务', '架构设计'],
            'medium': ['模块', '功能', '开发', '优化'],
            'low': ['简单', '基础', '小型']
        }
        for level, indicators in complexity_indicators.items():
            if any(ind in answer for ind in indicators):
                return level
        return 'medium'

    def _extract_team_size(self, answer: str) -> Optional[int]:
        import re
        match = re.search(r'(\d+)\s*(人|成员)', answer)
        if match:
            return int(match.group(1))
        return None

    def _generate_next_question(self) -> Dict[str, Any]:
        current_round = self.get_current_round()

        if current_round >= len(self.ROUND_CONFIG):
            return self._finalize_session()

        round_config = self.ROUND_CONFIG[current_round]
        round_name = round_config['name']

        session_data = SessionManager.get_session(self.session_id)
        if not session_data:
            return self._build_error_response('Session not found')

        if round_name == 'special_requirement':
            return self._handle_special_requirement_round(session_data)

        context = {
            'resume': session_data.get('resume', {}),
            'job_config': session_data.get('job_config', {}),
            'dialogue_history': session_data.get('dialogue_history', []),
        }

        missing_fields = session_data.get('hard_fields_missing', [])
        project_info = self._get_project_info(session_data)

        question = QwenService.generate_interview_question(
            round_type=round_name,
            context=context,
            missing_fields=missing_fields if round_name == 'hard_field' else None,
            project_info=project_info if 'role' in round_name else None
        )

        if not question:
            return self._build_error_response('Failed to generate question')

        SessionManager.add_dialogue(self.session_id, 'assistant', question)

        return {
            'session_id': self.session_id,
            'question': question,
            'round': current_round + 1,
            'round_name': round_name,
            'total_rounds': len(self.ROUND_CONFIG),
            'reasked': False,
        }

    def _handle_special_requirement_round(self, session_data: dict) -> Dict[str, Any]:
        custom_questions = session_data.get('custom_questions', {})
        custom_questions_asked = session_data.get('custom_questions_asked', [])

        if custom_questions and len(custom_questions_asked) < len(custom_questions):
            remaining_questions = {
                k: v for k, v in custom_questions.items()
                if k not in custom_questions_asked
            }

            if remaining_questions:
                next_key = list(remaining_questions.keys())[0]
                next_question = remaining_questions[next_key]

                SessionManager.add_dialogue(self.session_id, 'assistant', next_question)
                SessionManager.update_session(self.session_id, {
                    'custom_questions_asked': custom_questions_asked + [next_key]
                })

                return {
                    'session_id': self.session_id,
                    'question': next_question,
                    'round': len(self.ROUND_CONFIG),
                    'round_name': 'special_requirement',
                    'total_rounds': len(self.ROUND_CONFIG),
                    'reasked': False,
                    'custom_question_key': next_key,
                    'custom_questions_remaining': len(remaining_questions) - 1,
                }

        return self._finalize_session()

    def _get_project_info(self, session_data: dict) -> dict:
        resume = session_data.get('resume', {})
        projects = resume.get('projects', [])
        if projects and isinstance(projects, list) and len(projects) > 0:
            return projects[0] if isinstance(projects[0], dict) else {'name': projects[0]}
        return {}

    def _finalize_session(self) -> Dict[str, Any]:
        SessionManager.end_session(self.session_id, 'completed')
        return self._build_final_response(incomplete=False)

    def _build_final_response(self, incomplete: bool, reason: str = None) -> Dict[str, Any]:
        session_data = SessionManager.get_session(self.session_id)
        if not session_data:
            return self._build_error_response('Session not found')

        hard_fields_results = session_data.get('hard_fields_collected', {})
        project_role_results = session_data.get('project_roles_collected', {})

        confidence_score = self._calculate_confidence(
            hard_fields_results,
            project_role_results
        )

        candidate_id = session_data.get('candidate_id', '')
        dialogue_history = session_data.get('dialogue_history', [])
        current_round = session_data.get('current_round', 0)
        last_question = self._get_last_question()

        profile, _ = TalentProfile.objects.update_or_create(
            session_id=self.session_id,
            defaults={
                'candidate_id': candidate_id,
                'session_incomplete': incomplete,
                'interview_completed': (not incomplete),
                'raw_resume': session_data.get('resume', {}),
                'job_config': session_data.get('job_config', {}),
                'hard_fields_results': hard_fields_results,
                'project_role_results': project_role_results,
                'confidence_score': confidence_score,
                'incomplete_reasons': session_data.get('incomplete_reasons', []),
                'current_round': current_round,
                'dialogue_history': dialogue_history,
                'last_question': last_question,
            }
        )

        if incomplete:
            return {
                'candidate_id': candidate_id,
                'session_id': self.session_id,
                'session_incomplete': incomplete,
                'hard_fields_results': hard_fields_results,
                'project_role_results': project_role_results,
                'custom_question_results': session_data.get('custom_questions_answered', {}),
                'confidence_score': confidence_score,
                'profile_id': str(profile.id),
                'message': reason or '会话异常结束',
            }
        else:
            return {
                'candidate_id': candidate_id,
                'session_id': self.session_id,
                'session_incomplete': incomplete,
                'hard_fields_results': hard_fields_results,
                'project_role_results': project_role_results,
                'custom_question_results': session_data.get('custom_questions_answered', {}),
                'confidence_score': confidence_score,
                'profile_id': str(profile.id),
                'message': '感谢您参与本次AI面试，祝您生活顺利',
                'interview_completed': True,
                'completion_message': '感谢您参与本次AI面试，祝您生活顺利',
            }

    def _calculate_confidence(
        self,
        hard_fields_results: dict,
        project_role_results: dict
    ) -> float:
        scores = []

        if hard_fields_results:
            valid_count = sum(1 for r in hard_fields_results.values() if r.get('verified'))
            scores.append(valid_count / max(len(hard_fields_results), 1))

        if project_role_results:
            depths = project_role_results.get('role_depth', {})
            conf = depths.get('confidence', 0.5)
            scores.append(conf)

        if not scores:
            return 0.3

        return sum(scores) / len(scores)

    def _build_error_response(self, message: str) -> Dict[str, Any]:
        return {
            'error': True,
            'message': message,
            'session_id': self.session_id,
        }

    def start_session(self) -> Dict[str, Any]:
        session_data = SessionManager.get_session(self.session_id)
        if not session_data:
            return self._build_error_response('Session not found')

        missing_fields = HardFieldDetector.detect_missing_hard_fields(
            resume=session_data.get('resume', {}),
            required_hard_fields=session_data.get('required_hard_fields', [])
        )
        SessionManager.update_session(self.session_id, {'hard_fields_missing': missing_fields})

        return self._generate_next_question()
