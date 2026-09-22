"""Global single-flight database import progress (shared across workers/UI)."""

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

_STALE_PROCESSING_SECONDS = 60 * 45  # imports can take ~10 minutes; expire stuck jobs
_TERMINAL_STATUS_TTL_SECONDS = 90  # succeeded/failed only until UI has consumed them


def _progress_dir() -> Path:
    root = Path(settings.MEDIA_ROOT) / "job_progress"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _status_path() -> Path:
    return _progress_dir() / "database_import_status.json"


def _lock_path() -> Path:
    return _progress_dir() / "database_import.lock"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
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


def read_import_status() -> dict[str, Any]:
    """Return current import status for UI polling.

    Self-heals stuck ``processing`` and expires old terminal statuses to idle.
    """
    path = _status_path()
    if not path.is_file():
        return {"status": STATUS_IDLE}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"status": STATUS_IDLE}
    if not isinstance(data, dict):
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
                "message": "Import timed out or the server stopped. Previous database unchanged.",
                "updated_at": now,
                "finished_at": now,
                "started_at": data.get("started_at"),
                "filename": data.get("filename") or "",
                "uploaded_by_email": data.get("uploaded_by_email") or "",
            }
            try:
                _write_json(path, failed)
                _release_lock_file()
            except Exception:
                logger.exception("Failed marking stale database import as failed")
            return failed

    if status in (STATUS_SUCCEEDED, STATUS_FAILED) and finished_at:
        if (now - finished_at) > _TERMINAL_STATUS_TTL_SECONDS:
            try:
                path.unlink(missing_ok=True)
                if status == STATUS_FAILED:
                    _release_lock_file()
            except Exception:
                logger.exception("Failed clearing terminal database import status")
            return {"status": STATUS_IDLE}

    return {
        "status": status,
        "message": str(data.get("message") or ""),
        "phase": str(data.get("phase") or ""),
        "filename": str(data.get("filename") or ""),
        "uploaded_by_email": str(data.get("uploaded_by_email") or ""),
        "version_number": data.get("version_number"),
        "started_at": data.get("started_at"),
        "updated_at": data.get("updated_at"),
        "finished_at": data.get("finished_at"),
    }


def is_import_busy() -> bool:
    return read_import_status().get("status") == STATUS_PROCESSING


def _release_lock_file() -> None:
    path = _lock_path()
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        logger.warning("Failed releasing database import lock", exc_info=True)


def try_begin_import(
    *,
    uploaded_by_id: int | None,
    uploaded_by_email: str,
    filename: str,
) -> bool:
    """Acquire the global import lock. Returns False if another import is running."""
    if is_import_busy():
        return False

    lock = _lock_path()
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    except FileExistsError:
        # Another process may hold the lock; refresh status for stale jobs first.
        if is_import_busy():
            return False
        try:
            lock.unlink()
        except OSError:
            return False
        return try_begin_import(
            uploaded_by_id=uploaded_by_id,
            uploaded_by_email=uploaded_by_email,
            filename=filename,
        )

    now = time.time()
    payload = {
        "status": STATUS_PROCESSING,
        "phase": "importing",
        "message": "Import and embeddings are running…",
        "filename": filename,
        "uploaded_by_id": uploaded_by_id,
        "uploaded_by_email": uploaded_by_email,
        "started_at": now,
        "updated_at": now,
    }
    try:
        _write_json(_status_path(), payload)
    except Exception:
        logger.exception("Failed writing database import status")
        _release_lock_file()
        return False
    return True


def update_import_phase(phase: str, message: str = "") -> None:
    data = read_import_status()
    if data.get("status") != STATUS_PROCESSING:
        return
    data["phase"] = phase
    if message:
        data["message"] = message
    data["updated_at"] = time.time()
    try:
        _write_json(_status_path(), data)
    except Exception:
        logger.exception("Failed updating database import phase")


def mark_import_succeeded(*, version_number: int, message: str = "") -> None:
    now = time.time()
    data = read_import_status()
    payload = {
        "status": STATUS_SUCCEEDED,
        "phase": "done",
        "message": message
        or "Database imported, embeddings complete, and previous master data purged.",
        "filename": data.get("filename") or "",
        "uploaded_by_email": data.get("uploaded_by_email") or "",
        "uploaded_by_id": data.get("uploaded_by_id"),
        "version_number": version_number,
        "started_at": data.get("started_at"),
        "updated_at": now,
        "finished_at": now,
    }
    try:
        _write_json(_status_path(), payload)
    finally:
        _release_lock_file()


def mark_import_failed(message: str) -> None:
    now = time.time()
    data = read_import_status()
    payload = {
        "status": STATUS_FAILED,
        "phase": "failed",
        "message": message or "Database import failed. Previous database unchanged.",
        "filename": data.get("filename") or "",
        "uploaded_by_email": data.get("uploaded_by_email") or "",
        "uploaded_by_id": data.get("uploaded_by_id"),
        "started_at": data.get("started_at"),
        "updated_at": now,
        "finished_at": now,
    }
    try:
        _write_json(_status_path(), payload)
    finally:
        _release_lock_file()
