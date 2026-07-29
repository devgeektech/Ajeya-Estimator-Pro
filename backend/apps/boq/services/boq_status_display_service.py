"""User-facing BOQ status label and badge styling."""
from __future__ import annotations

import logging

from django.db import transaction

from apps.boq.models import BOQ
from common.choices import BOQStatus

logger = logging.getLogger("boq_ai")

EXPORT_SESSION_KEY = "boq_exported_{boq_id}"
DETAIL_TAB_SESSION_KEY = "boq_detail_tab_{boq_id}"

_VALID_TABS = {
    "boq",
    "make_list",
    "analysis",
    "make_vendor",
    "labour",
    "review",
    "match_results",  # legacy alias → review
}


def export_session_key(boq_id: int) -> str:
    return EXPORT_SESSION_KEY.format(boq_id=boq_id)


def detail_tab_session_key(boq_id: int) -> str:
    return DETAIL_TAB_SESSION_KEY.format(boq_id=boq_id)


def is_exported_in_session(boq_id: int, session) -> bool:
    return bool(session.get(export_session_key(boq_id)))


def mark_exported_in_session(boq_id: int, session) -> None:
    session[export_session_key(boq_id)] = True
    session.modified = True


def clear_exported_in_session(boq_id: int, session) -> None:
    session.pop(export_session_key(boq_id), None)
    session.modified = True


def remember_detail_tab(boq_id: int, session, tab: str) -> None:
    """Remember last opened detail tab so hard refresh stays on it."""
    if not tab:
        return
    # Persist canonical review tab, not the legacy alias.
    session[detail_tab_session_key(boq_id)] = (
        "review" if tab == "match_results" else tab
    )
    session.modified = True


def remembered_detail_tab(boq_id: int, session) -> str:
    tab = str(session.get(detail_tab_session_key(boq_id)) or "").strip()
    if tab == "match_results":
        return "review"
    return tab


def _products_have_vendor_progress(analysis: dict) -> bool:
    """True when Next (or cascade) has already written vendor selections on products."""
    for row in analysis.get("rows") or []:
        for product in row.get("products") or []:
            if not isinstance(product, dict):
                continue
            source = str(product.get("vendor_selection_source") or "").strip()
            if source in {"lowest_defaults", "manual", "not_found"}:
                return True
            if product.get("vendor_selection"):
                return True
    return False


def _has_make_vendor_defaults(analysis: dict) -> bool:
    if bool(analysis.get("make_vendor_defaults_applied")):
        return True
    selections = analysis.get("subcategory_make_selections") or {}
    if any(
        isinstance(value, dict)
        and value.get("source") in {"lowest_defaults", "manual", "not_found"}
        for value in selections.values()
    ):
        return True
    return _products_have_vendor_progress(analysis)


def _labour_ready(analysis: dict) -> bool:
    config = analysis.get("labour_config") or {}
    return bool(config.get("labour_ready"))


def heal_make_vendor_unlock(boq: BOQ) -> bool:
    """
    Persist Make & Vendor unlock when product vendor progress already exists.

    Fixes hard-refresh falling back to Analysis with a greyed Make & Vendor tab
    after Next succeeded but status/flag were not saved (or were partially wiped).
    """
    analysis = dict(boq.analysis_data or {})
    if not analysis.get("rows"):
        return False
    if boq.status in {
        BOQStatus.PROCESSING,
        BOQStatus.MATCHING,
        BOQStatus.UPLOADED,
        BOQStatus.LABOUR,
        BOQStatus.PROCESSED,
        BOQStatus.READY_EXPORT,
        BOQStatus.EXPORTED,
    }:
        return False

    if not _has_make_vendor_defaults(analysis):
        return False

    changed_fields: list[str] = []
    if not analysis.get("make_vendor_defaults_applied"):
        analysis["make_vendor_defaults_applied"] = True
        boq.analysis_data = analysis
        changed_fields.append("analysis_data")
    if boq.status != BOQStatus.MAKE_VENDOR:
        boq.status = BOQStatus.MAKE_VENDOR
        changed_fields.append("status")

    if not changed_fields:
        return False

    with transaction.atomic():
        boq.save(update_fields=list(dict.fromkeys(changed_fields)))
    logger.info(
        "Healed Make & Vendor unlock for BOQ id=%s status=%s fields=%s",
        boq.pk,
        boq.status,
        changed_fields,
    )
    return True


