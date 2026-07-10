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
from .services.boq_parser import parse_boq_workbook
from .services.boq_service import BOQCreationService, upload_basename
from .services.make_list_parser import parse_make_list_file
from .services.serial_normalizer import structure_for_display

logger = logging.getLogger("boq_ai")


def _display_structure(boq: BOQ, *, kind: str) -> dict:
    """Parse from the stored file when possible so the UI always reflects current rules."""
    try:
        if kind == "boq" and boq.uploaded_file:
            payload = parse_boq_workbook(
                boq.uploaded_file,
                source_filename=upload_basename(boq.uploaded_file),
            )
        elif kind == "make_list" and boq.make_list_file:
            payload = parse_make_list_file(
                boq.make_list_file,
                source_filename=upload_basename(boq.make_list_file),
            )
        else:
            payload = boq.boq_data if kind == "boq" else boq.make_list_data
            return structure_for_display(payload or {})
        return structure_for_display(payload)
    except Exception:
        logger.exception("Failed to parse %s for BOQ id=%s", kind, boq.pk)
        payload = boq.boq_data if kind == "boq" else boq.make_list_data
        return structure_for_display(payload or {})


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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        boq = context["boq"]
        context["boq_structure"] = _display_structure(boq, kind="boq")
        context["make_list_structure"] = _display_structure(boq, kind="make_list")
        context["has_make_list"] = bool(boq.make_list_file)
        context["default_tab"] = self.request.GET.get("tab", "boq")
        if context["default_tab"] not in {"boq", "make_list"}:
            context["default_tab"] = "boq"
        return context


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
