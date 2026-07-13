"""User-facing BOQ status label and badge styling."""
from __future__ import annotations

from apps.boq.models import BOQ
from common.choices import BOQStatus

EXPORT_SESSION_KEY = "boq_exported_{boq_id}"


def export_session_key(boq_id: int) -> str:
    return EXPORT_SESSION_KEY.format(boq_id=boq_id)


def is_exported_in_session(boq_id: int, session) -> bool:
    return bool(session.get(export_session_key(boq_id)))


def mark_exported_in_session(boq_id: int, session) -> None:
    session[export_session_key(boq_id)] = True
    session.modified = True


def clear_exported_in_session(boq_id: int, session) -> None:
    session.pop(export_session_key(boq_id), None)
    session.modified = True


def build_boq_status_display(boq: BOQ, session) -> dict[str, str]:
    """Return display label and badge CSS class for the BOQ header."""
    if is_exported_in_session(boq.pk, session):
        return {"label": "Exported", "badge": "badge--green"}

    status = boq.status
    mapping = {
        BOQStatus.UPLOADED: ("Uploaded", "badge--dark"),
        BOQStatus.PROCESSING: ("Analysing", "badge--yellow"),
        BOQStatus.EXTRACTED: ("Analysis completed", "badge--green"),
        BOQStatus.MATCHING: ("Matching", "badge--red"),
        BOQStatus.PROCESSED: ("Matching complete", "badge--green"),
        BOQStatus.ANALYSIS_FAILED: ("Failed", "badge--red"),
    }
    label, badge = mapping.get(status, ("Unknown", "badge--gray"))
    return {"label": label, "badge": badge}


_ANALYSIS_STATUSES = {
    BOQStatus.PROCESSING,
    BOQStatus.EXTRACTED,
    BOQStatus.ANALYSIS_FAILED,
}

_MATCHING_STATUSES = {
    BOQStatus.MATCHING,
    BOQStatus.PROCESSED,
}


def build_boq_tab_access(boq: BOQ) -> dict[str, bool]:
    """Which detail tabs the user may open for the current BOQ state."""
    status = boq.status
    return {
        "analysis": status in _ANALYSIS_STATUSES
        or bool((boq.analysis_data or {}).get("rows")),
        "match_results": status in _MATCHING_STATUSES,
    }


def default_detail_tab_for_boq(boq: BOQ, session) -> str:
    """Default tab when opening BOQ detail (list View button, bare detail URL)."""
    if is_exported_in_session(boq.pk, session) or boq.status in _MATCHING_STATUSES:
        return "match_results"
    if boq.status in _ANALYSIS_STATUSES:
        return "analysis"
    return "boq"


def resolve_detail_tab(boq: BOQ, session, requested_tab: str | None) -> str:
    """Pick a valid tab, falling back when the request targets a locked tab."""
    access = build_boq_tab_access(boq)
    tab = (requested_tab or "").strip() or default_detail_tab_for_boq(boq, session)
    if tab not in {"boq", "make_list", "analysis", "match_results"}:
        tab = default_detail_tab_for_boq(boq, session)
    if tab == "analysis" and not access["analysis"]:
        tab = "boq"
    elif tab == "match_results" and not access["match_results"]:
        tab = "analysis" if access["analysis"] else "boq"
    return tab