def build_boq_status_display(boq: BOQ, session) -> dict[str, str]:
    """Return display label and badge CSS class for the BOQ header."""
    status = boq.status
    analysis = boq.analysis_data or {}

    if status == BOQStatus.EXPORTED:
        return {"label": "Exported", "badge": "badge--green"}
    if is_exported_in_session(boq.pk, session) and status == BOQStatus.READY_EXPORT:
        return {"label": "Exported", "badge": "badge--green"}

    if status == BOQStatus.EXTRACTED and _has_make_vendor_defaults(analysis):
        return {"label": "Make/Vendor selection", "badge": "badge--blue"}

    mapping = {
        BOQStatus.UPLOADED: ("Uploaded", "badge--dark"),
        BOQStatus.PROCESSING: ("Analysing...", "badge--yellow"),
        BOQStatus.EXTRACTED: ("Analysed", "badge--blue"),
        BOQStatus.MAKE_VENDOR: ("Make/Vendor selection", "badge--blue"),
        BOQStatus.LABOUR: ("Labour", "badge--blue"),
        BOQStatus.MATCHING: ("Matching", "badge--red"),
        BOQStatus.PROCESSED: ("Matched", "badge--green"),
        BOQStatus.READY_EXPORT: ("Ready to Export", "badge--green"),
        BOQStatus.EXPORTED: ("Exported", "badge--green"),
        BOQStatus.ANALYSIS_FAILED: ("Failed", "badge--red"),
    }
    label, badge = mapping.get(status, ("Unknown", "badge--gray"))
    return {"label": label, "badge": badge}


_ANALYSIS_STATUSES = {
    BOQStatus.PROCESSING,
    BOQStatus.EXTRACTED,
    BOQStatus.ANALYSIS_FAILED,
}

_MAKE_VENDOR_STATUSES = {
    BOQStatus.MAKE_VENDOR,
    BOQStatus.LABOUR,
    BOQStatus.MATCHING,
    BOQStatus.PROCESSED,
    BOQStatus.READY_EXPORT,
    BOQStatus.EXPORTED,
    BOQStatus.ANALYSIS_FAILED,
}

_LABOUR_STATUSES = {
    BOQStatus.LABOUR,
    BOQStatus.MATCHING,
    BOQStatus.PROCESSED,
    BOQStatus.READY_EXPORT,
    BOQStatus.EXPORTED,
}

_REVIEW_STATUSES = {
    BOQStatus.READY_EXPORT,
    BOQStatus.EXPORTED,
    BOQStatus.PROCESSED,  # legacy match complete
    BOQStatus.MATCHING,
}

_EXPORT_READY_STATUSES = {
    BOQStatus.READY_EXPORT,
    BOQStatus.EXPORTED,
}

_POST_ANALYSIS_PIPELINE = {
    BOQStatus.MAKE_VENDOR,
    BOQStatus.LABOUR,
    BOQStatus.MATCHING,
    BOQStatus.PROCESSED,
    BOQStatus.READY_EXPORT,
    BOQStatus.EXPORTED,
}


def should_skip_attribute_enrichment(boq: BOQ) -> bool:
    """Do not rewrite analysis after Make & Vendor has been unlocked."""
    if boq.status in _POST_ANALYSIS_PIPELINE:
        return True
    analysis = boq.analysis_data or {}
    return _has_make_vendor_defaults(analysis)


def build_boq_tab_access(boq: BOQ) -> dict[str, bool]:
    """Which detail tabs the user may open for the current BOQ state."""
    status = boq.status
    analysis = boq.analysis_data or {}
    has_rows = bool(analysis.get("rows"))
    make_vendor_ready = _has_make_vendor_defaults(analysis)
    if not make_vendor_ready and has_rows and status in _LABOUR_STATUSES:
        make_vendor_ready = True
    if status == BOQStatus.MAKE_VENDOR:
        make_vendor_ready = True

    labour_ready = status in _LABOUR_STATUSES or (
        has_rows and _labour_ready(analysis)
    )
    review_ready = (
        status in _REVIEW_STATUSES
        or bool(analysis.get("pricing_ready"))
        or (status == BOQStatus.LABOUR and _labour_ready(analysis) and bool(analysis.get("pricing_ready")))
    )
    # Review opens after Labour → Next sets READY_EXPORT / pricing_ready.
    if status in {BOQStatus.READY_EXPORT, BOQStatus.EXPORTED}:
        review_ready = True
    if status in {BOQStatus.PROCESSED, BOQStatus.MATCHING}:
        review_ready = True

    return {
        "analysis": status in _ANALYSIS_STATUSES
        or status in _MAKE_VENDOR_STATUSES
        or has_rows,
        "make_vendor": has_rows
        and make_vendor_ready
        and status
        in {
            BOQStatus.EXTRACTED,
            BOQStatus.MAKE_VENDOR,
            BOQStatus.LABOUR,
            BOQStatus.PROCESSED,
            BOQStatus.READY_EXPORT,
            BOQStatus.EXPORTED,
            BOQStatus.ANALYSIS_FAILED,
            BOQStatus.MATCHING,
        },
        "labour": has_rows and labour_ready,
        "review": has_rows and review_ready,
        # Legacy key for older templates/JS.
        "match_results": has_rows and review_ready,
    }


