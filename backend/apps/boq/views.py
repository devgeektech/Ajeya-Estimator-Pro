"""BOQ views (thin). Experts access their own BOQs; Super Admin sees all."""

import logging
from decimal import Decimal
from pathlib import PurePath

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import DetailView, FormView, ListView, View

from common.choices import RunStatus
from common.exceptions import ValidationError

from .forms import BOQUploadForm, MakeListUploadForm
from .models import BOQ
from .services.boq_service import BOQCreationService
from .services.make_list_service import BOQMakeListUploadService
from .services.parser import CANONICAL_BOQ_HEADERS, format_serial_number

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
    paginate_by = 10


class BOQDetailView(LoginRequiredMixin, OwnedBOQQuerysetMixin, DetailView):
    template_name = "boq/boq_detail.html"
    context_object_name = "boq"

    @staticmethod
    def _display_headers(_run):
        return CANONICAL_BOQ_HEADERS

    @staticmethod
    def _display_quantity(original_data: dict, item) -> object:
        qty = original_data.get("quantity")
        if qty not in (None, ""):
            return qty
        if not (original_data.get("unit") or item.unit) and item.quantity == Decimal("0"):
            return ""
        return item.quantity

    @staticmethod
    def _format_cell_value(key: str, value):
        if value in (None, ""):
            return ""
        if key == "s_no":
            return format_serial_number(value) or ""
        return value

    @staticmethod
    def _display_row(item, headers, *, show_pricing: bool):
        original_data = item.original_data or {}
        row_values = {
            "s_no": original_data.get("s_no"),
            "description": original_data.get("description") or item.description,
            "unit": original_data.get("unit") or item.unit,
            "quantity": BOQDetailView._display_quantity(original_data, item),
        }
        cells = [
            BOQDetailView._format_cell_value(header["key"], row_values.get(header["key"]))
            for header in headers
        ]
        final_rate = None
        if show_pricing:
            matches = list(item.product_matches.all())
            match = matches[0] if matches else None
            detail = getattr(match, "rate_detail", None) if match else None
            final_rate = detail.rate_contribution if detail else None
        amount = (
            (final_rate * item.quantity).quantize(Decimal("0.01"))
            if final_rate is not None
            else None
        )
        return {
            "item": item,
            "cells": cells,
            "final_rate": final_rate,
            "amount": amount,
        }

    @classmethod
    def _expand_display_rows(cls, item, headers, *, show_pricing: bool):
        row_json = item.row_json or {}
        nested_rows = row_json.get("rows") or []
        if len(nested_rows) <= 1:
            return [cls._display_row(item, headers, show_pricing=show_pricing)]

        primary_row_num = (
            row_json.get("target_excel_row")
            or row_json.get("primary_excel_row_number")
            or item.row_number
        )
        base = cls._display_row(item, headers, show_pricing=show_pricing)
        final_rate = base["final_rate"]
        amount = base["amount"]
        expanded = []
        for nested in nested_rows:
            row_values = {
                "s_no": nested.get("serial_number"),
                "description": nested.get("description"),
                "unit": nested.get("unit"),
                "quantity": nested.get("quantity"),
            }
            cells = [
                cls._format_cell_value(header["key"], row_values.get(header["key"]))
                for header in headers
            ]
            is_primary = nested.get("excel_row_number") == primary_row_num
            if is_primary and show_pricing:
                expanded.append(
                    {
                        "item": item,
                        "cells": cells,
                        "final_rate": final_rate,
                        "amount": amount,
                    }
                )
            else:
                expanded.append(
                    {
                        "item": item,
                        "cells": cells,
                        "final_rate": None,
                        "amount": None,
                    }
                )
        return expanded

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        latest_run = self.object.runs.order_by("-run_number").first()
        ctx["latest_run"] = latest_run
        if latest_run:
            items_qs = (
                latest_run.items.all()
                .order_by("row_number")
                .prefetch_related("product_matches__rate_detail")
            )
            ctx["total_items"] = items_qs.count()

            display_headers = self._display_headers(latest_run)
            show_pricing = latest_run.status == RunStatus.COMPLETED
            ctx["display_headers"] = display_headers
            ctx["item_rows"] = [
                display_row
                for item in items_qs
                for display_row in self._expand_display_rows(
                    item, display_headers, show_pricing=show_pricing
                )
            ]
            ctx["items"] = items_qs

            ctx["make_entries"] = latest_run.make_list_entries.all()
        else:
            ctx["items"] = []
            ctx["item_rows"] = []
            ctx["display_headers"] = []
            ctx["total_items"] = 0
            ctx["make_entries"] = []
        return ctx


class BOQMakeListView(LoginRequiredMixin, OwnedBOQQuerysetMixin, DetailView):
    template_name = "boq/make_list.html"
    context_object_name = "boq"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        latest_run = self.object.runs.order_by("-run_number").first()
        ctx["latest_run"] = latest_run
        ctx["make_list_form"] = MakeListUploadForm()
        ctx["make_list_filename"] = (
            PurePath(self.object.make_list_file.name).name
            if self.object.make_list_file
            else ""
        )
        if latest_run:
            make_qs = latest_run.make_list_entries.all().order_by("category", "make")
            ctx["total_makes"] = make_qs.count()
            ctx["make_entries"] = make_qs
        else:
            ctx["make_entries"] = []
            ctx["total_makes"] = 0
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


class BOQMakeListUploadView(LoginRequiredMixin, OwnedBOQQuerysetMixin, View):
    def post(self, request, pk):
        boq = get_object_or_404(self.get_queryset(), pk=pk)
        form = MakeListUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
            return redirect("boq:detail", pk=boq.pk)

        try:
            count = BOQMakeListUploadService(
                boq=boq,
                make_list_file=form.cleaned_data["make_list_file"],
            ).run()
        except ValidationError as exc:
            messages.error(request, str(exc))
            return redirect("boq:detail", pk=boq.pk)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Make-list upload failed for BOQ %s", boq.pk)
            messages.error(request, f"Make-list upload failed: {exc}")
            return redirect("boq:detail", pk=boq.pk)

        messages.success(request, f"Make list updated with {count} entries.")
        return redirect("boq:make_list", pk=boq.pk)
