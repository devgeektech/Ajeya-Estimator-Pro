"""BOQ views (list, detail, upload)."""

import logging
from typing import cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.generic import DetailView, FormView, ListView

from apps.accounts.models import User

from .forms import BOQUploadForm
from .models import BOQ
from .services.boq_service import BOQCreationService

logger = logging.getLogger("boq_ai")


class BOQListView(LoginRequiredMixin, ListView):
    model = BOQ
    template_name = "boq/boq_list.html"
    context_object_name = "boqs"

    def get_queryset(self):
        user = cast(User, self.request.user)
        qs = BOQ.objects.select_related("user").order_by("-created_at")
        if not user.is_super_admin:
            qs = qs.filter(user=user)
        return qs


class BOQDetailView(LoginRequiredMixin, DetailView):
    model = BOQ
    template_name = "boq/boq_detail.html"
    context_object_name = "boq"

    def get_queryset(self):
        user = cast(User, self.request.user)
        qs = BOQ.objects.select_related("user")
        if not user.is_super_admin:
            qs = qs.filter(user=user)
        return qs


class BOQUploadView(LoginRequiredMixin, FormView):
    form_class = BOQUploadForm
    template_name = "boq/boq_form.html"

    def form_valid(self, form):
        try:
            BOQCreationService(
                user=self.request.user,
                boq_name=form.cleaned_data["boq_name"],
                uploaded_file=form.cleaned_data["uploaded_file"],
                make_list_file=form.cleaned_data.get("make_list_file"),
            ).run()
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("BOQ upload failed")
            messages.error(self.request, f"Upload failed: {exc}")
            return self.form_invalid(form)

        messages.success(
            self.request,
            f"BOQ '{form.cleaned_data['boq_name']}' uploaded successfully.",
        )
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("boq:list")
