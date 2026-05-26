
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-dev-key-change-in-production')

DEBUG = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
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

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

DASHSCOPE_API_KEY = os.getenv('DASHSCOPE_API_KEY', '')
QWEN_MODEL = os.getenv('QWEN_MODEL', 'qwen-plus')
QWEN_MODEL_BASE = os.getenv('QWEN_MODEL_BASE', 'qwen-plus')
QWEN_EMBEDDING_MODEL = os.getenv('QWEN_EMBEDDING_MODEL', 'text-embedding-v4')
EMBEDDING_MODEL = QWEN_EMBEDDING_MODEL
SESSION_TIMEOUT = int(os.getenv('SESSION_TIMEOUT', '120'))

# 调试输出：打印当前配置
print(f"[DEBUG] DASHSCOPE_API_KEY: {'已配置' if DASHSCOPE_API_KEY else '未配置'}")
print(f"[DEBUG] QWEN_MODEL (高级): {QWEN_MODEL}")
print(f"[DEBUG] QWEN_MODEL_BASE (基础): {QWEN_MODEL_BASE}")
print(f"[DEBUG] QWEN_EMBEDDING_MODEL: {QWEN_EMBEDDING_MODEL}")
