from .interview_types import can_analyze_report, get_interview_type_label, is_qa_only_report


def get_profile_interview_type(profile):
    job_config = profile.job_config if profile and isinstance(profile.job_config, dict) else {}
    return job_config.get("interview_type")


def get_report_policy_for_profile(profile):
    interview_type = get_profile_interview_type(profile)
    return {
        "interview_type": interview_type,
        "interview_type_label": get_interview_type_label(interview_type),
        "qa_only": is_qa_only_report(interview_type),
        "can_analyze_report": can_analyze_report(interview_type),
    }
