"""Single settings module for BOQ_AI.

All runtimes use this module. Environment values are read from ``.env`` in the
project root when present, and production safety checks are enabled whenever
``DEBUG=False``.
"""

from pathlib import Path
import sys

import environ
from django.core.exceptions import ImproperlyConfigured

# backend/ directory (contains manage.py, config/, apps/, ...)
BASE_DIR = Path(__file__).resolve().parents[1]
# Project root (contains backend/, docs/, templates/, static/, media/, ...)
ROOT_DIR = BASE_DIR.parent

if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)

env_file = ROOT_DIR / ".env"
if env_file.exists():
    env.read_env(str(env_file))

SECRET_KEY = env("SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

if not DEBUG and SECRET_KEY == "insecure-dev-key-change-me":
    raise ImproperlyConfigured(
        "SECRET_KEY must be set in the environment before starting BOQ_AI."
    )

# --- Applications -----------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "django_htmx",
]

LOCAL_APPS = [
    "apps.accounts",
    "apps.users",
    "apps.database_manager",
    "apps.boq",
    "apps.make_list",
    "apps.processing",
    "apps.matching",
    "apps.costing",
    "apps.review",
    "apps.exports",
    "apps.notifications",
    "apps.audit",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

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
    "django_htmx.middleware.HtmxMiddleware",
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

DATABASE_URL = env("DATABASE_URL", default="")
if DATABASE_URL:
    DATABASES = {"default": env.db_url_config(DATABASE_URL)}
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

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 60 * 30
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)

# --- OpenAI -----------------------------------------------------------------

OPENAI_API_KEY = env("OPENAI_API_KEY", default="")
OPENAI_MODEL = env("OPENAI_MODEL", default="gpt-5-mini")
OPENAI_EMBEDDING_MODEL = env("OPENAI_EMBEDDING_MODEL", default="text-embedding-3-small")
OPENAI_EMBEDDING_DIMENSIONS = env.int("OPENAI_EMBEDDING_DIMENSIONS", default=1536)
OPENAI_TIMEOUT_SECONDS = env.int("OPENAI_TIMEOUT_SECONDS", default=120)
OPENAI_MAX_RETRIES = env.int("OPENAI_MAX_RETRIES", default=1)
AI_ROW_EXTRACTION_BATCH_SIZE = env.int("AI_ROW_EXTRACTION_BATCH_SIZE", default=10)

# --- Chroma -----------------------------------------------------------------

CHROMA_PATH = env("CHROMA_PATH", default=str(MEDIA_ROOT / "chroma"))
CHROMA_COLLECTION = env("CHROMA_COLLECTION", default="rate_master_products")

# --- Email ------------------------------------------------------------------

if env("EMAIL_HOST", default=""):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = env("EMAIL_HOST")
    EMAIL_PORT = env.int("EMAIL_PORT", default=587)
    EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
    EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@boq-ai.local")

# --- Security ---------------------------------------------------------------

SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=SECURE_SSL_REDIRECT)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=SECURE_SSL_REDIRECT)
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
X_FRAME_OPTIONS = "DENY"

# --- Logging ----------------------------------------------------------------

LOGS_DIR = ROOT_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} [{levelname}] {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "app_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOGS_DIR / "application.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOGS_DIR / "errors.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "level": "ERROR",
            "formatter": "verbose",
        },
        "ai_extraction_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOGS_DIR / "ai_extractions.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 10,
            "formatter": "verbose",
        },
        "ai_instruction_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOGS_DIR / "ai_instructions.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 10,
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
        "boq_ai.ai_rows": {
            "handlers": ["ai_extraction_file", "error_file"],
            "level": "INFO",
            "propagate": False,
        },
        "boq_ai.ai_instructions": {
            "handlers": ["ai_instruction_file", "error_file"],
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
    },
}
