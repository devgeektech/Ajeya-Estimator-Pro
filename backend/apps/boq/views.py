"""BOQ views (list, detail, upload)."""

import logging
from typing import cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Case, IntegerField, Value, When
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
from .services.boq_analysis_dispatch import dispatch_boq_extraction, dispatch_boq_matching
from .services.boq_confirmation_service import BOQConfirmationService
from .services.boq_export_service import BOQExportService
from .services.boq_labour_service import BOQLabourService
from .services.boq_review_display_service import BOQReviewDisplayService
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
    heal_make_vendor_unlock,
    is_export_ready,
    mark_exported_in_session,
    resolve_boq_database_label,
    resolve_detail_tab,
)
from .services.serial_normalizer import (
    structure_for_analysis,
    structure_for_display,
    structure_for_make_list_display,
)

logger = logging.getLogger("boq_ai")


def _upload_error_message(exc: BaseException) -> str:
    """Flatten Django ValidationError list-style messages for UI display."""
    messages_attr = getattr(exc, "messages", None)
    if messages_attr:
        return "; ".join(str(item) for item in messages_attr)
    return str(exc)


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
            BOQStatus.MAKE_VENDOR,
            BOQStatus.PROCESSED,
            BOQStatus.READY_EXPORT,
            BOQStatus.EXPORTED,
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
    from apps.boq.services.boq_job_progress import (
        get_boq_job_progress,
        heal_stale_running_boq,
    )

    # Dead Celery/worker leaves PROCESSING forever — unblock on poll.
    if heal_stale_running_boq(boq):
        boq.refresh_from_db(fields=["status", "analysis_data"])

    expect_key = (expect or "extract").strip().lower()
    if expect_key == "match":
        ready = boq.status in {BOQStatus.PROCESSED, BOQStatus.ANALYSIS_FAILED}
    else:
        ready = boq.status in {BOQStatus.EXTRACTED, BOQStatus.ANALYSIS_FAILED}
    display = build_boq_status_display(boq, session)
    progress = get_boq_job_progress(boq.pk)
    percent = int(progress.get("percent") or 0)
    if ready and boq.status != BOQStatus.ANALYSIS_FAILED:
        percent = 100
    elif boq.status in {BOQStatus.PROCESSING, BOQStatus.MATCHING} and percent <= 0:
        percent = 1
    return {
        "status": boq.status,
        "ready": ready,
        "failed": boq.status == BOQStatus.ANALYSIS_FAILED,
        "expect": expect_key,
        "label": display["label"],
        "badge": display["badge"],
        "polling": boq.status in {BOQStatus.PROCESSING, BOQStatus.MATCHING},
        "progress_percent": percent,
        "progress_label": progress.get("label") or display["label"],
    }


