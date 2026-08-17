"""Verify Redis broker and Celery worker availability."""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.boq.services.boq_analysis_dispatch import broker_is_available, worker_is_available
from apps.boq.services.celery_worker_heartbeat import read_celery_worker_heartbeat


class Command(BaseCommand):
    help = "Check Redis broker and Celery worker readiness for BOQ analysis."

    def handle(self, *args, **options):
        self.stdout.write(f"CELERY_TASK_ALWAYS_EAGER={settings.CELERY_TASK_ALWAYS_EAGER}")
        self.stdout.write(f"CELERY_BROKER_URL={settings.CELERY_BROKER_URL}")

        broker_ok = broker_is_available()
        worker_ok = worker_is_available()
        heartbeat = read_celery_worker_heartbeat()

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
            age = heartbeat.get("age_seconds")
            age_txt = f"{age:.1f}s ago" if isinstance(age, (int, float)) else "unknown"
            self.stdout.write(
                self.style.SUCCESS(
                    f"Celery worker: OK (heartbeat {age_txt}, host={heartbeat.get('hostname') or '-'})"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Celery worker: NOT RUNNING"))
            self.stdout.write(
                "  Heartbeat file missing or stale. Start: .\\scripts\\run_celery_worker.ps1"
            )

        if not broker_ok or not worker_ok:
            self.stdout.write(
                self.style.WARNING(
                    "Analyse will refuse to start until Redis and Celery are up. "
                    "See docs/OPS.md."
                )
            )
