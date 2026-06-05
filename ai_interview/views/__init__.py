from .utils import talent_profiles_for_config, mark_profile_completed_if_finished
from .interview import (
    InterviewView,
    InterviewSessionView,
    InterviewSessionDetailView,
)
from .resume import (
    ResumeParserView,
    ResumeValidateView,
)
from .voice import (
    VoiceTTSView,
    VoiceASRView,
    SpeechTTSView,
    SpeechASRView,
)
from .hr import (
    HRDashboardView,
    CandidateManagementView,
    CandidateListView,
    CandidateDeleteView,
    CandidateUpdateView,
    CandidateAssessmentGroupSwitchView,
)
from .batch import (
    BatchInterviewView,
)
from .hr_auth import (
    HRAuthContextView,
    HRLoginView,
    HRLogoutView,
)
from .hr_users import (
    HRUserManagementView,
    HRUserListCreateView,
    HRUserDetailView,
)
from .report import (
    CandidateInterviewReportView,
    CandidateInterviewReportDataView,
    CandidateInterviewReportAnalyzeView,
    build_interview_report_analysis,
)
from .email import (
    SendEmailView,
    SendEmailImageView,
    SendEmailAPIView,
    EMAIL_LOGO_FILENAME,
    EMAIL_CONTACT,
    EMAIL_SUPPORT_PHONE,
    get_email_logo_path,
    build_interview_email_text,
    build_logo_html,
    build_interview_email_html,
    send_message_via_smtp,
)
from .candidate import (
    CandidateEntryView,
    CandidateWelcomeView,
    HRCreateJobView,
    JobInfoView,
    VerifyAndStartView,
    ReleaseInterviewLockView,
    VerifyIdentityView,
)
from .external import (
    ExternalAISessionCreateView,
    ExternalAISessionReportView,
    ExternalAISessionTranscriptView,
)
from .feishu import (
    FeishuEventCallbackView,
)

__all__ = [
    'talent_profiles_for_config',
    'mark_profile_completed_if_finished',
    'InterviewView',
    'InterviewSessionView',
    'InterviewSessionDetailView',
    'ResumeParserView',
    'ResumeValidateView',
    'VoiceTTSView',
    'VoiceASRView',
    'SpeechTTSView',
    'SpeechASRView',
    'HRDashboardView',
    'BatchInterviewView',
    'CandidateManagementView',
    'CandidateListView',
    'CandidateDeleteView',
    'CandidateUpdateView',
    'CandidateAssessmentGroupSwitchView',
    'HRAuthContextView',
    'HRLoginView',
    'HRLogoutView',
    'HRUserManagementView',
    'HRUserListCreateView',
    'HRUserDetailView',
    'CandidateInterviewReportView',
    'CandidateInterviewReportDataView',
    'CandidateInterviewReportAnalyzeView',
    'build_interview_report_analysis',
    'SendEmailView',
    'SendEmailImageView',
    'SendEmailAPIView',
    'EMAIL_LOGO_FILENAME',
    'EMAIL_CONTACT',
    'EMAIL_SUPPORT_PHONE',
    'get_email_logo_path',
    'build_interview_email_text',
    'build_logo_html',
    'build_interview_email_html',
    'send_message_via_smtp',
    'CandidateEntryView',
    'CandidateWelcomeView',
    'HRCreateJobView',
    'JobInfoView',
    'VerifyAndStartView',
    'ReleaseInterviewLockView',
    'VerifyIdentityView',
    'ExternalAISessionCreateView',
    'ExternalAISessionReportView',
    'ExternalAISessionTranscriptView',
    'FeishuEventCallbackView',
]
