"""Map OpenAI / AI provider exceptions to short UI messages."""
from __future__ import annotations

AI_CREDITS_EMPTY_MESSAGE = (
    "OpenAI API credits are empty. Add credits in OpenAI billing, then try again."
)

AI_RATE_LIMIT_MESSAGE = (
    "OpenAI rate limit reached. Wait a moment, then try again."
)

# Generic labels written by older workers / heal paths — upgrade for the UI.
_GENERIC_FAILURE_LABELS = frozenset(
    {
        "analysis failed",
        "analysis failed - click analyse boq to retry",
        "analysis failed. click retry analyse.",
        "analysis stalled - click analyse boq to retry",
        "failed",
    }
)

ANALYSIS_FAILED_DEFAULT_MESSAGE = (
    "Analysis failed. Common cause: OpenAI API credits are empty - "
    "add credits in OpenAI billing, then click Analyse BOQ again."
)


_FRIENDLY_AI_MESSAGES = frozenset(
    {
        AI_CREDITS_EMPTY_MESSAGE,
        AI_RATE_LIMIT_MESSAGE,
        ANALYSIS_FAILED_DEFAULT_MESSAGE,
    }
)

_WRAPPER_PREFIXES = (
    "AI request failed: ",
    "Embedding request failed: ",
    "Database import failed during embedding generation: ",
    "Database import failed: ",
    "Import failed: ",
)


def format_ai_error_message(exc: BaseException | str | None) -> str:
    """Return a user-facing message for AI failures (quota, rate limit, etc.)."""
    text = str(exc or "").strip()
    text = _strip_error_wrappers(text)
    if text in _FRIENDLY_AI_MESSAGES:
        return text
    lower = text.casefold()
    if lower in _GENERIC_FAILURE_LABELS:
        return ANALYSIS_FAILED_DEFAULT_MESSAGE
    if any(
        token in lower
        for token in (
            "credit_balance_exhausted",
            "insufficient_quota",
            "no credits remaining",
            "credits are empty",
            "exceeded your current quota",
            "billing hard limit",
        )
    ):
        return AI_CREDITS_EMPTY_MESSAGE
    if "rate_limit" in lower or "rate limit" in lower or "429" in lower:
        # Quota exhaustion is often reported as RateLimitError 429 — check first above.
        if "quota" in lower or "credit" in lower:
            return AI_CREDITS_EMPTY_MESSAGE
        return AI_RATE_LIMIT_MESSAGE
    if not text:
        return ANALYSIS_FAILED_DEFAULT_MESSAGE
    for prefix in ("Error code: 429 - ",):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    if len(text) > 220:
        text = text[:217].rstrip() + "…"
    return f"AI request failed: {text}"


def is_fatal_ai_limit_error(exc: BaseException | str | None) -> bool:
    """True when remaining OpenAI calls must stop (empty credits or rate limit)."""
    return format_ai_error_message(exc) in {
        AI_CREDITS_EMPTY_MESSAGE,
        AI_RATE_LIMIT_MESSAGE,
    }


def _strip_error_wrappers(text: str) -> str:
    """Unwrap nested import/AI prefixes so quota text still maps to the UI message."""
    changed = True
    while changed:
        changed = False
        for prefix in _WRAPPER_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
                changed = True
                break
    return text


def resolve_analysis_error_message(
    *,
    last_error: str | None = None,
    progress_label: str | None = None,
) -> str:
    """Pick the best Analysis-failure message for banners / status poll."""
    for candidate in (last_error, progress_label):
        text = str(candidate or "").strip()
        if not text:
            continue
        return format_ai_error_message(text)
    return ANALYSIS_FAILED_DEFAULT_MESSAGE
