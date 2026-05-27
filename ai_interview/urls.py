from django.urls import path
from .views import (
    InterviewSessionView, InterviewSessionDetailView, TestToolView,
    ResumeParserView, ResumeValidateView, VoiceTTSView, VoiceASRView,
    SpeechTTSView, SpeechASRView, HRDashboardView, CandidateEntryView,
    HRCreateJobView, JobInfoView, VerifyAndStartView, VerifyIdentityView,
    InterviewView, CandidateManagementView, CandidateListView, CandidateUpdateView,
    SendEmailView, SendEmailImageView, SendEmailAPIView
)

urlpatterns = [
    path('', TestToolView.as_view(), name='test-tool-root'),
    
    path('interview/', InterviewView.as_view(), name='interview'),
    path('session/', InterviewSessionView.as_view(), name='interview-session'),
    path('session/<str:session_id>/', InterviewSessionDetailView.as_view(), name='interview-session-detail'),
    path('test/', TestToolView.as_view(), name='test-tool'),
    path('resume/parse/', ResumeParserView.as_view(), name='resume-parser'),
    path('resume/validate/', ResumeValidateView.as_view(), name='resume-validate'),
    path('voice/tts/', VoiceTTSView.as_view(), name='voice-tts'),
    path('voice/asr/', VoiceASRView.as_view(), name='voice-asr'),
    path('speech/tts/', SpeechTTSView.as_view(), name='speech-tts'),
    path('speech/asr/', SpeechASRView.as_view(), name='speech-asr'),
    
    path('hr/', HRDashboardView.as_view(), name='hr-dashboard'),
    path('hr/create-job/', HRCreateJobView.as_view(), name='hr-create-job'),
    path('hr/candidates/', CandidateManagementView.as_view(), name='hr-candidates'),
    path('hr/candidates/list/', CandidateListView.as_view(), name='hr-candidates-list'),
    path('hr/candidates/update/', CandidateUpdateView.as_view(), name='hr-candidates-update'),
    path('hr/send-email/', SendEmailView.as_view(), name='hr-send-email'),
    path('hr/send-email/images/<str:filename>', SendEmailImageView.as_view(), name='hr-send-email-image'),
    path('hr/send-email/api/', SendEmailAPIView.as_view(), name='hr-send-email-api'),
    path('create-job/', HRCreateJobView.as_view(), name='hr-create-job-short'),
    
    path('interview/entry/', CandidateEntryView.as_view(), name='candidate-entry'),
    path('interview/job-info/', JobInfoView.as_view(), name='job-info'),
    path('interview/verify-and-start/', VerifyAndStartView.as_view(), name='verify-and-start'),
    path('interview/verify-identity/', VerifyIdentityView.as_view(), name='verify-identity'),
    
    path('entry/', CandidateEntryView.as_view(), name='candidate-entry-short'),
    path('job-info/', JobInfoView.as_view(), name='job-info-short'),
    path('verify-and-start/', VerifyAndStartView.as_view(), name='verify-and-start-short'),
    path('verify-identity/', VerifyIdentityView.as_view(), name='verify-identity-short'),
]
