"""Parse make-list tables from PDF text extraction (pypdf)."""
from __future__ import annotations

import re
from typing import Any

from pypdf import PdfReader

from utils.text_boundary import (
    looks_like_make_token,
    looks_like_standalone_manufacturer,
    normalize_make_segment,
    peel_boundary_segment,
    peel_fused_case_makes,
    peel_fused_segment_boundary,
    repair_description_and_makes,
    word_count,
)

_SERIAL_LINE = re.compile(r"^(\d+)\.?\s+(.+)$")
_TITLE_MARKERS = re.compile(
    r"(?:list\s+of\s+acceptable|system\s*:-|acceptable\s+make\s+of\s+materials|"
    r"approved\s+makes?\s+of|make\s+list)",
    re.IGNORECASE,
)
_HEADER_LINE = re.compile(
    r"s\.?\s*no\.?.*(?:material|description).*(?:approved\s*)?makes?|"
    r"s\.?\s*no\.?.*make\s*/?\s*manufacturers?",
    re.IGNORECASE,
)
# Soft start of a new numbered item (used when deciding continuation vs new row).
_SOFT_SERIAL_START = re.compile(r"^\d+\.?\s+\S")


def _split_without_slashes(text: str) -> tuple[str, list[str]]:
    description, makes = peel_boundary_segment(text.strip(), allow_long_segment=True)
    return description, makes


def _strip_fused_title_suffix(line: str) -> str:
    match = _TITLE_MARKERS.search(line)
    if not match:
        return line.strip()
    return line[: match.start()].strip()


def is_pdf_section_heading(line: str) -> bool:
    """True for short Title-Case section banners (``Pipes and Fittings``, ``Valves``)."""
    text = line.strip()
    if not text or len(text) > 90:
        return False
    if _SERIAL_LINE.match(_strip_fused_title_suffix(text)):
        return False
    if _HEADER_LINE.search(text) or _TITLE_MARKERS.search(text):
        return True
    # Make lists are slash-separated; section banners are not.
    if "/" in text:
        return False
    # Reject fused PDF junk: ``GunmetalLandingValve,BranchPipeNozzle,Fireman``.
    if text.count(",") >= 2 and text.count(" ") <= 2:
        return False
    if re.search(r"[a-z][A-Z]", text) and text.count(" ") <= 1:
        return False
    words = text.split()
    if not words or len(words) > 10:
        return False
    significant = [
        word
        for word in words
        if word.casefold() not in {"and", "of", "for", "the", "a", "an", "to", "&", "-"}
    ]
    if not significant:
        return False
    titled = sum(1 for word in significant if word[:1].isupper() or word.isupper())
    if titled / len(significant) < 0.8:
        return False
    # Long lowercase sentences are continuation descriptions, not headings.
    lower = sum(1 for char in text if char.islower())
    upper = sum(1 for char in text if char.isupper())
    if lower > upper * 2 and len(words) >= 6:
        return False
    return True


def is_pdf_category_banner(line: str) -> bool:
    """
    True for material-category banners that may be longer than short sections.

    Examples: ``Gun Metal Fire Fighting Fittings & Accessories``, ``Plumbing pumps``.
    """
    text = line.strip()
    if not text or is_pdf_document_banner(text) or is_pdf_header_line(text):
        return False
    if is_pdf_section_heading(text):
        return True
    if "/" in text or _SERIAL_LINE.match(text):
        return False
    # Product/material rows often wrap with specs — never treat as banners.
    if "(" in text or ")" in text or "," in text:
        return False
    if re.search(r"[a-z][A-Z]", text) and text.count(" ") <= 1:
        return False
    blob = text.casefold()
    if "approved" in blob or re.search(r"\btype\b", blob):
        return False
    words = text.split()
    if not (1 <= len(words) <= 12):
        return False
    if any(char.isdigit() for char in text):
        return False

    # Short labels like ``Plumbing pumps`` / ``Fire Pumps`` (mixed case OK).
    category_tail = {
        "pump",
        "pumps",
        "valve",
        "valves",
        "pipe",
        "pipes",
        "fitting",
        "fittings",
        "plant",
        "fixture",
        "fixtures",
        "accessory",
        "accessories",
        "insulation",
        "miscellaneous",
        "items",
        "installation",
        "installations",
        "extinguisher",
        "extinguishers",
        "sprinkler",
        "sprinklers",
        "sanitary",
        "faucets",
    }
    if (
        len(words) <= 4
        and words[0][:1].isupper()
        and words[-1].casefold().strip(".,;") in category_tail
    ):
        return True

    titled = sum(1 for word in words if word[:1].isupper() or word.isupper())
    if titled / len(words) < 0.65:
        return False
    hints = (
        "fitting",
        "valve",
        "pipe",
        "pump",
        "plant",
        "accessory",
        "accessories",
        "sprinkler",
        "extinguisher",
        "miscellaneous",
        "installation",
        "sanitary",
        "insulation",
        "fixture",
        "faucet",
    )
    return any(hint in blob for hint in hints)


