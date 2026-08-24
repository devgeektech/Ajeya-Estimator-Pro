"""Single settings module for BOQ_AI.

All runtimes use this module. Environment values are read from ``.env`` in the
project root when present, and production safety checks are enabled whenever
``DEBUG=False``.
"""

from pathlib import Path
import sys

import environ
from django.core.exceptions import ImproperlyConfigured

from common.host_origins import csrf_trusted_origins_from_hosts

# Make Django model fields resolve to Python types under pyright/django-stubs.
try:
    import django_stubs_ext

    django_stubs_ext.monkeypatch()
except ImportError:
    pass

# backend/ directory (contains manage.py, config/, apps/, ...)
BASE_DIR = Path(__file__).resolve().parents[1]
# Project root (contains backend/, docs/, templates/, static/, media/, ...)
ROOT_DIR = BASE_DIR.parent

# Repo-root ``tests/`` plus ``backend/`` (apps, config, common).
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)

env_file = ROOT_DIR / ".env"
if env_file.exists():
    env.read_env(str(env_file))

SECRET_KEY = env.str("SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = [host.strip() for host in env.list("ALLOWED_HOSTS") if str(host).strip()]

if not DEBUG:
    if SECRET_KEY == "insecure-dev-key-change-me" or len(SECRET_KEY) < 50:
        raise ImproperlyConfigured(
            "SECRET_KEY must be a strong value in the environment before starting BOQ_AI."
        )
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured("ALLOWED_HOSTS must be set when DEBUG=False.")
    if "*" in ALLOWED_HOSTS:
        raise ImproperlyConfigured("ALLOWED_HOSTS must not include '*' when DEBUG=False.")

# --- Applications -----------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

LOCAL_APPS = [
    "apps.accounts",
    "apps.users",
    "apps.database_manager",
    "apps.boq",
    "apps.notifications",
    "apps.audit",
]

INSTALLED_APPS = DJANGO_APPS + LOCAL_APPS

# --- Middleware -------------------------------------------------------------

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "common.middleware.NoStoreAuthenticatedMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [ROOT_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.notifications.context_processors.notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --- Database ---------------------------------------------------------------

DATABASE_URL = env.str("DATABASE_URL", default="")
if DATABASE_URL:
    DATABASES = {"default": env.db_url_config(DATABASE_URL)}
    DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)
    DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
elif DEBUG:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ROOT_DIR / "db.sqlite3",
        }
    }
else:
    raise ImproperlyConfigured(
        "DATABASE_URL must be set. BOQ_AI uses PostgreSQL in production."
    )

# --- Authentication ---------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "accounts:login"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internationalization ---------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# --- Static & media ---------------------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [ROOT_DIR / "static"]
STATIC_ROOT = ROOT_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = ROOT_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Celery / Redis ---------------------------------------------------------

REDIS_URL = env.str("REDIS_URL", default="redis://localhost:6379/0")
CELERY_BROKER_URL = env.str("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env.str("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_RESULT_EXPIRES = 3600
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 60 * 30
# If the worker dies mid-task (Windows restart / Ctrl-C), re-queue so Analyse
# does not stay stuck in PROCESSING with a dead job.
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=DEBUG)
if not DEBUG and CELERY_TASK_ALWAYS_EAGER:
    raise ImproperlyConfigured(
        "CELERY_TASK_ALWAYS_EAGER must be False when DEBUG=False. "
        "Run Redis and the Celery worker for Analyse."
    )
# Shared heartbeat file max age — Analyse refuses to queue when stale/missing.
CELERY_WORKER_HEARTBEAT_MAX_AGE = env.float("CELERY_WORKER_HEARTBEAT_MAX_AGE", default=45.0)
# Skip liveness checks only for controlled tests.
CELERY_SKIP_WORKER_CHECK = env.bool("CELERY_SKIP_WORKER_CHECK", default=False)

# --- OpenAI -----------------------------------------------------------------

OPENAI_API_KEY = env.str("OPENAI_API_KEY", default="")
OPENAI_MODEL = env.str("OPENAI_MODEL", default="gpt-4o-mini")
OPENAI_EMBEDDING_MODEL = env.str("OPENAI_EMBEDDING_MODEL", default="text-embedding-3-small")
OPENAI_EMBEDDING_DIMENSIONS = env.int("OPENAI_EMBEDDING_DIMENSIONS", default=1536)
OPENAI_EMBEDDING_BATCH_SIZE = env.int("OPENAI_EMBEDDING_BATCH_SIZE", default=500)
OPENAI_TIMEOUT_SECONDS = env.int("OPENAI_TIMEOUT_SECONDS", default=120)
OPENAI_MAX_RETRIES = env.int("OPENAI_MAX_RETRIES", default=1)
AI_INSTRUCTION_LOGGING = env.bool("AI_INSTRUCTION_LOGGING", default=DEBUG)
# How many BOQ sections to send per extract_products AI call.
AI_ROW_EXTRACTION_BATCH_SIZE = env.int("AI_ROW_EXTRACTION_BATCH_SIZE", default=5)
# How many products to map per map_product_match AI call.
AI_PRODUCT_MAPPING_BATCH_SIZE = env.int("AI_PRODUCT_MAPPING_BATCH_SIZE", default=4)

