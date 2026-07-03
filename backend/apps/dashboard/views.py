"""Dashboard views (Sprint 2 - layout & navigation; live metrics from Sprint 5)."""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from apps.boq.models import BOQ
from common.choices import BOQStatus


class DashboardHomeView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx["greeting_name"] = user.full_name
        ctx["is_super_admin"] = user.is_super_admin

        boqs = BOQ.objects.all() if user.is_super_admin else BOQ.objects.filter(user=user)
        processing_states = [BOQStatus.UPLOADED, BOQStatus.PROCESSING]
        ctx["metrics"] = [
            {"label": "All BOQs uploaded" if user.is_super_admin else "My BOQs", "value": boqs.count()},
            {"label": "Processing", "value": boqs.filter(status__in=processing_states).count()},
            {"label": "Under Review", "value": boqs.filter(status=BOQStatus.UNDER_REVIEW).count()},
            {"label": "Approved", "value": boqs.filter(status=BOQStatus.APPROVED).count()},
        ]
        
        ctx["recent_boqs"] = boqs.order_by("-created_at")[:20]
        
        return ctx
