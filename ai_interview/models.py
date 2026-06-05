from django.db import models
import uuid
from datetime import timedelta
from .services.interview_types import INTERVIEW_TYPE_CHOICES, INITIAL_INTERVIEW


class AdminUser(models.Model):
    """Admin account for HR console management."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=64, unique=True, db_index=True)
    password_hash = models.CharField(max_length=256)
    is_active = models.BooleanField(default=True, db_index=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ai_admin_user'
        verbose_name = 'Admin user'
        verbose_name_plural = 'Admin users'

    def __str__(self):
        return self.username


class HRUser(models.Model):
    """HR account allowed to enter the HR console."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=64, unique=True, db_index=True)
    password_hash = models.CharField(max_length=256)
    name = models.CharField(max_length=64, blank=True)
    email = models.EmailField(max_length=128, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        AdminUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_hr_users',
    )
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ai_hr_user'
        verbose_name = 'HR user'
        verbose_name_plural = 'HR users'

    def __str__(self):
        return self.username


class TokenUsage(models.Model):
    """Token使用记录模型 - 持久化存储所有Token消耗记录"""
    
    CATEGORY_CHOICES = [
        ('resume_parsing', '简历解析'),
        ('job_match', '简历匹配度'),
        ('omni_interview', 'Omni语音面试'),
        ('answer_analysis', '回答分析'),
        ('feishu_assistant', '飞书'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES, db_index=True, help_text='Token消耗类别')
    input_tokens = models.IntegerField(default=0, help_text='输入Token数量')
    output_tokens = models.IntegerField(default=0, help_text='输出Token数量')
    total_tokens = models.IntegerField(default=0, help_text='总Token数量')
    model = models.CharField(max_length=128, blank=True, help_text='使用的模型名称')
    metadata = models.JSONField(default=dict, blank=True, help_text='额外元数据')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, help_text='记录创建时间')
    
    class Meta:
        db_table = 'ai_token_usage'
        verbose_name = 'Token使用记录'
        verbose_name_plural = 'Token使用记录'
        indexes = [
            models.Index(fields=['category', 'created_at']),
            models.Index(fields=['created_at']),
        ]
    
    @classmethod
    def get_daily_stats(cls, category=None, days=30):
        """获取最近N天的统计数据"""
        from django.utils import timezone
        from django.db.models import Sum, Count
        
        start_date = timezone.now() - timedelta(days=days)
        queryset = cls.objects.filter(created_at__gte=start_date)
        
        if category:
            queryset = queryset.filter(category=category)
        
        return queryset.aggregate(
            total_input_tokens=Sum('input_tokens'),
            total_output_tokens=Sum('output_tokens'),
            total_tokens=Sum('total_tokens'),
            call_count=Count('id')
        )
    
    @classmethod
    def get_category_stats(cls, category=None):
        """获取按类别统计的数据"""
        from django.db.models import Sum, Count
        
        queryset = cls.objects.all()
        if category:
            queryset = queryset.filter(category=category)
        
        return queryset.values('category').annotate(
            total_input_tokens=Sum('input_tokens'),
            total_output_tokens=Sum('output_tokens'),
            total_tokens=Sum('total_tokens'),
            call_count=Count('id')
        )


