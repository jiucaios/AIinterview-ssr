import json
import time
import uuid
from typing import Optional, Dict, Any, List
from django.core.cache import cache
from django.conf import settings
from ..models import TalentProfile, JobConfiguration


class SessionManager:
    SESSION_PREFIX = 'ai_interview:session:'
    CANDIDATE_INDEX_PREFIX = 'ai_interview:candidate:'
    SESSION_TIMEOUT = getattr(settings, 'SESSION_TIMEOUT', 1800)
    COMPLETE_KEYWORDS = [
        '面谈结束',
        '面谈完成',
        '面试结束',
        '面试完成',
        '到此为止',
        '感谢您参与此次面试',
        '感谢您参与',
        '所有轮次已完成',
        '祝你一切顺利',
        '感谢您在此次面试所付出的时间',
    ]

    @classmethod
    def has_interview_completed(cls, dialogue_history: List[Dict[str, Any]]) -> bool:
        for item in reversed(dialogue_history or []):
            if item.get('role') != 'assistant':
                continue
            content = str(item.get('content') or '')
            return any(keyword in content for keyword in cls.COMPLETE_KEYWORDS)
        return False

    @classmethod
    def normalize_custom_questions(cls, custom_questions: Any) -> Dict[str, str]:
        if not custom_questions:
            return {}
        if isinstance(custom_questions, list):
            return {
                f"q{index + 1}": str(question).strip()
                for index, question in enumerate(custom_questions)
                if str(question).strip()
            }
        if isinstance(custom_questions, dict):
            normalized = {}
            for index, (key, question) in enumerate(custom_questions.items(), start=1):
                text = str(question).strip()
                if text:
                    normalized[str(key).strip() or f"q{index}"] = text
            return normalized
        text = str(custom_questions).strip()
        return {"q1": text} if text else {}

    @classmethod
    def create_session(cls, candidate_id: str, resume: dict, job_config: dict, required_hard_fields: list, custom_questions: dict = None) -> str:
        session_id = str(uuid.uuid4())
        custom_questions = cls.normalize_custom_questions(custom_questions)
        session_data = {
            'session_id': session_id,
            'candidate_id': candidate_id,
            'resume': resume,
            'job_config': job_config,
            'required_hard_fields': required_hard_fields,
            'current_round': 0,
            'dialogue_history': [],
            'hard_fields_missing': [],
            'hard_fields_collected': {},
            'project_roles_collected': {},
            'invalid_answer_count': {},
            'last_question_time': time.time(),
            'state': 'active',
            'is_processing': False,
            'last_reasked': False,
            'custom_questions': custom_questions,
            'custom_questions_asked': [],
            'custom_questions_answered': {},
        }
        try:
            cache.set(
                f"{cls.SESSION_PREFIX}{session_id}",
                json.dumps(session_data, ensure_ascii=False),
                timeout=cls.SESSION_TIMEOUT + 60
            )
            cls._update_candidate_index(candidate_id, session_id)
            cls._sync_profile_from_session(session_data)
        except Exception as e:
            raise Exception(f"缓存连接失败: {str(e)}")
        return session_id

    @classmethod
    def restore_session_from_profile(cls, profile: TalentProfile) -> Optional[str]:
        """Restore an unfinished DB-backed session into cache so the interview can continue."""
        if not profile or profile.interview_completed:
            return None

        job_config = profile.job_config or {}
        custom_questions = cls.normalize_custom_questions(job_config.get('custom_questions', {}))
        session_data = {
            'session_id': profile.session_id,
            'candidate_id': profile.candidate_id,
            'resume': profile.raw_resume or {},
            'job_config': job_config,
            'required_hard_fields': job_config.get('hard_fields', []),
            'current_round': profile.current_round or 0,
            'dialogue_history': profile.dialogue_history or [],
            'hard_fields_missing': [],
            'hard_fields_collected': profile.hard_fields_results or {},
            'project_roles_collected': profile.project_role_results or {},
            'invalid_answer_count': {},
            'last_question_time': time.time(),
            'state': 'active',
            'is_processing': False,
            'last_reasked': False,
            'custom_questions': custom_questions,
            'custom_questions_asked': job_config.get('custom_questions_asked', []),
            'custom_questions_answered': (profile.profile_data or {}).get('custom_question_results', {}),
        }
        cache.set(
            f"{cls.SESSION_PREFIX}{profile.session_id}",
            json.dumps(session_data, ensure_ascii=False),
            timeout=cls.SESSION_TIMEOUT + 60
        )
        cls._update_candidate_index(profile.candidate_id, profile.session_id)
        cls._sync_profile_from_session(session_data)
        return profile.session_id

    @classmethod
    def _update_candidate_index(cls, candidate_id: str, session_id: str) -> None:
        """更新候选人索引，记录候选人与会话的关联"""
        try:
            index_key = f"{cls.CANDIDATE_INDEX_PREFIX}{candidate_id}"
            session_ids = cache.get(index_key)
            if session_ids:
                session_ids = json.loads(session_ids)
                if session_id not in session_ids:
                    session_ids.append(session_id)
            else:
                session_ids = [session_id]
            cache.set(index_key, json.dumps(session_ids), timeout=cls.SESSION_TIMEOUT + 60)
        except Exception as e:
            raise Exception(f"更新候选人索引失败: {str(e)}")

    @classmethod
    def get_sessions_by_candidate_id(cls, candidate_id: str) -> List[str]:
        """根据候选人ID获取所有关联的会话ID"""
        try:
            index_key = f"{cls.CANDIDATE_INDEX_PREFIX}{candidate_id}"
            session_ids = cache.get(index_key)
            if session_ids:
                return json.loads(session_ids)
            return []
        except Exception as e:
            raise Exception(f"获取候选人会话列表失败: {str(e)}")

    @classmethod
    def get_active_session_by_candidate_id(cls, candidate_id: str) -> Optional[str]:
        """根据候选人ID获取最近的活动会话"""
        session_ids = cls.get_sessions_by_candidate_id(candidate_id)
        for session_id in reversed(session_ids):
            session_data = cls.get_session(session_id)
            if session_data and session_data.get('state') == 'active':
                if not cls.check_timeout(session_id):
                    return session_id
        return None

    @classmethod
    def get_session(cls, session_id: str) -> Optional[Dict[str, Any]]:
        try:
            data = cache.get(f"{cls.SESSION_PREFIX}{session_id}")
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            raise Exception(f"缓存连接失败: {str(e)}")

    @classmethod
    def get_session_or_restore(cls, session_id: str) -> Optional[Dict[str, Any]]:
        session_data = cls.get_session(session_id)
        if session_data:
            return session_data

        profile = TalentProfile.objects.filter(session_id=session_id).first()
        if not profile:
            return None

        interview_completed = profile.interview_completed or cls.has_interview_completed(
            profile.dialogue_history or []
        )
        if interview_completed:
            return {
                'session_id': profile.session_id,
                'candidate_id': profile.candidate_id,
                'resume': profile.raw_resume or {},
                'job_config': profile.job_config or {},
                'required_hard_fields': (profile.job_config or {}).get('hard_fields', []),
                'current_round': profile.current_round or 0,
                'dialogue_history': profile.dialogue_history or [],
                'state': 'completed',
                'interview_completed': True,
                'interview_complete': True,
            }

        restored_session_id = cls.restore_session_from_profile(profile)
        if not restored_session_id:
            return None
        return cls.get_session(restored_session_id)

    @classmethod
    def update_session(cls, session_id: str, updates: Dict[str, Any]) -> bool:
        session_data = cls.get_session(session_id)
        if not session_data:
            return False
        session_data.update(updates)
        session_data['last_question_time'] = time.time()
        try:
            cache.set(
                f"{cls.SESSION_PREFIX}{session_id}",
                json.dumps(session_data, ensure_ascii=False),
                timeout=cls.SESSION_TIMEOUT + 60
            )
            cls._sync_profile_from_session(session_data)
        except Exception as e:
            raise Exception(f"缓存连接失败: {str(e)}")
        return True

    @classmethod
    def add_dialogue(cls, session_id: str, role: str, content: str) -> bool:
        session_data = cls.get_session(session_id)
        if not session_data:
            return False
        session_data['dialogue_history'].append({
            'role': role,
            'content': content,
            'timestamp': time.time()
        })
        session_data['last_question_time'] = time.time()
        try:
            cache.set(
                f"{cls.SESSION_PREFIX}{session_id}",
                json.dumps(session_data, ensure_ascii=False),
                timeout=cls.SESSION_TIMEOUT + 60
            )
            cls._sync_profile_from_session(session_data)
        except Exception as e:
            raise Exception(f"缓存连接失败: {str(e)}")
        return True

    @classmethod
    def check_timeout(cls, session_id: str) -> bool:
        session_data = cls.get_session(session_id)
        if not session_data:
            return True
        elapsed = time.time() - session_data.get('last_question_time', 0)
        return elapsed > cls.SESSION_TIMEOUT

    @classmethod
    def increment_invalid_count(cls, session_id: str, dimension: str) -> int:
        session_data = cls.get_session(session_id)
        if not session_data:
            return 0
        invalid_counts = session_data.get('invalid_answer_count', {})
        invalid_counts[dimension] = invalid_counts.get(dimension, 0) + 1
        session_data['invalid_answer_count'] = invalid_counts
        try:
            cache.set(
                f"{cls.SESSION_PREFIX}{session_id}",
                json.dumps(session_data, ensure_ascii=False),
                timeout=cls.SESSION_TIMEOUT + 60
            )
        except Exception as e:
            raise Exception(f"缓存连接失败: {str(e)}")
        return invalid_counts[dimension]

    @classmethod
    def get_invalid_count(cls, session_id: str, dimension: str) -> int:
        session_data = cls.get_session(session_id)
        if not session_data:
            return 0
        return session_data.get('invalid_answer_count', {}).get(dimension, 0)

    @classmethod
    def advance_round(cls, session_id: str) -> bool:
        session_data = cls.get_session(session_id)
        if not session_data:
            return False
        session_data['current_round'] = session_data.get('current_round', 0) + 1
        try:
            cache.set(
                f"{cls.SESSION_PREFIX}{session_id}",
                json.dumps(session_data, ensure_ascii=False),
                timeout=cls.SESSION_TIMEOUT + 60
            )
            cls._sync_profile_from_session(session_data)
        except Exception as e:
            raise Exception(f"缓存连接失败: {str(e)}")
        return True

    @classmethod
    def end_session(cls, session_id: str, reason: str = 'completed') -> bool:
        session_data = cls.get_session(session_id)
        if not session_data:
            return False
        interview_completed = reason == 'completed' or cls.has_interview_completed(
            session_data.get('dialogue_history', [])
        )
        session_data['state'] = 'completed' if interview_completed else reason
        session_data['interview_completed'] = interview_completed
        session_data['interview_complete'] = interview_completed
        try:
            cache.set(
                f"{cls.SESSION_PREFIX}{session_id}",
                json.dumps(session_data, ensure_ascii=False),
                timeout=cls.SESSION_TIMEOUT + 60
            )
            cls._sync_profile_from_session(
                session_data,
                session_incomplete=not interview_completed,
                interview_completed=interview_completed
            )
            if interview_completed:
                profile = TalentProfile.objects.filter(session_id=session_id).first()
                if profile:
                    from .external_ai_session import trigger_completion_callback_for_profile

                    trigger_completion_callback_for_profile(profile)
            cls.release_job_lock(session_data)
        except Exception as e:
            raise Exception(f"缓存连接失败: {str(e)}")
        return True

    @classmethod
    def release_job_lock(cls, session_data_or_config_id) -> bool:
        if isinstance(session_data_or_config_id, dict):
            job_config = session_data_or_config_id.get('job_config', {}) or {}
            config_id = job_config.get('config_id')
        else:
            config_id = session_data_or_config_id

        if not config_id:
            return False

        JobConfiguration.objects.filter(config_id=config_id).update(is_locked=False)
        return True

    @classmethod
    def build_qa_records(cls, dialogue_history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        qa_records = []
        pending_question = None

        for item in dialogue_history or []:
            role = item.get('role')
            if role == 'assistant':
                pending_question = item
            elif role == 'user' and pending_question:
                qa_records.append({
                    'round': len(qa_records) + 1,
                    'question': pending_question.get('content', ''),
                    'answer': item.get('content', ''),
                    'question_timestamp': pending_question.get('timestamp'),
                    'answer_timestamp': item.get('timestamp'),
                })
                pending_question = None

        if pending_question and not cls.has_interview_completed(dialogue_history or []):
            qa_records.append({
                'round': len(qa_records) + 1,
                'question': pending_question.get('content', ''),
                'answer': '',
                'question_timestamp': pending_question.get('timestamp'),
                'answer_timestamp': None,
            })

        if not qa_records:
            for index, item in enumerate(dialogue_history or []):
                if item.get('role') == 'assistant':
                    qa_records.append({
                        'round': index + 1,
                        'question': item.get('content', ''),
                        'answer': '',
                        'question_timestamp': item.get('timestamp'),
                        'answer_timestamp': None,
                    })

        return qa_records

    @classmethod
    def set_processing(cls, session_id: str, is_processing: bool) -> bool:
        session_data = cls.get_session(session_id)
        if not session_data:
            return False
        session_data['is_processing'] = is_processing
        try:
            cache.set(
                f"{cls.SESSION_PREFIX}{session_id}",
                json.dumps(session_data, ensure_ascii=False),
                timeout=cls.SESSION_TIMEOUT + 60
            )
        except Exception as e:
            raise Exception(f"缓存连接失败: {str(e)}")
        return True

    @classmethod
    def set_reasked(cls, session_id: str, reasked: bool) -> bool:
        session_data = cls.get_session(session_id)
        if not session_data:
            return False
        session_data['last_reasked'] = reasked
        try:
            cache.set(
                f"{cls.SESSION_PREFIX}{session_id}",
                json.dumps(session_data, ensure_ascii=False),
                timeout=cls.SESSION_TIMEOUT + 60
            )
        except Exception as e:
            raise Exception(f"缓存连接失败: {str(e)}")
        return True

    @classmethod
    def delete_session(cls, session_id: str) -> bool:
        try:
            session_data = cls.get_session(session_id)
            if session_data:
                candidate_id = session_data.get('candidate_id')
                if candidate_id:
                    cls._remove_from_candidate_index(candidate_id, session_id)
            cache.delete(f"{cls.SESSION_PREFIX}{session_id}")
        except Exception as e:
            raise Exception(f"缓存连接失败: {str(e)}")
        return True

    @classmethod
    def _remove_from_candidate_index(cls, candidate_id: str, session_id: str) -> None:
        """从候选人索引中移除会话ID"""
        try:
            index_key = f"{cls.CANDIDATE_INDEX_PREFIX}{candidate_id}"
            session_ids = cache.get(index_key)
            if session_ids:
                session_ids = json.loads(session_ids)
                if session_id in session_ids:
                    session_ids.remove(session_id)
                    cache.set(index_key, json.dumps(session_ids), timeout=cls.SESSION_TIMEOUT + 60)
        except Exception as e:
            raise Exception(f"更新候选人索引失败: {str(e)}")

    @classmethod
    def resume_session(cls, session_id: str) -> bool:
        """重新激活会话，用于重新连接"""
        session_data = cls.get_session(session_id)
        if not session_data:
            return False
        session_data['state'] = 'active'
        session_data['last_question_time'] = time.time()
        try:
            cache.set(
                f"{cls.SESSION_PREFIX}{session_id}",
                json.dumps(session_data, ensure_ascii=False),
                timeout=cls.SESSION_TIMEOUT + 60
            )
            cls._sync_profile_from_session(session_data)
        except Exception as e:
            raise Exception(f"缓存连接失败: {str(e)}")
        return True

    @classmethod
    def _sync_profile_from_session(
        cls,
        session_data: Dict[str, Any],
        session_incomplete: bool = None,
        interview_completed: bool = None
    ) -> None:
        """将会话实时同步到数据库，确保中断后可从DB恢复。"""
        session_id = session_data.get('session_id')
        candidate_id = session_data.get('candidate_id')
        if not session_id or not candidate_id:
            return

        dialogue_history = session_data.get('dialogue_history', [])
        last_question = ''
        for item in reversed(dialogue_history):
            if item.get('role') == 'assistant':
                last_question = item.get('content', '')
                break

        # 优先从session_data中获取状态值
        if session_incomplete is None:
            session_incomplete = session_data.get('session_incomplete', True)
        if interview_completed is None:
            interview_completed = (
                session_data.get('interview_completed')
                or session_data.get('interview_complete')
                or session_data.get('state') == 'completed'
                or cls.has_interview_completed(dialogue_history)
            )
        if interview_completed:
            session_incomplete = False

        defaults = {
            'candidate_id': candidate_id,
            'session_incomplete': session_incomplete,
            'interview_completed': interview_completed,
            'current_round': session_data.get('current_round', 0),
            'dialogue_history': dialogue_history,
            'last_question': last_question,
            'raw_resume': session_data.get('resume', {}),
            'job_config': session_data.get('job_config', {}),
            'hard_fields_results': session_data.get('hard_fields_collected', {}),
            'project_role_results': session_data.get('project_roles_collected', {}),
            'incomplete_reasons': session_data.get('incomplete_reasons', []),
            'profile_data': {
                'qa_records': cls.build_qa_records(dialogue_history),
                'dialogue_history': dialogue_history,
                'custom_question_results': session_data.get('custom_questions_answered', {}),
                'interview_completed': interview_completed,
                'session_state': session_data.get('state', 'active'),
            },
        }
        TalentProfile.objects.update_or_create(
            session_id=session_id,
            defaults=defaults,
        )
