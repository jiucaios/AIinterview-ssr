
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-dev-key-change-in-production')

DEBUG = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'daphne',
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'django.contrib.sessions',
    'django.contrib.messages',
    'rest_framework',
    'channels',
    'ai_interview',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

REST_FRAMEWORK = {
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.MultiPartParser',
        'rest_framework.parsers.FormParser',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'UNAUTHENTICATED_USER': None,
}

SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

DASHSCOPE_API_KEY = os.getenv('DASHSCOPE_API_KEY', '')
DASHSCOPE_BASE_URL = os.getenv('DASHSCOPE_BASE_URL', 'https://dashscope.aliyuncs.com')

# 文本任务模型（用于简历解析、JD摘要等不需要实时语音的任务）
QWEN_TEXT_MODEL = os.getenv('QWEN_TEXT_MODEL', 'qwen-plus')

# 实时语音模型（用于面试实时对话）
QWEN_REALTIME_MODEL = os.getenv('QWEN_REALTIME_MODEL', 'qwen3.5-omni-plus-realtime')
QWEN_REALTIME_VOICE = os.getenv('QWEN_REALTIME_VOICE', 'Sunnybobi')
QWEN_REALTIME_URL = os.getenv('QWEN_REALTIME_URL', 'wss://dashscope.aliyuncs.com/api-ws/v1/realtime')
QWEN_REALTIME_TRANSCRIPTION_MODEL = os.getenv('QWEN_REALTIME_TRANSCRIPTION_MODEL', '') or None
QWEN_REALTIME_VAD_THRESHOLD = float(os.getenv('QWEN_REALTIME_VAD_THRESHOLD', '0.5'))
QWEN_REALTIME_VAD_SILENCE_MS = int(os.getenv('QWEN_REALTIME_VAD_SILENCE_MS', '1500'))

QWEN_ENABLE_THINKING = env_bool('QWEN_ENABLE_THINKING', False)
ANSWER_EVALUATION_ENABLED = env_bool('ANSWER_EVALUATION_ENABLED', False)
JD_SUMMARY_ENABLED = env_bool('JD_SUMMARY_ENABLED', False)

QWEN_EMBEDDING_MODEL = os.getenv('QWEN_EMBEDDING_MODEL', 'text-embedding-v4')
EMBEDDING_MODEL = QWEN_EMBEDDING_MODEL

SESSION_TIMEOUT = int(os.getenv('SESSION_TIMEOUT', '600'))

EXTERNAL_AI_SESSION_TOKEN = os.getenv('EXTERNAL_AI_SESSION_TOKEN', 'change-me-before-public')
EXTERNAL_AI_SESSION_EXPIRE_DAYS = int(os.getenv('EXTERNAL_AI_SESSION_EXPIRE_DAYS', '7'))
EXTERNAL_RESUME_STORAGE_DIR = os.getenv('EXTERNAL_RESUME_STORAGE_DIR', str(BASE_DIR / 'external_resumes'))
EXTERNAL_CALLBACK_TIMEOUT_SECONDS = float(os.getenv('EXTERNAL_CALLBACK_TIMEOUT_SECONDS', '0.5'))
EXTERNAL_PUBLIC_BASE_URL = os.getenv('EXTERNAL_PUBLIC_BASE_URL', '').rstrip('/')
AI_INTERVIEW_PUBLIC_BASE_URL = os.getenv('AI_INTERVIEW_PUBLIC_BASE_URL', EXTERNAL_PUBLIC_BASE_URL).rstrip('/')

FEISHU_APP_ID = os.getenv('FEISHU_APP_ID', '').strip()
FEISHU_APP_SECRET = os.getenv('FEISHU_APP_SECRET', '').strip()
FEISHU_VERIFICATION_TOKEN = os.getenv('FEISHU_VERIFICATION_TOKEN', '').strip()
FEISHU_ENCRYPT_KEY = os.getenv('FEISHU_ENCRYPT_KEY', '').strip()

# 调试输出：打印当前配置
print(f"[DEBUG] DASHSCOPE_API_KEY: {'已配置' if DASHSCOPE_API_KEY else '未配置'}")
print(f"[DEBUG] QWEN_TEXT_MODEL (文本任务): {QWEN_TEXT_MODEL}")
print(f"[DEBUG] QWEN_REALTIME_MODEL (实时语音): {QWEN_REALTIME_MODEL}")
print(f"[DEBUG] QWEN_REALTIME_VOICE (音色): {QWEN_REALTIME_VOICE}")
print(f"[DEBUG] QWEN_EMBEDDING_MODEL: {QWEN_EMBEDDING_MODEL}")
