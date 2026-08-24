"""Persist BOQ analysis JSON alongside extract JSON."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from django.conf import settings

from .extract_json_store import _write_json, boq_extract_dir

logger = logging.getLogger("boq_ai")

ANALYSIS_FILENAME = "boq_analysis.json"


def save_boq_analysis_json(boq_name: str, payload: dict[str, Any]) -> Path:
    path = boq_extract_dir(boq_name) / ANALYSIS_FILENAME
    _write_json(path, payload)
    logger.info("Saved BOQ analysis JSON for '%s' at %s", boq_name, path)
    return path


def analysis_json_relative_path(boq_name: str) -> str:
    path = boq_extract_dir(boq_name) / ANALYSIS_FILENAME
    return str(path.relative_to(Path(settings.MEDIA_ROOT))).replace("\\", "/")
