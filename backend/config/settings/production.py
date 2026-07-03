"""Single runtime settings for the EC2-hosted BOQ_AI application."""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

ALLOWED_HOSTS = env("ALLOWED_HOSTS")

if SECRET_KEY == "insecure-dev-key-change-me":  # noqa: F405
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "SECRET_KEY must be set in /srv/boq_ai/.env before starting BOQ_AI."
    )

if not env("DATABASE_URL", default=""):
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "DATABASE_URL must be set. BOQ_AI uses PostgreSQL on the EC2 server."
    )

# Compressed + hashed static files served by WhiteNoise in production.
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
}

# Security hardening.
# Keep HTTPS flags environment-driven because the first EC2 stage may run on
# the public IP before a domain and TLS certificate are available.
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

# SMTP is optional until a domain or mail provider is configured. With no
# EMAIL_HOST, Django prints emails to the service logs instead of failing.
if env("EMAIL_HOST", default=""):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = env("EMAIL_HOST")
    EMAIL_PORT = env.int("EMAIL_PORT", default=587)
    EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
    EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
