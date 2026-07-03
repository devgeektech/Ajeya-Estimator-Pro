"""Authentication services.

Thin business-logic helpers for the accounts app. Views stay thin and
delegate here (docs/AGENTS.md - Required Architecture).
"""
from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

logger = logging.getLogger("boq_ai")

User = get_user_model()


def record_login(user) -> None:
    """Hook for audit logging on successful login."""
    logger.info("User logged in: %s", user.email)


def record_logout(user) -> None:
    if user and user.is_authenticated:
        logger.info("User logged out: %s", user.email)
