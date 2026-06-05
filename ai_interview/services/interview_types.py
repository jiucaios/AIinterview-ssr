INITIAL_INTERVIEW = "initial_interview"
DISCUSSION = "discussion"

INTERVIEW_TYPE_CHOICES = (
    (INITIAL_INTERVIEW, "初次面试"),
    (DISCUSSION, "面谈"),
)

INTERVIEW_TYPE_CONFIG = {
    INITIAL_INTERVIEW: {
        "label": "初次面试",
        "uses_job_level": True,
        "uses_hard_fields": True,
        "uses_custom_questions": True,
        "uses_recruitment_requirements": False,
        "prompt_builder": "initial",
        "result_view": "full_analysis",
        "can_analyze_report": True,
        "max_rounds": 6,
    },
    DISCUSSION: {
        "label": "面谈",
        "uses_job_level": True,
        "uses_hard_fields": False,
        "uses_custom_questions": False,
        "uses_recruitment_requirements": True,
        "prompt_builder": "discussion",
        "result_view": "qa_only",
        "can_analyze_report": False,
        "max_rounds": None,
    },
}


def normalize_interview_type(value):
    if value in INTERVIEW_TYPE_CONFIG:
        return value
    if value in {"discussion_interview", "talk", "meeting", "面谈"}:
        return DISCUSSION
    return INITIAL_INTERVIEW


def get_interview_type_config(value):
    interview_type = normalize_interview_type(value)
    return INTERVIEW_TYPE_CONFIG[interview_type]


def get_interview_type_label(value):
    return get_interview_type_config(value)["label"]


def can_analyze_report(value):
    return bool(get_interview_type_config(value).get("can_analyze_report"))


def is_qa_only_report(value):
    return get_interview_type_config(value).get("result_view") == "qa_only"
