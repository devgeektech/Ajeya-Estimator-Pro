"""Export priced BOQ workbook: original BOQ sheet or client Review sheet."""
from __future__ import annotations

import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Any

from django.core.files.storage import default_storage
from django.db import transaction
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from apps.boq.models import BOQ
from apps.boq.services.boq_files import upload_basename
from apps.boq.services.boq_price_calculation_service import (
    build_row_pricing,
    unmatched_qty_row_ids,
)
from apps.boq.services.boq_review_display_service import (
    REVIEW_OUTPUT_HEADER_SPECS,
    REVIEW_OUTPUT_HEADERS,
    BOQReviewDisplayService,
    review_output_values,
    _ordered_boq_rows,
)
from apps.boq.services.serial_normalizer import cell_value
from common.choices import BOQStatus

logger = logging.getLogger("boq_ai")

EXPORT_KIND_BOQ = "boq"
EXPORT_KIND_REVIEW = "review"
_EXPORT_KINDS = {EXPORT_KIND_BOQ, EXPORT_KIND_REVIEW}

_BOQ_SHEET_TITLE = "BOQ"
_REVIEW_SHEET_TITLE = "Review"

# Django FileField collision suffix: original_AbCdEfG.xlsx
_DJANGO_COLLISION_SUFFIX = re.compile(r"_[a-zA-Z0-9]{7}$")
_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n]+')

_RATE_KEYS = ("rate", "unit_rate", "price")
_AMOUNT_KEYS = ("amount", "total", "total_amount", "amt")
_QTY_KEYS = ("qty", "quantity", "qnty", "nos")
_UNIT_KEYS = ("unit", "uom")
_UNMATCHED_STATUSES = frozenset({"unmatched", "pending", "not_searched", "no_match"})

_DARK_BORDER = Border(
    left=Side(style="thin", color="000000"),
    right=Side(style="thin", color="000000"),
    top=Side(style="thin", color="000000"),
    bottom=Side(style="thin", color="000000"),
)
_CELL_ALIGNMENT = Alignment(horizontal="left", vertical="top", wrap_text=True)
_HEADER_FONT = Font(bold=True)
_RED_HEADER_FONT = Font(bold=True, color="FFFF0000")
_MISSING_PRODUCT_FILL = PatternFill(
    start_color="FFFFC7CE",
    end_color="FFFFC7CE",
    fill_type="solid",
)
# Zero-qty / Rate Only rows on BOQ result and Review exports.
_ZERO_OR_RATE_ONLY_FILL = PatternFill(
    start_color="FFFCE4D6",
    end_color="FFFCE4D6",
    fill_type="solid",
)


def _header_keys(
    headers: list[dict[str, Any]],
) -> tuple[str | None, str | None, str | None, str | None]:
    """Resolve Rate/Amount/Qty/Unit keys — including labels like ``RATE (Rs.)``."""
    rate_key = amount_key = qty_key = unit_key = None
    for header in headers:
        key = str(header.get("key") or "").lower()
        if not rate_key and key in _RATE_KEYS:
            rate_key = header["key"]
        if not amount_key and key in _AMOUNT_KEYS:
            amount_key = header["key"]
        if not qty_key and key in _QTY_KEYS:
            qty_key = header["key"]
        if not unit_key and key in _UNIT_KEYS:
            unit_key = header["key"]

    # Client workbooks often use rate_rs / amount_rs (from ``RATE (Rs.)``).
    for header in headers:
        key = str(header.get("key") or "")
        label = str(header.get("label") or "").replace("\n", " ")
        blob = f"{key} {label}".casefold()
        if not rate_key and "rate" in blob and "amount" not in key.casefold():
            rate_key = key or header.get("key")
        if not amount_key and "amount" in blob:
            amount_key = key or header.get("key")
        if not qty_key and any(token in blob for token in ("qty", "quantity", "qnty")):
            qty_key = key or header.get("key")
        if not unit_key and (
            key.casefold() in _UNIT_KEYS or blob.strip() in {"unit", "uom"}
        ):
            unit_key = key or header.get("key")
    return rate_key, amount_key, qty_key, unit_key


