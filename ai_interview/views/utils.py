from django.db.models import Q
from ..models import TalentProfile
from ..services.session_manager import SessionManager


def talent_profiles_for_config(config_id):
    profiles = TalentProfile.objects.all()
    matching_ids = []
    for profile in profiles:
        job_config = profile.job_config
        if isinstance(job_config, dict) and job_config.get('config_id') == config_id:
            matching_ids.append(profile.id)

    if matching_ids:
        return TalentProfile.objects.filter(id__in=matching_ids)
    return TalentProfile.objects.none()


def mark_profile_completed_if_finished(profile):
    if not profile or profile.interview_completed:
        return profile

    profile_data = profile.profile_data or {}
    finished = (
        profile_data.get('interview_completed')
        or profile_data.get('session_state') == 'completed'
        or SessionManager.has_interview_completed(profile.dialogue_history or [])
    )
    if not finished:
        return profile

    profile.interview_completed = True
    profile.session_incomplete = False
    profile_data['interview_completed'] = True
    profile_data['session_state'] = 'completed'
    profile_data['qa_records'] = profile_data.get('qa_records') or SessionManager.build_qa_records(
        profile.dialogue_history
    )
    profile.profile_data = profile_data
    profile.save(update_fields=['interview_completed', 'session_incomplete', 'profile_data', 'updated_at'])
    SessionManager.release_job_lock(profile.job_config.get('config_id') if isinstance(profile.job_config, dict) else '')
    from ..services.external_ai_session import trigger_completion_callback_for_profile

    trigger_completion_callback_for_profile(profile)
    return profile
