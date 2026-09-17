"""Per-user BOQ upload progress (survives tab switches like database import)."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from django.conf import settings

logger = logging.getLogger("boq_ai")

STATUS_IDLE = "idle"
STATUS_PROCESSING = "processing"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

# Sync upload + optional PDF make-list parse; expire stuck locks without ops help.
_STALE_PROCESSING_SECONDS = 60 * 5
# Succeeded/failed only matter until the UI has consumed them.
_TERMINAL_STATUS_TTL_SECONDS = 90


def _progress_dir() -> Path:
    root = Path(settings.MEDIA_ROOT) / "job_progress"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _status_path(user_id: int) -> Path:
    return _progress_dir() / f"boq_upload_status_{int(user_id)}.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomic write; recreate job_progress and retry once if the dir vanished."""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            if tmp.is_file():
                tmp.unlink()
        except OSError:
            pass
        raise


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        logger.exception("Failed removing BOQ upload status %s", path)


def read_upload_status(user_id: int) -> dict[str, Any]:
    """Return current BOQ upload status for this user (UI polling).

    Self-heals without ops:
    - stuck ``processing`` → ``failed`` after ``_STALE_PROCESSING_SECONDS``
    - old ``succeeded`` / ``failed`` → idle (file removed) after TTL
    """
    path = _status_path(user_id)
    if not path.is_file():
        return {"status": STATUS_IDLE}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _unlink_quiet(path)
        return {"status": STATUS_IDLE}
    if not isinstance(data, dict):
        _unlink_quiet(path)
        return {"status": STATUS_IDLE}

    status = str(data.get("status") or STATUS_IDLE)
    updated_at = float(data.get("updated_at") or 0)
    finished_at = float(data.get("finished_at") or updated_at or 0)
    now = time.time()

    if status == STATUS_PROCESSING and updated_at:
        age = now - updated_at
        if age > _STALE_PROCESSING_SECONDS:
            failed = {
                "status": STATUS_FAILED,
                "message": "Upload timed out or the server stopped. Try again.",
                "updated_at": now,
                "finished_at": now,
                "started_at": data.get("started_at"),
                "boq_name": data.get("boq_name") or "",
            }
            try:
                _write_json(path, failed)
            except Exception:
                logger.exception("Failed marking stale BOQ upload as failed")
                _unlink_quiet(path)
                return {
                    "status": STATUS_FAILED,
                    "message": failed["message"],
                    "boq_name": failed["boq_name"],
                    "started_at": failed.get("started_at"),
                    "updated_at": now,
                    "finished_at": now,
                }
            return failed

    if status in (STATUS_SUCCEEDED, STATUS_FAILED) and finished_at:
        if (now - finished_at) > _TERMINAL_STATUS_TTL_SECONDS:
            _unlink_quiet(path)
            return {"status": STATUS_IDLE}

    return {
        "status": status,
        "message": str(data.get("message") or ""),
        "boq_name": str(data.get("boq_name") or ""),
        "started_at": data.get("started_at"),
        "updated_at": data.get("updated_at"),
        "finished_at": data.get("finished_at"),
    }


def is_upload_busy(user_id: int) -> bool:
    return read_upload_status(user_id).get("status") == STATUS_PROCESSING


def begin_upload(*, user_id: int, boq_name: str) -> bool:
    """Mark this user's BOQ upload as processing. False if already busy."""
    if is_upload_busy(user_id):
        return False
    now = time.time()
    payload = {
        "status": STATUS_PROCESSING,
        "message": "Uploading and parsing BOQ…",
        "boq_name": boq_name or "",
        "started_at": now,
        "updated_at": now,
    }
    try:
        _write_json(_status_path(user_id), payload)
    except Exception:
        logger.exception("Failed writing BOQ upload status")
        return False
    return True


def mark_upload_succeeded(*, user_id: int, boq_name: str = "", message: str = "") -> None:
    now = time.time()
    data = read_upload_status(user_id)
    payload = {
        "status": STATUS_SUCCEEDED,
        "message": message or "BOQ uploaded successfully.",
        "boq_name": boq_name or data.get("boq_name") or "",
        "started_at": data.get("started_at"),
        "updated_at": now,
        "finished_at": now,
    }
    try:
        _write_json(_status_path(user_id), payload)
    except Exception:
        logger.exception("Failed marking BOQ upload succeeded")


def mark_upload_failed(*, user_id: int, message: str = "") -> None:
    now = time.time()
    data = read_upload_status(user_id)
    payload = {
        "status": STATUS_FAILED,
        "message": message or "BOQ upload failed.",
        "boq_name": data.get("boq_name") or "",
        "started_at": data.get("started_at"),
        "updated_at": now,
        "finished_at": now,
    }
    try:
        _write_json(_status_path(user_id), payload)
    except Exception:
        logger.exception("Failed marking BOQ upload failed")


def clear_terminal_upload_status(user_id: int) -> None:
    """Drop succeeded/failed markers so the next upload is not confused by them.

    Also invoked from upload/list GETs; ``read_upload_status`` expires them by TTL.
    """
    path = _status_path(user_id)
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _unlink_quiet(path)
        return
    if not isinstance(data, dict):
        _unlink_quiet(path)
        return
    status = str(data.get("status") or STATUS_IDLE)
    if status not in (STATUS_SUCCEEDED, STATUS_FAILED):
        return
    _unlink_quiet(path)
