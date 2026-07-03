"""
Base settings for BOQ_AI.

Shared Django configuration. The active EC2 runtime imports this through
production.py.

Derived from docs/TRD.md, docs/ARCHITECTURE.md and docs/PROJECT_STRUCTURE.md.
"""
from pathlib import Path

import environ

# backend/ directory (contains manage.py, config/, apps/, ...)
BASE_DIR = Path(__file__).resolve().parents[2]
# Project root (contains backend/, docs/, templates/, static/, media/, ...)
ROOT_DIR = BASE_DIR.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)

# Load .env from the project root if present.
env_file = ROOT_DIR / ".env"
if env_file.exists():
    env.read_env(str(env_file))

SECRET_KEY = env("SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# Make the apps/ package importable as `apps.<name>`.
import sys  # noqa: E402

sys.path.append(str(BASE_DIR / "apps"))

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
    "apps.pending_products",
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
# PostgreSQL is required for the single EC2 production runtime.

DATABASE_URL = env("DATABASE_URL", default="")
if DATABASE_URL:
    DATABASES = {"default": env.db_url_config(DATABASE_URL)}
else:
    DATABASES = {}

# --- Authentication ---------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "accounts:login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
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
    # Plain storage by default so {% static %} works without collectstatic.
    # Production swaps in WhiteNoise's compressed manifest storage.
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Celery / Redis ---------------------------------------------------------

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 60 * 30

# --- OpenAI -----------------------------------------------------------------

OPENAI_API_KEY = env("OPENAI_API_KEY", default="")
OPENAI_MODEL = env("OPENAI_MODEL", default="gpt-4o-mini")
OPENAI_EMBEDDING_MODEL = env("OPENAI_EMBEDDING_MODEL", default="text-embedding-3-small")
OPENAI_TIMEOUT_SECONDS = env.int("OPENAI_TIMEOUT_SECONDS", default=30)

# --- Email ------------------------------------------------------------------
# Console backend by default; production overrides with SMTP.

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@boq-ai.local")

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
            "class": "logging.FileHandler",
            "filename": str(LOGS_DIR / "application.log"),
            "formatter": "verbose",
        },
        "error_file": {
            "class": "logging.FileHandler",
            "filename": str(LOGS_DIR / "errors.log"),
            "level": "ERROR",
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
    },
}
