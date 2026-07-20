"""BOQ views (list, detail, upload)."""

import logging
from typing import cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
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
from .services.make_vendor_selection_service import MakeVendorSelectionService
from .services.boq_service import BOQCreationService
from .services.boq_status_display_service import (
    build_boq_status_display,
    build_boq_tab_access,
    clear_exported_in_session,
    default_detail_tab_for_boq,
    mark_exported_in_session,
    resolve_detail_tab,
)
from .services.serial_normalizer import (
    structure_for_analysis,
    structure_for_display,
    structure_for_make_list_display,
)

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
    return structure_for_display(boq_payload), structure_for_make_list_display(make_list_payload)


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


def _request_wants_json(request) -> bool:
    return _extraction_edit_is_ajax(request) or "application/json" in (
        request.headers.get("Accept") or ""
    )


def _extraction_edit_json_ok(message: str, **payload):
    return JsonResponse({"ok": True, "message": message, **payload})


def _extraction_edit_json_error(message: str, status: int = 400):
    return JsonResponse({"ok": False, "message": message}, status=status)


def _load_make_list_payload(boq: BOQ) -> dict:
    try:
        _, make_list_payload = load_extract_data(boq)
    except Exception:
        make_list_payload = boq.make_list_data or {}
    if make_list_payload is None:
        make_list_payload = {}
    return make_list_payload


def _can_edit_extraction(boq: BOQ) -> bool:
    return (
        boq.status
        in {
            BOQStatus.EXTRACTED,
            BOQStatus.PROCESSED,
            BOQStatus.ANALYSIS_FAILED,
        }
        and not _job_is_running(boq)
        and bool((boq.analysis_data or {}).get("rows"))
    )


def _render_extraction_line_html(request, boq: BOQ, row_id: str) -> str:
    """Render one Analysis tab row after rematch for silent DOM swap."""
    boq.refresh_from_db(fields=["analysis_data", "status", "make_list_data"])
    make_list_payload = _load_make_list_payload(boq)
    display = BOQExtractionDisplayService(
        boq,
        make_list_payload,
        has_make_list_file=bool(boq.make_list_file),
    ).build()
    line = next(
        (item for item in display.get("lines") or [] if str(item.get("row_id")) == str(row_id)),
        None,
    )
    if line is None:
        return ""
    return render_to_string(
        "boq/_extraction_line.html",
        {
            "boq": boq,
            "line": line,
            "can_edit_extraction": _can_edit_extraction(boq),
        },
        request=request,
    )


def _job_is_running(boq: BOQ) -> bool:
    return boq.status in {BOQStatus.PROCESSING, BOQStatus.MATCHING}


def _status_payload(boq: BOQ, session, *, expect: str = "extract") -> dict:
    """JSON fields for polling Analyse / Match completion."""
    expect_key = (expect or "extract").strip().lower()
    if expect_key == "match":
        ready = boq.status in {BOQStatus.PROCESSED, BOQStatus.ANALYSIS_FAILED}
    else:
        ready = boq.status in {BOQStatus.EXTRACTED, BOQStatus.ANALYSIS_FAILED}
    display = build_boq_status_display(boq, session)
    return {
        "status": boq.status,
        "ready": ready,
        "failed": boq.status == BOQStatus.ANALYSIS_FAILED,
        "expect": expect_key,
        "label": display["label"],
        "badge": display["badge"],
        "polling": boq.status in {BOQStatus.PROCESSING, BOQStatus.MATCHING},
    }


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
                "needs_status_poll": boq.status
                in {BOQStatus.PROCESSING, BOQStatus.MATCHING},
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

        # Attach Rate_Master Attribute schemas for products analysed before enrichment.
        if (boq.analysis_data or {}).get("rows") and not _job_is_running(boq):
            try:
                if BOQAnalysisService(boq.pk).ensure_attribute_enrichment():
                    boq.refresh_from_db(fields=["analysis_data"])
            except Exception:
                logger.exception("Attribute enrichment backfill failed for BOQ id=%s", boq.pk)

        context["extraction_display"] = BOQExtractionDisplayService(
            boq,
            make_list_payload,
            has_make_list_file=bool(boq.make_list_file),
        ).build()
        context["analysis_display"] = BOQAnalysisDisplayService(boq, confirmations).build()
        try:
            context["make_vendor_display"] = MakeVendorSelectionService(
                boq.pk,
                make_list_payload,
            ).build_display()
        except Exception:
            logger.exception("Failed to build Make & Vendor display for BOQ id=%s", boq.pk)
            context["make_vendor_display"] = {"has_products": False, "lines": [], "stats": {}}
        return context


