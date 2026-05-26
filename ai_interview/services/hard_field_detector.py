from typing import List, Dict, Any, Set


class HardFieldDetector:
    STANDARD_HARD_FIELDS = {
        'english_level': ['cet4', 'cet6', 'toefl', 'ielts', '英语四级', '英语六级', '托福', '雅思'],
        'cert_pmp': ['pmp', '项目管理专业人士', 'PMP认证'],
        'cert_cpa': ['cpa', '注册会计师', 'cpa证书'],
        'cert_cfa': ['cfa', '特许金融分析师', 'CFA认证'],
        'degree': ['本科', '硕士', '博士', 'Bachelor', 'Master', 'PhD', '学历'],
        'years_experience': ['年经验', '工作年限', '工作经历', 'years'],
    }
    
    # 中文字段名到英文键名的映射
    CHINESE_TO_ENGLISH = {
        '学历': 'degree',
        '工作年限': 'years_experience',
        '技术栈': 'skills',
        '项目经验': 'project_experience',
        '英语能力': 'english_level',
        '证书': 'certifications',
    }

    @classmethod
    def detect_missing_hard_fields(
        cls,
        resume: dict,
        required_hard_fields: List[str]
    ) -> List[str]:
        missing_fields = []
        for field in required_hard_fields:
            # 将中文字段名转换为英文键名
            field_key = cls._chinese_to_english(field)
            if not cls._field_exists_in_resume(field_key, resume):
                missing_fields.append(field)
        return missing_fields
    
    @classmethod
    def _chinese_to_english(cls, field: str) -> str:
        """将中文字段名转换为英文键名"""
        return cls.CHINESE_TO_ENGLISH.get(field, field)

    @classmethod
    def _field_exists_in_resume(cls, field: str, resume: dict) -> bool:
        field_lower = field.lower()

        field_value = resume.get(field) or resume.get(field_lower)
        if field_value:
            if isinstance(field_value, str) and field_value.strip():
                return True
            if isinstance(field_value, list) and len(field_value) > 0:
                return True

        resume_str = cls._flatten_resume_to_string(resume)

        if field_lower in ['english_level', 'cert_pmp', 'cert_cfa', 'cert_cpa']:
            keywords = cls.STANDARD_HARD_FIELDS.get(field, [])
            return any(keyword.lower() in resume_str for keyword in keywords)

        if field_lower == 'degree':
            degree_keywords = cls.STANDARD_HARD_FIELDS.get('degree', [])
            return any(kw.lower() in resume_str for kw in degree_keywords)

        if field_lower == 'years_experience':
            exp_keywords = cls.STANDARD_HARD_FIELDS.get('years_experience', [])
            return any(kw.lower() in resume_str for kw in exp_keywords)

        for key, value in resume.items():
            if isinstance(value, str) and field_lower in key.lower():
                return True
            if field_lower in str(value).lower():
                return True

        return False

    @classmethod
    def _flatten_resume_to_string(cls, resume: dict) -> str:
        parts = []

        def flatten(d, prefix=''):
            for key, value in d.items():
                if isinstance(value, dict):
                    flatten(value, f"{prefix}{key}_")
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            flatten(item, prefix)
                        else:
                            parts.append(str(item))
                else:
                    parts.append(f"{prefix}{key}:{value}")

        flatten(resume)
        return ' '.join(parts).lower()

    @classmethod
    def extract_field_value(cls, field: str, resume: dict) -> Any:
        field_lower = field.lower()

        if field_lower == 'english_level':
            return cls._extract_english_level(resume)
        if field_lower == 'cert_pmp':
            return cls._extract_cert(resume, 'pmp')
        if field_lower == 'cert_cpa':
            return cls._extract_cert(resume, 'cpa')
        if field_lower == 'cert_cfa':
            return cls._extract_cert(resume, 'cfa')
        if field_lower == 'degree':
            return cls._extract_degree(resume)
        if field_lower == 'years_experience':
            return cls._extract_years_experience(resume)

        return resume.get(field) or resume.get(field_lower)

    @classmethod
    def _extract_english_level(cls, resume: dict) -> str:
        resume_str = cls._flatten_resume_to_string(resume)
        if '雅思' in resume_str or 'ielts' in resume_str:
            return '雅思'
        if '托福' in resume_str or 'toefl' in resume_str:
            return '托福'
        if '英语六级' in resume_str or 'cet6' in resume_str:
            return '英语六级'
        if '英语四级' in resume_str or 'cet4' in resume_str:
            return '英语四级'
        return '未明确'

    @classmethod
    def _extract_cert(cls, resume: dict, cert_name: str) -> str:
        resume_str = cls._flatten_resume_to_string(resume)
        if cert_name.lower() in resume_str:
            return f'已获得{cert_name.upper()}认证'
        return '未获得'

    @classmethod
    def _extract_degree(cls, resume: dict) -> str:
        resume_str = cls._flatten_resume_to_string(resume)
        if '博士' in resume_str or 'phd' in resume_str or 'doctor' in resume_str:
            return '博士'
        if '硕士' in resume_str or 'master' in resume_str:
            return '硕士'
        if '本科' in resume_str or 'bachelor' in resume_str:
            return '本科'
        return '未明确'

    @classmethod
    def _extract_years_experience(cls, resume: dict) -> str:
        import re
        resume_str = cls._flatten_resume_to_string(resume)
        patterns = [
            r'(\d+)\s*年\s*经验',
            r'(\d+)\s*年\s*以上',
            r'(\d+)\s*years?\s*experience',
        ]
        for pattern in patterns:
            match = re.search(pattern, resume_str)
            if match:
                return f"{match.group(1)}年经验"
        return '未明确'

    @classmethod
    def get_field_display_name(cls, field: str) -> str:
        field_display = {
            'english_level': '英语水平',
            'cert_pmp': 'PMP认证',
            'cert_cpa': 'CPA认证',
            'cert_cfa': 'CFA认证',
            'degree': '学历',
            'years_experience': '工作年限',
        }
        return field_display.get(field, field)