class Candidate(models.Model):
    """候选人模型 - 存储候选人姓名、手机号和邮箱"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate_id = models.CharField(max_length=128, unique=True, db_index=True, help_text='候选人唯一标识(姓名_邮箱)')
    name = models.CharField(max_length=64, help_text='候选人姓名')
    phone = models.CharField(max_length=16, null=True, blank=True, help_text='候选人手机号')
    email = models.EmailField(max_length=128, default='', help_text='候选人邮箱')
    interview_id = models.CharField(max_length=32, null=True, blank=True, help_text='关联的面试ID')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'ai_candidate'
        verbose_name = '候选人'
        verbose_name_plural = '候选人'
    
    def save(self, *args, **kwargs):
        if not self.candidate_id:
            self.candidate_id = f"{self.name}_{self.email}"
        super().save(*args, **kwargs)


class AssessmentGroup(models.Model):
    """一次候选人-岗位评估批次，可包含一条面试和一条面谈。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='assessment_groups', null=True, blank=True)
    candidate_name = models.CharField(max_length=64, db_index=True)
    candidate_email = models.EmailField(max_length=128, db_index=True)
    job_key = models.CharField(max_length=256, db_index=True)
    job_name = models.CharField(max_length=256)
    group_number = models.IntegerField(default=1)
    is_temporary = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ai_assessment_group'
        verbose_name = '评估组'
        verbose_name_plural = '评估组'
        unique_together = ('candidate_email', 'candidate_name', 'job_key', 'group_number')
        indexes = [
            models.Index(fields=['candidate_email', 'candidate_name', 'job_key']),
        ]

    def __str__(self):
        if self.is_temporary:
            return f'{self.candidate_name}-{self.job_name}-临时组'
        return f'{self.candidate_name}-{self.job_name}-第{self.group_number}评估组'


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
    interview_type = models.CharField(max_length=32, choices=INTERVIEW_TYPE_CHOICES, default=INITIAL_INTERVIEW, db_index=True, help_text='面试类别')
    recruitment_requirements = models.TextField(blank=True, help_text='面谈招聘要求')
    
    hard_fields = models.JSONField(default=list, help_text='必问硬性字段列表')
    custom_questions = models.JSONField(default=dict, help_text='自定义问题字典')
    resume_json = models.JSONField(default=dict, blank=True, help_text='解析的简历JSON')
    resume_parse_status = models.CharField(max_length=16, default='completed', db_index=True)
    resume_parse_error = models.TextField(blank=True)
    resume_source_path = models.CharField(max_length=1024, blank=True)
    job_match_status = models.CharField(max_length=16, default='pending', db_index=True)
    job_match_score = models.IntegerField(null=True, blank=True)
    job_match_result = models.JSONField(default=dict, blank=True)
    job_match_error = models.TextField(blank=True)
    job_match_analyzed_at = models.DateTimeField(null=True, blank=True)
    
    status = models.CharField(max_length=16, choices=CONFIG_STATES, default='active', help_text='配置状态')
    is_locked = models.BooleanField(default=False, help_text='是否被锁定（有人正在面试）')
    expire_at = models.DateTimeField(null=True, blank=True, help_text='过期时间')
    max_interviews = models.IntegerField(default=1, help_text='最大面试人数')
    current_interviews = models.IntegerField(default=0, help_text='当前已面试人数')
    
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='job_configs', null=True, blank=True)
    assessment_group = models.ForeignKey(AssessmentGroup, on_delete=models.SET_NULL, related_name='job_configs', null=True, blank=True)
    
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


class ExternalAISession(models.Model):
    """External partner-facing AI interview task mapping."""

    STATUS_CHOICES = [
        ('pending', 'pending'),
        ('in_progress', 'in_progress'),
        ('completed', 'completed'),
        ('failed', 'failed'),
        ('expired', 'expired'),
        ('cancelled', 'cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_id = models.CharField(max_length=128, unique=True, db_index=True)
    external_session_id = models.CharField(max_length=64, unique=True, db_index=True)
    scene = models.CharField(max_length=64, default='ai_interview')
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='pending', db_index=True)

    external_candidate_id = models.CharField(max_length=128, blank=True)
    external_job_id = models.CharField(max_length=128, blank=True)
    callback_url = models.URLField(max_length=1024)

    candidate = models.ForeignKey(Candidate, on_delete=models.SET_NULL, null=True, blank=True, related_name='external_ai_sessions')
    job_config = models.ForeignKey(JobConfiguration, on_delete=models.SET_NULL, null=True, blank=True, related_name='external_ai_sessions')

    request_payload = models.JSONField(default=dict, blank=True)
    create_response = models.JSONField(default=dict, blank=True)
    result_payload = models.JSONField(default=dict, blank=True)

    downloaded_resume_path = models.CharField(max_length=1024, blank=True)
    resume_downloaded_at = models.DateTimeField(null=True, blank=True)

    callback_received = models.BooleanField(default=False)
    callback_attempts = models.IntegerField(default=0)
    callback_last_at = models.DateTimeField(null=True, blank=True)
    callback_last_error = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ai_external_session'
        verbose_name = 'External AI interview session'
        verbose_name_plural = 'External AI interview sessions'
        indexes = [
            models.Index(fields=['request_id', 'status']),
            models.Index(fields=['external_session_id', 'status']),
        ]
