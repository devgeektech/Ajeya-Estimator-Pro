"""Verify Redis broker and Celery worker availability."""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.boq.services.boq_analysis_dispatch import broker_is_available, worker_is_available


class Command(BaseCommand):
    help = "Check Redis broker and Celery worker readiness for BOQ analysis."

    def handle(self, *args, **options):
        self.stdout.write(f"CELERY_TASK_ALWAYS_EAGER={settings.CELERY_TASK_ALWAYS_EAGER}")
        self.stdout.write(f"CELERY_BROKER_URL={settings.CELERY_BROKER_URL}")

        broker_ok = broker_is_available()
        worker_ok = worker_is_available()

        if broker_ok:
            self.stdout.write(self.style.SUCCESS("Redis broker: OK"))
        else:
            self.stdout.write(self.style.ERROR("Redis broker: NOT AVAILABLE"))

        if settings.CELERY_TASK_ALWAYS_EAGER:
            self.stdout.write(
                self.style.WARNING(
                    "Celery worker: SKIPPED (CELERY_TASK_ALWAYS_EAGER=true; analysis runs inline)"
                )
            )
            return

        if worker_ok:
            self.stdout.write(self.style.SUCCESS("Celery worker: OK"))
        else:
            self.stdout.write(self.style.ERROR("Celery worker: NOT RUNNING"))

        if not broker_ok or not worker_ok:
            self.stdout.write(
                self.style.WARNING(
                    "Start Redis and the Celery worker. See README.md or docs/OPS.md."
                )
            )
