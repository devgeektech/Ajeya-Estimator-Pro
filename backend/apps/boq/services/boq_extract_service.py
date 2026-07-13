"""Refresh normalized BOQ / make-list JSON in PostgreSQL and extract_json files."""
from __future__ import annotations

import logging

from apps.boq.models import BOQ

from .boq_parser import parse_boq_workbook
from .boq_files import upload_basename
from .extract_json_store import save_extract_json_for_boq
from .make_list_parser import parse_make_list_file

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
