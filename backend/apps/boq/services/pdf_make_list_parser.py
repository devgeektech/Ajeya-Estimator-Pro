"""Parse make-list tables from PDF text extraction (pypdf)."""
from __future__ import annotations

import re
from typing import Any

from pypdf import PdfReader

_SERIAL_LINE = re.compile(r"^(\d+)\.?\s+(.+)$")
_TITLE_MARKERS = re.compile(
    r"(?:list\s+of\s+acceptable|system\s*:-|acceptable\s+make\s+of\s+materials)",
    re.IGNORECASE,
)
_HEADER_LINE = re.compile(
    r"s\.?\s*no\.?.*description.*(?:approved\s*)?makes?",
    re.IGNORECASE,
)


def _looks_like_make_token(token: str) -> bool:
    token = token.strip()
    if not token or len(token) > 40:
        return False
    letters = [char for char in token if char.isalpha()]
    if not letters:
        return False
    upper_ratio = sum(char.isupper() for char in letters) / len(letters)
    return upper_ratio >= 0.6 or token.isupper()


def _strip_fused_title_suffix(line: str) -> str:
    match = _TITLE_MARKERS.search(line)
    if not match:
        return line.strip()
    return line[: match.start()].strip()


def is_pdf_title_line(line: str) -> bool:
    text = line.strip()
    if not text:
        return True
    if _SERIAL_LINE.match(_strip_fused_title_suffix(text)):
        return False
    if _HEADER_LINE.search(text):
        return False
    if _TITLE_MARKERS.search(text):
        return True
    if _SERIAL_LINE.match(text):
        return False
    letters = [char for char in text if char.isalpha()]
    if letters and sum(char.isupper() for char in letters) / len(letters) > 0.85:
        return len(text) > 20
    return False


def is_pdf_header_line(line: str) -> bool:
    return bool(_HEADER_LINE.search(line.strip()))


def parse_make_list_pdf_line(line: str) -> tuple[str, str, list[str]] | None:
    """Split one PDF text line into serial, description, and approved makes."""
    cleaned = _strip_fused_title_suffix(line)
    match = _SERIAL_LINE.match(cleaned)
    if not match:
        return None

    serial, rest = match.group(1), match.group(2).strip()
    if not rest:
        return serial, "", []

    if "/" not in rest:
        return serial, rest, []

    segments = [segment.strip() for segment in rest.split("/") if segment.strip()]
    if len(segments) == 1:
        first_segment = segments[0]
        words = first_segment.rsplit(None, 1)
        if len(words) == 2 and _looks_like_make_token(words[1]):
            return serial, words[0].strip(), [words[1].strip()]
        return serial, first_segment, []

    makes: list[str] = []
    description_end = len(segments)

    for index in range(len(segments) - 1, -1, -1):
        segment = segments[index]
        if _looks_like_make_token(segment):
            makes.insert(0, segment)
            description_end = index
            continue
        words = segment.rsplit(None, 1)
        if len(words) == 2 and _looks_like_make_token(words[1]):
            makes.insert(0, words[1].strip())
            segments[index] = words[0].strip()
            description_end = index + 1
        break

    description = " / ".join(
        segment for segment in segments[:description_end] if segment
    ).strip()
    return serial, description, makes


def _make_list_headers(max_make_columns: int) -> list[dict]:
    headers = [
        {"key": "s_no", "label": "S. No.", "index": 0},
        {"key": "description", "label": "Description", "index": 1},
    ]
    for index in range(max_make_columns):
        suffix = "" if index == 0 else f" {index + 1}"
        headers.append(
            {
                "key": "approved_makes" if index == 0 else f"approved_makes_{index + 1}",
                "label": f"Approved Makes{suffix}",
                "index": 2 + index,
            }
        )
    return headers


def _record_from_parsed(
    *,
    line_number: int,
    page_number: int,
    serial: str,
    description: str,
    makes: list[str],
    headers: list[dict],
) -> dict[str, Any]:
    display_values: dict[str, Any] = {
        "s_no": serial,
        "description": description,
    }
    values: dict[str, Any] = dict(display_values)
    make_headers = [header for header in headers if header["key"].startswith("approved_makes")]
    for header, make in zip(make_headers, makes, strict=False):
        display_values[header["key"]] = make
        values[header["key"]] = make
    for header in make_headers[len(makes) :]:
        display_values[header["key"]] = None
        values[header["key"]] = None

    return {
        "excel_row_number": line_number,
        "page": page_number,
        "values": values,
        "display_values": display_values,
    }


def parse_make_list_pdf(file_path: str) -> tuple[list[dict], list[dict]]:
    """Return ``(headers, records)`` for a make-list PDF."""
    reader = PdfReader(file_path)
    parsed_rows: list[tuple[int, int, str, str, list[str]]] = []
    line_number = 0

    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or is_pdf_title_line(line) or is_pdf_header_line(line):
                continue
            parsed = parse_make_list_pdf_line(line)
            if not parsed:
                continue
            serial, description, makes = parsed
            line_number += 1
            parsed_rows.append((line_number, page_number, serial, description, makes))

    max_makes = max((len(makes) for *_, makes in parsed_rows), default=1)
    headers = _make_list_headers(max_makes)
    records = [
        _record_from_parsed(
            line_number=line_number,
            page_number=page_number,
            serial=serial,
            description=description,
            makes=makes,
            headers=headers,
        )
        for line_number, page_number, serial, description, makes in parsed_rows
    ]
    return headers, records
