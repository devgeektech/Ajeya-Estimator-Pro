"""BOQ views (upload only)."""

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.generic import FormView

from .forms import BOQUploadForm
from .services.boq_service import BOQCreationService

logger = logging.getLogger("boq_ai")


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
        return reverse("dashboard:home")
