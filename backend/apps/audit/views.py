"""Audit views (Super Admin only)."""
from django.views.generic import ListView
from django.contrib.auth import get_user_model
from django.db.models import Subquery, OuterRef

from common.choices import UserRole
from common.mixins import SuperAdminRequiredMixin

from apps.audit.models import AuditLog


class AuditLogListView(SuperAdminRequiredMixin, ListView):
    template_name = "audit/list.html"
    context_object_name = "users"
    paginate_by = 50

    def get_queryset(self):
        User = get_user_model()
        latest_audit = AuditLog.objects.filter(user=OuterRef("pk")).order_by("-timestamp")
        
        return User.objects.exclude(role=UserRole.SUPERADMIN).annotate(
            recent_action=Subquery(latest_audit.values("action")[:1]),
            recent_action_datetime=Subquery(latest_audit.values("timestamp")[:1])
        ).order_by("-recent_action_datetime")


class UserAuditLogListView(SuperAdminRequiredMixin, ListView):
    template_name = "audit/user_list.html"
    context_object_name = "logs"
    paginate_by = 50

    def get_queryset(self):
        return AuditLog.objects.filter(user_id=self.kwargs.get("pk")).exclude(user__role=UserRole.SUPERADMIN).select_related("user")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        User = get_user_model()
        context["audit_user"] = User.objects.filter(pk=self.kwargs.get("pk")).first()
        return context
