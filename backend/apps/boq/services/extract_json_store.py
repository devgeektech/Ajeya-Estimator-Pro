"""Persist normalized BOQ / make-list JSON under media/extract_json/."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from django.conf import settings

logger = logging.getLogger("boq_ai")

BOQ_FILENAME = "boq_data.json"
MAKE_LIST_FILENAME = "make_list_data.json"
_INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def extract_json_root() -> Path:
    return Path(settings.MEDIA_ROOT) / "extract_json"


def extract_json_folder_name(boq_name: str) -> str:
    """Return a safe folder name matching the BOQ display name."""
    cleaned = _INVALID_PATH_CHARS.sub("_", (boq_name or "").strip())
    cleaned = cleaned.rstrip(". ")
    return cleaned or "boq"


def boq_extract_dir(boq_name: str) -> Path:
    return extract_json_root() / extract_json_folder_name(boq_name)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def save_boq_extract_json(boq_name: str, payload: dict[str, Any]) -> Path:
    """Write BOQ normalized JSON to ``media/extract_json/{boq_name}/boq_data.json``."""
    path = boq_extract_dir(boq_name) / BOQ_FILENAME
    _write_json(path, payload)
    logger.info("Saved BOQ extract JSON for '%s' at %s", boq_name, path)
    return path


def save_make_list_extract_json(boq_name: str, payload: dict[str, Any]) -> Path:
    """Write make-list JSON to ``media/extract_json/{boq_name}/make_list_data.json``."""
    path = boq_extract_dir(boq_name) / MAKE_LIST_FILENAME
    _write_json(path, payload)
    logger.info("Saved make-list extract JSON for '%s' at %s", boq_name, path)
    return path


def save_extract_json_for_boq(
    boq_name: str,
    *,
    boq_data: dict[str, Any] | None = None,
    make_list_data: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Persist whichever payloads are provided; return written relative paths."""
    written: dict[str, str] = {}
    media_root = Path(settings.MEDIA_ROOT)
    if boq_data is not None:
        path = save_boq_extract_json(boq_name, boq_data)
        written["boq_data"] = str(path.relative_to(media_root)).replace("\\", "/")
    if make_list_data is not None:
        path = save_make_list_extract_json(boq_name, make_list_data)
        written["make_list_data"] = str(path.relative_to(media_root)).replace("\\", "/")
    return written


def read_boq_extract_json(boq_name: str) -> dict[str, Any] | None:
    path = boq_extract_dir(boq_name) / BOQ_FILENAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_make_list_extract_json(boq_name: str) -> dict[str, Any] | None:
    path = boq_extract_dir(boq_name) / MAKE_LIST_FILENAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
