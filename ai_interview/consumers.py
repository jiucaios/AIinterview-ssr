"""
重构版面试 Consumer - 让Omni全权负责整个流程
我们只做：透传消息、保存状态、UI状态同步
"""
import json
import logging
import asyncio
import base64
from datetime import datetime
from typing import Optional, Dict, Any, List

from django.conf import settings
from channels.generic.websocket import AsyncWebsocketConsumer
from dashscope.audio.qwen_omni.omni_realtime import OmniRealtimeConversation, OmniRealtimeCallback, MultiModality, AudioFormat
from asgiref.sync import sync_to_async

from ai_interview.services.session_manager import SessionManager
from ai_interview.services.token_utils import TokenRecorder
from ai_interview.services.interview_prompt_builder import build_interview_prompt
from ai_interview.services.interview_types import DISCUSSION, get_interview_type_label, normalize_interview_type

logger = logging.getLogger(__name__)


class VoiceInterviewCallback(OmniRealtimeCallback):
    """Omni回调类，用于处理Omni事件"""
    
    def __init__(self, consumer):
        super().__init__()
        self.consumer = consumer
        self.seen_user_transcription_events = set()
    
    def on_open(self):
        logger.info("[Interview] Omni connection opened")
    
    def on_close(self, close_status_code, close_msg):
        logger.info(f"[Interview] Omni closed: {close_status_code} - {close_msg}")
        self.consumer.omni_ready = False
        self.consumer.send_from_thread({"type": "omni.closed", "code": close_status_code})
    
    def on_error(self, error):
        logger.error(f"[Interview] Omni error: {error}")
        self.consumer.send_from_thread({"type": "omni.error", "error": str(error)})
    
    def on_event(self, message):
        event_type = message.get("type")
        
        if event_type == "session.updated":
            self.consumer.omni_ready = True
            self.consumer.send_from_thread({"type": "omni_ready"})
        
        elif event_type == "conversation.item.created":
            self.consumer.response_active = True
            self.consumer.current_assistant_text = ""
            self.consumer.interrupted = False
            self.consumer.send_from_thread({"type": "response.started"})
        
        elif event_type == "response.audio.delta":
            audio = message.get("delta")
            if audio:
                self.consumer.send_from_thread({"type": "omni.audio", "audio": audio})
        
        elif event_type == "response.audio_transcript.delta":
            delta = message.get("delta", "")
            if delta:
                self.consumer.current_assistant_text += delta
                self.consumer.send_from_thread({"type": "omni.text_delta", "text": delta})
        
        elif event_type == "response.audio_transcript.done":
            transcript = message.get("transcript", "") or self.consumer.current_assistant_text
            if transcript and not self.consumer.interrupted:
                clean_transcript = self.consumer._clean_round_tag_from_message(transcript)
                if (
                    self.consumer._should_force_discussion_complete_on_current_response(next_assistant=True)
                    and not self.consumer.pending_default_discussion_end
                ):
                    ending = " 面谈结束了，感谢您在本次面谈所付出的时间。"
                    if "面谈结束" not in transcript:
                        transcript = f"{transcript.rstrip()}{ending}"
                        clean_transcript = f"{clean_transcript.rstrip()}{ending}"
                self.consumer.record_omni_usage_from_thread(transcript)
                
                self.consumer.dialogue_history.append({
                    "role": "assistant",
                    "content": transcript,
                    "timestamp": datetime.now().timestamp()
                })
                
                self.consumer.interview_complete = SessionManager.has_interview_completed(
                    self.consumer.dialogue_history
                )
                
                current_round = self.consumer._extract_round_from_message(transcript)
                self.consumer.persist_state_from_thread(current_round=current_round)
                
                self.consumer.send_from_thread({
                    "type": "round.state",
                    "round_number": current_round,
                    "max_rounds": None if self.consumer.current_interview_type == DISCUSSION else 6,
                    "question": clean_transcript,
                    "content": clean_transcript,
                    "interview_type": self.consumer.current_interview_type,
                    "interview_type_label": get_interview_type_label(self.consumer.current_interview_type),
                    "interview_complete": self.consumer.interview_complete
                })

        elif event_type in (
            "input_audio_transcription.completed",
            "conversation.item.input_audio_transcription.completed",
        ):
            transcript = (
                message.get("transcript")
                or message.get("text")
                or message.get("content")
                or ""
            ).strip()
            if transcript:
                event_key = (
                    message.get("item_id")
                    or message.get("event_id")
                    or message.get("id")
                    or transcript
                )
                last_message = self.consumer.dialogue_history[-1] if self.consumer.dialogue_history else {}
                is_duplicate = (
                    event_key in self.seen_user_transcription_events
                    or (
                        last_message.get("role") == "user"
                        and last_message.get("content") == transcript
                    )
                )
                if not is_duplicate:
                    self.seen_user_transcription_events.add(event_key)
                    self.consumer.dialogue_history.append({
                        "role": "user",
                        "content": transcript,
                        "timestamp": datetime.now().timestamp()
                    })
                    self.consumer.last_omni_user_message = transcript
                    self.consumer.persist_state_from_thread()
                    self.consumer.request_default_discussion_end_from_thread()

                self.consumer.send_from_thread({
                    "type": event_type,
                    "transcript": transcript,
                })
        
        elif event_type == "response.done":
            self.consumer.response_active = False
        
        elif event_type == "input_audio_buffer.speech_started":
            self.consumer.send_from_thread({"type": "input_audio_buffer.speech_started"})
        
        elif event_type == "input_audio_buffer.speech_stopped":
            self.consumer.send_from_thread({
                "type": "input_audio_buffer.speech_stopped",
                "interrupted": self.consumer.interrupted
            })
        
        elif event_type == "input_audio_buffer.cleared":
            self.consumer.send_from_thread({
                "type": "input_audio_buffer.cleared",
                "interrupted": self.consumer.interrupted
            })
        
        elif event_type == "conversation.item.deleted":
            self.consumer.interrupted = True
            self.consumer.send_from_thread({"type": "omni.interrupted"})
        
        elif event_type == "error":
            error_msg = message.get("message", str(message))
            logger.error(f"[Interview] Omni error event: {error_msg}")
            self.consumer.send_from_thread({"type": "omni.error", "error": error_msg})


