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
    'django.contrib.sitemaps',
    'rest_framework',
    'books.apps.BooksConfig',
    'core.apps.CoreConfig',
    'accounts.apps.AccountsConfig',
    'intake.apps.IntakeConfig',
    'web.apps.WebConfig',
    'context.apps.ContextConfig',
    'marketing.apps.MarketingConfig',
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
    if 'test' in sys.argv or 'testserver' in sys.argv:
        # accounts/0001이 0002에서야 생기는 커스텀 User를 참조해 빈 DB에선 마이그레이션이 깨진다(운영 DB는 이미 적용 완료).
        # 테스트 DB는 현재 모델로 바로 만든다. 모델↔마이그레이션 일치는 `makemigrations --check`로 따로 확인.
        MIGRATION_MODULES = {app: None for app in ('accounts', 'books', 'core', 'intake', 'web', 'context', 'marketing')}
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

if ENV_MODE == 'prod' or os.getenv('MANIFEST_STATIC') == '1':
    # 파일 이름에 내용 해시를 붙여 배포 즉시 새 CSS가 보이고 긴 캐시가 안전해진다 (collectstatic 필수 — deploy.sh가 실행)
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'

if ENV_MODE == 'test':
    DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'
    MEDIA_ROOT = os.path.join(tempfile.gettempdir(), 'hantijae-test-media')
    # 화면 검증(testserver)에서 실제 S3 표지를 보려면 TEST_MEDIA_URL=https://hantijae-assets.s3.amazonaws.com/
    MEDIA_URL = os.getenv('TEST_MEDIA_URL', '/media/')
else:
    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
AWS_DEFAULT_ACL = 'public-read'
AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'

SITE_URL = os.getenv('SITE_URL', 'https://hantijae-bookstore.com')
NAVER_ANALYTICS_ID = secret_info.get('NAVER_ANALYTICS_ID', '')

INTAKE = {
    'TELEGRAM_BOT_TOKEN': secret_info.get('TELEGRAM_BOT_TOKEN', ''),
    'TELEGRAM_INVITE_CODE': secret_info.get('TELEGRAM_INVITE_CODE', ''),
    'SIDECAR_URL': secret_info.get('AI_SIDECAR_URL', ''),
    'SIDECAR_TOKEN': secret_info.get('AI_SIDECAR_AUTH_TOKEN', ''),
    'SIDECAR_MODEL': 'claude-opus-5-5[1m]',
    'GOOGLE_SERVICE_ACCOUNT_JSON': secret_info.get('GOOGLE_SERVICE_ACCOUNT_JSON', ''),
    'DRIVE_ROOT_FOLDER_ID': secret_info.get('DRIVE_ROOT_FOLDER_ID', ''),
    'NOTION_TOKEN': secret_info.get('NOTION_TOKEN', ''),
    'NOTION_DATA_SOURCE_ID': secret_info.get('NOTION_BOOKS_DATA_SOURCE_ID', ''),
    'WORK_DIR': os.getenv('INTAKE_WORK_DIR', os.path.join(tempfile.gettempdir(), 'hantijae-intake')),
    'DRIVE_SCAN_SECONDS': 600,
    'DRIVE_STABLE_SECONDS': 1800,
    'FUND_SCAN_SECONDS': 6 * 3600,
}

# 마케팅 비서 바깥 수집: 운영진 개인 SNS(Apify), 한티재 공식 채널(Meta), 독자 서평 검색(네이버 API HUB·카카오).
# 계정 주소는 공개 저장소에 두지 않는다.
MARKETING = {
    'APIFY_TOKEN': secret_info.get('APIFY_TOKEN', ''),
    'SOCIAL_ACCOUNTS': secret_info.get('SOCIAL_ACCOUNTS', ''),
    'META_PAGE_TOKEN': secret_info.get('META_PAGE_TOKEN', ''),
    'META_APP_SECRET': secret_info.get('META_APP_SECRET', ''),
    'META_PAGE_ID': secret_info.get('META_PAGE_ID', ''),
    'META_IG_USER_ID': secret_info.get('META_IG_USER_ID', ''),
    'META_ACCESS_EXPIRES': secret_info.get('META_ACCESS_EXPIRES', ''),   # 인스타 데이터 접근 만료일(YYYY-MM-DD), 다시 발급하면 바꾼다
    'KPIPA_BNK_ID': secret_info.get('KPIPA_BNK_ID', ''),   # 출판유통통합전산망(대표 계정, 대표 동의)
    'KPIPA_BNK_PASSWORD': secret_info.get('KPIPA_BNK_PASSWORD', ''),
    'KAKAO_REST_API_KEY': secret_info.get('KAKAO_REST_API_KEY', ''),
    'NAVER_HUB_CLIENT_ID': secret_info.get('NAVER_HUB_CLIENT_ID', ''),
    'NAVER_HUB_CLIENT_SECRET': secret_info.get('NAVER_HUB_CLIENT_SECRET', ''),
    'DATA4LIBRARY_AUTH_KEY': secret_info.get('DATA4LIBRARY_AUTH_KEY', ''),   # 도서관 정보나루(서버 IP 등록)
    'GOOGLE_ALERTS_FEEDS': secret_info.get('GOOGLE_ALERTS_FEEDS', ''),   # JSON 목록(피드 주소 자체가 비밀)
    'YOUTUBE_API_KEY': secret_info.get('YOUTUBE_API_KEY', ''),
}

# 맥락 기록(검수 방 대화 등). 원문은 가린 채 이 기간만 보관한다.
CONTEXT = {
    'RETENTION_DAYS': 90,
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'loggers': {'intake': {'handlers': ['console'], 'level': 'INFO'}},
}