def is_pdf_document_banner(line: str) -> bool:
    """True for document titles / headers that must not appear as make-list rows."""
    text = line.strip()
    if not text:
        return True
    # Numbered product rows are never banners (even when brands are ALL CAPS).
    if _SERIAL_LINE.match(_strip_fused_title_suffix(text)) or _SOFT_SERIAL_START.match(text):
        return False
    if _SOLO_SERIAL.match(text):
        return False
    if _TITLE_MARKERS.search(text) or _HEADER_LINE.search(text):
        return True
    letters = [char for char in text if char.isalpha()]
    if letters and sum(char.isupper() for char in letters) / len(letters) > 0.85:
        return len(text) > 20
    return False


def is_pdf_header_line(line: str) -> bool:
    return bool(_HEADER_LINE.search(line.strip()))


_LEGAL_SUFFIX_RE = re.compile(
    r"(?:\s|,)+(?:pvt\.?\s*ltd\.?|private\s+limited|ltd\.?|limited|co\.?|company)\s*$",
    re.IGNORECASE,
)


def split_make_list_body(body: str) -> tuple[str, list[str]]:
    """
    Split a make-list line body (no serial) into description + approved makes.

    Handles common PDF formats:
    - ``Material Brand1/Brand2``
    - fused brands ``…Approved)Tyco``
    - manufacturer-only lines (RO Plant / pump lists)
    - Excel-like free text with trailing brand lists
    """
    rest = str(body or "").strip()
    if not rest:
        return "", []

    rest = re.sub(r"\s*/\s*", " / ", rest)
    rest = re.sub(r"\s+", " ", rest).strip()

    # Manufacturer-only rows: keep name in Description and Approved Makes so the
    # UI still mirrors the PDF Material column while constraints get the brand.
    if "/" not in rest and looks_like_standalone_manufacturer(rest):
        company = _LEGAL_SUFFIX_RE.sub("", normalize_make_segment(rest)).strip(" ,")
        name = company or normalize_make_segment(rest)
        description, makes = repair_description_and_makes(name, [name])
        return description, makes

    if "/" not in rest:
        rest, fused_makes = peel_fused_case_makes(rest)
        description, makes = _split_without_slashes(rest)
        return repair_description_and_makes(
            description,
            [normalize_make_segment(item) for item in fused_makes + makes],
        )

    segments = [segment.strip() for segment in rest.split("/") if segment.strip()]
    if len(segments) == 1:
        segment, fused_makes = peel_fused_case_makes(segments[0])
        description, makes = _split_without_slashes(segment)
        return repair_description_and_makes(
            description,
            [normalize_make_segment(item) for item in fused_makes + makes],
        )

    normalized_segments: list[str] = []
    leading_fused_makes: list[str] = []
    for segment in segments:
        cleaned_segment, fused = peel_fused_case_makes(segment)
        if fused and cleaned_segment:
            normalized_segments.append(cleaned_segment)
            leading_fused_makes.extend(fused)
        elif fused and not cleaned_segment:
            leading_fused_makes.extend(fused)
        else:
            normalized_segments.append(segment)
    segments = normalized_segments or segments

    makes: list[str] = []
    split_index = len(segments)

    for index in range(len(segments) - 1, -1, -1):
        segment = segments[index]
        if index > 0 and looks_like_make_token(segment):
            makes.insert(0, normalize_make_segment(segment))
            split_index = index
            continue
        if index > 0:
            if word_count(segment) <= 4:
                peeled_description, peeled_makes = peel_fused_segment_boundary(segment)
                if not peeled_makes:
                    peeled_description, peeled_makes = peel_boundary_segment(
                        segment,
                        allow_long_segment=True,
                    )
                if peeled_makes:
                    makes = [normalize_make_segment(item) for item in peeled_makes] + makes
                    segments[index] = peeled_description
                    split_index = index + 1
                    break
            split_index = index + 1
            break
        split_index = 1
        break

    description_parts = [segment for segment in segments[:split_index] if segment]
    if description_parts and makes:
        allow_long_segment = len(description_parts) == 1
        peeled_description, peeled_makes = peel_boundary_segment(
            description_parts[-1],
            allow_long_segment=allow_long_segment,
        )
        description_parts[-1] = peeled_description
        makes = [normalize_make_segment(item) for item in peeled_makes] + makes
    elif description_parts and not makes:
        peeled_description, peeled_makes = peel_boundary_segment(
            description_parts[-1],
            allow_long_segment=True,
        )
        description_parts[-1] = peeled_description
        makes = [normalize_make_segment(item) for item in peeled_makes]

    makes = [normalize_make_segment(item) for item in leading_fused_makes + makes]
    # Preserve slash separators from the Material/Make columns.
    description = " / ".join(part for part in description_parts if part).strip()
    description = re.sub(r"\s+", " ", description)
    description = re.sub(r"\s*/\s*", " / ", description).strip(" /")
    return repair_description_and_makes(description, makes)


