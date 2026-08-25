"""Which BOQs each role may list and open."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.boq.models import BOQ
from common.choices import UserRole


def boqs_visible_to_user(user) -> QuerySet[BOQ]:
    """Return BOQs the signed-in user may list and open.

    Ownership stays with the uploader. Visibility:

    - **Expert** / **Superadmin**: only their own BOQs.
    - **Admin**: their own BOQs plus every Expert's BOQs (not other Admins'
      or Superadmins' BOQs).
    """
    qs = BOQ.objects.select_related("user")
    if getattr(user, "is_admin", False):
        return qs.filter(Q(user=user) | Q(user__role=UserRole.EXPERT))
    return qs.filter(user=user)