def default_detail_tab_for_boq(boq: BOQ, session) -> str:
    """
    Default tab when opening BOQ detail (list View, bare detail URL).

    Driven by ``BOQ.status`` so Analysed opens Analysis, Make/Vendor opens
    Make & Vendor, etc. Session memory only applies for pre-analysis tabs
    (BOQ / Make list).
    """
    status = boq.status
    if status == BOQStatus.EXPORTED or is_exported_in_session(boq.pk, session):
        return "review"
    if status in {BOQStatus.READY_EXPORT, BOQStatus.PROCESSED}:
        return "review"
    if status == BOQStatus.LABOUR:
        return "labour"
    if status == BOQStatus.MAKE_VENDOR:
        return "make_vendor"
    if status in {
        BOQStatus.EXTRACTED,
        BOQStatus.PROCESSING,
        BOQStatus.MATCHING,
        BOQStatus.ANALYSIS_FAILED,
    }:
        return "analysis"

    # UPLOADED (and unknown): stay on workbook tabs; remember BOQ vs Make list.
    remembered = remembered_detail_tab(boq.pk, session)
    if remembered in {"boq", "make_list"}:
        return remembered
    return "boq"


def resolve_detail_tab(boq: BOQ, session, requested_tab: str | None) -> str:
    """Pick a valid tab, falling back when the request targets a locked tab."""
    access = build_boq_tab_access(boq)
    tab = (requested_tab or "").strip() or default_detail_tab_for_boq(boq, session)
    if tab == "match_results":
        tab = "review"
    if tab not in _VALID_TABS:
        tab = default_detail_tab_for_boq(boq, session)
    if tab == "analysis" and not access["analysis"]:
        tab = "boq"
    elif tab == "make_vendor" and not access["make_vendor"]:
        tab = "analysis" if access["analysis"] else "boq"
    elif tab == "labour" and not access["labour"]:
        if access["make_vendor"]:
            tab = "make_vendor"
        elif access["analysis"]:
            tab = "analysis"
        else:
            tab = "boq"
    elif tab == "review" and not access["review"]:
        if access["labour"]:
            tab = "labour"
        elif access["make_vendor"]:
            tab = "make_vendor"
        elif access["analysis"]:
            tab = "analysis"
        else:
            tab = "boq"
    remember_detail_tab(boq.pk, session, tab)
    return tab


def is_export_ready(boq: BOQ) -> bool:
    """True when Labour → Next has completed pricing (or BOQ already exported)."""
    if boq.status in _EXPORT_READY_STATUSES:
        return True
    return bool((boq.analysis_data or {}).get("pricing_ready"))


def resolve_boq_database_label(boq: BOQ) -> str:
    """
    Master database name used for this BOQ after analysis.

    Blank until analysis has finished (upload / in-progress show nothing).
    Prefers the name snapshotted into ``analysis_data`` at Analyse time.
    """
    if boq.status in {BOQStatus.UPLOADED, BOQStatus.PROCESSING}:
        return ""

    analysis = boq.analysis_data or {}
    if not analysis.get("rows") and not analysis.get("database_version_id"):
        return ""

    stored_name = str(analysis.get("database_name") or "").strip()
    if stored_name:
        return stored_name

    db_id = int(analysis.get("database_version_id") or 0)
    if not db_id:
        return ""

    from apps.database_manager.models import DatabaseVersion

    version = (
        DatabaseVersion.objects.filter(pk=db_id)
        .only("name", "source_filename", "version_number")
        .first()
    )
    if version is None:
        return f"DB #{db_id}"
    return (
        str(version.name or "").strip()
        or str(version.source_filename or "").strip()
        or f"DB v{version.version_number}"
    )
