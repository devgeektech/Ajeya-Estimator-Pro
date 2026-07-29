"""Labour charges after Make & Vendor — Auto (Labour_Master) or Manual (% of material)."""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction

from apps.boq.models import BOQ
from apps.boq.services.boq_analysis_store import save_boq_analysis_json
from apps.boq.services.boq_line_output_service import BOQLineOutputService
from apps.boq.services.labour_detail_retrieval_service import LabourDetailRetrievalService
from apps.boq.services.serial_normalizer import analysis_fields
from apps.database_manager.services.activation import get_active_database_version
from common.choices import BOQStatus
from common.exceptions import BOQAIError, ValidationError
from utils.json_safe import json_safe
from utils.timestamps import now_local_iso

logger = logging.getLogger("boq_ai")

_QTY_KEYS = ("qty", "quantity", "qnty", "nos")
_UNIT_KEYS = ("unit", "uom")
_DESCRIPTION_KEYS = ("description", "item_description", "particulars", "item")


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


def _field_from_map(fields: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = fields.get(key)
        if value not in (None, ""):
            return value
    return None


def _ordered_boq_rows(boq_data: dict) -> list[dict[str, Any]]:
    from apps.boq.services.make_list_constraint_service import walk_rows_tree

    flat_rows = boq_data.get("rows") or []
    if flat_rows:
        return flat_rows
    return walk_rows_tree(boq_data.get("rows_tree") or [])


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
        """Make & Vendor → Next: open Labour tab."""
        boq = self._get_boq()
        self._ensure_pipeline_editable(boq)
        if not (boq.analysis_data or {}).get("rows"):
            raise ValidationError("Run Analyse and Make & Vendor first.")
        if not (boq.analysis_data or {}).get("make_vendor_defaults_applied") and not any(
            (p.get("vendor_selection") for r in (boq.analysis_data or {}).get("rows") or [] for p in (r.get("products") or []))
        ):
            raise ValidationError("Complete Make & Vendor selections first.")

        analysis = dict(boq.analysis_data or {})
        config = dict(analysis.get("labour_config") or {})
        config.setdefault("mode", "auto")
        config.setdefault("category_percentages", {})
        analysis["labour_config"] = config

        with transaction.atomic():
            safe = json_safe(analysis)
            save_boq_analysis_json(boq.boq_name, safe)
            boq.analysis_data = safe
            boq.status = BOQStatus.LABOUR
            boq.save(update_fields=["analysis_data", "status"])

        logger.info("Labour unlocked for BOQ id=%s", boq.pk)
        return {"status": BOQStatus.LABOUR, "mode": config.get("mode") or "auto"}

    def apply_auto(self) -> dict[str, Any]:
        """Fill labour from Labour_Master by each product Tech_Key."""
        boq = self._get_boq()
        self._ensure_labour_editable(boq)
        database_version_id = self._database_version_id(boq)
        if not database_version_id:
            raise ValidationError("No active master database. Upload a database first.")

        labour_service = LabourDetailRetrievalService(database_version_id)
        analysis = dict(boq.analysis_data or {})
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
                tech_key = str(
                    selection.get("tech_key")
                    or (rate_detail or {}).get("tech_key")
                    or ""
                ).strip()
                labour_detail = None
                if tech_key:
                    labour_detail = labour_service.get_by_tech_key(
                        tech_key,
                        size=product.get("size"),
                    )
                is_pending = not rate_detail or selection.get("status") not in {
                    "matched",
                    "pending",
                }
                # Keep material even when labour is missing.
                if rate_detail and selection.get("status") == "matched":
                    is_pending = False
                elif rate_detail:
                    is_pending = False

                line_output = BOQLineOutputService.build(
                    quantity=qty,
                    rate_detail=rate_detail,
                    labour_detail=labour_detail,
                    is_pending=not bool(rate_detail),
                )
                selection["labour_detail"] = labour_detail
                selection["line_output"] = line_output
                updated_product = dict(product)
                updated_product["vendor_selection"] = selection
                updated_product["labour_mode"] = "auto"
                updated_product["labour_percent"] = None
                products[index] = updated_product
                changed = True
                updated += 1
                if labour_detail and line_output.get("labour_rate"):
                    with_labour += 1
                elif tech_key:
                    missing += 1
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

        with transaction.atomic():
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
            category = str(raw_key or "").strip()
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
                        rate_detail.get("final_amount_excl_gst")
                        or rate_detail.get("net_material_rate")
                    )
                qty_dec = _to_decimal(qty)
                material_amount = None
                if qty_dec is not None and material_rate is not None:
                    material_amount = qty_dec * material_rate
                elif base_line.get("material_amount") not in (None, ""):
                    material_amount = _to_decimal(base_line.get("material_amount"))

                labour_rate = None
                labour_amount = None
                if percent is not None and material_rate is not None:
                    labour_rate = material_rate * (percent / Decimal("100"))
                if percent is not None and material_amount is not None:
                    labour_amount = material_amount * (percent / Decimal("100"))
                elif labour_rate is not None and qty_dec is not None:
                    labour_amount = qty_dec * labour_rate

                total_amount = None
                if material_amount is not None or labour_amount is not None:
                    total_amount = (material_amount or Decimal("0")) + (
                        labour_amount or Decimal("0")
                    )

                line_output = {
                    "quantity": qty,
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

        with transaction.atomic():
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
            qty = _field_from_map(fields, _QTY_KEYS)
            unit = _field_from_map(fields, _UNIT_KEYS)
            products_out: list[dict[str, Any]] = []
            for display_number, product in enumerate(
                analysis_row.get("products") or [],
                start=1,
            ):
                product_count += 1
                category = str(product.get("category") or "").strip() or "Uncategorised"
                categories[category] = categories.get(category, 0) + 1
                selection = dict(product.get("vendor_selection") or {})
                line_output = selection.get("line_output") or {}
                labour_rate = line_output.get("labour_rate")
                labour_amount = line_output.get("labour_amount")
                tech_key = str(
                    selection.get("tech_key")
                    or ((selection.get("rate_detail") or {}).get("tech_key") or "")
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
                        "supplier": selection.get("supplier")
                        or product.get("selected_supplier")
                        or "",
                        "tech_key": tech_key,
                        "status": selection.get("status") or "not_searched",
                        "labour_mode": product.get("labour_mode") or mode,
                        "labour_percent": product.get("labour_percent"),
                        "material_rate": line_output.get("material_rate"),
                        "material_amount": line_output.get("material_amount"),
                        "labour_rate": labour_rate,
                        "labour_amount": labour_amount,
                        "total_amount": line_output.get("total_amount"),
                        "labour_components": line_output.get("labour_components") or {},
                        "notes": selection.get("notes") or "",
                        "has_labour": has_labour,
                        "highlight_no_labour": not has_labour,
                    }
                )
            if products_out:
                lines.append(
                    {
                        "row_id": row_id,
                        "serial": boq_row.get("serial", ""),
                        "description": description,
                        "qty": qty,
                        "unit": unit,
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

        return {
            "has_products": product_count > 0,
            "mode": mode,
            "labour_ready": bool(config.get("labour_ready")),
            "applied_at": config.get("applied_at") or "",
            "category_rows": category_rows,
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
        return int(active.pk) if active else 0

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
