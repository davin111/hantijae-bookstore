import os
import json
import sys
import tempfile

import boto3

ENV_MODE = os.getenv('MODE', 'dev')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'books.apps.BooksConfig',
    'core.apps.CoreConfig',
    'accounts.apps.AccountsConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'hantijae_bookstore.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'hantijae_bookstore.wsgi.application'

if ENV_MODE == 'test':
    # 운영 DB·Secrets Manager 없이 도는 테스트 전용 설정
    secret_info = {}
    DEBUG = False
    ALLOWED_HOSTS = ['testserver', 'localhost']
    SECRET_KEY = 'test-only-secret-key'
    AWS_STORAGE_BUCKET_NAME = 'hantijae-assets-test'
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
    if 'test' in sys.argv:
        # accounts/0001이 0002에서야 생기는 커스텀 User를 참조해 빈 DB에선 마이그레이션이 깨진다(운영 DB는 이미 적용 완료).
        # 테스트 DB는 현재 모델로 바로 만든다. 모델↔마이그레이션 일치는 `makemigrations --check`로 따로 확인.
        MIGRATION_MODULES = {app: None for app in ('accounts', 'books', 'core', 'intake')}
elif ENV_MODE == 'prod':
    secrets_manager = boto3.client("secretsmanager", region_name="ap-northeast-2")
    credential = secrets_manager.get_secret_value(SecretId="prod/hantijae-bookstore")
    secret_info = json.loads(credential["SecretString"])

    DEBUG = False
    ALLOWED_HOSTS = [
        'localhost',
        '127.0.0.1',
        '[::1]',
        '.hantijae-bookstore.com',
    ]

    SECRET_KEY = secret_info['DJANGO_SECRET_KEY']

    AWS_STORAGE_BUCKET_NAME = "hantijae-assets"

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': secret_info['DATABASE_NAME'],
            'USER': secret_info['DATABASE_USER'],
            'PASSWORD': secret_info['DATABASE_PASSWORD'],
            'HOST': secret_info['DATABASE_HOST'],
            'PORT': secret_info['DATABASE_PORT'],
            'OPTIONS': {
                'init_command': "SET sql_mode='STRICT_ALL_TABLES'",
                'charset': 'utf8mb4',
                'autocommit': True,
                'connect_timeout': 3,
            },
        },
    }
else:
    secrets_manager = boto3.client("secretsmanager", region_name="ap-northeast-2")
    credential = secrets_manager.get_secret_value(SecretId="prod/hantijae-bookstore")
    secret_info = json.loads(credential["SecretString"])

    DEBUG = True
    ALLOWED_HOSTS = []

    SECRET_KEY = '%$(uu1zk1f4*8wnljep5ug(5t7*2u3+&exurk*0t+af56vbued'

    AWS_STORAGE_BUCKET_NAME = "hantijae-assets-dev"

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': secret_info['DATABASE_NAME'],
            'USER': secret_info['DATABASE_USER'],
            'PASSWORD': secret_info['DATABASE_PASSWORD'],
            'HOST': '127.0.0.1',
            'PORT': '13306',
            'OPTIONS': {
                'init_command': "SET sql_mode='STRICT_ALL_TABLES'",
                'charset': 'utf8mb4',
                'autocommit': True,
                'connect_timeout': 3,
            },
        },
    }

if ENV_MODE == 'test':
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'TIMEOUT': 3600}}
else:
    # uWSGI 워커들과 intake 워커가 같은 캐시를 봐야 무효화가 전파된다 (LocMemCache는 프로세스별)
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
            'LOCATION': os.getenv('DJANGO_CACHE_DIR', '/var/tmp/hantijae-django-cache'),
            'TIMEOUT': 3600,
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

CSRF_COOKIE_NAME = 'csrftoken'

AUTH_USER_MODEL = 'accounts.User'
SESSION_SAVE_EVERY_REQUEST = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

STATIC_URL = '/django_static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static')

if ENV_MODE == 'test':
    DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'
    MEDIA_ROOT = os.path.join(tempfile.gettempdir(), 'hantijae-test-media')
    MEDIA_URL = '/media/'
else:
    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
AWS_DEFAULT_ACL = 'public-read'
AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'

SITE_URL = os.getenv('SITE_URL', 'https://hantijae-bookstore.com')
