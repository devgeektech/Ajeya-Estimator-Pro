"""Parse nominal product sizes from BOQ text (exclude IS standard numbers)."""
from __future__ import annotations

import re
from typing import Any

from utils.attribute_parser import coerce_attributes_dict

_IS_STANDARD_NUMBER = re.compile(
    r"(?i)\bis\s*:?\s*(\d{2,6})(?:\s*[-/]\s*(\d{2,4}))?"
)
_SIZE_DIA = re.compile(
    r"(?i)(?<![0-9])(\d+(?:\.\d+)?)\s*(?:mm\s*)?dia(?:meter)?\b"
)
_SIZE_WITH_UNIT = re.compile(
    r"(?i)(?<![0-9])(\d+(?:\.\d+)?)\s*(mm|nb|inch|in|cm)\b"
)
_GENERIC_NUMBER = re.compile(
    r"(?i)(?<![0-9])(\d+(?:\.\d+)?)\s*(mm|nb|inch|in|cm)?\b"
)
_INVALID_SIZE_LITERAL = re.compile(r"(?i)^is(?:\s+standard)?$")


def _trim_size_number(value: str) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".", 1)[0]
    try:
        number = float(text)
        if number.is_integer():
            return str(int(number))
    except ValueError:
        pass
    return text


def _unit_from_token(token: str | None, *, blob: str) -> str | None:
    unit_token = str(token or "").strip().lower()
    if unit_token in {"mm", "cm"}:
        return unit_token
    if unit_token == "nb":
        return "NB"
    if unit_token in {"inch", "in"}:
        return "inch"
    if re.search(r"(?i)\bmm\b", blob):
        return "mm"
    if re.search(r"(?i)\bnb\b", blob):
        return "NB"
    return None


def is_is_standard_number(text: str, number: str) -> bool:
    """True when ``number`` is part of an Indian Standard code in ``text``."""
    digits = re.sub(r"[^0-9.]", "", str(number or ""))
    if not digits:
        return False
    blob = str(text or "")
    if not _IS_STANDARD_NUMBER.search(blob):
        return False
    for match in _IS_STANDARD_NUMBER.finditer(blob):
        std_no = match.group(1)
        year_suffix = match.group(2) or ""
        if std_no == digits or std_no.lstrip("0") == digits.lstrip("0"):
            if re.search(
                rf"(?i)(?<![0-9]){re.escape(digits)}\s*(?:mm|nb|dia(?:meter)?)\b",
                blob,
            ):
                return False
            return True
        if year_suffix and (
            year_suffix == digits or year_suffix.lstrip("0") == digits.lstrip("0")
        ):
            return True
    return False


def parse_nominal_size_from_text(
    text: Any,
    *,
    require_explicit_unit: bool = False,
) -> tuple[str | None, str | None]:
    """
    Return nominal (size, unit) from BOQ prose.

    Prefers ``63 mm dia`` over ``IS : 636-1979`` standard numbers.
    When ``require_explicit_unit`` is True, only ``dia`` / ``mm`` / ``NB`` /
    ``inch`` patterns match — never bare numbers (uncertain → null).
    """
    blob = str(text or "").strip()
    if not blob:
        return None, None

    candidates: list[tuple[int, str, str | None]] = []

    for match in _SIZE_DIA.finditer(blob):
        size = _trim_size_number(match.group(1))
        if is_is_standard_number(blob, size):
            continue
        candidates.append((0, size, _unit_from_token("mm", blob=blob) or "mm"))

    for match in _SIZE_WITH_UNIT.finditer(blob):
        size = _trim_size_number(match.group(1))
        if is_is_standard_number(blob, size):
            continue
        unit = _unit_from_token(match.group(2), blob=blob)
        candidates.append((1, size, unit))

    if not require_explicit_unit:
        for match in _GENERIC_NUMBER.finditer(blob):
            size = _trim_size_number(match.group(1))
            if is_is_standard_number(blob, size):
                continue
            unit = _unit_from_token(match.group(2), blob=blob)
            candidates.append((2, size, unit))

    if not candidates:
        return None, None

    candidates.sort(key=lambda item: (item[0], len(item[1])))
    _, size, unit = candidates[0]
    return size, unit


def is_invalid_extracted_size(
    size: Any,
    *,
    context_text: str = "",
    attributes: dict[str, Any] | None = None,
) -> bool:
    """True when AI confused an IS standard (or label) with nominal size."""
    raw = str(size or "").strip()
    if not raw:
        return False
    if _INVALID_SIZE_LITERAL.fullmatch(raw):
        return True
    if not re.search(r"\d", raw):
        return True

    digits = re.sub(r"[^0-9.]", "", raw)
    if not digits:
        return True

    attrs = attributes or {}
    is_value = attrs.get("is") or attrs.get("is_standard")
    if is_value:
        is_digits = re.sub(r"[^0-9]", "", str(is_value))
        if is_digits and is_digits == digits:
            return True

    if context_text and is_is_standard_number(context_text, digits):
        confident, _ = parse_nominal_size_from_text(
            context_text,
            require_explicit_unit=True,
        )
        if confident and confident != digits:
            return True
        return True

    return False


def sanitize_product_size(
    product: dict[str, Any],
    *,
    extra_texts: list[str] | None = None,
    use_description_hint: bool = True,
) -> dict[str, Any]:
    """Clear invalid or uncertain AI sizes — never substitute another value."""
    item = dict(product)
    attrs = coerce_attributes_dict(item.get("attributes"))
    sources: list[str] = []
    if use_description_hint:
        sources.append(str(item.get("description_hint") or ""))
    sources.append(str(item.get("product_context") or ""))
    sources.extend(extra_texts or [])
    context_text = " ".join(part for part in sources if part).strip()

    current_size = item.get("size")
    if not is_invalid_extracted_size(
        current_size,
        context_text=context_text,
        attributes=attrs,
    ):
        return item

    item["size"] = None
    return item


# Backward-compatible alias.
repair_product_size = sanitize_product_size
