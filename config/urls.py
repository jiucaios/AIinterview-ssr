from django.urls import path, include
from ai_interview.views import (
    HRDashboardView, CandidateEntryView, CandidateWelcomeView, InterviewView,
    HRLoginView, HRLogoutView,
    JobInfoView, VerifyAndStartView, VerifyIdentityView, HRCreateJobView,
    ReleaseInterviewLockView,
    ResumeParserView, ResumeValidateView, VoiceTTSView, VoiceASRView,
    SpeechTTSView, SpeechASRView, InterviewSessionView, InterviewSessionDetailView,
    ExternalAISessionCreateView, ExternalAISessionReportView, ExternalAISessionTranscriptView
)

urlpatterns = [
    # 完整路径 - 主API入口
    path('api/ai-interview/', include('ai_interview.urls')),
    path('api/external/ai-session/create', ExternalAISessionCreateView.as_view(), name='external-ai-session-create-no-slash-api'),
    path('api/external/ai-session/create/', ExternalAISessionCreateView.as_view(), name='external-ai-session-create-api'),
    path('api/external/ai-session/<str:external_session_id>/report/', ExternalAISessionReportView.as_view(), name='external-ai-session-report-api'),
    path('api/external/ai-session/<str:external_session_id>/transcript/', ExternalAISessionTranscriptView.as_view(), name='external-ai-session-transcript-api'),
    
    # 简化路径 - HR管理页面
    path('hr/', HRDashboardView.as_view(), name='hr-dashboard-short'),
    path('hr/login/', HRLoginView.as_view(), name='hr-login-short'),
    path('hr/logout/', HRLogoutView.as_view(), name='hr-logout-short'),
    
    # 简化路径 - 候选人入口页面
    path('interview/', CandidateEntryView.as_view(), name='candidate-entry-short'),
    
    # 简化路径 - 面试对话页面（候选人验证后直接进入）
    path('start-interview/', InterviewView.as_view(), name='start-interview'),
    
    # HR相关API
    path('api/hr/create-job/', HRCreateJobView.as_view(), name='hr-create-job-api'),
    
    # 简历解析API
    path('api/resume/parse/', ResumeParserView.as_view(), name='resume-parser-api'),
    path('api/resume/validate/', ResumeValidateView.as_view(), name='resume-validate-api'),
    
    # 候选人面试API
    path('api/interview/welcome/', CandidateWelcomeView.as_view(), name='candidate-welcome-api'),
    path('api/interview/entry/', CandidateEntryView.as_view(), name='candidate-entry-api'),
    path('api/interview/job-info/', JobInfoView.as_view(), name='job-info-api'),
    path('api/interview/verify-and-start/', VerifyAndStartView.as_view(), name='verify-and-start-api'),
    path('api/interview/verify-identity/', VerifyIdentityView.as_view(), name='verify-identity-api'),
    path('api/interview/release-lock/', ReleaseInterviewLockView.as_view(), name='release-interview-lock-api'),
    
    # 语音服务API
    path('api/ai-interview/voice/tts/', VoiceTTSView.as_view(), name='voice-tts-api'),
    path('api/ai-interview/voice/asr/', VoiceASRView.as_view(), name='voice-asr-api'),
    path('api/ai-interview/speech/tts/', SpeechTTSView.as_view(), name='speech-tts-api'),
    path('api/ai-interview/speech/asr/', SpeechASRView.as_view(), name='speech-asr-api'),
    
    # 会话API
    path('api/ai-interview/session/', InterviewSessionView.as_view(), name='session-api'),
    path('api/ai-interview/session/<str:session_id>/', InterviewSessionDetailView.as_view(), name='session-detail-api'),
]
