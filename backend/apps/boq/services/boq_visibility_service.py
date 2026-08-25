"""Which BOQs each role may list and open."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.boq.models import BOQ
from common.choices import UserRole


def boqs_visible_to_user(user) -> QuerySet[BOQ]:
    """Return BOQs the signed-in user may list and open.

    Ownership stays with the uploader. Visibility:

    - **Superadmin**: every BOQ (Admin and Expert uploads).
    - **Admin**: their own BOQs plus BOQs from Experts they created
      (``user.created_by``). Not other Admins or those Admins' Experts.
    - **Expert**: only their own BOQs.
    """
    qs = BOQ.objects.select_related("user")
    if getattr(user, "is_superadmin", False) or getattr(user, "is_superuser", False):
        return qs
    if getattr(user, "is_admin", False):
        return qs.filter(
            Q(user=user) | Q(user__role=UserRole.EXPERT, user__created_by=user)
        )
    return qs.filter(user=user)
