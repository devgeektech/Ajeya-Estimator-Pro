"""Prune server audit logs, notifications, and log files according to queue retention policies."""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.audit.services import (
    MAX_AUDIT_LOGS_PER_USER,
    prune_all_audit_logs,
)
from apps.notifications.services import (
    MAX_NOTIFICATIONS_PER_USER,
    prune_all_notifications,
)
from common.logging_handlers import MAX_LOG_LINES, trim_log_file


class Command(BaseCommand):
    help = (
        "Enforce queue retention: keep recent 50 audit logs per user, "
        "recent 50 notifications per user, and recent 5,000 lines on every log file."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--audit-limit",
            type=int,
            default=MAX_AUDIT_LOGS_PER_USER,
            help=f"Recent audit logs to keep per user (default: {MAX_AUDIT_LOGS_PER_USER}).",
        )
        parser.add_argument(
            "--notif-limit",
            type=int,
            default=MAX_NOTIFICATIONS_PER_USER,
            help=f"Recent notifications to keep per user (default: {MAX_NOTIFICATIONS_PER_USER}).",
        )
        parser.add_argument(
            "--log-lines",
            type=int,
            default=MAX_LOG_LINES,
            help=f"Recent lines to keep per log file (default: {MAX_LOG_LINES}).",
        )

    def handle(self, *args, **options):
        audit_limit = options["audit_limit"]
        notif_limit = options["notif_limit"]
        log_lines = options["log_lines"]

        self.stdout.write("Pruning server data queues...")

        # 1. Audit logs
        deleted_audits = prune_all_audit_logs(limit=audit_limit)
        self.stdout.write(
            self.style.SUCCESS(
                f"Audit logs pruned: removed {deleted_audits} older entries (keeping recent {audit_limit} per user)."
            )
        )

        # 2. Notifications
        deleted_notifs = prune_all_notifications(limit=notif_limit)
        self.stdout.write(
            self.style.SUCCESS(
                f"Notifications pruned: removed {deleted_notifs} older entries (keeping recent {notif_limit} per user)."
            )
        )

        # 3. Server log files
        logs_dir = getattr(settings, "LOGS_DIR", None)
        if logs_dir and Path(logs_dir).is_dir():
            for log_file in Path(logs_dir).glob("*.log"):
                trimmed = trim_log_file(log_file, max_lines=log_lines)
                status = "trimmed to recent lines" if trimmed else "already within line cap"
                self.stdout.write(f"  {log_file.name}: {status} (cap: {log_lines} lines)")
            self.stdout.write(self.style.SUCCESS(f"Log files verified in {logs_dir}."))
        else:
            self.stdout.write(self.style.WARNING("LOGS_DIR not found; skipped log file check."))
