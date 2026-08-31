"""Celery application for BOQ_AI."""
import logging
import logging.config
import os
import threading

from celery import Celery
from celery.signals import heartbeat_sent, worker_ready, worker_shutting_down

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("boq_ai")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

_HEARTBEAT_THREAD_STOP = threading.Event()
_HEARTBEAT_THREAD: threading.Thread | None = None


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


def _start_heartbeat_thread(sender=None) -> None:
    """Windows ``threads`` pool may not emit heartbeat_sent reliably — poll locally."""
    global _HEARTBEAT_THREAD
    if _HEARTBEAT_THREAD is not None and _HEARTBEAT_THREAD.is_alive():
        return
    _HEARTBEAT_THREAD_STOP.clear()

    def _loop() -> None:
        while not _HEARTBEAT_THREAD_STOP.wait(15.0):
            _touch_heartbeat(sender=sender)

    _HEARTBEAT_THREAD = threading.Thread(
        target=_loop,
        name="celery-worker-heartbeat",
        daemon=True,
    )
    _HEARTBEAT_THREAD.start()


def _stop_heartbeat_thread() -> None:
    _HEARTBEAT_THREAD_STOP.set()


@worker_ready.connect
def _configure_django_logging(sender=None, **kwargs) -> None:
    """Ensure Django LOGGING handlers (including instructions.log) are active in workers."""
    import django

    django.setup()
    from django.conf import settings as django_settings

    if hasattr(django_settings, "LOGGING"):
        logging.config.dictConfig(django_settings.LOGGING)
    _touch_heartbeat(sender=sender)
    _start_heartbeat_thread(sender=sender)
    logging.getLogger("boq_ai").info(
        "Celery worker ready hostname=%s — Analyse jobs will be consumed",
        getattr(sender, "hostname", ""),
    )


@heartbeat_sent.connect
def _on_celery_heartbeat(sender=None, **kwargs) -> None:
    _touch_heartbeat(sender=sender)


@worker_shutting_down.connect
def _on_celery_shutdown(**_kwargs) -> None:
    _stop_heartbeat_thread()
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
