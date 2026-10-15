"""Audit service (Phase 11, Sprint 20).

Records significant user/admin actions for auditability
(docs/PRODUCT.md). Secrets/passwords are never logged.
Defensive so audit failures never break core flows.
"""
from __future__ import annotations

import logging

from apps.audit.models import AuditLog

logger = logging.getLogger("boq_ai")


MAX_AUDIT_LOGS_PER_USER = 50


def prune_audit_logs_for_user(user, limit: int = MAX_AUDIT_LOGS_PER_USER) -> int:
    """Retain only the most recent `limit` audit logs for the given user, deleting older entries."""
    if user is None or not getattr(user, "is_authenticated", False):
        qs = AuditLog.objects.filter(user__isnull=True)
    else:
        qs = AuditLog.objects.filter(user=user)

    keep_ids = list(
        qs.order_by("-timestamp", "-id").values_list("id", flat=True)[:limit]
    )
    if not keep_ids:
        return 0

    deleted, _ = qs.exclude(id__in=keep_ids).delete()
    return deleted


def prune_all_audit_logs(limit: int = MAX_AUDIT_LOGS_PER_USER) -> int:
    """Prune audit logs across all users to keep only the recent `limit` per user."""
    total_deleted = 0
    user_ids = list(
        AuditLog.objects.filter(user__isnull=False)
        .values_list("user_id", flat=True)
        .distinct()
    )
    for uid in user_ids:
        qs = AuditLog.objects.filter(user_id=uid)
        keep_ids = list(
            qs.order_by("-timestamp", "-id").values_list("id", flat=True)[:limit]
        )
        if keep_ids:
            deleted, _ = qs.exclude(id__in=keep_ids).delete()
            total_deleted += deleted

    null_qs = AuditLog.objects.filter(user__isnull=True)
    null_keep = list(
        null_qs.order_by("-timestamp", "-id").values_list("id", flat=True)[:limit]
    )
    if null_keep:
        deleted, _ = null_qs.exclude(id__in=null_keep).delete()
        total_deleted += deleted

    return total_deleted


def record(user, action: str, entity: str = "", entity_id="") -> None:
    """Write an audit log entry and enforce the 50 recent entries per user queue. Never raises."""
    try:
        auth_user = user if getattr(user, "is_authenticated", False) else None
        AuditLog.objects.create(
            user=auth_user,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id != "" else "",
        )
        prune_audit_logs_for_user(auth_user, limit=MAX_AUDIT_LOGS_PER_USER)
    except Exception:  # noqa: BLE001 - audit must not break core flows
        logger.exception("Failed to write audit log: %s", action)
