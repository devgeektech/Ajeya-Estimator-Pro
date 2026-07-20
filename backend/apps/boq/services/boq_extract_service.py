"""Refresh normalized BOQ / make-list JSON in PostgreSQL and extract_json files."""
from __future__ import annotations

import logging

from apps.boq.models import BOQ

from .boq_parser import parse_boq_workbook
from .boq_files import upload_basename
from .extract_json_store import save_extract_json_for_boq
from .make_list_parser import parse_make_list_file
from apps.boq.services.serial_normalizer import structure_for_analysis
from utils.make_list_splits import attach_approved_makes_list, row_has_make_source

logger = logging.getLogger("boq_ai")


def _safe_parse_boq(boq: BOQ) -> dict:
    try:
        return parse_boq_workbook(
            boq.uploaded_file,
            source_filename=upload_basename(boq.uploaded_file),
        )
    except Exception as exc:
        logger.exception("BOQ parse failed for id=%s", boq.pk)
        return {"version": 1, "error": str(exc), "headers": [], "rows": []}


def _safe_parse_make_list(boq: BOQ) -> dict:
    try:
        return parse_make_list_file(
            boq.make_list_file,
            source_filename=upload_basename(boq.make_list_file),
        )
    except Exception as exc:
        logger.exception("Make list parse failed for BOQ id=%s", boq.pk)
        return {"version": 1, "error": str(exc), "headers": [], "rows": []}


def persist_extract_json(
    boq: BOQ,
    *,
    boq_data: dict | None = None,
    make_list_data: dict | None = None,
    update_database: bool = True,
) -> dict[str, str]:
    """Write extract JSON files and optionally sync ``BOQ`` JSON fields."""
    update_fields: list[str] = []
    if boq_data is not None:
        boq.boq_data = boq_data
        update_fields.append("boq_data")
    if make_list_data is not None:
        boq.make_list_data = make_list_data
        update_fields.append("make_list_data")
    if update_fields and update_database:
        boq.save(update_fields=update_fields)

    return save_extract_json_for_boq(
        boq.boq_name,
        boq_data=boq_data if boq_data is not None else boq.boq_data,
        make_list_data=make_list_data if make_list_data is not None else boq.make_list_data or None,
    )


def refresh_boq_extract(boq: BOQ) -> dict:
    """Re-parse BOQ workbook, persist DB + ``media/extract_json/{boq_name}/``."""
    payload = _safe_parse_boq(boq)
    persist_extract_json(boq, boq_data=payload)
    return payload


def refresh_make_list_extract(boq: BOQ) -> dict:
    """Re-parse make list, persist DB + ``media/extract_json/{boq_name}/``."""
    if not boq.make_list_file:
        return {}
    payload = _safe_parse_make_list(boq)
    persist_extract_json(boq, make_list_data=payload)
    return payload


def refresh_all_extract(boq: BOQ) -> tuple[dict, dict]:
    """Re-parse BOQ and optional make list; persist DB + extract JSON files."""
    boq_payload = _safe_parse_boq(boq)
    make_list_payload = _safe_parse_make_list(boq) if boq.make_list_file else {}
    persist_extract_json(
        boq,
        boq_data=boq_payload,
        make_list_data=make_list_payload or None,
    )
    return boq_payload, make_list_payload


def _make_list_sheet_names(payload: dict | None) -> set[str]:
    rows = list((payload or {}).get("rows") or [])
    names = {str(row.get("sheet_name") or "").strip() for row in rows}
    names.discard("")
    declared = (payload or {}).get("sheets") or []
    for name in declared:
        text = str(name or "").strip()
        if text:
            names.add(text)
    return names


def make_list_payload_is_polluted(payload: dict | None) -> bool:
    """True when stored make-list JSON looks like a multi-sheet / rate merge."""
    if not payload:
        return False
    headers = list(payload.get("headers") or [])
    rows = list(payload.get("rows") or [])
    if len(headers) > 12 or len(rows) > 300:
        return True

    sheet_names = _make_list_sheet_names(payload)
    if len(sheet_names) > 1:
        return True

    header_blob = " ".join(
        f"{(h.get('key') or '')} {(h.get('label') or '')}".lower() for h in headers
    )
    for bad in (
        "approved_dmrc",
        "basic_rate",
        "packing_freight",
        "age_increase",
        "rate_adopted",
        "boq_item_page",
        "sub_head",
    ):
        if bad in header_blob:
            return True

    roles = payload.get("column_roles") or {}
    make_keys = list(roles.get("make_keys") or [])
    from utils.make_list_splits import is_excluded_make_key

    return any(
        is_excluded_make_key(key) and not str(key).lower().startswith("approved_makes")
        for key in make_keys
    )


