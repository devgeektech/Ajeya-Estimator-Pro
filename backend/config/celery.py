"""Celery application for BOQ_AI."""
import logging
import logging.config
import os

from celery import Celery
from celery.signals import heartbeat_sent, worker_ready, worker_shutting_down

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("boq_ai")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


def _touch_heartbeat(sender=None, **_kwargs) -> None:
    """Keep a shared heartbeat file fresh so Analyse can detect a live worker."""
    try:
        import django

        django.setup()
        from apps.boq.services.celery_worker_heartbeat import touch_celery_worker_heartbeat

        hostname = ""
        try:
            hostname = str(getattr(sender, "hostname", "") or "")
        except Exception:
            hostname = ""
        touch_celery_worker_heartbeat(hostname=hostname)
    except Exception:
        logging.getLogger("boq_ai").exception("Celery heartbeat touch failed")


@worker_ready.connect
def _configure_django_logging(sender=None, **kwargs) -> None:
    """Ensure Django LOGGING handlers (including instructions.log) are active in workers."""
    import django

    django.setup()
    from django.conf import settings as django_settings

    if hasattr(django_settings, "LOGGING"):
        logging.config.dictConfig(django_settings.LOGGING)
    _touch_heartbeat(sender=sender)
    logging.getLogger("boq_ai").info(
        "Celery worker ready hostname=%s — Analyse jobs will be consumed",
        getattr(sender, "hostname", ""),
    )


@heartbeat_sent.connect
def _on_celery_heartbeat(sender=None, **kwargs) -> None:
    _touch_heartbeat(sender=sender)


@worker_shutting_down.connect
def _on_celery_shutdown(**_kwargs) -> None:
    try:
        import django

        django.setup()
        from apps.boq.services.celery_worker_heartbeat import clear_celery_worker_heartbeat

        clear_celery_worker_heartbeat()
        logging.getLogger("boq_ai").warning(
            "Celery worker shutting down — Analyse will not process until restarted"
        )
    except Exception:
        logging.getLogger("boq_ai").exception("Celery shutdown heartbeat clear failed")
