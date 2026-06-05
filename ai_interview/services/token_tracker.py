from typing import Any, Dict

from django.core.cache import cache
from django.db.models import Count, Sum

from .interview_types import INITIAL_INTERVIEW, DISCUSSION, get_interview_type_label


class TokenTracker:
    """Track token usage in the database."""

    CACHE_PREFIX = 'ai_interview:token:'

    CATEGORY_RESUME_PARSING = 'resume_parsing'
    CATEGORY_JOB_MATCH = 'job_match'
    CATEGORY_OMNI_INTERVIEW = 'omni_interview'
    CATEGORY_ANSWER_ANALYSIS = 'answer_analysis'
    CATEGORY_FEISHU_ASSISTANT = 'feishu_assistant'

    CATEGORY_NAMES = {
        CATEGORY_RESUME_PARSING: '\u7b80\u5386\u89e3\u6790',
        CATEGORY_JOB_MATCH: '\u7b80\u5386\u5339\u914d\u5ea6',
        CATEGORY_OMNI_INTERVIEW: 'Omni\u8bed\u97f3\u9762\u8bd5',
        CATEGORY_ANSWER_ANALYSIS: '\u56de\u7b54\u5206\u6790',
        CATEGORY_FEISHU_ASSISTANT: '\u98de\u4e66',
    }

    @classmethod
    def _get_cache_key(cls, category: str) -> str:
        return f"{cls.CACHE_PREFIX}{category}"

    @classmethod
    def _get_total_key(cls) -> str:
        return f"{cls.CACHE_PREFIX}total"

    @classmethod
    def _save_to_database(
        cls,
        category: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        model: str = None,
        metadata: dict = None,
    ) -> bool:
        """Save one token usage record to the database."""
        try:
            from ..models import TokenUsage

            TokenUsage.objects.create(
                category=category,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                model=model or '',
                metadata=metadata or {},
            )
            return True
        except Exception as e:
            print(f"Token database write failed: {e}")
            return False

    @classmethod
    def record_usage(
        cls,
        category: str,
        input_tokens: int,
        output_tokens: int,
        model: str = None,
        metadata: dict = None,
    ) -> bool:
        """Record one token usage row in the database."""
        try:
            total_tokens = input_tokens + output_tokens
            return cls._save_to_database(
                category,
                input_tokens,
                output_tokens,
                total_tokens,
                model,
                metadata,
            )
        except Exception as e:
            print(f"Token usage record failed: {e}")
            return False

    @classmethod
    def get_category_stats(cls, category: str) -> Dict[str, Any]:
        """Get stats for one category from the database."""
        for item in cls.get_stats_from_database()['categories']:
            if item['category'] == category:
                return item

        return {
            'category': category,
            'category_name': cls.CATEGORY_NAMES.get(category, category),
            'input_tokens': 0,
            'output_tokens': 0,
            'total_tokens': 0,
            'call_count': 0,
            'model': '',
            'recent_records': [],
        }

    @classmethod
    def get_all_stats(cls) -> Dict[str, Any]:
        """Get all token stats from the database."""
        return cls.get_stats_from_database()

    @classmethod
    def clear_stats(cls, category: str = None) -> bool:
        """Clear token stats from the database and remove stale cache keys."""
        try:
            from ..models import TokenUsage

            if category:
                TokenUsage.objects.filter(category=category).delete()
                cache.delete(cls._get_cache_key(category))
            else:
                TokenUsage.objects.all().delete()
                for cat in cls.CATEGORY_NAMES.keys():
                    cache.delete(cls._get_cache_key(cat))
                cache.delete(cls._get_total_key())
            return True
        except Exception as e:
            print(f"Token stats clear failed: {e}")
            return False

    @classmethod
    def get_stats_from_database(cls) -> Dict[str, Any]:
        """Get token stats directly from the database."""
        from ..models import TokenUsage

        total_data = TokenUsage.objects.aggregate(
            input_tokens=Sum('input_tokens'),
            output_tokens=Sum('output_tokens'),
            total_tokens=Sum('total_tokens'),
            call_count=Count('id'),
        )

        category_stats = []
        for cat in cls.CATEGORY_NAMES.keys():
            cat_data = TokenUsage.objects.filter(category=cat).aggregate(
                input_tokens=Sum('input_tokens'),
                output_tokens=Sum('output_tokens'),
                total_tokens=Sum('total_tokens'),
                call_count=Count('id'),
            )
            latest_record = TokenUsage.objects.filter(category=cat).order_by('-created_at').first()

            recent_records = [
                {
                    'timestamp': record.created_at.timestamp(),
                    'input_tokens': record.input_tokens,
                    'output_tokens': record.output_tokens,
                    'total_tokens': record.total_tokens,
                    'model': record.model,
                    'metadata': record.metadata,
                }
                for record in TokenUsage.objects.filter(category=cat).order_by('-created_at')[:10]
            ]

            category_stats.append({
                'category': cat,
                'category_name': cls.CATEGORY_NAMES[cat],
                'input_tokens': cat_data['input_tokens'] or 0,
                'output_tokens': cat_data['output_tokens'] or 0,
                'total_tokens': cat_data['total_tokens'] or 0,
                'call_count': cat_data['call_count'] or 0,
                'model': latest_record.model if latest_record else '',
                'branches': cls._get_omni_branches(TokenUsage) if cat == cls.CATEGORY_OMNI_INTERVIEW else [],
                'recent_records': recent_records,
            })

        return {
            'total': {
                'input_tokens': total_data['input_tokens'] or 0,
                'output_tokens': total_data['output_tokens'] or 0,
                'total_tokens': total_data['total_tokens'] or 0,
                'call_count': total_data['call_count'] or 0,
            },
            'categories': category_stats,
            'category_names': cls.CATEGORY_NAMES,
        }

    @classmethod
    def _get_omni_branches(cls, token_usage_model):
        branches = []
        for interview_type in (INITIAL_INTERVIEW, DISCUSSION):
            queryset = token_usage_model.objects.filter(category=cls.CATEGORY_OMNI_INTERVIEW)
            if interview_type == DISCUSSION:
                queryset = queryset.filter(metadata__interview_type=DISCUSSION)
            else:
                queryset = queryset.exclude(metadata__interview_type=DISCUSSION)
            data = queryset.aggregate(
                input_tokens=Sum('input_tokens'),
                output_tokens=Sum('output_tokens'),
                total_tokens=Sum('total_tokens'),
                call_count=Count('id'),
            )
            latest_record = queryset.order_by('-created_at').first()
            branches.append({
                'interview_type': interview_type,
                'label': get_interview_type_label(interview_type),
                'input_tokens': data['input_tokens'] or 0,
                'output_tokens': data['output_tokens'] or 0,
                'total_tokens': data['total_tokens'] or 0,
                'call_count': data['call_count'] or 0,
                'model': latest_record.model if latest_record else '',
            })
        return branches
