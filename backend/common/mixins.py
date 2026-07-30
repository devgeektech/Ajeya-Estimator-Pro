"""Reusable view mixins for access control."""
from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restrict a view to authenticated Admin (client admin) users.

    Used for user management, database management and product approval
    (docs/PRODUCT.md). Also grants access to Django superusers
    (Developer tier).
    """

    request: Any

    def test_func(self) -> bool:
        user = self.request.user
        # Django superuser (Developer) always passes; Admin role is the standard gate.
        return user.is_authenticated and (user.is_superuser or user.is_admin)


# Backward-compat alias — existing views import SuperAdminRequiredMixin; this keeps them working.
SuperAdminRequiredMixin = AdminRequiredMixin


class DatabaseAccessRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restrict a view to Admin users or Experts with DB access."""
    
    request: Any

    def test_func(self) -> bool:
        user = self.request.user
        return user.is_authenticated and (
            user.is_superuser or user.is_admin or getattr(user, 'allow_db_access', False)
        )
