from django.db import transaction
from django.db.models import Max

from ..models import AssessmentGroup, JobConfiguration


def normalize_group_text(value):
    return (value or '').strip()


def build_job_key(job_name):
    return normalize_group_text(job_name).lower()


def find_compatible_assessment_group(candidate, candidate_name, candidate_email, job_name, interview_type):
    candidate_name = normalize_group_text(candidate_name)
    candidate_email = normalize_group_text(candidate_email).lower()
    job_key = build_job_key(job_name)
    groups = AssessmentGroup.objects.filter(
        candidate_name=candidate_name,
        candidate_email=candidate_email,
        job_key=job_key,
        is_temporary=False,
    ).order_by('group_number', 'created_at')

    for group in groups:
        if not group.job_configs.filter(interview_type=interview_type).exists():
            return group
    return None


def create_next_assessment_group(candidate, candidate_name, candidate_email, job_name):
    candidate_name = normalize_group_text(candidate_name)
    candidate_email = normalize_group_text(candidate_email).lower()
    job_name = normalize_group_text(job_name)
    job_key = build_job_key(job_name)
    max_number = AssessmentGroup.objects.filter(
        candidate_name=candidate_name,
        candidate_email=candidate_email,
        job_key=job_key,
        is_temporary=False,
    ).aggregate(value=Max('group_number'))['value'] or 0
    return AssessmentGroup.objects.create(
        candidate=candidate,
        candidate_name=candidate_name,
        candidate_email=candidate_email,
        job_key=job_key,
        job_name=job_name,
        group_number=max_number + 1,
        is_temporary=False,
    )


def get_or_create_temporary_assessment_group(candidate, candidate_name, candidate_email, job_name):
    candidate_name = normalize_group_text(candidate_name)
    candidate_email = normalize_group_text(candidate_email).lower()
    job_name = normalize_group_text(job_name)
    job_key = build_job_key(job_name)
    group, _created = AssessmentGroup.objects.get_or_create(
        candidate_name=candidate_name,
        candidate_email=candidate_email,
        job_key=job_key,
        group_number=0,
        defaults={
            'candidate': candidate,
            'job_name': job_name,
            'is_temporary': True,
        },
    )
    if not group.is_temporary:
        group.is_temporary = True
        group.save(update_fields=['is_temporary', 'updated_at'])
    return group


@transaction.atomic
def assign_assessment_group(job_config):
    if not job_config or job_config.assessment_group_id:
        return job_config.assessment_group if job_config else None
    candidate = job_config.candidate
    candidate_name = candidate.name if candidate else ''
    candidate_email = candidate.email if candidate else ''
    group = find_compatible_assessment_group(
        candidate,
        candidate_name,
        candidate_email,
        job_config.job_name,
        job_config.interview_type,
    )
    if not group:
        group = create_next_assessment_group(candidate, candidate_name, candidate_email, job_config.job_name)
    JobConfiguration.objects.filter(id=job_config.id).update(assessment_group=group)
    job_config.assessment_group = group
    return group


def available_assessment_groups_for_config(job_config):
    group = assign_assessment_group(job_config)
    if not group:
        return []
    groups = AssessmentGroup.objects.filter(
        candidate_name=group.candidate_name,
        candidate_email=group.candidate_email,
        job_key=group.job_key,
    ).order_by('is_temporary', 'group_number', 'created_at')
    values = []
    for item in groups:
        type_labels = []
        existing_types = set(item.job_configs.values_list('interview_type', flat=True))
        if 'initial_interview' in existing_types:
            type_labels.append('面试')
        if 'discussion' in existing_types:
            type_labels.append('面谈')
        values.append({
            'id': str(item.id),
            'label': '临时组' if item.is_temporary else f'第{item.group_number}评估组',
            'detail': '、'.join(type_labels) if type_labels else '暂无记录',
            'group_number': item.group_number,
            'is_temporary': item.is_temporary,
        })
    return values


@transaction.atomic
def switch_assessment_group(job_config, group_id):
    current_group = assign_assessment_group(job_config)
    if group_id == '__temporary__':
        if not current_group:
            raise ValueError('当前记录没有可用评估组')
        target_group = get_or_create_temporary_assessment_group(
            job_config.candidate,
            current_group.candidate_name,
            current_group.candidate_email,
            current_group.job_name,
        )
        JobConfiguration.objects.filter(id=job_config.id).update(assessment_group=target_group)
        job_config.assessment_group = target_group
        return target_group

    target_group = AssessmentGroup.objects.filter(id=group_id).first()
    if not target_group:
        raise ValueError('评估组不存在')
    if not current_group:
        raise ValueError('当前记录没有可用评估组')
    if (
        target_group.candidate_name != current_group.candidate_name
        or target_group.candidate_email != current_group.candidate_email
        or target_group.job_key != current_group.job_key
    ):
        raise ValueError('只能切换到同一候选人同一岗位下的评估组')
    has_same_type = target_group.job_configs.exclude(id=job_config.id).filter(
        interview_type=job_config.interview_type
    ).exists()
    if has_same_type:
        raise ValueError('目标评估组已有同类型记录，不能重复放入')
    JobConfiguration.objects.filter(id=job_config.id).update(assessment_group=target_group)
    job_config.assessment_group = target_group
    return target_group
