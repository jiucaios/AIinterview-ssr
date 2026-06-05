from urllib.parse import quote

from django.conf import settings


DEFAULT_WELCOME_PATH = "/api/ai-interview/interview/welcome/"
DEFAULT_INTERVIEW_PATH = "/api/ai-interview/interview/"


def get_public_base_url(request):
    configured = (
        getattr(settings, "AI_INTERVIEW_PUBLIC_BASE_URL", "")
        or getattr(settings, "EXTERNAL_PUBLIC_BASE_URL", "")
        or ""
    ).strip().rstrip("/")
    if configured:
        return configured

    return f"https://{request.get_host()}"


def build_interview_welcome_url(request, config_id):
    base_url = get_public_base_url(request)
    return f"{base_url}{DEFAULT_WELCOME_PATH}?config_id={quote(str(config_id))}"


def build_start_interview_url(request, session_id, candidate_id, config_id):
    base_url = get_public_base_url(request)
    return (
        f"{base_url}{DEFAULT_INTERVIEW_PATH}?session_id={quote(str(session_id))}"
        f"&candidate_id={quote(str(candidate_id))}"
        f"&config_id={quote(str(config_id))}"
    )
