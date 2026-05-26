from django.db import models
import uuid
from datetime import timedelta


class Candidate(models.Model):
    """候选人模型 - 存储候选人姓名和手机号"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate_id = models.CharField(max_length=128, unique=True, db_index=True, help_text='候选人唯一标识(姓名_手机号)')
    name = models.CharField(max_length=64, help_text='候选人姓名')
    phone = models.CharField(max_length=16, help_text='候选人手机号')
    interview_id = models.CharField(max_length=32, null=True, blank=True, help_text='关联的面试ID')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'ai_candidate'
        verbose_name = '候选人'
        verbose_name_plural = '候选人'
    
    def save(self, *args, **kwargs):
        if not self.candidate_id:
            self.candidate_id = f"{self.name}_{self.phone}"
        super().save(*args, **kwargs)


class JobConfiguration(models.Model):
    """岗位配置模型 - HR配置的岗位信息"""
    
    CONFIG_STATES = [
        ('active', '启用'),
        ('inactive', '禁用'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    config_id = models.CharField(max_length=32, unique=True, db_index=True, help_text='公开访问的配置ID')
    
    job_name = models.CharField(max_length=256, help_text='岗位名称')
    job_description = models.TextField(blank=True, help_text='岗位描述(JD)')
    job_level = models.CharField(max_length=32, default='中级', help_text='岗位级别')
    target_position = models.CharField(max_length=128, help_text='目标职位')
    
    hard_fields = models.JSONField(default=list, help_text='必问硬性字段列表')
    custom_questions = models.JSONField(default=dict, help_text='自定义问题字典')
    resume_json = models.JSONField(default=dict, blank=True, help_text='解析的简历JSON')
    
    status = models.CharField(max_length=16, choices=CONFIG_STATES, default='active', help_text='配置状态')
    is_locked = models.BooleanField(default=False, help_text='是否被锁定（有人正在面试）')
    expire_at = models.DateTimeField(null=True, blank=True, help_text='过期时间')
    max_interviews = models.IntegerField(default=1, help_text='最大面试人数')
    current_interviews = models.IntegerField(default=0, help_text='当前已面试人数')
    
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='job_configs', null=True, blank=True)
    
    created_by = models.CharField(max_length=64, blank=True, help_text='创建者标识')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'ai_job_configuration'
        verbose_name = '岗位配置'
        verbose_name_plural = '岗位配置'
        indexes = [
            models.Index(fields=['config_id', 'status']),
            models.Index(fields=['expire_at']),
        ]
    
    @classmethod
    def generate_config_id(cls):
        return uuid.uuid4().hex[:16]
    
    def is_valid(self):
        if self.status != 'active':
            return False
        from django.utils import timezone
        if self.expire_at and self.expire_at < timezone.now():
            return False
        if self.current_interviews >= self.max_interviews:
            return False
        return True
    
    def increment_interview_count(self):
        self.current_interviews = models.F('current_interviews') + 1
        self.save(update_fields=['current_interviews', 'updated_at'])


class TalentProfile(models.Model):
    ROLE_LEVELS = [
        ('leading', '主导'),
        ('participating', '参与'),
        ('peripheral', '边缘'),
    ]

    PROFILE_STATES = [
        ('incomplete', '未完成'),
        ('complete', '已完成'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate_id = models.CharField(max_length=64, db_index=True, help_text='候选人ID')
    session_id = models.CharField(max_length=64, unique=True, db_index=True, help_text='会话ID')
    session_incomplete = models.BooleanField(default=True, help_text='会话是否未完成')
    current_round = models.IntegerField(default=0, help_text='当前轮次')
    dialogue_history = models.JSONField(default=list, help_text='对话历史记录')
    last_question = models.TextField(blank=True, help_text='上一个问题')

    raw_resume = models.JSONField(default=dict, help_text='原始简历JSON')
    job_config = models.JSONField(default=dict, help_text='岗位配置JSON')

    hard_fields_results = models.JSONField(default=dict, help_text='硬性字段结果')
    project_role_results = models.JSONField(default=dict, help_text='项目角色深度结果')

    profile_data = models.JSONField(default=dict, help_text='完整画像数据')

    confidence_score = models.FloatField(default=0.0, help_text='可信度评分')
    interview_completed = models.BooleanField(default=False, help_text='面试是否已完成（六轮全部结束）')

    incomplete_reasons = models.JSONField(default=list, help_text='未完成原因')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ai_talent_profile'
        verbose_name = '人才画像'
        verbose_name_plural = '人才画像'
        indexes = [
            models.Index(fields=['candidate_id', 'session_id']),
        ]

    def mark_complete(self):
        self.session_incomplete = False
        self.save(update_fields=['session_incomplete', 'updated_at'])

    def add_hard_field_result(self, field: str, value: any):
        self.hard_fields_results[field] = value
        self.save(update_fields=['hard_fields_results', 'updated_at'])

    def add_project_role_result(self, project: str, role_level: str, depth_info: dict):
        if 'projects' not in self.project_role_results:
            self.project_role_results['projects'] = {}
        self.project_role_results['projects'][project] = {
            'role_level': role_level,
            'depth_info': depth_info,
        }
        self.save(update_fields=['project_role_results', 'updated_at'])