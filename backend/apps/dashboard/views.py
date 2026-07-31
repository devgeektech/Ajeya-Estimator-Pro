"""Dashboard views."""
from typing import cast

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from apps.accounts.models import User
from apps.boq.models import BOQ
from apps.boq.services.boq_status_display_service import build_boq_status_display
from common.choices import BOQStatus


class DashboardHomeView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = cast(User, self.request.user)
        ctx["greeting_name"] = user.full_name
        ctx["is_super_admin"] = user.is_super_admin

        boqs = BOQ.objects.all() if user.is_super_admin else BOQ.objects.filter(user=user)
        total = boqs.count()
        analysing = boqs.filter(
            status__in=[BOQStatus.PROCESSING, BOQStatus.MATCHING]
        ).count()
        analysis_complete = boqs.filter(
            status__in=[
                BOQStatus.EXTRACTED,
                BOQStatus.MAKE_VENDOR,
            ]
        ).count()
        matching_complete = boqs.filter(
            status__in=[
                BOQStatus.PROCESSED,
                BOQStatus.READY_EXPORT,
                BOQStatus.EXPORTED,
            ]
        ).count()

        ctx["metrics"] = [
            {
                "label": "All BOQs" if user.is_super_admin else "My BOQs",
                "value": total,
                "tone": "blue",
            },
            {
                "label": "Analysing",
                "value": analysing,
                "tone": "amber",
            },
            {
                "label": "Analysis Completed",
                "value": analysis_complete,
                "tone": "red",
            },
            {
                "label": "Exported",
                "value": matching_complete,
                "tone": "green",
            },
        ]

        recent = list(boqs.order_by("-created_at")[:7])
        session = self.request.session
        ctx["recent_boqs"] = [
            {
                "boq": boq,
                "status_display": build_boq_status_display(boq, session),
            }
            for boq in recent
        ]
        return ctx
