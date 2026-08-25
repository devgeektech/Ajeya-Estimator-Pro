"""Reusable view mixins for access control."""
from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restrict a view to Admin or Superadmin (and Django superusers).

    Used for user management of Experts and other Admin-level app screens
    (docs/PRODUCT.md). Peer-Admin management is enforced in the users app,
    not by this mixin alone.
    """

    request: Any

    def test_func(self) -> bool:
        user = self.request.user
        return user.is_authenticated and (
            user.is_superuser
            or getattr(user, "is_superadmin", False)
            or user.is_admin
        )


class SuperAdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restrict a view to Superadmin role or Django superuser only.

    Admins do not pass. Used for audit and any Superadmin-only screens.
    """

    request: Any

    def test_func(self) -> bool:
        user = self.request.user
        return user.is_authenticated and (
            user.is_superuser or getattr(user, "is_superadmin", False)
        )


class DatabaseAccessRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restrict a view to Admin/Superadmin or Experts with DB upload access."""

    request: Any

    def test_func(self) -> bool:
        user = self.request.user
        return user.is_authenticated and (
            user.is_superuser
            or getattr(user, "is_superadmin", False)
            or user.is_admin
            or getattr(user, "allow_db_access", False)
        )
