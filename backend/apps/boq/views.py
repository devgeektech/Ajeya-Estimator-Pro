"""BOQ views (list, detail, upload)."""

import logging
from typing import cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, FormView, ListView

from apps.accounts.models import User
from common.choices import BOQStatus
from common.exceptions import AIServiceError, BOQAIError, ValidationError

from .forms import BOQUploadForm
from .models import BOQ
from .services.boq_analysis_display_service import BOQAnalysisDisplayService
from .services.boq_analysis_dispatch import dispatch_boq_extraction, dispatch_boq_matching
from .services.boq_confirmation_service import BOQConfirmationService
from .services.boq_export_service import BOQExportService
from .services.boq_extract_service import load_extract_data
from .services.boq_analysis_service import BOQAnalysisService, _row_description
from .services.boq_extraction_edit_service import BOQExtractionEditService
from .services.boq_extraction_display_service import (
    BOQExtractionDisplayService,
    build_product_save_feedback,
)
from .services.boq_service import BOQCreationService
from .services.boq_status_display_service import (
    build_boq_status_display,
    build_boq_tab_access,
    clear_exported_in_session,
    default_detail_tab_for_boq,
    mark_exported_in_session,
    resolve_detail_tab,
)
from .services.serial_normalizer import structure_for_analysis, structure_for_display

logger = logging.getLogger("boq_ai")


def _structures_for_display(boq: BOQ) -> tuple[dict, dict]:
    """Shape stored extract JSON for template rendering (no re-parse on each view)."""
    try:
        boq_payload, make_list_payload = load_extract_data(boq)
    except Exception:
        logger.exception("Failed to load extract JSON for BOQ id=%s", boq.pk)
        boq_payload = boq.boq_data or {}
        make_list_payload = boq.make_list_data or {}
    if not boq.make_list_file:
        make_list_payload = {}
    return structure_for_display(boq_payload), structure_for_display(make_list_payload)


def _boq_queryset_for_user(user: User):
    qs = BOQ.objects.select_related("user")
    if not user.is_super_admin:
        qs = qs.filter(user=user)
    return qs


def _detail_tab_url(pk: int, tab: str) -> str:
    return reverse("boq:detail", kwargs={"pk": pk}) + f"?tab={tab}"


def _extraction_edit_is_ajax(request) -> bool:
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.POST.get("ajax") == "1"
    )


def _extraction_edit_json_ok(message: str, **payload):
    return JsonResponse({"ok": True, "message": message, **payload})


def _extraction_edit_json_error(message: str, status: int = 400):
    return JsonResponse({"ok": False, "message": message}, status=status)


def _job_is_running(boq: BOQ) -> bool:
    return boq.status in {BOQStatus.PROCESSING, BOQStatus.MATCHING}


class BOQListView(LoginRequiredMixin, ListView):
    model = BOQ
    template_name = "boq/boq_list.html"
    context_object_name = "boqs"

    def get_queryset(self):
        user = cast(User, self.request.user)
        return _boq_queryset_for_user(user).order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        session = self.request.session
        context["boq_items"] = [
            {
                "boq": boq,
                "status_display": build_boq_status_display(boq, session),
                "detail_tab": default_detail_tab_for_boq(boq, session),
            }
            for boq in context["boqs"]
        ]
        return context