# --- Chroma -----------------------------------------------------------------

_chroma_env = env.str("CHROMA_PATH", default="")
if _chroma_env and Path(_chroma_env).is_absolute():
    CHROMA_PATH = _chroma_env
else:
    # Always keep Chroma beside other uploaded media, not cwd-relative paths.
    CHROMA_PATH = str(MEDIA_ROOT / "chroma")
CHROMA_COLLECTION = env.str("CHROMA_COLLECTION", default="rate_master_products")

# --- Email ------------------------------------------------------------------

if env.str("EMAIL_HOST", default=""):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = env.str("EMAIL_HOST")
    EMAIL_PORT = env.int("EMAIL_PORT", default=587)
    EMAIL_HOST_USER = env.str("EMAIL_HOST_USER", default="")
    EMAIL_HOST_PASSWORD = env.str("EMAIL_HOST_PASSWORD", default="")
    EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

DEFAULT_FROM_EMAIL = env.str("DEFAULT_FROM_EMAIL", default="no-reply@boq-ai.local")

# --- Uploads ----------------------------------------------------------------

# Nginx allows 50MB; keep a modest in-memory cap so large workbooks spill to disk.
DATA_UPLOAD_MAX_MEMORY_SIZE = env.int("DATA_UPLOAD_MAX_MEMORY_SIZE", default=10 * 1024 * 1024)
FILE_UPLOAD_MAX_MEMORY_SIZE = env.int("FILE_UPLOAD_MAX_MEMORY_SIZE", default=10 * 1024 * 1024)
DATA_UPLOAD_MAX_NUMBER_FIELDS = env.int("DATA_UPLOAD_MAX_NUMBER_FIELDS", default=10000)
FILE_UPLOAD_PERMISSIONS = 0o640
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o750

# --- Security ---------------------------------------------------------------

SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=SECURE_SSL_REDIRECT)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=SECURE_SSL_REDIRECT)
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_HSTS_SECONDS = env.int(
    "SECURE_HSTS_SECONDS",
    default=(60 * 60 * 24 * 365 if SECURE_SSL_REDIRECT else 0),
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    default=SECURE_SSL_REDIRECT,
)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=SECURE_SSL_REDIRECT)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

_csrf_from_env = [
    origin.strip()
    for origin in env.list("CSRF_TRUSTED_ORIGINS", default=[])
    if str(origin).strip()
]
CSRF_TRUSTED_ORIGINS = _csrf_from_env or csrf_trusted_origins_from_hosts(
    ALLOWED_HOSTS, https=SECURE_SSL_REDIRECT
)

# HTTP-on-IP is the current EC2 go-live mode (no domain/TLS yet). Re-enable these
# checks automatically when SECURE_SSL_REDIRECT=True after certbot.
if not SECURE_SSL_REDIRECT:
    SILENCED_SYSTEM_CHECKS = [
        "security.W004",
        "security.W008",
        "security.W012",
        "security.W016",
    ]

# --- Logging ----------------------------------------------------------------

LOGS_DIR = ROOT_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "()": "common.logging_formatters.LocalTimeFormatter",
            "format": "{asctime} [{levelname}] {name}: {message}",
            "style": "{",
        },
    },
    "filters": {
        "skip_broken_pipe": {
            "()": "common.logging_handlers.SkipBrokenPipeFilter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "filters": ["skip_broken_pipe"],
        },
        "app_file": {
            "class": "common.logging_handlers.SafeRotatingFileHandler",
            "filename": str(LOGS_DIR / "application.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
            "filters": ["skip_broken_pipe"],
        },
        "error_file": {
            "class": "common.logging_handlers.SafeRotatingFileHandler",
            "filename": str(LOGS_DIR / "errors.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "level": "ERROR",
            "formatter": "verbose",
        },
        "instruction_file": {
            "class": "common.logging_handlers.SafeRotatingFileHandler",
            "filename": str(LOGS_DIR / "instructions.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console", "app_file"],
        "level": "INFO",
    },
    "loggers": {
        "boq_ai": {
            "handlers": ["console", "app_file", "error_file"],
            "level": "INFO",
            "propagate": False,
        },
        "boq_ai.instructions": {
            "handlers": ["console", "instruction_file"],
            "level": "INFO",
            "propagate": False,
        },
        "django": {
            "handlers": ["console", "app_file", "error_file"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console", "error_file"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console", "error_file"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.server": {
            "handlers": ["console", "app_file"],
            "level": "INFO",
            "propagate": False,
            "filters": ["skip_broken_pipe"],
        },
        "celery": {
            "handlers": ["console", "app_file", "error_file"],
            "level": "INFO",
            "propagate": False,
        },
        "celery.task": {
            "handlers": ["console", "app_file", "error_file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
