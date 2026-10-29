import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import dj_database_url

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file if it exists
load_dotenv(BASE_DIR / '.env')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')

# Insecure placeholder substrings prohibited in production environments
INSECURE_SECRET_PATTERNS = [
    'django-insecure',
    'change-this',
    'secret-key',
    'placeholder',
    'default',
]


def validate_secret_key(key: str, debug: bool) -> str:
    """
    Validates Django SECRET_KEY configuration.
    In production (DEBUG=False):
      - Must be provided and non-empty.
      - Must be at least 32 characters long.
      - Must not contain known insecure placeholder substrings.
      - Raises ImproperlyConfigured on any violation.
    In development (DEBUG=True):
      - Permits explicit environment key or uses isolated development-only fallback.
    """
    cleaned = (key or '').strip('\'"')
    if not debug:
        from django.core.exceptions import ImproperlyConfigured
        if not cleaned:
            raise ImproperlyConfigured(
                "CRITICAL SECURITY CONFIGURATION ERROR: SECRET_KEY environment variable is missing in production (DEBUG=False). "
                "Set a strong, random SECRET_KEY in your hosting environment."
            )
        if any(pat in cleaned.lower() for pat in INSECURE_SECRET_PATTERNS) or len(cleaned) < 32:
            raise ImproperlyConfigured(
                "CRITICAL SECURITY CONFIGURATION ERROR: SECRET_KEY in production (DEBUG=False) is insecure or too short (< 32 chars). "
                "Must be a strong, cryptographically random secret."
            )
        return cleaned

    if cleaned:
        return cleaned
    return 'django-insecure-dev-local-only-flickpick-do-not-use-in-production-2026'


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = validate_secret_key(os.getenv('SECRET_KEY', ''), DEBUG)

ALLOWED_HOSTS = [host.strip() for host in os.getenv('ALLOWED_HOSTS', '127.0.0.1,localhost,testserver').split(',') if host.strip()]
if 'testserver' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append('testserver')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # FlickPick apps
    'movies.apps.MoviesConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'movies.middleware.RequestLoggingMiddleware',
]

ROOT_URLCONF = 'flickpick.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'movies.context_processors.flickpick_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'flickpick.wsgi.application'

# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases
DATABASE_URL = os.getenv('DATABASE_URL')
if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.strip('\'"')
DATABASE_URL_UNPOOLED = os.getenv('DATABASE_URL_UNPOOLED')
if DATABASE_URL_UNPOOLED:
    DATABASE_URL_UNPOOLED = DATABASE_URL_UNPOOLED.strip('\'"')

# Schema migrations and administrative / bulk commands should use the direct unpooled connection
# to avoid PgBouncer transaction pooling limitations in Neon.
is_migration_or_management = any(
    cmd in sys.argv
    for cmd in [
        'migrate',
        'makemigrations',
        'inspectdb',
        'dbshell',
        'loaddata',
        'dumpdata',
        'import_movie_datasets',
        'seed_faqs_and_errors',
        'apply_approved_posters',
        'bulk_retrieve_tmdb_posters',
    ]
)
active_db_url = (
    DATABASE_URL_UNPOOLED if is_migration_or_management and DATABASE_URL_UNPOOLED else DATABASE_URL
)

if active_db_url:
    DATABASES = {
        'default': dj_database_url.parse(
            active_db_url,
            conn_max_age=600,
            conn_health_checks=True,
            ssl_require=True,
        ),
        'sqlite': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        },
    }
    DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': Path(os.getenv('SQLITE_DB_PATH', BASE_DIR / 'db.sqlite3')),
        }
    }

# Password validation
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

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Authentication URLs
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'home'
LOGIN_URL = 'login'

# TMDB Configuration (Optional)
TMDB_API_KEY = os.getenv('TMDB_API_KEY', '').strip('\'"')

# FlickPick AI Configuration
FLICKPICK_AI_ENABLED = os.getenv('FLICKPICK_AI_ENABLED', 'True').lower() in ('true', '1', 'yes')
FLICKPICK_LLM_PROVIDER = os.getenv('FLICKPICK_LLM_PROVIDER', 'ollama').lower().strip('\'"')
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434').strip('\'"')
FLICKPICK_OLLAMA_MODEL = os.getenv('FLICKPICK_OLLAMA_MODEL', 'qwen3:4b').strip('\'"')
FLICKPICK_EMBEDDING_MODEL = os.getenv('FLICKPICK_EMBEDDING_MODEL', 'BAAI/bge-small-en-v1.5').strip('\'"')
FLICKPICK_GEMINI_API_KEY = os.getenv('FLICKPICK_GEMINI_API_KEY', '').strip('\'"')
FLICKPICK_GEMINI_MODEL = os.getenv('FLICKPICK_GEMINI_MODEL', 'gemini-2.5-flash').strip('\'"')
FLICKPICK_AI_REQUEST_TIMEOUT = int(os.getenv('FLICKPICK_AI_REQUEST_TIMEOUT', '15'))

# MongoDB Configuration (Optional chat logging & user feedback)
MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/').strip('\'"')
MONGODB_DB_NAME = os.getenv('MONGODB_DB_NAME', 'flickpick_logs').strip('\'"')
MONGODB_TIMEOUT_MS = int(os.getenv('MONGODB_TIMEOUT_MS', '2000'))

# Production-safe logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'flickpick.requests': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'movies': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