class VoiceInterviewConsumer(AsyncWebsocketConsumer):
    
    async def connect(self):
        self.session_id: Optional[str] = None
        self.candidate_id: Optional[str] = None
        self.config_id: Optional[str] = None
        self.dialogue_history: List[Dict[str, str]] = []
        self.loop = asyncio.get_running_loop()
        self.omni: Optional[OmniRealtimeConversation] = None
        self.omni_callback: Optional[VoiceInterviewCallback] = None
        self.omni_ready = False
        self.omni_error_sent = False
        self.response_active = False
        self.interview_complete = False
        self.current_assistant_text = ""
        self.interrupted = False
        self.last_omni_user_message = ""
        self.current_interview_type = "initial_interview"
        self.current_config_id = ""
        self.current_recruitment_requirements = ""
        self.default_discussion_end_requested = False
        self.pending_default_discussion_end = False
        
        await self.accept()
        self.send_json({
            "type": "connected",
            "message": "Realtime websocket connected",
        })
    
    async def disconnect(self, close_code):
        if self.omni:
            try:
                await asyncio.to_thread(self.omni.close)
            except Exception as e:
                logger.error(f"[Interview] Error closing omni: {e}")
        if self.session_id:
            await self._save_final_state()
    
    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data:
            await self._handle_audio(bytes_data)
        elif text_data:
            try:
                data = json.loads(text_data)
                await self._handle_message(data)
            except json.JSONDecodeError:
                logger.error(f"[Interview] Invalid JSON: {text_data[:100]}")
    
    async def _handle_message(self, data: Dict[str, Any]):
        msg_type = data.get("type")
        
        if msg_type == "start_interview":
            await self._start_or_resume(data)
        elif msg_type == "audio_chunk":
            await self._handle_audio_chunk(data)
        elif msg_type == "text_message":
            await self._handle_text_message(data)
        elif msg_type == "interrupt":
            await self._handle_interrupt()
        elif msg_type == "save_state":
            await self._handle_save_state(data)
        elif msg_type == "finish_session":
            await self._handle_finish_session()
    
    async def _handle_audio(self, audio_data: bytes):
        if not self.omni or not self.omni_ready:
            return
        try:
            audio_b64 = base64.b64encode(audio_data).decode('utf-8')
            await asyncio.to_thread(self.omni.append_audio, audio_b64)
        except Exception as e:
            logger.error(f"[Interview] Send audio error: {e}")
    
    async def _handle_audio_chunk(self, data: Dict[str, Any]):
        if not self.omni or not self.omni_ready:
            return
        try:
            audio_b64 = data.get("audio", "")
            if audio_b64:
                await asyncio.to_thread(self.omni.append_audio, audio_b64)
        except Exception as e:
            logger.error(f"[Interview] Handle audio chunk error: {e}")
    
    async def _start_or_resume(self, data: Dict[str, Any]):
        self.session_id = data.get("session_id")
        self.candidate_id = data.get("candidate_id")
        self.config_id = data.get("config_id")
        
        session_data = None
        if self.session_id:
            get_session_sync = sync_to_async(SessionManager.get_session_or_restore)
            session_data = await get_session_sync(self.session_id)

        if session_data and (
            session_data.get("interview_completed")
            or session_data.get("interview_complete")
            or session_data.get("state") == "completed"
            or SessionManager.has_interview_completed(session_data.get("dialogue_history", []))
        ):
            self.interview_complete = True
            self.dialogue_history = session_data.get("dialogue_history", [])
            self.send_json({
                "type": "interview_complete",
                "session_id": self.session_id,
                "interview_completed": True
            })
            return
        
        await self._init_omni()
        
        resume = None
        job_config = None
        required_hard_fields = []
        custom_questions = []
        current_question = ""
        
        if session_data and session_data.get("dialogue_history"):
            self.dialogue_history = session_data.get("dialogue_history", [])
            resume = session_data.get("resume", {})
            job_config = session_data.get("job_config", {})
            self.current_interview_type = normalize_interview_type(job_config.get("interview_type"))
            self.current_config_id = job_config.get("config_id", "")
            self.current_recruitment_requirements = str(
                job_config.get("recruitment_requirements")
                or job_config.get("discussion_requirements")
                or ""
            ).strip()
            required_hard_fields = session_data.get("required_hard_fields", [])
            custom_questions_raw = session_data.get("custom_questions", {})
            if isinstance(custom_questions_raw, list):
                custom_questions = [q for q in custom_questions_raw if q and str(q).strip()]
            else:
                custom_questions = [v for v in (custom_questions_raw.values() if isinstance(custom_questions_raw, dict) else []) if v and str(v).strip()]
            current_question = "继续之前的面试"
            await self._resume_from_history(session_data)
        else:
            resume = data.get("resume", session_data.get("resume", {}) if session_data else {})
            job_config = data.get("job_config", session_data.get("job_config", {}) if session_data else {})
            self.current_interview_type = normalize_interview_type(job_config.get("interview_type"))
            self.current_config_id = job_config.get("config_id", "")
            self.current_recruitment_requirements = str(
                job_config.get("recruitment_requirements")
                or job_config.get("discussion_requirements")
                or ""
            ).strip()
            required_hard_fields = data.get("required_hard_fields", session_data.get("required_hard_fields", []) if session_data else [])
            
            custom_questions_raw = data.get("custom_questions", session_data.get("custom_questions", {}) if session_data else {})
            if isinstance(custom_questions_raw, list):
                custom_questions = [q for q in custom_questions_raw if q and str(q).strip()]
            else:
                custom_questions = [v for v in (custom_questions_raw.values() if isinstance(custom_questions_raw, dict) else []) if v and str(v).strip()]
            
            current_question = "正在准备面试..."
            await self._start_new_interview({
                "resume": resume,
                "job_config": job_config,
                "required_hard_fields": required_hard_fields,
                "custom_questions": custom_questions
            })
        
        self.send_json({
            "type": "session_started",
            "session_id": self.session_id,
            "candidate_id": self.candidate_id,
            "current_question": current_question,
            "round_number": 1,
            "max_rounds": None if self.current_interview_type == DISCUSSION else 6,
            "job_level": job_config.get("job_level", "中级") if job_config else "中级",
            "interview_type": self.current_interview_type,
            "interview_type_label": get_interview_type_label(self.current_interview_type),
            "dialogue_history": self.dialogue_history
        })
    
    async def _init_omni(self):
        """初始化Omni"""
        api_key = getattr(settings, "DASHSCOPE_API_KEY", None)
        if not api_key:
            self.send_json({
                "type": "error",
                "message": "API key not configured"
            })
            return
        
        import dashscope
        base_url = getattr(settings, "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com")
        dashscope.api_key = api_key
        dashscope.base_url = base_url
        
        self.omni_callback = VoiceInterviewCallback(self)
        self.omni = OmniRealtimeConversation(
            model=getattr(settings, "QWEN_REALTIME_MODEL", "qwen3.5-omni-plus-realtime"),
            callback=self.omni_callback,
            url=getattr(settings, "QWEN_REALTIME_URL", None),
        )
        
        voice = getattr(settings, "QWEN_REALTIME_VOICE", "Sunnybobi")
        vad_threshold = float(getattr(settings, "QWEN_REALTIME_VAD_THRESHOLD", 0.5))
        vad_silence = int(getattr(settings, "QWEN_REALTIME_VAD_SILENCE_MS", 1500))
        
        system_prompt = """你是一个专业、友好的AI面试官。
进行自然、口语化的中文对话。
不要输出任何JSON、代码标记或特殊格式。
每次回复通常1-3句话。
"""
        
        await asyncio.to_thread(self.omni.connect)
        
        await asyncio.to_thread(
            self.omni.update_session,
            output_modalities=[MultiModality.TEXT, MultiModality.AUDIO],
            voice=voice,
            input_audio_format=AudioFormat.PCM_16000HZ_MONO_16BIT,
            output_audio_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            enable_input_audio_transcription=True,
            enable_turn_detection=True,
            turn_detection_type="semantic_vad",
            turn_detection_threshold=vad_threshold,
            turn_detection_silence_duration_ms=vad_silence,
            instructions=system_prompt,
        )
        
        logger.info("[Interview] Omni initialized")
    
    async def _start_new_interview(self, data: Dict[str, Any]):
        """全新面试：发一个完整的prompt"""
        resume = data.get("resume", {})
        job_config = data.get("job_config", {})
        required_hard_fields = data.get("required_hard_fields", [])
        custom_questions = data.get("custom_questions", [])
        
        complete_prompt = build_interview_prompt(
            resume,
            job_config,
            required_hard_fields,
            custom_questions,
            legacy_builder=self._build_complete_prompt,
        )
        logger.info(f"[Interview] Starting, prompt length: {len(complete_prompt)}")
        
        item = {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": complete_prompt}],
        }
        await asyncio.to_thread(self.omni.create_item, item)
        self.last_omni_user_message = complete_prompt
        await self._run_omni("create_response",
                           output_modalities=[MultiModality.TEXT, MultiModality.AUDIO])
    
    async def _resume_from_history(self, session_data: Dict[str, Any]):
        """从历史恢复"""
        resume_prompt = f"""[断点续面]

请继续之前的面试。

对话历史（最近15条）：
"""
        for msg in self.dialogue_history[-15:]:
            role = "候选人" if msg.get("role") == "user" else "面试官"
            resume_prompt += f"{role}：{msg.get('content', '')}\n"
        
        resume_prompt += "\n请继续面试。"
        
        logger.info(f"[Interview] Resuming with {len(self.dialogue_history)} messages")
        
        item = {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": resume_prompt}],
        }
        await asyncio.to_thread(self.omni.create_item, item)
        self.last_omni_user_message = resume_prompt
        await self._run_omni("create_response",
                           output_modalities=[MultiModality.TEXT, MultiModality.AUDIO])
    
    async def _handle_text_message(self, data: Dict[str, Any]):
        """透传用户文本"""
        text = (data.get("text") or "").strip()
        if not text or not self.omni_ready:
            return
        
        self.dialogue_history.append({
            "role": "user",
            "content": text,
            "timestamp": datetime.now().timestamp()
        })
        await self._persist_state()

        if self._should_end_default_discussion_after_user():
            end_text = self._build_default_discussion_end_instruction()
            self.default_discussion_end_requested = True
            item = {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": end_text}],
            }
            await asyncio.to_thread(self.omni.create_item, item)
            self.last_omni_user_message = end_text
            await self._run_omni("create_response",
                               output_modalities=[MultiModality.TEXT, MultiModality.AUDIO])
            return
        
        item = {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": text}],
        }
        await asyncio.to_thread(self.omni.create_item, item)
        self.last_omni_user_message = text
        await self._run_omni("create_response",
                           output_modalities=[MultiModality.TEXT, MultiModality.AUDIO])
    
    async def _handle_interrupt(self):
        """处理中断请求"""
        if self.omni:
            try:
                await asyncio.to_thread(self.omni.clear_appended_audio)
                self.interrupted = True
                self.send_json({"type": "interrupted"})
            except Exception as e:
                logger.error(f"[Interview] Interrupt error: {e}")
    
    async def _handle_save_state(self, data: Dict[str, Any]):
        """保存状态"""
        if not self.session_id:
            return
        
        try:
            client_dialogue_history = data.get("dialogue_history") or []
            dialogue_history = (
                client_dialogue_history
                if len(client_dialogue_history) > len(self.dialogue_history)
                else self.dialogue_history
            )
            self.dialogue_history = dialogue_history
            updates = {
                "dialogue_history": dialogue_history,
                "interview_complete": self.interview_complete,
                "interview_completed": self.interview_complete,
                "last_updated": str(datetime.now())
            }
            current_round = data.get("current_round")
            if current_round is not None:
                updates["current_round"] = current_round
            update_session_sync = sync_to_async(SessionManager.update_session)
            await update_session_sync(self.session_id, updates)
            
            self.send_json({
                "type": "state_saved",
                "success": True,
                "session_id": self.session_id
            })
            logger.info(f"[Interview] State saved for session {self.session_id}")
        except Exception as e:
            logger.error(f"[Interview] Save error: {e}")
    
    async def _save_final_state(self):
        """断开时保存"""
        if not self.session_id:
            return
        try:
            update_session_sync = sync_to_async(SessionManager.update_session)
            await update_session_sync(self.session_id, {
                "dialogue_history": self.dialogue_history,
                "interview_complete": self.interview_complete,
                "interview_completed": self.interview_complete,
                "last_updated": str(datetime.now())
            })
        except Exception as e:
            logger.error(f"[Interview] Final save error: {e}")

    def persist_state_from_thread(self, current_round: int = None):
        asyncio.run_coroutine_threadsafe(
            self._persist_state(current_round=current_round),
            self.loop
        )

    def record_omni_usage_from_thread(self, assistant_text: str):
        try:
            prompt = self.last_omni_user_message or ''
            model = getattr(settings, "QWEN_REALTIME_MODEL", "qwen3.5-omni-plus-realtime")
            TokenRecorder.record_omni_interview(
                prompt,
                assistant_text or '',
                model,
                metadata={
                    "interview_type": self.current_interview_type,
                    "interview_type_label": get_interview_type_label(self.current_interview_type),
                    "config_id": self.current_config_id,
                    "session_id": self.session_id,
                },
            )
        except Exception as e:
            logger.error(f"[Interview] Token record error: {e}")

    async def _persist_state(self, current_round: int = None):
        if not self.session_id:
            return
        try:
            updates = {
                "dialogue_history": self.dialogue_history,
                "interview_complete": self.interview_complete,
                "interview_completed": self.interview_complete,
                "last_updated": str(datetime.now())
            }
            if current_round is not None:
                updates["current_round"] = current_round
            update_session_sync = sync_to_async(SessionManager.update_session)
            await update_session_sync(self.session_id, updates)
        except Exception as e:
            logger.error(f"[Interview] Persist state error: {e}")
    
    async def _handle_finish_session(self):
        """处理面试结束消息"""
        if not self.session_id:
            return
        try:
            self.interview_complete = self.interview_complete or SessionManager.has_interview_completed(
                self.dialogue_history
            )
            reason = 'completed' if self.interview_complete else 'exited'
            end_session_sync = sync_to_async(SessionManager.end_session)
            await end_session_sync(self.session_id, reason)
            
            self.send_json({
                "type": "session_finished",
                "success": True,
                "session_id": self.session_id,
                "interview_completed": self.interview_complete
            })
            logger.info(f"[Interview] Session {self.session_id} finished with reason: {reason}")
        except Exception as e:
            logger.error(f"[Interview] Finish session error: {e}")
    
    async def _run_omni(self, method_name: str, *args, **kwargs):
        if not self.omni:
            return None
        method = getattr(self.omni, method_name)
        try:
            return await asyncio.to_thread(method, *args, **kwargs)
        except Exception as e:
            logger.error(f"[Interview] Omni error: {e}")
    
    def _build_complete_prompt(self, resume: dict, job_config: dict, 
                               required_hard_fields: list = None,
                               custom_questions: list = None) -> str:
        """
        构建完整的面试prompt
        一次性把所有规则、简历、岗位信息都放进去
        """
        target_position = job_config.get("target_position", "") or job_config.get("position", "") or "未知岗位"
        job_description = job_config.get("job_description", "") or job_config.get("requirements", "")
        job_level = job_config.get("job_level", "") or "中级"
        
        resume_summary = resume.get("summary", "")
        projects = json.dumps(resume.get("projects", []), ensure_ascii=False)
        skills = json.dumps(resume.get("skills", []), ensure_ascii=False)
        
        if required_hard_fields and len(required_hard_fields) > 0:
            hard_fields_note = f"""
第一轮：硬性指标补全
需要确认的硬性信息：{required_hard_fields}
如果候选人简历里已经有这些信息，可以快速确认后进入下一轮。
"""
        else:
            hard_fields_note = """
第一轮：硬性指标补全（已省略）
由于HR没有勾选需要确认的硬性指标，直接从第二轮开始面试。
第一轮跳过，你直接开始第二轮面试即可，不要说"我们继续"之类的话。
"""
        
        if custom_questions and len(custom_questions) > 0:
            custom_questions_note = f"""
第六轮：补充提问
HR希望了解以下内容：
{chr(10).join([f"- {q}" for q in custom_questions])}

请按顺序询问以上问题。
"""
        else:
            custom_questions_note = """
第六轮：补充提问（已省略）
由于HR没有设置补充提问，跳过第六轮。
面试在第五轮后结束。
"""
        
        rounds_note = f"""1. 面试共6个维度（部分可能根据HR配置被跳过）：
   - 第1轮：硬性指标补全（若前端没有勾选则跳过本轮）
   - 第2轮：项目角色真实性验证
   - 第3轮：项目角色深度考察
   - 第4轮：技能偏差验证
   - 第5轮：语言逻辑能力
   - 第6轮：补充提问（若HR没有设置则跳过本轮）"""
        
        level_guidance = {
            "初级": """
   - 重点考察：基础知识掌握、学习态度、动手能力
   - 提问风格：更详细、更耐心，允许候选人解释概念
   - 避免：过于深入的技术架构问题或复杂的系统设计问题
   - 示例：问基础概念、简单算法、工具使用、代码规范等""",
            "中级": """
   - 重点考察：独立解决问题能力、技术深度、项目经验
   - 提问风格：适中深度，要求有具体项目经验支撑
   - 避免：过于基础的知识点或过于宏观的系统架构
   - 示例：问技术选型、问题排查、最佳实践、团队协作等""",
            "高级": """
   - 重点考察：架构设计能力、技术领导力、复杂问题解决
   - 提问风格：深入追问，要求能说清楚"为什么"
   - 避免：过于基础的知识点
   - 示例：问架构设计、技术决策、团队管理、技术规划等""",
            "资深": """
   - 重点考察：技术战略思维、跨团队影响力、技术体系建设
   - 提问风格：抽象与具体结合，要求有宏观视角和细节把控
   - 示例：问技术愿景、团队建设、技术品牌、跨部门协作等""",
            "管理": """
   - 重点考察：团队管理能力、业务理解、战略执行
   - 提问风格：关注管理和战略层面，不过多深入技术细节
   - 示例：问团队管理、项目管理、跨团队协作、业务理解等"""
        }
        
        default_guidance = """
   - 根据候选人简历和实际回答情况灵活调整
   - 既要验证简历真实性，也要评估能力边界
   - 遇到不熟悉的领域可以深入追问"""
        
        guidance = level_guidance.get(job_level, default_guidance)
        level_guide = f"""
职级提问深度指导（{job_level}）：
{guidance}"""
        
        return f"""【开始面试】

你是一个专业、友好的AI面试官。现在开始进行一场结构化面试。

------------------
面试者信息：
目标岗位：{target_position}
职级要求：{job_level}
岗位描述：{job_description}

{level_guide}

候选人简历摘要：
{resume_summary}

项目经历：
{projects}

技能：
{skills}
------------------

面试规则（必须严格遵守）：

{rounds_note}

{hard_fields_note}

2. 回答质量判断标准：
   高质量回答（直接进入下一轮）：
   - 针对问题核心，不跑题
   - 有具体的例子、数据、细节
   - 逻辑清晰，有条理
   - 使用第一人称描述自己的贡献

   低质量回答（需要追问）：
   - 回答模糊，没有具体内容
   - 答非所问
   - 过于简短（少于2句话）且无实质内容
   - 明显敷衍或编造

{custom_questions_note}

5. 特殊情况处理：
   - 候选人说"等一下"、"我想想"、"稍等" → "好的，你慢慢想"
   - 候选人说"没听清"、"再说一遍"、"重复一下" → 简洁重复问题
   - 候选人说"不懂"、"不会"、"不知道"、"不清楚" → "没关系，我们继续下一个问题"
   - 候选人说"什么意思"、"解释一下" → 简单解释后继续
   - 候选人有疑问 → 简单解释后继续

6. 回答完成判断（重要）：
   当候选人说完后（通过VAD检测），根据以下标准判断：
   
   ✅ 回答完整，可以进入下一轮：
   - 包含了具体的技术细节、经验描述
   - 有逻辑性，能说清楚做了什么、怎么做的
   - 有数据支撑或具体成果
   - 长度适中（通常3-5句话或以上）
   
   ❌ 回答不完整，需要追问：
   - 只有结论，没有具体说明
   - 说"我参与过"但不说明自己的具体贡献
   - 过于简短（少于2-3句话）
   - 明显敷衍或编造

   追问话术示例：
   - "能具体说说你在项目中具体负责了哪些部分吗？"
   - "能举个例子说明吗？"
   - "这个过程中遇到的最大挑战是什么？"

7. 追问规则：
   - 只有在回答不完整时才追问
   - 每轮最多追问1次
   - 追问后，如果回答仍然不好，直接进入下一轮，不要一直追问

8. 轮次过渡规则（重要）：
   完成一个轮次后：
   - 说一句简短的总结/感谢
   - 自然过渡到下一个维度
   - 在问题最后加上轮次标记 `<<ROUND2>>`、`<<ROUND3>>` 等（TTS会读出，但很短）
   - 示例："好的，感谢分享。在之前的项目中，你具体负责了什么技术工作呢？<<ROUND2>>"
   - 示例："好的，我们进入下一个环节。能详细说说你在项目中的具体职责吗？<<ROUND3>>"

9. 面试结束：
   - 所有轮次完成后，说："面试结束了，感谢您在此次面试所付出的时间，祝您一切顺利"
   - 不要继续问任何问题

现在，请开始面试。直接问第一个问题。
"""
    
    def send_json(self, data: Dict[str, Any]):
        asyncio.run_coroutine_threadsafe(
            self._send_json_async(data),
            self.loop
        )
    
    async def _send_json_async(self, data: Dict[str, Any]):
        await self.send(text_data=json.dumps(data, ensure_ascii=False))
    
    def send_from_thread(self, data: Dict[str, Any]):
        self.send_json(data)
    
    def _extract_round_from_message(self, message: str) -> int:
        """从AI的回复里提取轮次信息"""
        import re
        match = re.search(r'<<ROUND(\d+)>>', message)
        if match:
            round_num = int(match.group(1))
            logger.info(f"[Interview] Detected round {round_num} from <<ROUND>> tag")
            return round_num
        
        round_indicators = [
            ("【第1轮】", "第1轮", "硬性指标", 1),
            ("【第2轮】", "第2轮", "项目角色真实", 2),
            ("【第3轮】", "第3轮", "项目角色深度", 3),
            ("【第4轮】", "第4轮", "技能偏差", 4),
            ("【第5轮】", "第5轮", "语言逻辑", 5),
            ("【第6轮】", "第6轮", "岗位特殊要求", 6),
        ]
        
        for indicator1, indicator2, indicator3, round_num in round_indicators:
            if indicator1 in message or indicator2 in message or indicator3 in message:
                logger.info(f"[Interview] Detected round {round_num} from text")
                return round_num
        
        return 1
    
    def _clean_round_tag_from_message(self, message: str) -> str:
        """从消息中移除轮次标记，返回干净的消息"""
        import re
        return re.sub(r'\s*<<ROUND\d+>>\s*$', '', message)

    def _should_force_discussion_complete_on_current_response(self, next_assistant: bool = False) -> bool:
        """面谈达到结束条件后，兜底补上结束语。"""
        if self.current_interview_type != DISCUSSION:
            return False
        if self._count_default_discussion_assistant_turns(next_assistant=next_assistant) >= 10:
            return True
        if not self._is_default_discussion_template():
            return False
        return (
            self._count_default_discussion_effective_answers() >= 4
        )

    def _is_default_discussion_template(self) -> bool:
        if self.current_interview_type != DISCUSSION:
            return False
        if (self.current_recruitment_requirements or "").strip():
            return False
        return True

    def _count_default_discussion_assistant_turns(self, next_assistant: bool = False) -> int:
        assistant_turns = sum(
            1
            for item in self.dialogue_history
            if item.get("role") == "assistant"
        )
        if next_assistant:
            assistant_turns += 1
        return assistant_turns

    def _count_default_discussion_effective_answers(self) -> int:
        effective_count = 0
        previous_assistant = ""
        for item in self.dialogue_history:
            role = item.get("role")
            content = item.get("content", "")
            if role == "assistant":
                previous_assistant = content
            elif role == "user" and self._is_effective_default_discussion_answer(
                content,
                previous_assistant,
            ):
                effective_count += 1
        return effective_count

    def _is_effective_default_discussion_answer(self, content: str, question: str = "") -> bool:
        text = "".join(str(content or "").split())
        if not text:
            return False
        weak_phrases = [
            "不会", "不知道", "不清楚", "不了解", "没有", "没什么",
            "下一个", "下个问题", "跳过", "随便", "没想过", "不方便回答",
        ]
        if len(text) <= 18 and any(phrase in text for phrase in weak_phrases):
            return False
        if self._answer_stays_on_question_topic(text, question):
            return True
        if len(text) < 4:
            return False
        return True

    def _answer_stays_on_question_topic(self, answer: str, question: str = "") -> bool:
        """回答还在围绕当前题目说，就宽松计为有效。"""
        import re
        answer_lower = str(answer or "").lower()
        question_lower = str(question or "").lower()
        if not answer_lower or not question_lower:
            return False
        if len(answer_lower) >= 6:
            return True
        topic_tokens = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_+#.-]{1,}", question_lower))
        topic_tokens.update(re.findall(r"[\u4e00-\u9fff]{2,}", question_lower))
        ignore_tokens = {
            "ai", "hr", "json", "markdown", "round",
            "the", "and", "for", "with", "your", "you",
            "你对", "哪些", "什么", "怎么", "如何", "是否", "可以", "一下",
            "说说", "谈谈", "介绍", "经验", "理解", "相关", "方面",
        }
        return any(
            token not in ignore_tokens and token in answer_lower
            for token in topic_tokens
        )

    def _should_end_default_discussion_after_user(self) -> bool:
        if self.current_interview_type != DISCUSSION:
            return False
        if self.interview_complete:
            return False
        if self.pending_default_discussion_end:
            return True
        if self.default_discussion_end_requested:
            return False
        if self._count_default_discussion_assistant_turns() >= 9:
            return True
        if not self._is_default_discussion_template():
            return False
        return (
            self._count_default_discussion_effective_answers() >= 4
        )

    def _build_default_discussion_end_instruction(self) -> str:
        return (
            "[系统结束控制]\n"
            "候选人刚刚已经完成回答，后端判定本次默认面谈已达到结束条件。"
            "请不要继续提出任何新问题，也不要继续追问。"
            "请只输出一句自然的结束语，必须包含“面谈结束”，例如："
            "“面谈结束了，感谢您在本次面谈所付出的时间，祝您一切顺利。”"
        )

    def request_default_discussion_end_from_thread(self):
        if not self._should_end_default_discussion_after_user():
            return
        if self.response_active and not self.pending_default_discussion_end:
            self.pending_default_discussion_end = True
            return
        self.pending_default_discussion_end = False
        self.default_discussion_end_requested = True
        asyncio.run_coroutine_threadsafe(
            self._request_default_discussion_end(),
            self.loop
        )

    async def _request_default_discussion_end(self):
        if not self.omni or not self.omni_ready:
            return
        if self.response_active:
            self.pending_default_discussion_end = True
            return
        self.pending_default_discussion_end = False
        self.default_discussion_end_requested = True
        item = {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": self._build_default_discussion_end_instruction()}],
        }
        await asyncio.to_thread(self.omni.create_item, item)
        self.last_omni_user_message = self._build_default_discussion_end_instruction()
        await self._run_omni("create_response",
                           output_modalities=[MultiModality.TEXT, MultiModality.AUDIO])