class BOQDetailView(LoginRequiredMixin, DetailView):
    model = BOQ
    template_name = "boq/boq_detail.html"
    context_object_name = "boq"

    def get_queryset(self):
        return _boq_queryset_for_user(cast(User, self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        boq = context["boq"]
        boq_structure, make_list_structure = _structures_for_display(boq)
        try:
            _, make_list_payload = load_extract_data(boq)
        except Exception:
            make_list_payload = boq.make_list_data or {}
        if not boq.make_list_file:
            make_list_payload = {}
        confirmations = BOQConfirmationService(boq.pk, self.request.session).all()
        context["boq_structure"] = boq_structure
        context["make_list_structure"] = make_list_structure
        context["has_make_list"] = bool(boq.make_list_file)
        context["tab_access"] = build_boq_tab_access(boq)
        context["default_tab"] = resolve_detail_tab(
            boq,
            self.request.session,
            self.request.GET.get("tab"),
        )
        context["is_extracting"] = boq.status == BOQStatus.PROCESSING
        context["is_matching"] = boq.status == BOQStatus.MATCHING
        context["is_processing"] = _job_is_running(boq)
        context["can_analyse"] = boq.status in {
            BOQStatus.UPLOADED,
            BOQStatus.EXTRACTED,
            BOQStatus.PROCESSED,
            BOQStatus.ANALYSIS_FAILED,
        } and not _job_is_running(boq)
        context["can_match"] = (
            boq.status in {BOQStatus.EXTRACTED, BOQStatus.PROCESSED}
            and bool((boq.analysis_data or {}).get("rows"))
            and not _job_is_running(boq)
        )
        context["can_export"] = boq.status == BOQStatus.PROCESSED and bool(boq.analysis_data)
        # Per-row Re-match only after a full Match has completed (Match Results tab).
        context["can_rematch"] = (
            boq.status == BOQStatus.PROCESSED
            and bool((boq.analysis_data or {}).get("rows"))
            and not _job_is_running(boq)
        )
        context["can_edit_extraction"] = boq.status in {
            BOQStatus.EXTRACTED,
            BOQStatus.PROCESSED,
            BOQStatus.ANALYSIS_FAILED,
        } and not _job_is_running(boq) and bool((boq.analysis_data or {}).get("rows"))
        context["status_display"] = build_boq_status_display(boq, self.request.session)
        context["extraction_stats"] = (boq.analysis_data or {}).get("stats")
        context["analysis_stats"] = (boq.analysis_data or {}).get("stats")
        context["extraction_display"] = BOQExtractionDisplayService(
            boq,
            make_list_payload,
            has_make_list_file=bool(boq.make_list_file),
        ).build()
        context["analysis_display"] = BOQAnalysisDisplayService(boq, confirmations).build()
        return context


class BOQExtractView(LoginRequiredMixin, View):
    """Trigger AI product/activity extraction for one BOQ."""

    def post(self, request, pk: int):
        user = cast(User, request.user)
        boq = get_object_or_404(_boq_queryset_for_user(user), pk=pk)

        if _job_is_running(boq):
            messages.info(request, "A job is already running for this BOQ.")
            return HttpResponseRedirect(_detail_tab_url(boq.pk, "analysis"))

        clear_exported_in_session(boq.pk, request.session)

        try:
            result = dispatch_boq_extraction(boq.pk)
            if result.mode == "failed":
                messages.error(request, result.message or "Could not start extraction.")
            elif result.mode == "sync":
                messages.success(request, f"Products extracted for '{boq.boq_name}'.")
            else:
                messages.info(
                    request,
                    f"Extraction started for '{boq.boq_name}'. Results will appear when complete.",
                )
        except (AIServiceError, BOQAIError) as exc:
            messages.error(request, str(exc))
        except Exception:
            logger.exception("Failed to start BOQ extraction for id=%s", boq.pk)
            messages.error(request, "Failed to start extraction.")

        return HttpResponseRedirect(_detail_tab_url(boq.pk, "analysis"))


class BOQRowExtractView(LoginRequiredMixin, View):
    """Re-analyse a single BOQ anchor group."""

    def post(self, request, pk: int, row_id: str):
        user = cast(User, request.user)
        boq = get_object_or_404(_boq_queryset_for_user(user), pk=pk)
        redirect_url = _detail_tab_url(boq.pk, "analysis")
        ajax = _extraction_edit_is_ajax(request)
        row_id = (row_id or request.POST.get("row_id") or "").strip()

        if _job_is_running(boq):
            message = "Wait for the current job to finish."
            if ajax:
                return _extraction_edit_json_error(message)
            messages.info(request, message)
            return HttpResponseRedirect(redirect_url)

        if not row_id:
            message = "Missing BOQ row."
            if ajax:
                return _extraction_edit_json_error(message)
            messages.error(request, message)
            return HttpResponseRedirect(redirect_url)

        clear_exported_in_session(boq.pk, request.session)
        try:
            BOQAnalysisService(boq.pk).re_extract_row(row_id)
            message = "Row re-analysed."
            if ajax:
                return _extraction_edit_json_ok(message, row_id=row_id)
            messages.success(request, message)
        except ValidationError as exc:
            if ajax:
                return _extraction_edit_json_error(str(exc))
            messages.error(request, str(exc))
        except (AIServiceError, BOQAIError) as exc:
            if ajax:
                return _extraction_edit_json_error(str(exc))
            messages.error(request, str(exc))
        except Exception:
            logger.exception("BOQ row extract failed for id=%s row=%s", boq.pk, row_id)
            message = "Failed to re-analyse this row."
            if ajax:
                return _extraction_edit_json_error(message, status=500)
            messages.error(request, message)
        return HttpResponseRedirect(redirect_url)


class BOQRowMatchView(LoginRequiredMixin, View):
    """Re-match a single BOQ anchor group."""

    def post(self, request, pk: int, row_id: str):
        user = cast(User, request.user)
        boq = get_object_or_404(_boq_queryset_for_user(user), pk=pk)
        redirect_url = _detail_tab_url(boq.pk, "match_results")
        ajax = _extraction_edit_is_ajax(request)
        row_id = (row_id or request.POST.get("row_id") or "").strip()

        if _job_is_running(boq):
            message = "Wait for the current job to finish."
            if ajax:
                return _extraction_edit_json_error(message)
            messages.info(request, message)
            return HttpResponseRedirect(redirect_url)

        if not row_id:
            message = "Missing BOQ row."
            if ajax:
                return _extraction_edit_json_error(message)
            messages.error(request, message)
            return HttpResponseRedirect(redirect_url)

        clear_exported_in_session(boq.pk, request.session)
        try:
            BOQAnalysisService(boq.pk).re_match_row(row_id)
            message = "Row re-matched."
            if ajax:
                return _extraction_edit_json_ok(message, row_id=row_id)
            messages.success(request, message)
        except ValidationError as exc:
            if ajax:
                return _extraction_edit_json_error(str(exc))
            messages.error(request, str(exc))
        except (AIServiceError, BOQAIError) as exc:
            if ajax:
                return _extraction_edit_json_error(str(exc))
            messages.error(request, str(exc))
        except Exception:
            logger.exception("BOQ row match failed for id=%s row=%s", boq.pk, row_id)
            message = "Failed to re-match this row."
            if ajax:
                return _extraction_edit_json_error(message, status=500)
            messages.error(request, message)
        return HttpResponseRedirect(redirect_url)


class BOQExtractionEditView(LoginRequiredMixin, View):
    """Save user corrections to extracted products on the Analysis tab."""

    def post(self, request, pk: int):
        user = cast(User, request.user)
        boq = get_object_or_404(_boq_queryset_for_user(user), pk=pk)
        redirect_url = _detail_tab_url(boq.pk, "analysis")
        ajax = _extraction_edit_is_ajax(request)
        action = (request.POST.get("action") or "update_product").strip().lower()
        row_id = (request.POST.get("row_id") or "").strip()
        if not row_id:
            message = "Missing BOQ row."
            if ajax:
                return _extraction_edit_json_error(message)
            messages.error(request, message)
            return HttpResponseRedirect(redirect_url)

        editor = BOQExtractionEditService(boq.pk)
        try:
            if action == "add_product":
                product = editor.add_product(row_id=row_id)
                message = "Blank product added."
                if ajax:
                    return _extraction_edit_json_ok(
                        message,
                        product_index=int(product.get("product_index") or 0),
                    )
                messages.success(request, message)
            elif action == "remove_product":
                try:
                    product_index = int(request.POST.get("product_index") or "0")
                except ValueError:
                    message = "Invalid product index."
                    if ajax:
                        return _extraction_edit_json_error(message)
                    messages.error(request, message)
                    return HttpResponseRedirect(redirect_url)
                editor.remove_product(row_id=row_id, product_index=product_index)
                message = "Product removed from this row."
                if ajax:
                    return _extraction_edit_json_ok(message)
                messages.success(request, message)
            elif action == "update_make":
                selected_make = (request.POST.get("selected_make") or "").strip()
                custom_make = (request.POST.get("custom_make") or "").strip()
                category = (request.POST.get("category") or "").strip()
                sub_category = (request.POST.get("sub_category") or "").strip()
                try:
                    boq_payload, make_list_payload = load_extract_data(boq)
                except Exception:
                    boq_payload = boq.boq_data or {}
                    make_list_payload = boq.make_list_data or {}
                boq_data = structure_for_analysis(boq_payload)
                description = _row_description(boq_data, row_id)
                make_list = editor.update_row_make(
                    row_id=row_id,
                    selected_make=selected_make,
                    custom_make=custom_make,
                    make_list_data=make_list_payload,
                    boq_description=description,
                    category=category,
                    sub_category=sub_category,
                )
                message = "Make saved."
                if ajax:
                    return _extraction_edit_json_ok(
                        message,
                        selected_make=make_list.get("selected_make") or "",
                    )
                messages.success(request, message)
            else:
                try:
                    product_index = int(request.POST.get("product_index") or "0")
                except ValueError:
                    message = "Invalid product index."
                    if ajax:
                        return _extraction_edit_json_error(message)
                    messages.error(request, message)
                    return HttpResponseRedirect(redirect_url)

                fields = {
                    key: request.POST.get(key, "")
                    for key in (
                        "description_hint",
                        "category",
                        "sub_category",
                        "class",
                        "size",
                        "unit",
                        "capacity",
                        "make_hint",
                        "quantity",
                        "quantity_unit",
                    )
                }
                attributes = editor.parse_attributes_from_form(request.POST)
                product_row_id = (request.POST.get("product_row_id") or row_id).strip()
                updated = editor.update_product(
                    row_id=product_row_id,
                    product_index=product_index,
                    fields=fields,
                    attributes=attributes,
                )
                message = "Product saved."
                if ajax:
                    return _extraction_edit_json_ok(
                        message,
                        product=build_product_save_feedback(updated),
                    )
                messages.success(request, message)
        except ValidationError as exc:
            if ajax:
                return _extraction_edit_json_error(str(exc))
            messages.error(request, str(exc))
        except Exception:
            logger.exception("BOQ extraction edit failed for id=%s", boq.pk)
            message = "Failed to save product changes."
            if ajax:
                return _extraction_edit_json_error(message, status=500)
            messages.error(request, message)

        return HttpResponseRedirect(redirect_url)


class BOQMatchView(LoginRequiredMixin, View):
    """Match extracted products against the master database."""

    def post(self, request, pk: int):
        user = cast(User, request.user)
        boq = get_object_or_404(_boq_queryset_for_user(user), pk=pk)

        if _job_is_running(boq):
            messages.info(request, "A job is already running for this BOQ.")
            return HttpResponseRedirect(_detail_tab_url(boq.pk, "match_results"))

        if not (boq.analysis_data or {}).get("rows"):
            messages.error(request, "Run Analyse first to extract products.")
            return HttpResponseRedirect(_detail_tab_url(boq.pk, "analysis"))

        try:
            result = dispatch_boq_matching(boq.pk)
            if result.mode == "failed":
                messages.error(request, result.message or "Could not start matching.")
                return HttpResponseRedirect(_detail_tab_url(boq.pk, "analysis"))
            if result.mode == "sync":
                messages.success(request, f"Matching completed for '{boq.boq_name}'.")
            else:
                messages.info(
                    request,
                    f"Matching started for '{boq.boq_name}'. Results will appear when complete.",
                )
        except (AIServiceError, BOQAIError) as exc:
            messages.error(request, str(exc))
            return HttpResponseRedirect(_detail_tab_url(boq.pk, "analysis"))
        except Exception:
            logger.exception("Failed to start BOQ matching for id=%s", boq.pk)
            messages.error(request, "Failed to start matching.")
            return HttpResponseRedirect(_detail_tab_url(boq.pk, "analysis"))

        return HttpResponseRedirect(_detail_tab_url(boq.pk, "match_results"))


class BOQMatchResultsView(LoginRequiredMixin, View):
    """Backward-compatible redirect to the Match Results tab on BOQ detail."""

    def get(self, request, pk: int):
        user = cast(User, request.user)
        boq = get_object_or_404(_boq_queryset_for_user(user), pk=pk)
        if boq.status == BOQStatus.EXTRACTED:
            messages.info(request, "Click Match to compare extracted products against the database.")
            return HttpResponseRedirect(_detail_tab_url(boq.pk, "analysis"))
        return HttpResponseRedirect(_detail_tab_url(boq.pk, "match_results"))


class BOQAnalysisStatusView(LoginRequiredMixin, View):
    """JSON status for polling while Celery jobs run."""

    def get(self, request, pk: int):
        user = cast(User, request.user)
        qs = BOQ.objects.only("pk", "status")
        if not user.is_super_admin:
            qs = qs.filter(user=user)
        boq = get_object_or_404(qs, pk=pk)

        expect = (request.GET.get("expect") or "extract").strip().lower()
        if expect == "match":
            ready = boq.status in {BOQStatus.PROCESSED, BOQStatus.ANALYSIS_FAILED}
        else:
            ready = boq.status in {BOQStatus.EXTRACTED, BOQStatus.ANALYSIS_FAILED}

        return JsonResponse(
            {
                "status": boq.status,
                "ready": ready,
                "failed": boq.status == BOQStatus.ANALYSIS_FAILED,
                "expect": expect,
            }
        )


class BOQConfirmView(LoginRequiredMixin, View):
    """Confirm one analysis line for the current session (no database write)."""

    def post(self, request, pk: int):
        user = cast(User, request.user)
        boq = get_object_or_404(_boq_queryset_for_user(user), pk=pk)

        line_key = (request.POST.get("line_key") or request.POST.get("override_key") or "").strip()
        rate_master_id_raw = (request.POST.get("rate_master_id") or "").strip()
        action = (request.POST.get("action") or "confirm").strip().lower()

        redirect_url = _detail_tab_url(boq.pk, "match_results")
        confirmation_service = BOQConfirmationService(boq.pk, request.session)

        if action == "unconfirm":
            if line_key:
                confirmation_service.unconfirm(line_key)
                messages.success(request, "Confirmation removed for this line.")
            return HttpResponseRedirect(redirect_url)

        if not line_key:
            messages.error(request, "Missing analysis line.")
            return HttpResponseRedirect(redirect_url)

        try:
            rate_master_id = int(rate_master_id_raw) if rate_master_id_raw else None
            confirmation_service.confirm(line_key=line_key, rate_master_id=rate_master_id)
            messages.success(request, "Line confirmed for this session.")
        except ValidationError as exc:
            messages.error(request, str(exc))
        except Exception:
            logger.exception("BOQ confirmation failed for id=%s", boq.pk)
            messages.error(request, "Failed to confirm line.")

        return HttpResponseRedirect(redirect_url)


class BOQExportView(LoginRequiredMixin, View):
    """Download priced analysis as Excel."""

    def get(self, request, pk: int):
        user = cast(User, request.user)
        boq = get_object_or_404(_boq_queryset_for_user(user), pk=pk)

        try:
            confirmations = BOQConfirmationService(boq.pk, request.session).all()
            content, filename = BOQExportService(boq.pk, confirmations).run()
            mark_exported_in_session(boq.pk, request.session)
        except ValueError as exc:
            messages.error(request, str(exc))
            return HttpResponseRedirect(_detail_tab_url(boq.pk, "match_results"))
        except Exception:
            logger.exception("BOQ export failed for id=%s", boq.pk)
            messages.error(request, "Export failed.")
            return HttpResponseRedirect(_detail_tab_url(boq.pk, "match_results"))

        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


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


# Backward-compatible alias.
class BOQProcessView(BOQExtractView):
    """Deprecated — use BOQExtractView."""