class BOQListView(LoginRequiredMixin, ListView):
    model = BOQ
    template_name = "boq/boq_list.html"
    context_object_name = "boqs"

    _SORT_FIELDS = {
        "name": "boq_name",
        "owner": "user__first_name",
        "status": "status",
        "created": "created_at",
    }

    def get_queryset(self):
        user = cast(User, self.request.user)
        qs = _boq_queryset_for_user(user)

        # Search is client-side (live filter over the full list). Keep all rows
        # so Clear / typing can restore matches without a reload; `q` is only
        # echoed into the template for initialQuery + sort URL preservation.

        sort_key = (self.request.GET.get("sort") or "created").strip().lower()
        direction = (self.request.GET.get("dir") or "desc").strip().lower()
        if sort_key not in self._SORT_FIELDS:
            sort_key = "created"
        if direction not in {"asc", "desc"}:
            direction = "desc"

        if sort_key == "owner":
            if direction == "desc":
                return qs.order_by("-user__first_name", "-user__last_name", "-user__email", "-id")
            return qs.order_by("user__first_name", "user__last_name", "user__email", "-id")

        if sort_key == "status":
            # Pipeline order so Status sort is meaningful (not alphabetical codes).
            status_rank = Case(
                When(status=BOQStatus.UPLOADED, then=Value(10)),
                When(status=BOQStatus.PROCESSING, then=Value(20)),
                When(status=BOQStatus.EXTRACTED, then=Value(30)),
                When(status=BOQStatus.MAKE_VENDOR, then=Value(40)),
                When(status=BOQStatus.LABOUR, then=Value(50)),
                When(status=BOQStatus.MATCHING, then=Value(55)),
                When(status=BOQStatus.PROCESSED, then=Value(60)),
                When(status=BOQStatus.READY_EXPORT, then=Value(70)),
                When(status=BOQStatus.EXPORTED, then=Value(80)),
                When(status=BOQStatus.ANALYSIS_FAILED, then=Value(90)),
                default=Value(100),
                output_field=IntegerField(),
            )
            qs = qs.annotate(_status_rank=status_rank)
            if direction == "desc":
                return qs.order_by("-_status_rank", "-created_at", "-id")
            return qs.order_by("_status_rank", "created_at", "-id")

        order_field = self._SORT_FIELDS[sort_key]
        if direction == "desc":
            order_field = f"-{order_field}"
        return qs.order_by(order_field, "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        session = self.request.session
        query = (self.request.GET.get("q") or "").strip()
        sort_key = (self.request.GET.get("sort") or "created").strip().lower()
        direction = (self.request.GET.get("dir") or "desc").strip().lower()
        if sort_key not in self._SORT_FIELDS:
            sort_key = "created"
        if direction not in {"asc", "desc"}:
            direction = "desc"

        context["search_q"] = query
        context["sort"] = sort_key
        context["dir"] = direction
        context["boq_items"] = [
            {
                "boq": boq,
                "status_display": build_boq_status_display(boq, session),
                "database_label": resolve_boq_database_label(boq),
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
        # Persist unlock if Next already wrote vendor selections but status/flag lagged.
        try:
            if heal_make_vendor_unlock(boq):
                boq.refresh_from_db(fields=["analysis_data", "status"])
        except Exception:
            logger.exception("Make & Vendor unlock heal failed for BOQ id=%s", boq.pk)
        try:
            from apps.boq.services.boq_job_progress import heal_stale_running_boq

            if heal_stale_running_boq(boq):
                boq.refresh_from_db(fields=["analysis_data", "status"])
        except Exception:
            logger.exception("Stale job heal failed for BOQ id=%s", boq.pk)

        context["tab_access"] = build_boq_tab_access(boq)
        context["default_tab"] = resolve_detail_tab(
            boq,
            self.request.session,
            self.request.GET.get("tab"),
        )
        active_tab = context["default_tab"]

        # Load extract JSON only for tabs that render it (keeps switches light).
        boq_payload: dict = {}
        make_list_payload: dict = {}
        if active_tab == "boq":
            # Sheet display uses stored BOQ JSON — skip make-list normalize path.
            boq_payload = boq.boq_data or {}
        elif active_tab in {"make_list", "analysis", "make_vendor"}:
            try:
                _loaded_boq, loaded_make_list = load_extract_data(boq)
            except Exception:
                logger.exception("Failed to load extract JSON for BOQ id=%s", boq.pk)
                loaded_make_list = boq.make_list_data or {}
            make_list_payload = loaded_make_list if boq.make_list_file else {}
            if active_tab == "make_list":
                # make_list display needs the make-list payload only.
                pass

        # Per-tab payloads only — keeps tab switches fast (no multi-MB combined HTML).
        context["boq_structure"] = {}
        context["make_list_structure"] = {}
        if active_tab == "boq":
            context["boq_structure"] = structure_for_display(boq_payload)
        elif active_tab == "make_list" and boq.make_list_file:
            context["make_list_structure"] = structure_for_make_list_display(
                make_list_payload
            )
        context["has_make_list"] = bool(boq.make_list_file)
        context["has_analysis_rows"] = bool((boq.analysis_data or {}).get("rows"))
        context["is_extracting"] = boq.status == BOQStatus.PROCESSING
        context["is_matching"] = boq.status == BOQStatus.MATCHING
        context["is_processing"] = _job_is_running(boq)
        context["can_analyse"] = boq.status in {
            BOQStatus.UPLOADED,
            BOQStatus.EXTRACTED,
            BOQStatus.MAKE_VENDOR,
            BOQStatus.LABOUR,
            BOQStatus.PROCESSED,
            BOQStatus.READY_EXPORT,
            BOQStatus.EXPORTED,
            BOQStatus.ANALYSIS_FAILED,
        } and not _job_is_running(boq)
        # Make & Vendor → Next opens Labour (Match rematch retired from UI).
        context["can_unlock_labour"] = (
            boq.status
            in {
                BOQStatus.MAKE_VENDOR,
                BOQStatus.EXTRACTED,
            }
            and bool((boq.analysis_data or {}).get("rows"))
            and bool(
                (boq.analysis_data or {}).get("make_vendor_defaults_applied")
                or boq.status == BOQStatus.MAKE_VENDOR
            )
            and not _job_is_running(boq)
        )
        # Include MAKE_VENDOR: labour_ready can remain after MV edits, and
        # BOQLabourService._ensure_labour_editable already allows that status.
        context["can_apply_labour"] = (
            boq.status
            in {
                BOQStatus.MAKE_VENDOR,
                BOQStatus.LABOUR,
                BOQStatus.READY_EXPORT,
                BOQStatus.EXPORTED,
                BOQStatus.PROCESSED,
            }
            and bool((boq.analysis_data or {}).get("rows"))
            and not _job_is_running(boq)
        )
        labour_ready = bool(
            ((boq.analysis_data or {}).get("labour_config") or {}).get("labour_ready")
        )
        context["can_complete_labour"] = (
            labour_ready
            and boq.status
            in {
                BOQStatus.MAKE_VENDOR,
                BOQStatus.LABOUR,
                BOQStatus.READY_EXPORT,
                BOQStatus.PROCESSED,
            }
            and not _job_is_running(boq)
        )
        context["can_export"] = is_export_ready(boq) and bool(boq.analysis_data)
        context["can_rematch"] = False
        context["can_match"] = False
        context["can_edit_extraction"] = boq.status in {
            BOQStatus.EXTRACTED,
            BOQStatus.MAKE_VENDOR,
            BOQStatus.LABOUR,
            BOQStatus.PROCESSED,
            BOQStatus.READY_EXPORT,
            BOQStatus.EXPORTED,
            BOQStatus.ANALYSIS_FAILED,
        } and not _job_is_running(boq) and bool((boq.analysis_data or {}).get("rows"))
        context["status_display"] = build_boq_status_display(boq, self.request.session)
        context["extraction_stats"] = (boq.analysis_data or {}).get("stats")
        context["analysis_stats"] = (boq.analysis_data or {}).get("stats")

        from apps.boq.services.boq_job_progress import get_boq_job_progress

        job_progress = get_boq_job_progress(boq.pk)
        initial_progress = int(job_progress.get("percent") or 0)
        if context["is_extracting"] and initial_progress <= 0:
            initial_progress = 1
        if not context["is_extracting"]:
            initial_progress = 0
        context["analysis_progress_percent"] = initial_progress
        context["analysis_progress_label"] = (
            job_progress.get("label") or ""
            if context["is_extracting"]
            else ""
        )

        empty_extraction = {
            "has_extraction": False,
            "lines": [],
            "product_count": 0,
            "multiproduct_review_count": 0,
            "missing_field_count": 0,
        }
        empty_review = {
            "has_analysis": False,
            "lines": [],
            "stats": {},
            "confirmation_stats": {},
            "review_headers": [],
        }
        empty_make_vendor = {"has_products": False, "lines": [], "stats": {}}
        empty_labour = {
            "has_products": False,
            "lines": [],
            "category_rows": [],
            "stats": {},
            "mode": "auto",
            "labour_ready": False,
        }
        context["extraction_display"] = empty_extraction
        context["analysis_display"] = empty_review
        context["make_vendor_display"] = empty_make_vendor
        context["labour_display"] = empty_labour

        if active_tab == "analysis" and not context["is_extracting"]:
            context["extraction_display"] = BOQExtractionDisplayService(
                boq,
                make_list_payload,
                has_make_list_file=bool(boq.make_list_file),
            ).build()
        elif active_tab == "make_vendor":
            try:
                context["make_vendor_display"] = MakeVendorSelectionService(
                    boq.pk,
                    make_list_payload,
                ).build_display()
            except Exception:
                logger.exception(
                    "Failed to build Make & Vendor display for BOQ id=%s", boq.pk
                )
        elif active_tab == "labour":
            try:
                context["labour_display"] = BOQLabourService(boq.pk).build_display()
            except Exception:
                logger.exception("Failed to build Labour display for BOQ id=%s", boq.pk)
        elif active_tab == "review":
            confirmations = BOQConfirmationService(boq.pk, self.request.session).all()
            context["analysis_display"] = BOQReviewDisplayService(
                boq, confirmations
            ).build()
        return context


class BOQExtractView(LoginRequiredMixin, View):
    """Trigger AI product extraction for one BOQ."""

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
        product_index_raw = (request.POST.get("product_index") or "").strip()
        product_index = None
        if product_index_raw != "":
            try:
                product_index = int(product_index_raw)
            except (TypeError, ValueError):
                message = "Invalid product index."
                if ajax:
                    return _extraction_edit_json_error(message)
                messages.error(request, message)
                return HttpResponseRedirect(redirect_url)
        mode = (request.POST.get("mode") or "").strip().lower()
        # Product Re-analyse: rematch using saved fields + filled blanks.
        # Empty-section / explicit reextract: rebuild from BOQ workbook text.
        force_reextract = mode in {"reextract", "re-extract", "extract", "analyse", "analyze"}
        if mode in {"", "rematch", "match", "reanalyse", "re-analyse", "reanalyze"}:
            force_reextract = False
        # Empty section has no products — must re-extract.
        if not force_reextract:
            analysis_rows = list((boq.analysis_data or {}).get("rows") or [])
            target = next(
                (row for row in analysis_rows if str(row.get("row_id")) == str(row_id)),
                None,
            )
            if not target or not (target.get("products") or []):
                force_reextract = True
            elif product_index is None:
                message = "Select a product to re-analyse."
                if ajax:
                    return _extraction_edit_json_error(message)
                messages.error(request, message)
                return HttpResponseRedirect(redirect_url)
        try:
            # Product rematch uses product_index; empty section re-extracts.
            BOQAnalysisService(boq.pk).rematch_row(
                row_id,
                product_index=None if force_reextract else product_index,
                force_reextract=force_reextract,
            )
            message = (
                "Section re-extracted from the BOQ workbook."
                if force_reextract
                else "Product re-analysed using BOQ row, filled attributes, and prior match details."
            )
            if ajax:
                line_html = _render_extraction_line_html(request, boq, row_id)
                return _extraction_edit_json_ok(
                    message,
                    row_id=row_id,
                    line_html=line_html,
                    product_index=product_index,
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
        redirect_url = _detail_tab_url(boq.pk, "review")
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
            elif action == "select_candidate":
                try:
                    product_index = int(request.POST.get("product_index") or "0")
                    rate_master_id = int(request.POST.get("rate_master_id") or "0")
                except ValueError:
                    message = "Invalid candidate selection."
                    if ajax:
                        return _extraction_edit_json_error(message)
                    messages.error(request, message)
                    return HttpResponseRedirect(redirect_url)
                if not rate_master_id:
                    message = "Select a database candidate."
                    if ajax:
                        return _extraction_edit_json_error(message)
                    messages.error(request, message)
                    return HttpResponseRedirect(redirect_url)
                editor.select_candidate(
                    row_id=row_id,
                    product_index=product_index,
                    rate_master_id=rate_master_id,
                )
                message = "Database product selected."
                if ajax:
                    line_html = _render_extraction_line_html(request, boq, row_id)
                    return _extraction_edit_json_ok(
                        message,
                        row_id=row_id,
                        product_index=product_index,
                        line_html=line_html,
                    )
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
    """Save make/vendor (product or category) and exact-match Rate_Master_Output + rates."""

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
            if action == "apply_lowest_defaults":
                find_rates = (request.POST.get("find_rates") or "1").strip() != "0"
                result = service.apply_lowest_defaults_all(find_rates=find_rates)
                message = (
                    f"Prefilled lowest approved make/vendor on {result['updated_count']} "
                    f"product(s) ({result['matched_count']} matched with rates)."
                )
                if ajax:
                    return _extraction_edit_json_ok(message, selection=result, reload=True)
                messages.success(request, message)
                return HttpResponseRedirect(redirect_url)

            if action == "apply_subcategory":
                category = (request.POST.get("category") or "").strip()
                sub_category = (request.POST.get("sub_category") or "").strip()
                make = (request.POST.get("make") or "").strip()
                vendor = (request.POST.get("vendor") or "").strip()
                find_rates = (request.POST.get("find_rates") or "1").strip() != "0"
                result = service.apply_subcategory_make(
                    category=category,
                    sub_category=sub_category,
                    make=make,
                    vendor=vendor,
                    find_rates=find_rates,
                )
                message = (
                    f"Applied {result.get('make') or 'lowest price'} to "
                    f"{result['updated_count']} product(s) in "
                    f"{result['category']}"
                    + (
                        f" / {result['sub_category']}"
                        if result.get("sub_category")
                        else " (entire category)"
                    )
                    + f" ({result['matched_count']} matched with rates)."
                )
                if ajax:
                    return _extraction_edit_json_ok(message, selection=result, reload=True)
                messages.success(request, message)
                return HttpResponseRedirect(redirect_url)

            if action == "remove_subcategory_filter":
                category = (request.POST.get("category") or "").strip()
                sub_category = (request.POST.get("sub_category") or "").strip()
                result = service.remove_subcategory_filter(
                    category=category,
                    sub_category=sub_category,
                )
                label = result["category"]
                if result.get("sub_category"):
                    label = f"{label} / {result['sub_category']}"
                else:
                    label = f"{label} (entire category)"
                message = f"Removed applied filter for {label}."
                if ajax:
                    return _extraction_edit_json_ok(message, selection=result, reload=True)
                messages.success(request, message)
                return HttpResponseRedirect(redirect_url)

            if action == "resolve_same_price":
                row_id = (request.POST.get("row_id") or "").strip()
                try:
                    product_index = int(request.POST.get("product_index") or "0")
                    rate_master_id = int(request.POST.get("rate_master_id") or "0")
                except ValueError:
                    message = "Invalid same-price selection."
                    if ajax:
                        return _extraction_edit_json_error(message)
                    messages.error(request, message)
                    return HttpResponseRedirect(redirect_url)
                if not row_id or not rate_master_id:
                    message = "Choose one of the same-price options."
                    if ajax:
                        return _extraction_edit_json_error(message)
                    messages.error(request, message)
                    return HttpResponseRedirect(redirect_url)
                result = service.resolve_same_price_choice(
                    row_id=row_id,
                    product_index=product_index,
                    rate_master_id=rate_master_id,
                )
                message = (
                    f"Selected vendor {result.get('vendor') or '—'} "
                    f"({result.get('make') or '—'}) for same-price tie."
                )
                if ajax:
                    return _extraction_edit_json_ok(
                        message,
                        row_id=row_id,
                        product_index=product_index,
                        selection=result,
                        reload=True,
                    )
                messages.success(request, message)
                return HttpResponseRedirect(redirect_url)

            if action == "find_in_db":
                row_id = (request.POST.get("row_id") or "").strip()
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
                result = service.find_in_db(row_id=row_id, product_index=product_index)
                message = (
                    f"Found Product_ID {result.get('product_id') or '—'} in database; "
                    f"loaded make/vendor rates."
                )
                if ajax:
                    return _extraction_edit_json_ok(
                        message,
                        row_id=row_id,
                        product_index=product_index,
                        selection=result,
                        reload=True,
                    )
                messages.success(request, message)
                return HttpResponseRedirect(redirect_url)

            if action == "apply_category":
                category = (request.POST.get("category") or "").strip()
                make = (request.POST.get("make") or "").strip()
                vendor = (request.POST.get("vendor") or "").strip()
                find_rates = (request.POST.get("find_rates") or "1").strip() != "0"
                result = service.apply_category_make(
                    category=category,
                    make=make,
                    vendor=vendor,
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
            vendor = (request.POST.get("vendor") or "").strip()
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
                vendor=vendor,
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
            message = "Failed to match make/vendor against the database."
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
        match_url = _detail_tab_url(boq.pk, "review")

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
    """Backward-compatible redirect to the Review tab on BOQ detail."""

    def get(self, request, pk: int):
        user = cast(User, request.user)
        boq = get_object_or_404(_boq_queryset_for_user(user), pk=pk)
        if boq.status in {
            BOQStatus.EXTRACTED,
            BOQStatus.MAKE_VENDOR,
            BOQStatus.UPLOADED,
        }:
            messages.info(request, "Complete Make & Vendor, then continue to Labour.")
            if boq.status == BOQStatus.MAKE_VENDOR or (
                (boq.analysis_data or {}).get("make_vendor_defaults_applied")
            ):
                return HttpResponseRedirect(_detail_tab_url(boq.pk, "make_vendor"))
            return HttpResponseRedirect(_detail_tab_url(boq.pk, "analysis"))
        if boq.status == BOQStatus.LABOUR and not (
            (boq.analysis_data or {}).get("pricing_ready")
        ):
            return HttpResponseRedirect(_detail_tab_url(boq.pk, "labour"))
        return HttpResponseRedirect(_detail_tab_url(boq.pk, "review"))


class BOQLabourView(LoginRequiredMixin, View):
    """Labour tab actions: unlock, apply auto/manual, complete → Review."""

    def post(self, request, pk: int):
        user = cast(User, request.user)
        boq = get_object_or_404(_boq_queryset_for_user(user), pk=pk)
        ajax = _request_wants_json(request)
        action = (request.POST.get("action") or "").strip()
        labour_url = _detail_tab_url(boq.pk, "labour")
        review_url = _detail_tab_url(boq.pk, "review")

        if _job_is_running(boq):
            message = "Wait for the current job to finish."
            if ajax:
                return JsonResponse({"ok": False, "message": message}, status=400)
            messages.error(request, message)
            return HttpResponseRedirect(labour_url)

        service = BOQLabourService(boq.pk)
        try:
            if action == "unlock":
                result = service.unlock()
                clear_exported_in_session(boq.pk, request.session)
                message = "Labour tab unlocked. Choose Auto or Manual, then Apply."
                if ajax:
                    return JsonResponse(
                        {
                            "ok": True,
                            "message": message,
                            "status": result.get("status"),
                            "redirect": labour_url,
                        }
                    )
                messages.success(request, message)
                return HttpResponseRedirect(labour_url)

            if action == "apply_auto":
                result = service.apply_auto()
                clear_exported_in_session(boq.pk, request.session)
                message = (
                    f"Auto labour applied to {result['updated_count']} product(s) "
                    f"({result['with_labour_count']} with Labour_Master rates)."
                )
                if ajax:
                    return JsonResponse(
                        {
                            "ok": True,
                            "message": message,
                            "selection": result,
                            "redirect": labour_url,
                        }
                    )
                messages.success(request, message)
                return HttpResponseRedirect(labour_url)

            if action == "apply_manual":
                percentages: dict[str, str] = {}
                for key, value in request.POST.items():
                    if key.startswith("percent__"):
                        category = key[len("percent__") :]
                        percentages[category] = value
                # Also accept JSON-style category map from ajax body fields.
                raw_json = (request.POST.get("category_percentages") or "").strip()
                if raw_json:
                    import json

                    try:
                        parsed = json.loads(raw_json)
                        if isinstance(parsed, dict):
                            percentages.update(
                                {str(k): v for k, v in parsed.items()}
                            )
                    except json.JSONDecodeError as exc:
                        raise ValidationError("Invalid category percentages payload.") from exc
                result = service.apply_manual(percentages)
                clear_exported_in_session(boq.pk, request.session)
                message = (
                    f"Manual labour applied to {result['updated_count']} product(s) "
                    f"across {len(result.get('category_percentages') or {})} categor"
                    f"{'y' if len(result.get('category_percentages') or {}) == 1 else 'ies'}."
                )
                if ajax:
                    return JsonResponse(
                        {
                            "ok": True,
                            "message": message,
                            "selection": result,
                            "redirect": labour_url,
                        }
                    )
                messages.success(request, message)
                return HttpResponseRedirect(labour_url)

            if action == "complete":
                result = service.complete()
                clear_exported_in_session(boq.pk, request.session)
                message = (
                    f"Labour complete. Prices ready for {result.get('row_count', 0)} "
                    "row(s). Review and export."
                )
                if ajax:
                    return JsonResponse(
                        {
                            "ok": True,
                            "message": message,
                            "status": result.get("status"),
                            "redirect": review_url,
                        }
                    )
                messages.success(request, message)
                return HttpResponseRedirect(review_url)

            message = "Unknown labour action."
            if ajax:
                return JsonResponse({"ok": False, "message": message}, status=400)
            messages.error(request, message)
            return HttpResponseRedirect(labour_url)
        except ValidationError as exc:
            if ajax:
                return JsonResponse({"ok": False, "message": str(exc)}, status=400)
            messages.error(request, str(exc))
            return HttpResponseRedirect(labour_url)
        except Exception:
            logger.exception("Labour action failed for BOQ id=%s action=%s", boq.pk, action)
            message = "Labour action failed."
            if ajax:
                return JsonResponse({"ok": False, "message": message}, status=500)
            messages.error(request, message)
            return HttpResponseRedirect(labour_url)


class BOQCalculatePriceView(LoginRequiredMixin, View):
    """Legacy endpoint — redirects to Labour complete (pricing + Review)."""

    def post(self, request, pk: int):
        user = cast(User, request.user)
        boq = get_object_or_404(_boq_queryset_for_user(user), pk=pk)
        wants_json = _request_wants_json(request)
        redirect_url = _detail_tab_url(boq.pk, "review")

        if _job_is_running(boq):
            message = "Wait for the current job to finish."
            if wants_json:
                return JsonResponse({"ok": False, "message": message}, status=400)
            messages.error(request, message)
            return HttpResponseRedirect(_detail_tab_url(boq.pk, "labour"))

        try:
            result = BOQLabourService(boq.pk).complete()
            clear_exported_in_session(boq.pk, request.session)
            message = (
                f"Prices calculated for {result.get('row_count', 0)} row(s). "
                "Ready to export."
            )
            if wants_json:
                return JsonResponse(
                    {
                        "ok": True,
                        "message": message,
                        "status": result.get("status"),
                        "redirect": redirect_url,
                    }
                )
            messages.success(request, message)
        except ValidationError as exc:
            if wants_json:
                return JsonResponse({"ok": False, "message": str(exc)}, status=400)
            messages.error(request, str(exc))
            return HttpResponseRedirect(_detail_tab_url(boq.pk, "labour"))
        except Exception:
            logger.exception("BOQ calculate price failed for id=%s", boq.pk)
            message = "Failed to calculate prices."
            if wants_json:
                return JsonResponse({"ok": False, "message": message}, status=500)
            messages.error(request, message)
            return HttpResponseRedirect(_detail_tab_url(boq.pk, "labour"))

        return HttpResponseRedirect(redirect_url)


class BOQAnalysisStatusView(LoginRequiredMixin, View):
    """JSON status for polling while Celery jobs run."""

    def get(self, request, pk: int):
        user = cast(User, request.user)
        qs = BOQ.objects.only("pk", "status", "analysis_data", "boq_name", "user_id")
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

        redirect_url = _detail_tab_url(boq.pk, "review")
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
    """Download Review sheet or priced original BOQ Excel (`?kind=review|boq`)."""

    def get(self, request, pk: int):
        user = cast(User, request.user)
        boq = get_object_or_404(_boq_queryset_for_user(user), pk=pk)
        kind = str(request.GET.get("kind") or "review").strip().lower()

        try:
            confirmations = BOQConfirmationService(boq.pk, request.session).all()
            content, filename = BOQExportService(boq.pk, confirmations).run(kind=kind)
            mark_exported_in_session(boq.pk, request.session)
        except ValueError as exc:
            messages.error(request, str(exc))
            return HttpResponseRedirect(_detail_tab_url(boq.pk, "review"))
        except Exception:
            logger.exception("BOQ export failed for id=%s kind=%s", boq.pk, kind)
            messages.error(request, "Export failed.")
            return HttpResponseRedirect(_detail_tab_url(boq.pk, "review"))

        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class BOQUploadView(LoginRequiredMixin, FormView):
    form_class = BOQUploadForm
    template_name = "boq/boq_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.database_manager.services.activation import get_active_database_version

        context["has_active_database"] = get_active_database_version() is not None
        return context

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
            message = _upload_error_message(exc)
            form.add_error(None, f"Upload failed: {message}")
            if not self._wants_json():
                messages.error(self.request, f"Upload failed: {message}")
            return self.form_invalid(form)

        messages.success(
            self.request,
            f"BOQ '{form.cleaned_data['boq_name']}' uploaded successfully.",
        )
        from apps.notifications.services import notify

        notify(
            self.request.user,
            "BOQ uploaded",
            f"BOQ '{form.cleaned_data['boq_name']}' is ready. Open it and run Analyse.",
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