def _normalize_make_list_payload(payload: dict | None) -> dict:
    """Ensure stored make-list JSON has approved makes and rows_tree."""
    if not payload:
        return {}

    rows = list(payload.get("rows") or [])
    if not rows:
        return payload

    headers = list(payload.get("headers") or [])
    roles = payload.get("column_roles") or {}
    make_keys = list(roles.get("make_keys") or [])

    from utils.make_list_splits import is_excluded_make_key
    from apps.boq.services.make_list_parser import slim_make_list_payload

    polluted_make_keys = any(
        is_excluded_make_key(key) and not str(key).lower().startswith("approved_makes")
        for key in make_keys
    )
    polluted = make_list_payload_is_polluted(payload)

    needs_attach = (
        (not make_keys)
        or polluted_make_keys
        or polluted
        or any(
            (not (row.get("approved_makes_list") or []))
            and row_has_make_source(row, make_keys=make_keys or None)
            for row in rows
        )
    )

    normalized = dict(payload)
    if needs_attach:
        attached_rows, column_roles = attach_approved_makes_list(rows, headers=headers or None)
        normalized["rows"] = attached_rows
        normalized["column_roles"] = column_roles

    # Always slim polluted legacy payloads (merged rate sheets) to make-list columns only.
    if polluted or polluted_make_keys:
        normalized = slim_make_list_payload(normalized)
    elif not normalized.get("rows_tree"):
        normalized = structure_for_analysis(normalized)
    elif needs_attach:
        normalized = structure_for_analysis({**normalized, "rows": normalized["rows"]})

    try:
        from apps.boq.services.make_list_category_mapping_service import (
            MakeListCategoryMappingService,
        )

        mapped = MakeListCategoryMappingService().ensure_mappings(normalized)
        if mapped != normalized:
            # Rebuild rows_tree after category stamps on flat rows.
            normalized = structure_for_analysis(mapped) if mapped.get("rows") else mapped
        else:
            normalized = mapped
    except Exception:
        logger.exception("Make-list category mapping failed during normalize")

    return normalized


def load_extract_data(boq: BOQ, *, refresh: bool = False) -> tuple[dict, dict]:
    """Return BOQ / make-list JSON from PostgreSQL; parse files only when needed."""
    if refresh:
        return refresh_all_extract(boq)

    boq_payload = boq.boq_data or {}
    make_list_payload = (boq.make_list_data or {}) if boq.make_list_file else {}

    if not boq_payload.get("rows") and boq.uploaded_file:
        logger.info("BOQ id=%s missing extract JSON; parsing workbook once", boq.pk)
        boq_payload = refresh_boq_extract(boq)
    if boq.make_list_file and not make_list_payload.get("rows"):
        logger.info("BOQ id=%s missing make-list JSON; parsing file once", boq.pk)
        make_list_payload = refresh_make_list_extract(boq)

    # Re-parse from the uploaded make-list file when stored JSON still has merged junk.
    if boq.make_list_file and make_list_payload_is_polluted(make_list_payload):
        headers = list((make_list_payload or {}).get("headers") or [])
        rows = list((make_list_payload or {}).get("rows") or [])
        sheets = sorted(_make_list_sheet_names(make_list_payload))
        logger.info(
            "BOQ id=%s make-list JSON polluted (%s headers, %s rows, sheets=%s); re-parsing file",
            boq.pk,
            len(headers),
            len(rows),
            sheets,
        )
        make_list_payload = refresh_make_list_extract(boq)

    before = make_list_payload
    make_list_payload = _normalize_make_list_payload(make_list_payload)
    if boq.make_list_file and make_list_payload.get("rows") and make_list_payload != (boq.make_list_data or {}):
        if make_list_payload != before or make_list_payload != (boq.make_list_data or {}):
            persist_extract_json(boq, make_list_data=make_list_payload)

    return boq_payload, make_list_payload
