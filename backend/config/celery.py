"""Celery application for BOQ_AI background processing."""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

app = Celery("boq_ai")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
