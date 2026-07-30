"""Audit service (Phase 11, Sprint 20).

Records significant user/admin actions for auditability
(docs/PRODUCT.md). Secrets/passwords are never logged.
Defensive so audit failures never break core flows.
"""
from __future__ import annotations

import logging

from apps.audit.models import AuditLog

logger = logging.getLogger("boq_ai")


def record(user, action: str, entity: str = "", entity_id="") -> None:
    """Write an audit log entry. Never raises."""
    try:
        AuditLog.objects.create(
            user=user if getattr(user, "is_authenticated", False) else None,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id != "" else "",
        )
    except Exception:  # noqa: BLE001 - audit must not break core flows
        logger.exception("Failed to write audit log: %s", action)
