"""User-facing BOQ status label and badge styling."""
from __future__ import annotations

import logging

from django.db import transaction

from apps.boq.models import BOQ
from common.choices import BOQStatus

logger = logging.getLogger("boq_ai")

EXPORT_SESSION_KEY = "boq_exported_{boq_id}"
DETAIL_TAB_SESSION_KEY = "boq_detail_tab_{boq_id}"


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
    session[detail_tab_session_key(boq_id)] = tab
    session.modified = True


def remembered_detail_tab(boq_id: int, session) -> str:
    return str(session.get(detail_tab_session_key(boq_id)) or "").strip()


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

    # Persisted export wins over session-only legacy flag.
    if status == BOQStatus.EXPORTED:
        return {"label": "Exported", "badge": "badge--green"}
    if is_exported_in_session(boq.pk, session) and status == BOQStatus.READY_EXPORT:
        return {"label": "Exported", "badge": "badge--green"}

    # Older BOQs: EXTRACTED + Next already applied → show Make/Vendor selection.
    if status == BOQStatus.EXTRACTED and _has_make_vendor_defaults(analysis):
        return {"label": "Make/Vendor selection", "badge": "badge--blue"}

    mapping = {
        BOQStatus.UPLOADED: ("Uploaded", "badge--dark"),
        BOQStatus.PROCESSING: ("Analysing...", "badge--yellow"),
        BOQStatus.EXTRACTED: ("Analysed", "badge--blue"),
        BOQStatus.MAKE_VENDOR: ("Make/Vendor selection", "badge--blue"),
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
    BOQStatus.MATCHING,
    BOQStatus.PROCESSED,
    BOQStatus.READY_EXPORT,
    BOQStatus.EXPORTED,
    BOQStatus.ANALYSIS_FAILED,
}

_MATCHING_STATUSES = {
    BOQStatus.MATCHING,
    BOQStatus.PROCESSED,
    BOQStatus.READY_EXPORT,
    BOQStatus.EXPORTED,
}

_EXPORT_READY_STATUSES = {
    BOQStatus.READY_EXPORT,
    BOQStatus.EXPORTED,
}

_POST_ANALYSIS_PIPELINE = {
    BOQStatus.MAKE_VENDOR,
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
    # After Match, Make & Vendor must stay open even if older match runs dropped the flag.
    if not make_vendor_ready and has_rows and status in _MATCHING_STATUSES:
        make_vendor_ready = True
    if status == BOQStatus.MAKE_VENDOR:
        make_vendor_ready = True
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
            BOQStatus.PROCESSED,
            BOQStatus.READY_EXPORT,
            BOQStatus.EXPORTED,
            BOQStatus.ANALYSIS_FAILED,
            BOQStatus.MATCHING,
        },
        "match_results": status in _MATCHING_STATUSES,
    }


def default_detail_tab_for_boq(boq: BOQ, session) -> str:
    """Default tab when opening BOQ detail (list View button, bare detail URL)."""
    if boq.status == BOQStatus.EXPORTED or is_exported_in_session(boq.pk, session):
        return "match_results"
    if boq.status in {BOQStatus.READY_EXPORT, BOQStatus.PROCESSED, BOQStatus.MATCHING}:
        return "match_results"
    if boq.status == BOQStatus.MAKE_VENDOR or (
        boq.status == BOQStatus.EXTRACTED
        and _has_make_vendor_defaults(boq.analysis_data or {})
    ):
        return "make_vendor"
    remembered = remembered_detail_tab(boq.pk, session)
    if remembered:
        return remembered
    if boq.status in _ANALYSIS_STATUSES:
        return "analysis"
    return "boq"


def resolve_detail_tab(boq: BOQ, session, requested_tab: str | None) -> str:
    """Pick a valid tab, falling back when the request targets a locked tab."""
    access = build_boq_tab_access(boq)
    tab = (requested_tab or "").strip() or default_detail_tab_for_boq(boq, session)
    if tab not in {"boq", "make_list", "analysis", "make_vendor", "match_results"}:
        tab = default_detail_tab_for_boq(boq, session)
    if tab == "analysis" and not access["analysis"]:
        tab = "boq"
    elif tab == "make_vendor" and not access["make_vendor"]:
        tab = "analysis" if access["analysis"] else "boq"
    elif tab == "match_results" and not access["match_results"]:
        if access["make_vendor"]:
            tab = "make_vendor"
        elif access["analysis"]:
            tab = "analysis"
        else:
            tab = "boq"
    remember_detail_tab(boq.pk, session, tab)
    return tab


def is_export_ready(boq: BOQ) -> bool:
    """True when Calculate Price has completed (or BOQ already exported)."""
    if boq.status in _EXPORT_READY_STATUSES:
        return True
    return bool((boq.analysis_data or {}).get("pricing_ready"))
