"""BOQ views (thin). Experts access their own BOQs; Super Admin sees all."""
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.generic import DetailView, FormView, ListView

from .forms import BOQUploadForm
from .models import BOQ
from .services.boq_service import BOQCreationService

logger = logging.getLogger("boq_ai")


class OwnedBOQQuerysetMixin:
    """Limit BOQ access to the owner, unless the user is a Super Admin."""

    def get_queryset(self):
        qs = BOQ.objects.select_related("user")
        user = self.request.user
        if user.is_super_admin:
            return qs
        return qs.filter(user=user)


class BOQListView(LoginRequiredMixin, OwnedBOQQuerysetMixin, ListView):
    template_name = "boq/boq_list.html"
    context_object_name = "boqs"
    paginate_by = 25


class BOQDetailView(LoginRequiredMixin, OwnedBOQQuerysetMixin, DetailView):
    template_name = "boq/boq_detail.html"
    context_object_name = "boq"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        latest_run = self.object.runs.order_by("-run_number").first()
        ctx["latest_run"] = latest_run
        if latest_run:
            ctx["items"] = latest_run.items.all()
            ctx["make_entries"] = latest_run.make_list_entries.all()
        else:
            ctx["items"] = []
            ctx["make_entries"] = []
        return ctx


class BOQUploadView(LoginRequiredMixin, FormView):
    form_class = BOQUploadForm
    template_name = "boq/boq_form.html"

    def form_valid(self, form):
        try:
            boq = BOQCreationService(
                user=self.request.user,
                boq_name=form.cleaned_data["boq_name"],
                uploaded_file=form.cleaned_data["uploaded_file"],
                make_list_file=form.cleaned_data.get("make_list_file"),
            ).run()
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("BOQ upload failed")
            messages.error(self.request, f"Upload failed: {exc}")
            return self.form_invalid(form)

        messages.success(self.request, f"BOQ '{boq.boq_name}' uploaded.")
        self.success_boq = boq
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("boq:detail", args=[self.success_boq.pk])
