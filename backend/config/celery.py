"""Celery application for BOQ_AI."""
import logging
import logging.config
import os

from celery import Celery
from celery.signals import worker_ready

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("boq_ai")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@worker_ready.connect
def _configure_django_logging(**_kwargs) -> None:
    """Ensure Django LOGGING handlers (including instructions.log) are active in workers."""
    import django

    django.setup()
    from django.conf import settings as django_settings

    if hasattr(django_settings, "LOGGING"):
        logging.config.dictConfig(django_settings.LOGGING)