def parse_make_list_pdf_line(line: str) -> tuple[str, str, list[str]] | None:
    """Split one PDF text line into serial, description, and approved makes."""
    cleaned = _strip_fused_title_suffix(line)
    match = _SERIAL_LINE.match(cleaned)
    if not match:
        return None

    serial, rest = match.group(1), match.group(2).strip()
    if not rest:
        return serial, "", []
    description, makes = split_make_list_body(rest)
    return serial, description, makes


def _make_list_headers(max_make_columns: int) -> list[dict]:
    headers = [
        {"key": "s_no", "label": "S. No.", "index": 0},
        {"key": "description", "label": "Description", "index": 1},
    ]
    for index in range(max(1, max_make_columns)):
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
    is_section_heading: bool = False,
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

    record: dict[str, Any] = {
        "excel_row_number": line_number,
        "page": page_number,
        "values": values,
        "display_values": display_values,
        "approved_makes_list": list(makes),
    }
    if is_section_heading:
        # Display-only banner: no Category mapping and no approved-make constraints.
        record["is_section_heading"] = True
    return record



def _is_manufacturer_only_row(description: str, makes: list[str]) -> bool:
    """True when the row is a company name listed in the Material column."""
    desc = str(description or "").strip()
    if not makes:
        return False
    if not desc:
        return True
    if len(makes) == 1 and desc.casefold() == str(makes[0]).casefold():
        return True
    return looks_like_standalone_manufacturer(desc)


def _resplit_merged_row(
    description: str,
    makes: list[str],
) -> tuple[str, list[str]]:
    """
    Re-run body split after wrap merge so brands that arrived on later lines
    (``Thermaflex/Vidoflex``, ``Minimax/Newage``, ``Tyco /Rapidrop``) peel correctly.
    """
    body = str(description or "").strip()
    if makes:
        # Preserve already-captured makes while re-evaluating the description.
        extras = " / ".join(str(item).strip() for item in makes if str(item).strip())
        if extras and extras.casefold() not in body.casefold():
            body = f"{body} {extras}".strip()
    if not body:
        return description, makes
    return split_make_list_body(body)


