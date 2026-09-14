"""OpenAI call retry with TPM-aware backoff."""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import TypeVar

from django.conf import settings

from ai.errors import format_ai_error_message, is_fatal_ai_limit_error
from common.exceptions import AIServiceError

logger = logging.getLogger("boq_ai")

_T = TypeVar("_T")

_RETRY_AFTER_RE = re.compile(
    r"try again in\s+(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ms|s)\b",
    re.IGNORECASE,
)


def parse_openai_retry_seconds(exc: BaseException | str | None) -> float | None:
    """Parse OpenAI's suggested wait from a 429 TPM/RPM message."""
    match = _RETRY_AFTER_RE.search(str(exc or ""))
    if not match:
        return None
    value = float(match.group("value"))
    unit = match.group("unit").lower()
    if unit == "ms":
        return max(value / 1000.0, 0.05)
    return max(value, 0.05)


def is_transient_openai_rate_limit(exc: BaseException | str | None) -> bool:
    """True for short-lived TPM/RPM throttling (not empty credits/quota)."""
    if is_fatal_ai_limit_error(exc):
        return False
    text = str(exc or "").casefold()
    if any(
        token in text
        for token in ("tokens per min", "tpm", "requests per min", "rpm")
    ):
        return True
    is_rate_limited = any(
        token in text for token in ("rate limit", "rate_limit", "ratelimit", "429")
    )
    if is_rate_limited and parse_openai_retry_seconds(exc) is not None:
        return True
    return False


def openai_retry_max_attempts() -> int:
    return max(1, int(getattr(settings, "OPENAI_RETRY_MAX_ATTEMPTS", 8) or 8))


def call_with_openai_backoff(
    operation: Callable[[], _T],
    *,
    operation_name: str = "OpenAI request",
) -> _T:
    """Run ``operation``; sleep and retry on transient TPM/RPM 429s."""
    attempts = openai_retry_max_attempts()
    last_exc: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except AIServiceError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if is_fatal_ai_limit_error(exc):
                raise AIServiceError(format_ai_error_message(exc)) from exc
            if not is_transient_openai_rate_limit(exc) or attempt >= attempts:
                raise AIServiceError(format_ai_error_message(exc)) from exc

            wait = parse_openai_retry_seconds(exc)
            if wait is None:
                wait = min(2.0 ** (attempt - 1), 30.0)
            else:
                # Small cushion so the rolling TPM window can recover.
                wait = min(max(wait * 1.2, 0.25), 60.0)

            logger.warning(
                "%s hit transient OpenAI rate limit; retrying in %.2fs (%s/%s)",
                operation_name,
                wait,
                attempt,
                attempts,
            )
            time.sleep(wait)

    assert last_exc is not None
    raise AIServiceError(format_ai_error_message(last_exc)) from last_exc
