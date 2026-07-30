"""Excel helpers built on pandas / openpyxl.

Used by the database import and export layers. Kept dependency-light and
side-effect free so it can be unit tested in isolation.
"""
from __future__ import annotations

from datetime import date, datetime
import re
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from utils.xls_convert import (
    is_xls_filename,
    list_xls_visible_sheet_names,
    openxml_workbook_path,
)

HeaderKeys = set[str] | frozenset[str]


class MultiSheetWorkbookError(ValueError):
    """Raised when an Excel upload contains more than one visible worksheet."""


def read_sheets(file_path: str | Path) -> dict[str, pd.DataFrame]:
    """Read all sheets of a workbook into a mapping of {sheet_name: DataFrame}.

    Returns all sheets using pandas.
    """
    return pd.read_excel(file_path, sheet_name=None)


def list_sheet_names(file_path: str | Path) -> list[str]:
    """Return all worksheet names present in a workbook (including hidden)."""
    with openxml_workbook_path(file_path) as workbook_path:
        workbook = load_workbook(filename=workbook_path, read_only=True)
        try:
            return list(workbook.sheetnames)
        finally:
            workbook.close()


def list_visible_sheet_names(file_path: str | Path) -> list[str]:
    """Return visible worksheet names only (hidden sheets are ignored)."""
    path = Path(file_path)
    if is_xls_filename(path.name):
        return list_xls_visible_sheet_names(path)

    with openxml_workbook_path(path) as workbook_path:
        # Need full load for reliable sheet_state (read_only may not expose it).
        workbook = load_workbook(filename=workbook_path, read_only=False)
        try:
            names: list[str] = []
            for sheet in workbook.worksheets:
                state = str(getattr(sheet, "sheet_state", "visible") or "visible").lower()
                if state != "visible":
                    continue
                title = str(sheet.title or "").strip()
                if title:
                    names.append(title)
            return names
        finally:
            workbook.close()


def require_single_worksheet(
    file_path: str | Path,
    *,
    detail_label: str = "BOQ details",
) -> str:
    """Ensure the workbook has exactly one visible worksheet; return that name.

    Raises ``MultiSheetWorkbookError`` when there are multiple visible sheets.
    """
    names = list_visible_sheet_names(file_path)
    if len(names) == 1:
        return names[0]
    if not names:
        raise MultiSheetWorkbookError(
            f"This file is not valid. It has no visible worksheets. "
            f"Please upload single sheet file with {detail_label}."
        )
    sheet_list = ", ".join(names)
    raise MultiSheetWorkbookError(
        f"This file is not valid. It contains multiple sheets - {sheet_list}. "
        f"Please upload single sheet file with {detail_label}."
    )


def _normalize_header(value) -> str:
    """Normalize a header cell to a comparable key (lower snake_case)."""
    if value is None:
        return ""
    normalized = re.sub(r"[^0-9a-zA-Z]+", "_", str(value).strip().lower())
    return normalized.strip("_")