class BOQExtractView(LoginRequiredMixin, View):
    """Trigger AI product/activity extraction for one BOQ."""

    def post(self, request, pk: int):
        user = cast(User, request.user)
        boq = get_object_or_404(_boq_queryset_for_user(user), pk=pk)
        wants_json = _request_wants_json(request)
        redirect_url = _detail_tab_url(boq.pk, "analysis")

        if _job_is_running(boq):
            message = "A job is already running for this BOQ."
            if wants_json:
                boq.refresh_from_db(fields=["status"])
                return JsonResponse(
                    {
                        "ok": True,
                        "message": message,
                        "mode": "async",
                        **_status_payload(boq, request.session, expect="extract"),
                    }
                )
            messages.info(request, message)
            return HttpResponseRedirect(redirect_url)

        clear_exported_in_session(boq.pk, request.session)

        try:
            result = dispatch_boq_extraction(boq.pk)
            boq.refresh_from_db(fields=["status"])
            if result.mode == "failed":
                message = result.message or "Could not start extraction."
                if wants_json:
                    return JsonResponse(
                        {
                            "ok": False,
                            "message": message,
                            "mode": result.mode,
                            **_status_payload(boq, request.session, expect="extract"),
                        },
                        status=400,
                    )
                messages.error(request, message)
            elif result.mode == "sync":
                message = f"Products extracted for '{boq.boq_name}'."
                if wants_json:
                    return JsonResponse(
                        {
                            "ok": True,
                            "message": message,
                            "mode": result.mode,
                            **_status_payload(boq, request.session, expect="extract"),
                        }
                    )
                messages.success(request, message)
            else:
                message = (
                    f"Extraction started for '{boq.boq_name}'. "
                    "Results will appear when complete."
                )
                if wants_json:
                    return JsonResponse(
                        {
                            "ok": True,
                            "message": message,
                            "mode": result.mode,
                            **_status_payload(boq, request.session, expect="extract"),
                        }
                    )
                messages.info(request, message)
        except (AIServiceError, BOQAIError) as exc:
            if wants_json:
                return JsonResponse({"ok": False, "message": str(exc)}, status=400)
            messages.error(request, str(exc))
        except Exception:
            logger.exception("Failed to start BOQ extraction for id=%s", boq.pk)
            message = "Failed to start extraction."
            if wants_json:
                return JsonResponse({"ok": False, "message": message}, status=500)
            messages.error(request, message)

        return HttpResponseRedirect(redirect_url)


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
            BOQAnalysisService(boq.pk).rematch_row(row_id)
            message = "Row re-analysed against the database."
            if ajax:
                line_html = _render_extraction_line_html(request, boq, row_id)
                return _extraction_edit_json_ok(
                    message,
                    row_id=row_id,
                    line_html=line_html,
                )
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
            elif action == "add_activity":
                activity = (request.POST.get("activity") or "").strip()
                editor.add_activity(row_id=row_id, activity=activity)
                message = "Activity added."
                if ajax:
                    line_html = _render_extraction_line_html(request, boq, row_id)
                    return _extraction_edit_json_ok(message, row_id=row_id, line_html=line_html)
                messages.success(request, message)
            elif action == "remove_activity":
                activity = (request.POST.get("activity") or "").strip()
                editor.remove_activity(row_id=row_id, activity=activity)
                message = "Activity removed."
                if ajax:
                    line_html = _render_extraction_line_html(request, boq, row_id)
                    return _extraction_edit_json_ok(message, row_id=row_id, line_html=line_html)
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


