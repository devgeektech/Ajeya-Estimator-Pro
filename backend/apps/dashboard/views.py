"""Dashboard views."""
from typing import cast

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from apps.accounts.models import User
from apps.boq.models import BOQ


class DashboardHomeView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = cast(User, self.request.user)
        ctx["greeting_name"] = user.full_name
        ctx["is_super_admin"] = user.is_super_admin

        boqs = BOQ.objects.all() if user.is_super_admin else BOQ.objects.filter(user=user)
        ctx["metrics"] = [
            {
                "label": "All BOQs uploaded" if user.is_super_admin else "My BOQs",
                "value": boqs.count(),
            },
        ]
        ctx["recent_boqs"] = boqs.order_by("-created_at")[:10]
        return ctx
