"""Log final AI instructions and responses to logs/instructions.log."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from django.conf import settings

logger = logging.getLogger("boq_ai.instructions")

_SEPARATOR = "=" * 88


def instruction_log_path() -> Path:
    logs_dir = Path(getattr(settings, "LOGS_DIR", Path.cwd() / "logs"))
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / "instructions.log"


def log_instruction(
    *,
    template_name: str,
    model: str,
    prompt: str,
    response: str = "",
    error: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append one AI exchange to ``logs/instructions.log``."""
    if not getattr(settings, "AI_INSTRUCTION_LOGGING", True):
        return

    timestamp = datetime.now(timezone.utc).isoformat()
    meta = metadata or {}
    meta_parts = [f"{key}={value}" for key, value in meta.items() if value not in (None, "")]
    meta_line = " ".join(meta_parts)

    lines = [
        _SEPARATOR,
        f"timestamp: {timestamp}",
        f"call: {template_name or 'ai'}",
        f"model: {model}",
    ]
    if meta_line:
        lines.append(f"meta: {meta_line}")
    lines.extend(
        [
            "--- instruction ---",
            prompt or "",
            "--- response ---",
            response or "(none)",
        ]
    )
    if error:
        lines.extend(["--- error ---", error])
    lines.append(_SEPARATOR)

    message = "\n".join(lines)
    log_path = instruction_log_path()
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(message)
        handle.write("\n\n")

    summary = f"AI instruction logged call={template_name or 'ai'} model={model} file={log_path}"
    if error:
        logger.error("%s error=%s", summary, error)
    else:
        logger.info("%s", summary)
