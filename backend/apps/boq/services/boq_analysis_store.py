"""Persist BOQ analysis JSON alongside extract JSON."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from django.conf import settings

from .extract_json_store import _write_json, boq_extract_dir

logger = logging.getLogger("boq_ai")

ANALYSIS_FILENAME = "boq_analysis.json"
MATCH_RESULTS_FILENAME = "boq_match_results.json"


def save_boq_analysis_json(boq_name: str, payload: dict[str, Any]) -> Path:
    path = boq_extract_dir(boq_name) / ANALYSIS_FILENAME
    _write_json(path, payload)
    logger.info("Saved BOQ analysis JSON for '%s' at %s", boq_name, path)
    return path


def read_boq_analysis_json(boq_name: str) -> dict[str, Any] | None:
    path = boq_extract_dir(boq_name) / ANALYSIS_FILENAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def analysis_json_relative_path(boq_name: str) -> str:
    path = boq_extract_dir(boq_name) / ANALYSIS_FILENAME
    return str(path.relative_to(Path(settings.MEDIA_ROOT))).replace("\\", "/")


def build_match_results_payload(analysis_payload: dict[str, Any]) -> dict[str, Any]:
    """Shape a dedicated match-results snapshot for internal tracking."""
    from utils.timestamps import now_local_iso

    rows: list[dict[str, Any]] = []
    for row in analysis_payload.get("rows") or []:
        rows.append(
            {
                "row_id": row.get("row_id"),
                "skip_matching": row.get("skip_matching"),
                "products": row.get("products") or [],
                "activities": row.get("activities") or [],
                "make_list": row.get("make_list"),
                "product_matches": row.get("product_matches") or [],
            }
        )
    return {
        "schema_version": 1,
        "phase": analysis_payload.get("phase"),
        "boq_id": analysis_payload.get("boq_id"),
        "boq_name": analysis_payload.get("boq_name"),
        "database_version_id": analysis_payload.get("database_version_id"),
        "matched_at": now_local_iso(),
        "stats": analysis_payload.get("stats") or {},
        "rows": rows,
    }


def save_boq_match_results_json(boq_name: str, payload: dict[str, Any]) -> Path:
    path = boq_extract_dir(boq_name) / MATCH_RESULTS_FILENAME
    _write_json(path, payload)
    logger.info("Saved BOQ match results JSON for '%s' at %s", boq_name, path)
    return path


def match_results_json_relative_path(boq_name: str) -> str:
    path = boq_extract_dir(boq_name) / MATCH_RESULTS_FILENAME
    return str(path.relative_to(Path(settings.MEDIA_ROOT))).replace("\\", "/")
