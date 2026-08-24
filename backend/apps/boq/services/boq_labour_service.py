"""Labour charges after Make & Vendor using Labour_master_Output or manual rates."""
from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from common.db import atomic

from apps.boq.models import BOQ
from apps.boq.services.boq_analysis_store import save_boq_analysis_json
from apps.boq.services.boq_extraction_service import (
    quantity_display_fields,
    rehydrate_analysis_rows_quantity,
    rehydrate_products_quantity_from_group,
)
from apps.boq.services.boq_line_output_service import (
    BOQLineOutputService,
    quantity_is_rate_sum_only,
)
from apps.boq.services.boq_row_fields import (
    DESCRIPTION_KEYS as _DESCRIPTION_KEYS,
    QTY_KEYS as _QTY_KEYS,
    UNIT_KEYS as _UNIT_KEYS,
    field_from_map as _field_from_map,
    ordered_boq_rows as _ordered_boq_rows,
    resolve_activity_only,
)
from apps.boq.services.labour_detail_retrieval_service import LabourDetailRetrievalService
from apps.boq.services.serial_normalizer import analysis_fields
from apps.database_manager.services.activation import get_active_database_version
from common.choices import BOQStatus
from common.exceptions import BOQAIError, ValidationError
from utils.json_safe import json_safe
from utils.timestamps import now_local_iso

logger = logging.getLogger("boq_ai")


def _product_id_for_labour(product: dict[str, Any] | None) -> str:
    """Resolve Product_ID for Labour_master_Output (Postgres join; not Chroma)."""
    item = product or {}
    selection = item.get("vendor_selection") or {}
    rate_detail = selection.get("rate_detail") or {}
    # Prefer the captured Analysis / Make & Vendor catalog id on the product
    # itself so a stale vendor_selection cannot keep an old Product_ID.
    for key in (
        "catalog_product_id",
        "product_id",
        "suggested_catalog_product_id",
    ):
        text = str(item.get(key) or "").strip()
        if text:
            return text
    for source in (selection, rate_detail):
        for key in (
            "catalog_product_id",
            "product_id",
            "suggested_catalog_product_id",
        ):
            text = str(source.get(key) or "").strip()
            if text:
                return text
    return ""


def _make_list_payload_for_boq(boq: BOQ) -> dict[str, Any]:
    if not boq.make_list_file:
        return {}
    return dict(boq.make_list_data or {})


def _sync_product_ids_from_analysis(boq_id: int, boq: BOQ) -> dict[str, Any]:
    """Capture latest Analysis Product_IDs before labour load."""
    from apps.boq.services.make_vendor_selection_service import MakeVendorSelectionService

    return MakeVendorSelectionService(
        boq_id,
        _make_list_payload_for_boq(boq),
    ).sync_analysis_product_ids(refresh_rates_if_changed=True)


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _format_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _product_summary(product: dict[str, Any]) -> str:
    parts = [
        str(product.get("category") or "").strip(),
        str(product.get("sub_category") or "").strip(),
        str(product.get("class") or "").strip(),
    ]
    return " / ".join(part for part in parts if part) or (
        str(product.get("description_hint") or "").strip() or "Product"
    )


def _taxonomy_label(product: dict[str, Any]) -> str:
    category = str(product.get("category") or "").strip()
    sub_category = str(product.get("sub_category") or "").strip()
    if category and sub_category:
        return f"{category} / {sub_category}"
    return category or sub_category or "—"


def _has_positive_labour(labour_rate: Any, labour_amount: Any) -> bool:
    """True when labour rate/amount is present and greater than zero."""
    for value in (labour_rate, labour_amount):
        amount = _to_decimal(value)
        if amount is not None and amount > 0:
            return True
    return False


