"""Audit views — Superadmin sees all; Admin sees self + their Experts."""
from django.contrib.auth import get_user_model
from django.db.models import Q, QuerySet, Subquery, OuterRef
from django.shortcuts import get_object_or_404
from django.views.generic import ListView

from common.choices import UserRole
from common.mixins import AdminRequiredMixin

from apps.audit.models import AuditLog


def _users_visible_in_audit(actor) -> QuerySet:
    """Users whose audit activity the actor may review.

    - Superadmin / Django superuser: everyone except SUPERADMIN role accounts.
    - Admin: themselves plus Experts they created (not peer Admins).
    """
    User = get_user_model()
    qs = User.objects.exclude(role=UserRole.SUPERADMIN)
    if getattr(actor, "is_superuser", False) or getattr(actor, "is_superadmin", False):
        return qs
    if getattr(actor, "is_admin", False):
        return qs.filter(Q(pk=actor.pk) | Q(role=UserRole.EXPERT, created_by=actor))
    return qs.none()


class AuditLogListView(AdminRequiredMixin, ListView):
    template_name = "audit/list.html"
    context_object_name = "users"
    paginate_by = 50

    _SORT_FIELDS = {
        "name": "first_name",
        "action": "recent_action",
        "when": "recent_action_datetime",
    }

    def get_queryset(self):
        latest_audit = AuditLog.objects.filter(user=OuterRef("pk")).order_by("-timestamp")

        qs = _users_visible_in_audit(self.request.user).annotate(
            recent_action=Subquery(latest_audit.values("action")[:1]),
            recent_action_datetime=Subquery(latest_audit.values("timestamp")[:1]),
        )

        query = (self.request.GET.get("q") or "").strip()
        if query:
            for token in query.split():
                qs = qs.filter(
                    Q(first_name__icontains=token)
                    | Q(last_name__icontains=token)
                    | Q(email__icontains=token)
                    | Q(recent_action__icontains=token)
                )

        sort_key = (self.request.GET.get("sort") or "when").strip().lower()
        direction = (self.request.GET.get("dir") or "desc").strip().lower()
        if sort_key not in self._SORT_FIELDS:
            sort_key = "when"
        if direction not in {"asc", "desc"}:
            direction = "desc"

        if sort_key == "name":
            if direction == "desc":
                return qs.order_by("-first_name", "-last_name", "-email", "-id")
            return qs.order_by("first_name", "last_name", "email", "-id")

        order_field = self._SORT_FIELDS[sort_key]
        if direction == "desc":
            order_field = f"-{order_field}"
        return qs.order_by(order_field, "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sort_key = (self.request.GET.get("sort") or "when").strip().lower()
        direction = (self.request.GET.get("dir") or "desc").strip().lower()
        if sort_key not in self._SORT_FIELDS:
            sort_key = "when"
        if direction not in {"asc", "desc"}:
            direction = "desc"
        context["search_q"] = (self.request.GET.get("q") or "").strip()
        context["sort"] = sort_key
        context["dir"] = direction
        return context


class UserAuditLogListView(AdminRequiredMixin, ListView):
    template_name = "audit/user_list.html"
    context_object_name = "logs"
    paginate_by = 50

    _SORT_FIELDS = {
        "id": "entity_id",
        "action": "action",
        "entity": "entity",
        "when": "timestamp",
    }

    def get_queryset(self):
        audit_user = get_object_or_404(
            _users_visible_in_audit(self.request.user),
            pk=self.kwargs.get("pk"),
        )
        qs = AuditLog.objects.filter(user=audit_user).select_related("user")

        query = (self.request.GET.get("q") or "").strip()
        if query:
            for token in query.split():
                qs = qs.filter(
                    Q(action__icontains=token)
                    | Q(entity__icontains=token)
                    | Q(entity_id__icontains=token)
                )

        sort_key = (self.request.GET.get("sort") or "when").strip().lower()
        direction = (self.request.GET.get("dir") or "desc").strip().lower()
        if sort_key not in self._SORT_FIELDS:
            sort_key = "when"
        if direction not in {"asc", "desc"}:
            direction = "desc"

        order_field = self._SORT_FIELDS[sort_key]
        if direction == "desc":
            order_field = f"-{order_field}"
        return qs.order_by(order_field, "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["audit_user"] = get_object_or_404(
            _users_visible_in_audit(self.request.user),
            pk=self.kwargs.get("pk"),
        )
        sort_key = (self.request.GET.get("sort") or "when").strip().lower()
        direction = (self.request.GET.get("dir") or "desc").strip().lower()
        if sort_key not in self._SORT_FIELDS:
            sort_key = "when"
        if direction not in {"asc", "desc"}:
            direction = "desc"
        context["search_q"] = (self.request.GET.get("q") or "").strip()
        context["sort"] = sort_key
        context["dir"] = direction
        return context