def _display_value(value):
    """Return a stable display value for JSON/UI preservation."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return format(value, ".15g")
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _dedupe_headers(headers: list[dict]) -> list[dict]:
    seen: dict[str, int] = {}
    deduped: list[dict] = []
    for header in headers:
        key = header["key"]
        seen[key] = seen.get(key, 0) + 1
        unique_key = key if seen[key] == 1 else f"{key}_{seen[key]}"
        deduped.append({**header, "key": unique_key})
    return deduped


def _headers_from_cells(cells) -> list[dict]:
    headers = []
    for idx, cell in enumerate(cells):
        key = _normalize_header(cell.value)
        if key:
            headers.append({"key": key, "label": str(cell.value).strip(), "index": idx})
    return _dedupe_headers(headers)


def _key_matches_hints(key: str, header_keys: HeaderKeys | None) -> bool:
    if not header_keys or not key:
        return False
    if key in header_keys:
        return True
    return any(hint in key for hint in header_keys)


def _header_score(headers: list[dict], header_keys: HeaderKeys | None) -> tuple[int, int]:
    if not header_keys:
        return (0, len(headers))
    matches = sum(1 for header in headers if _key_matches_hints(header["key"], header_keys))
    return (matches, len(headers))


def _expand_headers_to_width(headers: list[dict], max_col_index: int) -> list[dict]:
    """Add synthetic headers for data columns beyond the named header cells."""
    if max_col_index < 0:
        return headers
    covered = {header["index"] for header in headers}
    expanded = list(headers)
    anchor = expanded[-1] if expanded else None
    for idx in range(max_col_index + 1):
        if idx in covered:
            continue
        if anchor and "approved" in anchor["key"]:
            suffix = idx - anchor["index"]
            label = f"{anchor['label']} {suffix}" if suffix else anchor["label"]
            key = _normalize_header(label) or f"approved_makes_{suffix}"
        else:
            label = f"Column {idx + 1}"
            key = f"column_{idx + 1}"
        expanded.append({"key": key, "label": label, "index": idx})
    expanded.sort(key=lambda header: header["index"])
    return _dedupe_headers(expanded)


def _max_data_column_index(non_empty_rows, header_row_number: int) -> int:
    max_idx = 0
    for row_number, cells in non_empty_rows:
        if row_number <= header_row_number:
            continue
        for idx, cell in enumerate(cells):
            if cell.value is not None and str(cell.value).strip() != "":
                max_idx = max(max_idx, idx)
    return max_idx


def _select_header_row(non_empty_rows, header_keys: HeaderKeys | None):
    if not non_empty_rows:
        return None
    if not header_keys:
        row_number, cells = non_empty_rows[0]
        return row_number, cells, _headers_from_cells(cells)
    scan_limit = min(len(non_empty_rows), 50)
    candidates = [
        (row_number, cells, _headers_from_cells(cells))
        for row_number, cells in non_empty_rows[:scan_limit]
    ]
    best = max(candidates, key=lambda candidate: _header_score(candidate[2], header_keys))
    if _header_score(best[2], header_keys)[0] > 0:
        return best
    row_number, cells = non_empty_rows[0]
    return row_number, cells, _headers_from_cells(cells)


def _row_has_data(display_values: dict) -> bool:
    return any(
        value is not None and str(value).strip() != ""
        for value in display_values.values()
    )


def _read_worksheet_rows_with_metadata(
    worksheet,
    header_keys: HeaderKeys | None,
    *,
    expand_columns: bool = False,
) -> tuple[list[dict], list[dict]]:
    if worksheet is None:
        return [], []
    non_empty_rows = [
        (row_number, cells)
        for row_number, cells in enumerate(worksheet.iter_rows(), start=1)
        if cells and any(cell.value is not None for cell in cells)
    ]
    selected = _select_header_row(non_empty_rows, header_keys)
    if not selected:
        return [], []
    header_row_number, _header_cells, headers = selected
    if expand_columns:
        max_col = _max_data_column_index(non_empty_rows, header_row_number)
        headers = _expand_headers_to_width(headers, max_col)

    records: list[dict] = []
    for row_number, cells in non_empty_rows:
        if row_number <= header_row_number:
            continue
        values = {
            header["key"]: cells[header["index"]].value
            if header["index"] < len(cells) else None
            for header in headers
        }
        display_values = {
            header["key"]: _display_value(cells[header["index"]].value)
            if header["index"] < len(cells) else None
            for header in headers
        }
        if not _row_has_data(display_values):
            continue
        records.append(
            {
                "excel_row_number": row_number,
                "values": values,
                "display_values": display_values,
            }
        )
    return headers, records


def _sheet_selection_score(
    headers: list[dict],
    records: list[dict],
    header_keys: HeaderKeys | None,
) -> tuple[int, int, int]:
    matches, header_count = _header_score(headers, header_keys)
    return (matches, len(records), header_count)


def score_make_list_sheet(
    headers: list[dict],
    records: list[dict],
    sheet_name: str = "",
) -> tuple[int, int, int, int]:
    """
    Rank worksheets for make-list extraction.

    Prefers sheets named like MAKE LIST and headers with approved makes /
    manufacturer columns. Penalizes rate/amount/BOQ analysis sheets and does
    **not** prefer larger row counts (that selected wrong DMRC sheets before).
    """
    name = re.sub(r"[^0-9a-zA-Z]+", " ", (sheet_name or "").lower()).strip()
    header_blob = " ".join(
        f"{(h.get('key') or '')} {(h.get('label') or '')}".lower() for h in headers
    )

    score = 0
    if "make list" in name or name in {"makes", "make", "approved makes"}:
        score += 200
    elif "make" in name:
        score += 80

    make_header_hits = 0
    for token in (
        "approved_makes",
        "approved make",
        "manufacturer",
        "manufacturers",
        "make_manufacturers",
    ):
        if token in header_blob:
            make_header_hits += 1
            score += 60
    if re.search(r"\bmake\b|\bmakes\b|\bbrand\b", header_blob):
        make_header_hits += 1
        score += 40
    if "description" in header_blob or "material" in header_blob:
        score += 20
    if any(hint in header_blob for hint in ("s_no", "s. no", "sl_no", "serial")):
        score += 10

    # Rate / estimate sheets dominate many client workbooks — demote them.
    for bad in (
        "rate",
        "amount",
        "analysis",
        "dmrc",
        "discount",
        "qty",
        "quantity",
        "boq format",
        "packing",
        "freight",
    ):
        if bad in header_blob:
            score -= 35
        if bad in name:
            score -= 50

    # Prefer compact make lists over giant analysis sheets.
    row_count = len(records)
    if 5 <= row_count <= 250:
        score += 25
    elif row_count > 250:
        score -= min(120, row_count // 5)

    # Content signal: cells that look like slash-separated makes.
    make_like = 0
    checked = 0
    for record in records[:40]:
        values = record.get("display_values") or {}
        for value in values.values():
            text = str(value or "").strip()
            if not text:
                continue
            checked += 1
            if "/" in text and 1 <= len(text.split("/")) <= 8 and len(text) < 120:
                make_like += 1
            elif 1 <= len(text.split()) <= 3 and text[:1].isalpha() and len(text) < 40:
                make_like += 0.25
    if checked:
        score += int(40 * (make_like / checked))

    # Tie-breakers: more make-header hits, then fewer rows, then fewer columns.
    return (score, make_header_hits, -row_count, -len(headers))


def _merge_headers(header_sets: list[list[dict]]) -> list[dict]:
    """Union headers by key, preserving first-seen order and labels."""
    merged: list[dict] = []
    seen: set[str] = set()
    for headers in header_sets:
        for header in headers:
            key = header.get("key") or ""
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(
                {
                    "key": key,
                    "label": header.get("label") or key,
                    "index": len(merged),
                }
            )
    return merged


def read_rows_with_metadata(
    file_path: str | Path,
    sheet_name: str | None = None,
    header_keys: HeaderKeys | None = None,
    *,
    expand_columns: bool = False,
    merge_matching_sheets: bool = False,
    min_header_matches: int = 2,
    sheet_score_fn=None,
) -> tuple[list[dict], list[dict]]:
    """Read rows with original header labels and worksheet row numbers.

    Returns ``(headers, records)`` where headers are ``{key, label}`` dicts and
    records include raw ``values``, ``display_values`` and ``excel_row_number``.
    Fully empty rows are skipped, but blank cells inside captured rows are
    preserved. When ``sheet_name`` is omitted, every worksheet is scored and the
    best match for ``header_keys`` is used.

    When ``merge_matching_sheets`` is True, all worksheets scoring at least
    ``min_header_matches`` header hits (or matching the best sheet's score floor)
    are concatenated; each record is tagged with ``sheet_name``.

    ``sheet_score_fn(headers, records, sheet_name)`` may override default scoring
    (used by make-list parsing to prefer the MAKE LIST sheet).
    """
    with openxml_workbook_path(file_path) as workbook_path:
        workbook = load_workbook(filename=workbook_path, read_only=True, data_only=True)
        try:
            if sheet_name:
                worksheet = workbook[sheet_name]
                headers, records = _read_worksheet_rows_with_metadata(
                    worksheet,
                    header_keys,
                    expand_columns=expand_columns,
                )
                for record in records:
                    record.setdefault("sheet_name", sheet_name)
                return headers, records

            scored: list[tuple[tuple, str, list[dict], list[dict]]] = []
            for worksheet in workbook.worksheets:
                headers, records = _read_worksheet_rows_with_metadata(
                    worksheet,
                    header_keys,
                    expand_columns=expand_columns,
                )
                if sheet_score_fn is not None:
                    score = sheet_score_fn(headers, records, worksheet.title)
                else:
                    score = _sheet_selection_score(headers, records, header_keys)
                scored.append((score, worksheet.title, headers, records))

            if not scored:
                return [], []

            scored.sort(key=lambda item: item[0], reverse=True)
            best_score, best_name, best_headers, best_records = scored[0]

            if not merge_matching_sheets:
                for record in best_records:
                    record.setdefault("sheet_name", best_name)
                return best_headers, best_records

            # Merge every sheet that looks like a BOQ table (default scorer only).
            selected = []
            for score, name, headers, records in scored:
                matches = score[0] if isinstance(score, tuple) else 0
                if matches >= min_header_matches or score == best_score:
                    if records:
                        selected.append((score, name, headers, records))
            if not selected:
                selected = [scored[0]]

            merged_headers = _merge_headers(
                [headers for *_, headers, _records in selected]
            )
            merged_records: list[dict] = []
            for _score, name, _headers, records in selected:
                for record in records:
                    tagged = {**record, "sheet_name": name}
                    merged_records.append(tagged)
            return merged_headers, merged_records
        finally:
            workbook.close()


def read_rows(file_path: str | Path, sheet_name: str | None = None) -> list[dict]:
    """Read a worksheet into a list of {normalized_header: value} dicts.

    The first non-empty row is treated as the header. Fully empty rows are
    skipped. When ``sheet_name`` is None the active (first) worksheet is used.
    Uses openpyxl only (no pandas) so it installs cleanly everywhere.
    """
    _, records = read_rows_with_metadata(file_path, sheet_name=sheet_name)
    return [record["values"] for record in records]