class BOQLabourService:
    """Apply and display labour charges; unlock Review via complete()."""

    def __init__(self, boq_id: int):
        self.boq_id = boq_id

    def unlock(self) -> dict[str, Any]:
        """Make & Vendor → Next: open Labour and load charges by Product_ID."""
        boq = self._get_boq()
        self._ensure_pipeline_editable(boq)
        if not (boq.analysis_data or {}).get("rows"):
            raise ValidationError("Run Analyse and Make & Vendor first.")
        if not (boq.analysis_data or {}).get("make_vendor_defaults_applied") and not any(
            (p.get("vendor_selection") for r in (boq.analysis_data or {}).get("rows") or [] for p in (r.get("products") or []))
        ):
            raise ValidationError("Complete Make & Vendor selections first.")

        # Re-capture Analysis Product_IDs (and rates when an id changed) before labour.
        sync = _sync_product_ids_from_analysis(self.boq_id, boq)
        boq = self._get_boq()

        analysis = dict(boq.analysis_data or {})
        config = dict(analysis.get("labour_config") or {})
        config.setdefault("mode", "auto")
        config.setdefault("category_percentages", {})
        analysis["labour_config"] = config

        with atomic():
            safe = json_safe(analysis)
            save_boq_analysis_json(boq.boq_name, safe)
            boq.analysis_data = safe
            boq.status = BOQStatus.LABOUR
            boq.save(update_fields=["analysis_data", "status"])

        # Load Labour_master_Output amounts from PostgreSQL by Product_ID.
        applied = self.apply_auto(sync_product_ids=False)
        logger.info(
            "Labour unlocked for BOQ id=%s product_ids=%s changed=%s",
            boq.pk,
            sync.get("product_id_count"),
            sync.get("changed_count"),
        )
        return {
            "status": BOQStatus.LABOUR,
            "mode": "auto",
            "synced_product_ids": sync.get("product_ids") or [],
            **{k: v for k, v in applied.items() if k != "status"},
        }

    def apply_auto(self, *, sync_product_ids: bool = True) -> dict[str, Any]:
        """Fill labour from Labour_master_Output by each selected Product_ID."""
        boq = self._get_boq()
        self._ensure_labour_editable(boq)
        if sync_product_ids:
            _sync_product_ids_from_analysis(self.boq_id, boq)
            boq = self._get_boq()
        database_version_id = self._database_version_id(boq)
        if not database_version_id:
            raise ValidationError("No active master database. Upload a database first.")

        labour_service = LabourDetailRetrievalService(database_version_id)
        analysis = dict(boq.analysis_data or {})
        analysis["rows"] = rehydrate_analysis_rows_quantity(
            boq.boq_data or {},
            list(analysis.get("rows") or []),
        )
        rows = list(analysis.get("rows") or [])
        boq_by_id = {
            str(row.get("row_id")): row
            for row in _ordered_boq_rows(boq.boq_data or {})
            if row.get("row_id")
        }

        updated = 0
        with_labour = 0
        missing = 0
        for row in rows:
            products = list(row.get("products") or [])
            if not products:
                continue
            row_id = str(row.get("row_id") or "")
            qty = _field_from_map(analysis_fields(boq_by_id.get(row_id) or {}), _QTY_KEYS)
            changed = False
            for index, product in enumerate(products):
                selection = dict(product.get("vendor_selection") or {})
                rate_detail = selection.get("rate_detail")
                # Product_ID from Analysis / Make & Vendor (Postgres join key).
                product_id = _product_id_for_labour(
                    {**product, "vendor_selection": selection}
                )
                labour_detail = None
                if product_id:
                    labour_detail = labour_service.get_by_product_id(product_id)
                    selection["product_id"] = product_id
                    selection["catalog_product_id"] = product_id
                # Keep material even when labour is missing.
                line_output = BOQLineOutputService.build(
                    quantity=(
                        product.get("quantity")
                        if product.get("quantity") not in (None, "")
                        else qty
                    ),
                    rate_detail=rate_detail,
                    labour_detail=labour_detail,
                    is_pending=not bool(rate_detail),
                    rate_only=bool(product.get("rate_only")),
                )
                selection["labour_detail"] = labour_detail
                selection["line_output"] = line_output
                updated_product = dict(product)
                updated_product["vendor_selection"] = selection
                if product_id:
                    updated_product["catalog_product_id"] = product_id
                updated_product["labour_mode"] = "auto"
                updated_product["labour_percent"] = None
                products[index] = updated_product
                changed = True
                updated += 1
                if labour_detail and line_output.get("labour_rate"):
                    with_labour += 1
                else:
                    missing += 1
            if changed:
                row["products"] = products

        config = dict(analysis.get("labour_config") or {})
        config["mode"] = "auto"
        config["labour_ready"] = True
        config["applied_at"] = now_local_iso()
        analysis["labour_config"] = config
        analysis["rows"] = rows
        analysis["pricing_ready"] = False
        analysis.pop("row_pricing", None)
        if analysis.get("make_vendor_product_ids") is None:
            analysis["make_vendor_product_ids"] = sorted(
                {
                    str(p.get("catalog_product_id") or "").strip()
                    for r in rows
                    for p in (r.get("products") or [])
                    if str(p.get("catalog_product_id") or "").strip()
                }
            )

        with atomic():
            safe = json_safe(analysis)
            save_boq_analysis_json(boq.boq_name, safe)
            boq.analysis_data = safe
            if boq.status not in {BOQStatus.LABOUR, BOQStatus.READY_EXPORT, BOQStatus.EXPORTED}:
                boq.status = BOQStatus.LABOUR
                boq.save(update_fields=["analysis_data", "status"])
            else:
                # Re-apply clears export readiness until Next.
                if boq.status == BOQStatus.READY_EXPORT:
                    boq.status = BOQStatus.LABOUR
                    boq.save(update_fields=["analysis_data", "status"])
                else:
                    boq.save(update_fields=["analysis_data"])

        logger.info(
            "Labour auto applied boq=%s updated=%s with_labour=%s missing=%s",
            boq.pk,
            updated,
            with_labour,
            missing,
        )
        return {
            "mode": "auto",
            "updated_count": updated,
            "with_labour_count": with_labour,
            "missing_count": missing,
            "labour_ready": True,
        }

    def apply_manual(self, category_percentages: dict[str, Any]) -> dict[str, Any]:
        """Set labour as a percentage of material amount/rate, by category."""
        boq = self._get_boq()
        self._ensure_labour_editable(boq)

        percents: dict[str, Decimal] = {}
        for raw_key, raw_value in (category_percentages or {}).items():
            category = (raw_key or "").strip()
            if not category:
                continue
            value = _to_decimal(raw_value)
            if value is None:
                continue
            if value < 0:
                raise ValidationError(f"Percentage for {category} cannot be negative.")
            percents[category] = value

        if not percents:
            raise ValidationError("Enter at least one category percentage.")

        analysis = dict(boq.analysis_data or {})
        rows = list(analysis.get("rows") or [])
        boq_by_id = {
            str(row.get("row_id")): row
            for row in _ordered_boq_rows(boq.boq_data or {})
            if row.get("row_id")
        }

        updated = 0
        for row in rows:
            products = list(row.get("products") or [])
            if not products:
                continue
            row_id = str(row.get("row_id") or "")
            qty = _field_from_map(analysis_fields(boq_by_id.get(row_id) or {}), _QTY_KEYS)
            changed = False
            for index, product in enumerate(products):
                category = str(product.get("category") or "").strip()
                percent = percents.get(category)
                if percent is None:
                    # Case-insensitive category match.
                    for key, value in percents.items():
                        if key.casefold() == category.casefold():
                            percent = value
                            break
                selection = dict(product.get("vendor_selection") or {})
                rate_detail = selection.get("rate_detail")
                base_line = selection.get("line_output") or {}
                material_rate = _to_decimal(base_line.get("material_rate"))
                if material_rate is None and rate_detail:
                    material_rate = _to_decimal(
                        rate_detail.get("final_material_amount")
                        or rate_detail.get("selection_amount")
                        or rate_detail.get("net_material_rate")
                    )
                product_qty = (
                    product.get("quantity")
                    if product.get("quantity") not in (None, "")
                    else qty
                )
                qty_dec = _to_decimal(product_qty)
                use_rate_sum = quantity_is_rate_sum_only(
                    product_qty,
                    rate_only=bool(product.get("rate_only")),
                )
                material_amount = None
                if use_rate_sum and material_rate is not None:
                    material_amount = material_rate
                elif qty_dec is not None and material_rate is not None:
                    material_amount = qty_dec * material_rate
                elif base_line.get("material_amount") not in (None, ""):
                    material_amount = _to_decimal(base_line.get("material_amount"))

                labour_rate = None
                labour_amount = None
                if percent is not None and material_rate is not None:
                    labour_rate = material_rate * (percent / Decimal("100"))
                if use_rate_sum and labour_rate is not None:
                    labour_amount = labour_rate
                elif percent is not None and material_amount is not None and not use_rate_sum:
                    labour_amount = material_amount * (percent / Decimal("100"))
                elif labour_rate is not None and qty_dec is not None and not use_rate_sum:
                    labour_amount = qty_dec * labour_rate

                total_amount = None
                if material_amount is not None or labour_amount is not None:
                    total_amount = (material_amount or Decimal("0")) + (
                        labour_amount or Decimal("0")
                    )

                line_output = {
                    "quantity": product_qty,
                    "material_rate": _format_decimal(material_rate),
                    "labour_rate": _format_decimal(labour_rate),
                    "labour_components": {
                        "manual_percent": _format_decimal(percent)
                        if percent is not None
                        else None,
                        "note": (
                            f"Manual labour = {percent}% of material"
                            if percent is not None
                            else "No percentage for this category"
                        ),
                    },
                    "material_amount": _format_decimal(material_amount),
                    "labour_amount": _format_decimal(labour_amount),
                    "total_amount": _format_decimal(total_amount),
                    "is_blank": material_rate is None and material_amount is None,
                    "amount_is_rate_sum": use_rate_sum,
                }
                selection["labour_detail"] = {
                    "source": "manual",
                    "percent": _format_decimal(percent) if percent is not None else None,
                    "category": category,
                    "effective_labour_rate": _format_decimal(labour_rate),
                }
                selection["line_output"] = line_output
                updated_product = dict(product)
                updated_product["vendor_selection"] = selection
                updated_product["labour_mode"] = "manual"
                updated_product["labour_percent"] = (
                    float(percent) if percent is not None else None
                )
                products[index] = updated_product
                changed = True
                updated += 1
            if changed:
                row["products"] = products

        stored_percents = {
            key: float(value) for key, value in percents.items()
        }
        config = dict(analysis.get("labour_config") or {})
        config["mode"] = "manual"
        config["category_percentages"] = stored_percents
        config["labour_ready"] = True
        config["applied_at"] = now_local_iso()
        analysis["labour_config"] = config
        analysis["rows"] = rows
        analysis["pricing_ready"] = False
        analysis.pop("row_pricing", None)

        with atomic():
            safe = json_safe(analysis)
            save_boq_analysis_json(boq.boq_name, safe)
            boq.analysis_data = safe
            if boq.status == BOQStatus.READY_EXPORT:
                boq.status = BOQStatus.LABOUR
                boq.save(update_fields=["analysis_data", "status"])
            elif boq.status != BOQStatus.LABOUR:
                boq.status = BOQStatus.LABOUR
                boq.save(update_fields=["analysis_data", "status"])
            else:
                boq.save(update_fields=["analysis_data"])

        logger.info(
            "Labour manual applied boq=%s updated=%s categories=%s",
            boq.pk,
            updated,
            list(stored_percents.keys()),
        )
        return {
            "mode": "manual",
            "updated_count": updated,
            "category_percentages": stored_percents,
            "labour_ready": True,
        }

    def complete(self) -> dict[str, Any]:
        """Labour → Next: aggregate row pricing and unlock Review / export."""
        from apps.boq.services.boq_price_calculation_service import BOQPriceCalculationService

        boq = self._get_boq()
        self._ensure_labour_editable(boq)
        analysis = boq.analysis_data or {}
        config = analysis.get("labour_config") or {}
        if not config.get("labour_ready"):
            raise ValidationError("Apply Auto or Manual labour before continuing.")

        result = BOQPriceCalculationService(boq.pk).run()
        return result

    def build_display(self) -> dict[str, Any]:
        """Shape Labour tab: mode, category %, and per-product labour rows."""
        from apps.boq.services.boq_row_grouping_service import grouped_anchor_rows

        boq = self._get_boq()
        analysis = boq.analysis_data or {}
        config = dict(analysis.get("labour_config") or {})
        mode = str(config.get("mode") or "auto").strip().lower()
        if mode not in {"auto", "manual"}:
            mode = "auto"
        percentages = dict(config.get("category_percentages") or {})

        boq_by_id = {
            str(row.get("row_id")): row
            for row in _ordered_boq_rows(boq.boq_data or {})
            if row.get("row_id")
        }

        group_by_row: dict[str, dict[str, Any]] = {}
        for group in grouped_anchor_rows(boq.boq_data or {}):
            group_by_row[str(group.get("row_id") or "")] = group

        categories: dict[str, int] = {}
        lines: list[dict[str, Any]] = []
        product_count = 0
        with_labour = 0
        missing_labour = 0

        for analysis_row in analysis.get("rows") or []:
            row_id = str(analysis_row.get("row_id") or "")
            if not row_id or analysis_row.get("skip_reason") == "lineage_child_row":
                continue
            boq_row = boq_by_id.get(row_id) or {}
            fields = analysis_fields(boq_row)
            description = _field_from_map(fields, _DESCRIPTION_KEYS) or ""
            group = group_by_row.get(row_id, {})
            products = rehydrate_products_quantity_from_group(
                list(analysis_row.get("products") or []),
                group,
            )
            is_act_only = resolve_activity_only(
                analysis_row,
                products=products,
                units=[
                    group.get("unit"),
                    *[row.get("unit") for row in (group.get("qty_rows") or [])],
                ],
            )
            line_status = "default" if is_act_only else ""

            products_out: list[dict[str, Any]] = []
            for display_number, product in enumerate(products, start=1):
                product_count += 1
                category = str(product.get("category") or "").strip() or "Uncategorised"
                categories[category] = categories.get(category, 0) + 1
                selection = dict(product.get("vendor_selection") or {})
                line_output = selection.get("line_output") or {}
                labour_rate = line_output.get("labour_rate")
                labour_amount = line_output.get("labour_amount")
                material_rate = line_output.get("material_rate")
                product_qty = (
                    product.get("quantity")
                    if product.get("quantity") not in (None, "")
                    else line_output.get("quantity")
                )
                if product_qty in (None, ""):
                    product_qty = _field_from_map(fields, _QTY_KEYS)
                qty_fields = quantity_display_fields(
                    {
                        **product,
                        "quantity": product_qty,
                        "quantity_unit": product.get("quantity_unit")
                        or _field_from_map(fields, _UNIT_KEYS),
                    }
                )
                unit_total = None
                material_dec = _to_decimal(material_rate)
                labour_dec = _to_decimal(labour_rate)
                if material_dec is not None or labour_dec is not None:
                    unit_total = _format_decimal(
                        (material_dec or Decimal("0")) + (labour_dec or Decimal("0"))
                    )
                labour_mode = product.get("labour_mode") or mode
                labour_percent = product.get("labour_percent")
                if labour_mode == "manual" and labour_percent not in (None, ""):
                    mode_label = f"Manual ({labour_percent}%)"
                elif labour_mode == "manual":
                    mode_label = "Manual"
                else:
                    mode_label = "Auto"
                rate_detail = selection.get("rate_detail") or {}
                product_id = _product_id_for_labour(
                    {**product, "vendor_selection": selection}
                ) or None
                tech_key = str(
                    selection.get("tech_key")
                    or rate_detail.get("product_display_key")
                    or rate_detail.get("tech_key")
                    or ""
                ).strip()
                has_labour = _has_positive_labour(labour_rate, labour_amount)
                if has_labour:
                    with_labour += 1
                else:
                    missing_labour += 1
                products_out.append(
                    {
                        "product_index": int(product.get("product_index") or 0),
                        "display_number": display_number,
                        "summary": _product_summary(product),
                        "taxonomy_label": _taxonomy_label(product),
                        "description_hint": product.get("description_hint") or "",
                        "category": category,
                        "sub_category": product.get("sub_category") or "",
                        "class": product.get("class") or "",
                        "size": product.get("size") if product.get("size") is not None else "",
                        "unit": product.get("unit") or "",
                        "capacity": product.get("capacity") or "",
                        "make": selection.get("make")
                        or product.get("selected_make")
                        or "",
                        "vendor": selection.get("vendor")
                        or product.get("selected_vendor")
                        or "",
                        "product_id": product_id,
                        "tech_key": tech_key,
                        "status": selection.get("status") or "not_searched",
                        "labour_mode": labour_mode,
                        "labour_percent": labour_percent,
                        "mode_label": mode_label,
                        **qty_fields,
                        "material_rate": material_rate,
                        "product_rate": material_rate,
                        "material_amount": line_output.get("material_amount"),
                        "labour_rate": labour_rate,
                        "labour_amount": labour_amount,
                        "total_amount": unit_total,
                        "final_amount": line_output.get("total_amount"),
                        "labour_components": line_output.get("labour_components") or {},
                        "notes": selection.get("notes") or "",
                        "has_labour": has_labour,
                        "highlight_no_labour": not has_labour,
                    }
                )
                if is_act_only:
                    products_out = []

            if products_out or is_act_only:
                qty = group.get("qty")
                unit = group.get("unit")
                qty_status = str(group.get("qty_status") or "empty")
                qty_rows = list(group.get("qty_rows") or [])
                if qty in (None, "") and qty_rows:
                    qty = qty_rows[0].get("qty")
                    unit = unit or qty_rows[0].get("unit")
                    qty_status = str(qty_rows[0].get("qty_status") or qty_status)
                if qty in (None, "") and not qty_rows:
                    qty = _field_from_map(fields, _QTY_KEYS)
                    unit = unit or _field_from_map(fields, _UNIT_KEYS)
                show_qty_unit = qty_status in {"numeric", "zero", "rate_only", "multi"} or qty not in (
                    None,
                    "",
                )
                if show_qty_unit and qty in (None, ""):
                    qty_display = "—"
                elif show_qty_unit:
                    qty_display = str(qty)
                else:
                    qty_display = ""
                unit_display = str(unit).strip() if unit not in (None, "") else "—"

                for item in products_out:
                    if item.get("quantity") in (None, ""):
                        item.update(
                            quantity_display_fields(
                                {
                                    "quantity": qty if qty not in (None, "") else "",
                                    "quantity_unit": unit,
                                    "rate_only": False,
                                }
                            )
                        )

                lines.append(
                    {
                        "row_id": row_id,
                        "serial": boq_row.get("serial", ""),
                        "description": group.get("description") or description,
                        "full_description": group.get("full_description") or description,
                        "lineage_parts": group.get("lineage_parts") or [],
                        "lineage_count": int(group.get("lineage_count") or 1),
                        "slot_count": int(group.get("slot_count") or 0),
                        "qty": qty,
                        "unit": unit,
                        "qty_display": qty_display,
                        "unit_display": unit_display,
                        "show_qty_unit": show_qty_unit,
                        "product_count": len(products_out),
                        "is_activity_only": is_act_only,
                        "line_status": line_status,
                        "products": products_out,
                    }
                )

        category_rows = [
            {
                "category": name,
                "product_count": count,
                "percent": percentages.get(name, ""),
            }
            for name, count in sorted(categories.items(), key=lambda item: item[0].lower())
        ]
        category_percents = {
            name: str(percentages.get(name, "") or "")
            for name in categories
        }

        return {
            "has_products": len(lines) > 0 or bool(analysis.get("rows")),
            "mode": mode,
            "labour_ready": bool(config.get("labour_ready")),
            "applied_at": config.get("applied_at") or "",
            "category_rows": category_rows,
            "category_percents_json": json.dumps(category_percents),
            "lines": lines,
            "stats": {
                "product_count": product_count,
                "with_labour_count": with_labour,
                "missing_labour_count": missing_labour,
                "category_count": len(category_rows),
            },
        }

    def _database_version_id(self, boq: BOQ) -> int:
        stored = int((boq.analysis_data or {}).get("database_version_id") or 0)
        if stored:
            return stored
        active = get_active_database_version()
        return active.pk if active else 0

    def _get_boq(self) -> BOQ:
        try:
            return BOQ.objects.get(pk=self.boq_id)
        except BOQ.DoesNotExist as exc:
            raise BOQAIError(f"BOQ id={self.boq_id} not found.") from exc

    @staticmethod
    def _ensure_pipeline_editable(boq: BOQ) -> None:
        if boq.status in {BOQStatus.PROCESSING, BOQStatus.MATCHING}:
            raise ValidationError("Wait for the current job to finish.")

    @staticmethod
    def _ensure_labour_editable(boq: BOQ) -> None:
        if boq.status in {BOQStatus.PROCESSING, BOQStatus.MATCHING}:
            raise ValidationError("Wait for the current job to finish.")
        if boq.status not in {
            BOQStatus.MAKE_VENDOR,
            BOQStatus.LABOUR,
            BOQStatus.READY_EXPORT,
            BOQStatus.EXPORTED,
            BOQStatus.PROCESSED,
        }:
            raise ValidationError("Open Labour from Make & Vendor first.")
        if not (boq.analysis_data or {}).get("rows"):
            raise ValidationError("Run Analyse first.")