class BOQMakeVendorSelectView(LoginRequiredMixin, View):
    """Save make/supplier (product or category) and exact-match Rate_Master + rates."""

    def post(self, request, pk: int):
        user = cast(User, request.user)
        boq = get_object_or_404(_boq_queryset_for_user(user), pk=pk)
        redirect_url = _detail_tab_url(boq.pk, "make_vendor")
        ajax = _extraction_edit_is_ajax(request)
        action = (request.POST.get("action") or "select_product").strip().lower()

        try:
            _, make_list_payload = load_extract_data(boq)
        except Exception:
            make_list_payload = boq.make_list_data or {}
        if not boq.make_list_file:
            make_list_payload = {}

        service = MakeVendorSelectionService(boq.pk, make_list_payload)

        try:
            if action == "apply_category":
                category = (request.POST.get("category") or "").strip()
                make = (request.POST.get("make") or "").strip()
                supplier = (request.POST.get("supplier") or "").strip()
                find_rates = (request.POST.get("find_rates") or "1").strip() != "0"
                result = service.apply_category_make(
                    category=category,
                    make=make,
                    supplier=supplier,
                    find_rates=find_rates,
                )
                message = (
                    f"Applied {result['make']} to {result['updated_count']} product(s) "
                    f"in {result['category']} "
                    f"({result['matched_count']} matched with rates)."
                )
                if ajax:
                    return _extraction_edit_json_ok(message, selection=result, reload=True)
                messages.success(request, message)
                return HttpResponseRedirect(redirect_url)

            row_id = (request.POST.get("row_id") or "").strip()
            make = (request.POST.get("make") or "").strip()
            supplier = (request.POST.get("supplier") or "").strip()
            try:
                product_index = int(request.POST.get("product_index") or "0")
            except ValueError:
                message = "Invalid product index."
                if ajax:
                    return _extraction_edit_json_error(message)
                messages.error(request, message)
                return HttpResponseRedirect(redirect_url)

            if not row_id:
                message = "Missing BOQ row."
                if ajax:
                    return _extraction_edit_json_error(message)
                messages.error(request, message)
                return HttpResponseRedirect(redirect_url)

            result = service.select_and_match(
                row_id=row_id,
                product_index=product_index,
                make=make,
                supplier=supplier,
            )
            message = (
                "Exact product matched and rates loaded."
                if result.get("status") == "matched"
                else "Selection saved — review the closest database match."
            )
            if ajax:
                return _extraction_edit_json_ok(
                    message,
                    row_id=row_id,
                    product_index=product_index,
                    selection=result,
                )
            messages.success(request, message)
        except ValidationError as exc:
            if ajax:
                return _extraction_edit_json_error(str(exc))
            messages.error(request, str(exc))
        except Exception:
            logger.exception("Make/vendor selection failed for BOQ id=%s", boq.pk)
            message = "Failed to match make/supplier against the database."
            if ajax:
                return _extraction_edit_json_error(message, status=500)
            messages.error(request, message)

        return HttpResponseRedirect(redirect_url)