def _header_excel_column(headers: list[dict[str, Any]], key: str | None) -> int | None:
    if not key:
        return None
    for header in headers:
        if header.get("key") != key:
            continue
        try:
            return int(header["index"]) + 1
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _is_zero_qty(value: Any) -> bool:
    """True for numeric zero quantities (0 / 0.0 / '0')."""
    if value in (0, 0.0, "0", "0.0"):
        return True
    try:
        return float(str(value).strip().replace(",", "")) == 0.0
    except (TypeError, ValueError):
        return False


def _excel_qty_value(value: Any) -> Any:
    """Prefer a numeric qty for Excel (replace SUM formulas with the resolved value)."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = str(value).strip()
    if not text:
        return None
    cleaned = text.replace(",", "")
    try:
        number = float(cleaned)
    except ValueError:
        return text
    if number.is_integer():
        return int(number)
    return number


def _excel_number_value(value: Any) -> Any:
    """Write Rate/Amount as real numbers so Excel does not treat them as text/formulas."""
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return None
        return value
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        # Never write a leading '=' string as a broken formula.
        if text.startswith("="):
            return text.lstrip("=")
        return text
    if number != number or number in (float("inf"), float("-inf")):
        return None
    if number.is_integer():
        return int(number)
    return number


def _sanitize_workbook_for_excel(workbook) -> None:
    """
    Strip parts that openpyxl often corrupts on round-trip of client BOQs.

    Client uploads (AutoCAD / older Excel) carry dozens of defined names and
    external links. After load/save many become ``#REF!``, which makes Excel
    show “We found a problem with some content…”. Export only needs filled
    Qty/Rate/Amount values, so drop those workbook extras.
    """
    try:
        workbook.defined_names = type(workbook.defined_names)()
    except Exception:
        try:
            for name in list(workbook.defined_names.keys()):
                del workbook.defined_names[name]
        except Exception:
            logger.exception("Failed clearing defined names on BOQ export")

    # External links are not required on the priced result sheet.
    for attr in ("_external_links", "external_links"):
        if hasattr(workbook, attr):
            try:
                setattr(workbook, attr, [])
            except Exception:
                pass


def _zero_or_rate_only_row_ids(
    display: dict[str, Any],
    *,
    boq_data: dict[str, Any] | None = None,
) -> set[str]:
    """BOQ qty-row ids that are zero quantity or Rate Only (orange highlight)."""
    from apps.boq.services.boq_row_grouping_service import grouped_anchor_rows

    ids: set[str] = set()
    for line in display.get("lines") or []:
        for product in line.get("products") or []:
            target = str(
                product.get("qty_row_id")
                or product.get("source_row_id")
                or line.get("row_id")
                or ""
            ).strip()
            if not target:
                continue
            qty = (
                product.get("qty")
                if product.get("qty") not in (None, "")
                else product.get("quantity")
            )
            if bool(product.get("rate_only")) or _is_zero_qty(qty):
                ids.add(target)

    for group in grouped_anchor_rows(boq_data or {}):
        for slot in group.get("slots") or group.get("qty_rows") or []:
            slot_id = str(slot.get("qty_row_id") or slot.get("row_id") or "").strip()
            if not slot_id:
                continue
            status = str(slot.get("qty_status") or "").strip().lower()
            if (
                status in {"zero", "rate_only"}
                or bool(slot.get("rate_only"))
                or _is_zero_qty(slot.get("qty"))
            ):
                ids.add(slot_id)
    return ids


def _product_is_unmatched(product: dict[str, Any]) -> bool:
    status = str(product.get("status") or "").strip().lower()
    line_output = product.get("line_output") or {}
    if status in _UNMATCHED_STATUSES:
        return True
    if line_output.get("is_blank") and status != "matched":
        return True
    if status != "matched":
        return True
    return False


def _product_is_zero_or_rate_only(product: dict[str, Any]) -> bool:
    qty = (
        product.get("qty")
        if product.get("qty") not in (None, "")
        else product.get("quantity")
    )
    return bool(product.get("rate_only")) or _is_zero_qty(qty)


def _highlight_row(
    sheet: Worksheet,
    row_number: int,
    *,
    max_column: int | None = None,
    fill: PatternFill | None = None,
) -> None:
    paint = fill or _MISSING_PRODUCT_FILL
    last_col = max_column or sheet.max_column or 1
    for col_idx in range(1, int(last_col) + 1):
        sheet.cell(row=row_number, column=col_idx).fill = paint


def _style_cell(cell) -> None:
    cell.alignment = _CELL_ALIGNMENT
    cell.border = _DARK_BORDER


def _style_used_range(
    sheet: Worksheet,
    *,
    skip_blank_rows: bool = True,
    red_header_columns: set[int] | None = None,
) -> None:
    """Apply top/right wrap alignment and dark borders to used cells."""
    if sheet.max_row is None or sheet.max_column is None:
        return
    red_cols = red_header_columns or set()
    for row_idx in range(1, sheet.max_row + 1):
        row_cells = list(sheet[row_idx])
        if skip_blank_rows and all(cell.value in (None, "") for cell in row_cells):
            continue
        for cell in row_cells:
            _style_cell(cell)
        if row_idx == 1:
            for col_idx, cell in enumerate(row_cells, start=1):
                cell.font = _RED_HEADER_FONT if col_idx in red_cols else _HEADER_FONT


def _autosize_columns(sheet: Worksheet, *, min_width: int = 10, max_width: int = 42) -> None:
    if sheet.max_column is None:
        return
    for col_idx in range(1, sheet.max_column + 1):
        letter = get_column_letter(col_idx)
        longest = 0
        for cell in sheet[letter]:
            if cell.value is None:
                continue
            longest = max(longest, min(max_width, len(str(cell.value))))
        sheet.column_dimensions[letter].width = max(min_width, longest + 2)


def _resolve_uploaded_path(uploaded_file) -> str | None:
    if not uploaded_file:
        return None
    try:
        if hasattr(uploaded_file, "path"):
            path = str(uploaded_file.path)
            if path and Path(path).is_file():
                return path
    except Exception:
        pass
    name = getattr(uploaded_file, "name", None)
    if not name:
        return None
    try:
        path = default_storage.path(name)
    except Exception:
        return None
    return path if path and Path(path).is_file() else None


def _export_stem_from_upload(boq: BOQ) -> str:
    """Base download name from the uploaded BOQ workbook (not the BOQ title)."""
    source = str((boq.boq_data or {}).get("source_filename") or "").strip()
    if not source and getattr(boq, "uploaded_file", None):
        source = upload_basename(boq.uploaded_file)
    stem = Path(source).stem if source else ""
    if stem:
        stem = _DJANGO_COLLISION_SUFFIX.sub("", stem)
    if not stem:
        stem = str(boq.boq_name or "").strip() or "boq"
    stem = _UNSAFE_FILENAME_CHARS.sub("_", stem).strip(" ._")
    return stem or "boq"


def _export_download_filename(boq: BOQ, kind: str) -> str:
    """
    Download names mirror the uploaded workbook:

    - BOQ export: ``{upload}_result.xlsx``
    - Review export: ``{upload}_review result sheet.xlsx``
    """
    stem = _export_stem_from_upload(boq)
    if kind == EXPORT_KIND_BOQ:
        return f"{stem}_result.xlsx"
    return f"{stem}_review result sheet.xlsx"


class BOQExportService:
    """Write either the priced original BOQ sheet or the client Review sheet."""

    def __init__(self, boq_id: int, confirmations: dict[str, dict[str, Any]] | None = None):
        self.boq_id = boq_id
        self.confirmations = confirmations or {}

    def run(self, kind: str = EXPORT_KIND_REVIEW) -> tuple[bytes, str]:
        kind = str(kind or EXPORT_KIND_REVIEW).strip().lower()
        if kind not in _EXPORT_KINDS:
            raise ValueError("Export kind must be 'review' or 'boq'.")

        boq = BOQ.objects.get(pk=self.boq_id)
        analysis = boq.analysis_data or {}
        if boq.status not in {BOQStatus.READY_EXPORT, BOQStatus.EXPORTED} and not analysis.get(
            "pricing_ready"
        ):
            raise ValueError("Finish Labour (Next to Review) before exporting.")

        display = BOQReviewDisplayService(boq, self.confirmations).build()
        if not display.get("has_analysis"):
            raise ValueError("Complete Make & Vendor and Labour before exporting.")

        # Always rebuild from live Review display so Rate/Amount land on qty rows.
        pricing = build_row_pricing(display)
        boq_data = boq.boq_data or {}
        highlight_ids = unmatched_qty_row_ids(display, boq_data=boq_data)
        orange_ids = _zero_or_rate_only_row_ids(display, boq_data=boq_data)
        filename = _export_download_filename(boq, kind)

        if kind == EXPORT_KIND_BOQ:
            payload = self._export_boq_workbook(
                boq,
                boq_data,
                pricing,
                highlight_ids,
                orange_ids,
            )
            audit_label = "Exported BOQ sheet"
        else:
            workbook = Workbook()
            sheet = workbook.active
            if sheet is None:
                sheet = workbook.create_sheet(_REVIEW_SHEET_TITLE)
            else:
                sheet.title = _REVIEW_SHEET_TITLE
            self._write_review_sheet(
                sheet,
                display,
                boq_data,
                orange_ids=orange_ids,
            )
            buffer = BytesIO()
            workbook.save(buffer)
            payload = buffer.getvalue()
            audit_label = "Exported Review sheet"

        with transaction.atomic():
            if boq.status != BOQStatus.EXPORTED:
                boq.status = BOQStatus.EXPORTED
                boq.save(update_fields=["status"])

        logger.info("Exported BOQ id=%s kind=%s (%s)", boq.pk, kind, filename)
        from apps.audit.services import record
        from apps.notifications.services import notify

        record(getattr(boq, "user", None), audit_label, "BOQ", boq.boq_name)
        notify(
            getattr(boq, "user", None),
            "BOQ exported",
            f"BOQ '{boq.boq_name}' was exported as {filename}.",
        )
        return payload, filename

    def _export_boq_workbook(
        self,
        boq: BOQ,
        boq_data: dict[str, Any],
        pricing: dict[str, dict[str, Any]],
        highlight_ids: set[str],
        orange_ids: set[str] | None = None,
    ) -> bytes:
        """Prefer the original upload layout; fall back to a rebuilt sheet."""
        orange_ids = orange_ids or set()
        path = _resolve_uploaded_path(boq.uploaded_file)
        if path:
            try:
                return self._fill_original_boq_workbook(
                    path,
                    boq_data,
                    pricing,
                    highlight_ids,
                    orange_ids,
                )
            except Exception:
                logger.exception(
                    "Original BOQ fill failed for id=%s; rebuilding from JSON",
                    boq.pk,
                )

        workbook = Workbook()
        sheet = workbook.active
        if sheet is None:
            sheet = workbook.create_sheet(_BOQ_SHEET_TITLE)
        else:
            sheet.title = _BOQ_SHEET_TITLE
        self._write_boq_sheet(sheet, boq_data, pricing, highlight_ids, orange_ids)
        buffer = BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    def _fill_original_boq_workbook(
        self,
        path: str,
        boq_data: dict[str, Any],
        pricing: dict[str, dict[str, Any]],
        highlight_ids: set[str],
        orange_ids: set[str] | None = None,
    ) -> bytes:
        """Copy the uploaded workbook and write Qty/Rate/Amount on qty+unit rows."""
        orange_ids = orange_ids or set()
        # keep_links=False avoids broken external-link XML that Excel must repair.
        workbook = load_workbook(path, keep_links=False)
        headers = list(boq_data.get("headers") or [])
        rate_key, amount_key, qty_key, unit_key = _header_keys(headers)
        rate_col = _header_excel_column(headers, rate_key)
        amount_col = _header_excel_column(headers, amount_key)
        qty_col = _header_excel_column(headers, qty_key)
        if rate_col is None and amount_col is None and qty_col is None:
            raise ValueError("Uploaded BOQ has no Qty, Rate, or Amount column to fill.")

        sheets_by_name = {name: workbook[name] for name in workbook.sheetnames}
        default_sheet = workbook.active
        used_columns = max((int(h.get("index") or 0) + 1 for h in headers), default=1)

        for row in boq_data.get("rows") or []:
            row_id = str(row.get("row_id") or "")
            excel_row = row.get("excel_row_number")
            try:
                excel_row_number = int(excel_row)
            except (TypeError, ValueError):
                continue
            if excel_row_number < 1:
                continue

            sheet_name = str(row.get("sheet_name") or "").strip()
            sheet = sheets_by_name.get(sheet_name) if sheet_name else None
            if sheet is None:
                sheet = default_sheet
            if sheet is None:
                continue

            qty_value = cell_value(row, qty_key) if qty_key else None
            unit_value = cell_value(row, unit_key) if unit_key else None
            has_qty = _is_filled(qty_value)
            has_unit = (not unit_key) or _is_filled(unit_value)
            can_price = has_qty and has_unit

            if can_price:
                # Write resolved qty so the QTY column shows a number (not only
                # a floor SUM formula that may look blank until Excel calculates).
                if qty_col is not None:
                    written_qty = _excel_qty_value(qty_value)
                    if written_qty is not None:
                        sheet.cell(
                            row=excel_row_number,
                            column=qty_col,
                            value=written_qty,
                        )
                priced = pricing.get(row_id)
                if priced:
                    if rate_col is not None and priced.get("rate") not in (None, ""):
                        sheet.cell(
                            row=excel_row_number,
                            column=rate_col,
                            value=_excel_number_value(priced.get("rate")),
                        )
                    if amount_col is not None and priced.get("amount") not in (None, ""):
                        sheet.cell(
                            row=excel_row_number,
                            column=amount_col,
                            value=_excel_number_value(priced.get("amount")),
                        )

            if can_price and row_id in orange_ids:
                _highlight_row(
                    sheet,
                    excel_row_number,
                    max_column=used_columns,
                    fill=_ZERO_OR_RATE_ONLY_FILL,
                )
            elif can_price and row_id in highlight_ids:
                _highlight_row(sheet, excel_row_number, max_column=used_columns)

        _sanitize_workbook_for_excel(workbook)
        buffer = BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    @staticmethod
    def _write_boq_sheet(
        sheet: Worksheet,
        boq_data: dict[str, Any],
        pricing: dict[str, dict[str, Any]],
        highlight_ids: set[str],
        orange_ids: set[str] | None = None,
    ) -> None:
        """Fallback rebuild when the original workbook cannot be loaded."""
        orange_ids = orange_ids or set()
        headers = boq_data.get("headers") or []
        rate_key, amount_key, qty_key, unit_key = _header_keys(headers)
        sheet.append([header.get("label") or header.get("key") or "" for header in headers])
        highlight_sheet_rows: list[tuple[int, PatternFill]] = []

        for row in boq_data.get("rows") or []:
            row_id = str(row.get("row_id") or "")
            row_values: dict[str, Any] = {}
            for header in headers:
                key = header.get("key")
                if not key:
                    continue
                row_values[key] = cell_value(row, key)

            qty_value = row_values.get(qty_key) if qty_key else None
            unit_value = row_values.get(unit_key) if unit_key else None
            can_price = _is_filled(qty_value) and (
                not unit_key or _is_filled(unit_value)
            )
            if can_price and qty_key:
                written_qty = _excel_qty_value(qty_value)
                if written_qty is not None:
                    row_values[qty_key] = written_qty
            priced = pricing.get(row_id) if can_price else None
            if priced:
                if rate_key:
                    row_values[rate_key] = priced.get("rate")
                if amount_key:
                    row_values[amount_key] = priced.get("amount")

            sheet.append([row_values.get(header.get("key")) for header in headers])
            if can_price and row_id in orange_ids:
                highlight_sheet_rows.append((sheet.max_row, _ZERO_OR_RATE_ONLY_FILL))
            elif can_price and row_id in highlight_ids:
                highlight_sheet_rows.append((sheet.max_row, _MISSING_PRODUCT_FILL))

        for row_number, fill in highlight_sheet_rows:
            _highlight_row(
                sheet,
                row_number,
                max_column=len(headers) or 1,
                fill=fill,
            )

        _style_used_range(sheet, skip_blank_rows=True)
        _autosize_columns(sheet)

    @staticmethod
    def _write_review_sheet(
        sheet: Worksheet,
        display: dict[str, Any],
        boq_data: dict[str, Any] | None = None,
        *,
        orange_ids: set[str] | None = None,
    ) -> None:
        orange_ids = orange_ids or set()
        sheet.append(list(REVIEW_OUTPUT_HEADERS))
        col_count = len(REVIEW_OUTPUT_HEADERS)
        red_header_columns = {
            index
            for index, (_label, is_red) in enumerate(REVIEW_OUTPUT_HEADER_SPECS, start=1)
            if is_red
        }
        lines = list(display.get("lines") or [])
        lines_by_id = {
            str(line.get("row_id") or ""): line
            for line in lines
            if line.get("row_id")
        }
        products_by_qty: dict[str, list[dict[str, Any]]] = {}
        for line in lines:
            for product in line.get("products") or []:
                qty_id = str(
                    product.get("qty_row_id") or product.get("source_row_id") or ""
                ).strip()
                if qty_id:
                    products_by_qty.setdefault(qty_id, []).append(product)

        def _append_structural(line: dict[str, Any]) -> None:
            empty = [None] * col_count
            empty[0] = line.get("serial")
            empty[1] = line.get("description")
            empty[18] = line.get("qty")
            sheet.append(empty)
            row_id = str(line.get("row_id") or "").strip()
            if row_id and row_id in orange_ids:
                highlight_sheet_rows.append((sheet.max_row, _ZERO_OR_RATE_ONLY_FILL))
            elif _is_zero_qty(line.get("qty")):
                highlight_sheet_rows.append((sheet.max_row, _ZERO_OR_RATE_ONLY_FILL))

        def _append_products(products: list[dict[str, Any]]) -> None:
            for product in products:
                marker = id(product)
                if marker in emitted_products:
                    continue
                emitted_products.add(marker)
                review_row = product.get("review_output") or {}
                sheet.append(review_output_values(review_row))
                target = str(
                    product.get("qty_row_id")
                    or product.get("source_row_id")
                    or product.get("row_id")
                    or ""
                ).strip()
                if _product_is_zero_or_rate_only(product) or (
                    target and target in orange_ids
                ):
                    highlight_sheet_rows.append((sheet.max_row, _ZERO_OR_RATE_ONLY_FILL))
                elif _product_is_unmatched(product):
                    highlight_sheet_rows.append((sheet.max_row, _MISSING_PRODUCT_FILL))

        highlight_sheet_rows: list[tuple[int, PatternFill]] = []
        emitted_products: set[int] = set()
        ordered = _ordered_boq_rows(boq_data or {})
        walk_rows = [
            row for row in ordered if str(row.get("row_id") or "").strip()
        ]
        if not walk_rows:
            walk_rows = [
                {"row_id": line.get("row_id"), "depth": line.get("depth")}
                for line in lines
                if line.get("row_id")
            ]

        prev_depth = None
        for boq_row in walk_rows:
            row_id = str(boq_row.get("row_id") or "")
            line = lines_by_id.get(row_id)
            slot_products = list(products_by_qty.get(row_id) or [])
            try:
                depth = int(
                    (line or {}).get("depth")
                    if line is not None
                    else boq_row.get("depth")
                    or 0
                )
            except (TypeError, ValueError):
                depth = 0
            will_write = bool(slot_products or line)
            # Blank spacer only before real top-level chapter headers.
            if (
                prev_depth is not None
                and depth == 0
                and line is not None
                and not slot_products
                and will_write
            ):
                sheet.append([None] * col_count)
            if will_write:
                prev_depth = depth

            # Qty letter row (a)/b)): write its priced product(s) here.
            if slot_products:
                _append_products(slot_products)
                continue

            if not line:
                continue

            owned = list(line.get("products") or [])
            # Parent item whose products bind to child qty slots — write the
            # BOQ item text first; products appear later on those slot rows.
            child_bound = [
                product
                for product in owned
                if str(
                    product.get("qty_row_id") or product.get("source_row_id") or ""
                ).strip()
                not in {"", row_id}
            ]
            if child_bound:
                _append_structural(line)
                continue

            if owned:
                _append_products(owned)
                continue

            _append_structural(line)

        for row_number, fill in highlight_sheet_rows:
            _highlight_row(sheet, row_number, max_column=col_count, fill=fill)

        _style_used_range(
            sheet,
            skip_blank_rows=True,
            red_header_columns=red_header_columns,
        )
        _autosize_columns(sheet, max_width=36)