def _merge_continuation_into_last(
    parsed_rows: list[tuple[int, int, str, str, list[str], bool]],
    *,
    page_number: int,
    continuation: str,
) -> bool:
    """Append wrapped PDF text onto the previous row's description or makes."""
    if not parsed_rows or not continuation.strip():
        return False
    if is_pdf_document_banner(continuation) or is_pdf_header_line(continuation):
        return False
    if is_pdf_category_banner(continuation):
        return False
    line_number, prev_page, serial, description, makes, is_section = parsed_rows[-1]
    # Section banners stay display-only — never fold product/make text into them.
    if is_section:
        return False
    # Manufacturer-only rows — do not absorb the next sub-heading / note
    # (e.g. ``Plumbing pumps`` after a company name).
    if _is_manufacturer_only_row(description, makes):
        return False
    text = continuation.strip()

    # Trailing make tokens on wrap lines (e.g. " / TYCO / HD").
    if text.startswith("/") or (makes and looks_like_make_token(text.split("/")[0].strip())):
        extra_parts = [part.strip() for part in text.strip("/ ").split("/") if part.strip()]
        for part in extra_parts:
            if looks_like_make_token(part) or word_count(part) <= 3:
                makes = [*makes, normalize_make_segment(part)]
            else:
                description = f"{description} {part}".strip()
        description, makes = _resplit_merged_row(description, makes)
        description, makes = repair_description_and_makes(description, makes)
        parsed_rows[-1] = (
            line_number,
            prev_page or page_number,
            serial,
            description,
            makes,
            False,
        )
        return True

    # Plain wrapped description (no new serial).
    if not _SOFT_SERIAL_START.match(text):
        description = f"{description} {text}".strip()
        description, makes = _resplit_merged_row(description, makes)
        description, makes = repair_description_and_makes(description, makes)
        parsed_rows[-1] = (
            line_number,
            prev_page or page_number,
            serial,
            description,
            makes,
            False,
        )
        return True
    return False


_SOLO_SERIAL = re.compile(r"^\d+\.?$")


def parse_make_list_pdf(file_path: str) -> tuple[list[dict], list[dict]]:
    """Return ``(headers, records)`` for a make-list PDF."""
    reader = PdfReader(file_path)
    # (line_number, page, serial, description, makes, is_section_heading)
    parsed_rows: list[tuple[int, int, str, str, list[str], bool]] = []
    line_number = 0
    pending_serial: str | None = None

    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or is_pdf_header_line(line) or is_pdf_document_banner(line):
                pending_serial = None
                continue
            # Section / category banners (e.g. "Pipes and Fittings",
            # "Gun Metal Fire Fighting Fittings & Accessories") — UI only.
            # Skip when a solo serial is pending — the next line is a product
            # wrap (e.g. Sprinkler Heads), not a new section.
            if pending_serial is None and is_pdf_category_banner(line):
                line_number += 1
                parsed_rows.append((line_number, page_number, "", line, [], True))
                continue

            # PDF often splits "1" onto its own line ahead of the material text.
            if _SOLO_SERIAL.match(line):
                pending_serial = line.rstrip(".")
                continue

            candidate = f"{pending_serial} {line}".strip() if pending_serial else line
            pending_serial = None

            # Category banners may arrive with a leftover pending serial cleared
            # above; catch banner text that was not alone on its line.
            if is_pdf_category_banner(candidate):
                line_number += 1
                parsed_rows.append((line_number, page_number, "", candidate, [], True))
                continue

            parsed = parse_make_list_pdf_line(candidate)
            if parsed:
                serial, description, makes = parsed
                line_number += 1
                parsed_rows.append(
                    (line_number, page_number, serial, description, makes, False)
                )
                continue

            # Orphan text under a section banner: show as description-only
            # (no mapping / no approved makes), rather than dropping it.
            if parsed_rows and parsed_rows[-1][5]:
                # Prefer promoting another category banner over a free text row.
                if is_pdf_category_banner(candidate):
                    line_number += 1
                    parsed_rows.append(
                        (line_number, page_number, "", candidate, [], True)
                    )
                else:
                    line_number += 1
                    parsed_rows.append(
                        (line_number, page_number, "", candidate, [], False)
                    )
                continue

            # Orphan under a manufacturer-only row (e.g. ``Plumbing pumps``).
            last = parsed_rows[-1] if parsed_rows else None
            if last and _is_manufacturer_only_row(last[3], last[4]) and not last[5]:
                line_number += 1
                parsed_rows.append(
                    (
                        line_number,
                        page_number,
                        "",
                        candidate,
                        [],
                        is_pdf_category_banner(candidate),
                    )
                )
                continue

            # Wrapped continuation of the previous numbered item.
            _merge_continuation_into_last(
                parsed_rows,
                page_number=page_number,
                continuation=candidate,
            )

    max_makes = max((len(makes) for *_, makes, _section in parsed_rows), default=1)
    headers = _make_list_headers(max_makes)
    records = [
        _record_from_parsed(
            line_number=line_number,
            page_number=page_number,
            serial=serial,
            description=description,
            makes=makes,
            headers=headers,
            is_section_heading=is_section,
        )
        for line_number, page_number, serial, description, makes, is_section in parsed_rows
    ]
    return headers, records