class BOQMatchView(LoginRequiredMixin, View):
    """Match extracted products against the master database."""

    def post(self, request, pk: int):
        user = cast(User, request.user)
        boq = get_object_or_404(_boq_queryset_for_user(user), pk=pk)
        wants_json = _request_wants_json(request)
        analysis_url = _detail_tab_url(boq.pk, "analysis")
        match_url = _detail_tab_url(boq.pk, "match_results")

        if _job_is_running(boq):
            message = "A job is already running for this BOQ."
            if wants_json:
                boq.refresh_from_db(fields=["status"])
                return JsonResponse(
                    {
                        "ok": True,
                        "message": message,
                        "mode": "async",
                        **_status_payload(boq, request.session, expect="match"),
                    }
                )
            messages.info(request, message)
            return HttpResponseRedirect(match_url)

        if not (boq.analysis_data or {}).get("rows"):
            message = "Run Analyse first to extract products."
            if wants_json:
                return JsonResponse({"ok": False, "message": message}, status=400)
            messages.error(request, message)
            return HttpResponseRedirect(analysis_url)

        try:
            result = dispatch_boq_matching(boq.pk)
            boq.refresh_from_db(fields=["status"])
            if result.mode == "failed":
                message = result.message or "Could not start matching."
                if wants_json:
                    return JsonResponse(
                        {
                            "ok": False,
                            "message": message,
                            "mode": result.mode,
                            **_status_payload(boq, request.session, expect="match"),
                        },
                        status=400,
                    )
                messages.error(request, message)
                return HttpResponseRedirect(analysis_url)
            if result.mode == "sync":
                message = f"Matching completed for '{boq.boq_name}'."
                if wants_json:
                    return JsonResponse(
                        {
                            "ok": True,
                            "message": message,
                            "mode": result.mode,
                            **_status_payload(boq, request.session, expect="match"),
                        }
                    )
                messages.success(request, message)
            else:
                message = (
                    f"Matching started for '{boq.boq_name}'. "
                    "Results will appear when complete."
                )
                if wants_json:
                    return JsonResponse(
                        {
                            "ok": True,
                            "message": message,
                            "mode": result.mode,
                            **_status_payload(boq, request.session, expect="match"),
                        }
                    )
                messages.info(request, message)
        except (AIServiceError, BOQAIError) as exc:
            if wants_json:
                return JsonResponse({"ok": False, "message": str(exc)}, status=400)
            messages.error(request, str(exc))
            return HttpResponseRedirect(analysis_url)
        except Exception:
            logger.exception("Failed to start BOQ matching for id=%s", boq.pk)
            message = "Failed to start matching."
            if wants_json:
                return JsonResponse({"ok": False, "message": message}, status=500)
            messages.error(request, message)
            return HttpResponseRedirect(analysis_url)

        return HttpResponseRedirect(match_url)


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
        return JsonResponse(_status_payload(boq, request.session, expect=expect))


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

    def _wants_json(self) -> bool:
        """True for AJAX upload / name-check style requests (no full page reload)."""
        if self.request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return True
        accept = (self.request.headers.get("Accept") or "").lower()
        return "application/json" in accept

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)

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
            form.add_error(None, f"Upload failed: {exc}")
            if not self._wants_json():
                messages.error(self.request, f"Upload failed: {exc}")
            return self.form_invalid(form)

        messages.success(
            self.request,
            f"BOQ '{form.cleaned_data['boq_name']}' uploaded successfully.",
        )
        if self._wants_json():
            return JsonResponse({"ok": True, "redirect": self.get_success_url()})
        return super().form_valid(form)

    def form_invalid(self, form):
        """Keep selected files in the browser by returning JSON errors (no reload)."""
        if self._wants_json():
            errors = {
                field: [str(error) for error in error_list]
                for field, error_list in form.errors.items()
            }
            first_message = next(
                (msg for msgs in errors.values() for msg in msgs),
                "Please fix the errors below.",
            )
            return JsonResponse(
                {"ok": False, "errors": errors, "message": first_message},
                status=400,
            )
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse("boq:list")


class BOQNameCheckView(LoginRequiredMixin, View):
    """JSON check: whether a BOQ name is available (case-insensitive)."""

    def get(self, request):
        name = (request.GET.get("boq_name") or "").strip()
        if not name:
            return JsonResponse(
                {"available": False, "message": "BOQ name is required."},
                status=400,
            )
        taken = BOQ.objects.filter(boq_name__iexact=name).exists()
        if taken:
            return JsonResponse(
                {
                    "available": False,
                    "message": "A BOQ with this name already exists. Choose a different name.",
                }
            )
        return JsonResponse({"available": True, "message": "Name is available."})


# Backward-compatible alias.
class BOQProcessView(BOQExtractView):
    """Deprecated — use BOQExtractView."""
