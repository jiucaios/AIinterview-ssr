from django.urls import path, include
from ai_interview.views import (
    HRDashboardView, CandidateEntryView, TestToolView, InterviewView,
    JobInfoView, VerifyAndStartView, VerifyIdentityView, HRCreateJobView,
    ResumeParserView, ResumeValidateView, VoiceTTSView, VoiceASRView,
    SpeechTTSView, SpeechASRView, InterviewSessionView, InterviewSessionDetailView
)

urlpatterns = [
    # 完整路径 - 主API入口
    path('api/ai-interview/', include('ai_interview.urls')),
    
    # 简化路径 - HR管理页面
    path('hr/', HRDashboardView.as_view(), name='hr-dashboard-short'),
    
    # 简化路径 - 候选人入口页面
    path('interview/', CandidateEntryView.as_view(), name='candidate-entry-short'),
    
    # 简化路径 - 测试页面
    path('test/', TestToolView.as_view(), name='test-tool-short'),
    
    # 简化路径 - 面试对话页面（候选人验证后直接进入）
    path('start-interview/', InterviewView.as_view(), name='start-interview'),
    
    # HR相关API
    path('api/hr/create-job/', HRCreateJobView.as_view(), name='hr-create-job-api'),
    
    # 简历解析API
    path('api/resume/parse/', ResumeParserView.as_view(), name='resume-parser-api'),
    path('api/resume/validate/', ResumeValidateView.as_view(), name='resume-validate-api'),
    
    # 测试页面API
    path('api/test/', include('ai_interview.urls')),
    
    # 候选人面试API
    path('api/interview/entry/', CandidateEntryView.as_view(), name='candidate-entry-api'),
    path('api/interview/job-info/', JobInfoView.as_view(), name='job-info-api'),
    path('api/interview/verify-and-start/', VerifyAndStartView.as_view(), name='verify-and-start-api'),
    path('api/interview/verify-identity/', VerifyIdentityView.as_view(), name='verify-identity-api'),
    
    # 语音服务API
    path('api/ai-interview/voice/tts/', VoiceTTSView.as_view(), name='voice-tts-api'),
    path('api/ai-interview/voice/asr/', VoiceASRView.as_view(), name='voice-asr-api'),
    path('api/ai-interview/speech/tts/', SpeechTTSView.as_view(), name='speech-tts-api'),
    path('api/ai-interview/speech/asr/', SpeechASRView.as_view(), name='speech-asr-api'),
    
    # 会话API
    path('api/ai-interview/session/', InterviewSessionView.as_view(), name='session-api'),
    path('api/ai-interview/session/<str:session_id>/', InterviewSessionDetailView.as_view(), name='session-detail-api'),
]
