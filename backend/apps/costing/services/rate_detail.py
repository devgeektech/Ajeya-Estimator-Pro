"""Rate and labour detail retrieval.

The active workflow copies selected values from Rate_Master and the linked
Labour_Master row. It does not recalculate workbook costing formulas.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal

from utils.text import normalize

from apps.costing.models import RateDetail
from apps.database_manager.models import DatabaseVersion, LabourMaster, LabourStructureSource
from apps.matching.models import ProductMatch

logger = logging.getLogger("boq_ai")

_CENTS = Decimal("0.01")


def _q2(value) -> Decimal:
    return Decimal(value or 0).quantize(_CENTS, rounding=ROUND_HALF_UP)


class RateDetailRetrievalService:
    """Persist selected Rate_Master and Labour_Master fields for matches."""

    @staticmethod
    def _load_context() -> dict:
        version = DatabaseVersion.objects.filter(is_active=True).first()
        if version is None:
            logger.warning("No active database version; labour retrieval unavailable")
            return {"labour_rates": {}, "labour_structures": []}

        labour_rates: dict[str, list[LabourMaster]] = {}
        for row in LabourMaster.objects.filter(database_version=version).order_by(
            "state", "tech_key"
        ):
            labour_rates.setdefault(normalize(row.tech_key), []).append(row)

        return {
            "labour_rates": labour_rates,
            "labour_structures": list(
                LabourStructureSource.objects.filter(database_version=version)
            ),
        }

    @staticmethod
    def _labour_for_product(product, context: dict) -> LabourMaster | None:
        direct = context["labour_rates"].get(normalize(product.tech_key), [])
        if direct:
            return direct[0]

        product_size = str(product.size_mm or "").strip()
        for structure in context["labour_structures"]:
            if normalize(structure.category) != normalize(product.category):
                continue
            if normalize(structure.sub_category) != normalize(product.sub_category):
                continue
            if normalize(structure.unit) and normalize(structure.unit) != normalize(product.unit):
                continue
            if normalize(structure.size) and normalize(structure.size) != normalize(product_size):
                continue
            rows = context["labour_rates"].get(normalize(structure.tech_key), [])
            if rows:
                return rows[0]
        return None

    @staticmethod
    def _rate_contribution(match: ProductMatch) -> Decimal:
        """Return selected rate adjusted only for component quantity basis."""
        if match.product is None or match.review_required:
            return Decimal("0")

        selected_rate = Decimal(match.product.final_amount_excl_gst or 0)
        product_qty = Decimal(match.product_quantity or 1)

        if match.quantity_basis == "per_boq_unit":
            return _q2(selected_rate * product_qty)

        if match.quantity_basis == "total_for_boq_row":
            boq_qty = Decimal(match.boq_item.quantity or 0)
            if boq_qty <= 0:
                match.review_required = True
                match.save(update_fields=["review_required"])
                return Decimal("0")
            return _q2((selected_rate * product_qty) / boq_qty)

        return Decimal("0")

    def retrieve_item(self, match: ProductMatch, context: dict | None = None):
        """Create/update RateDetail for one ProductMatch."""
        if match.product is None:
            RateDetail.objects.filter(product_match=match).delete()
            return None

        context = context or self._load_context()
        product = match.product
        labour = self._labour_for_product(product, context)

        detail, _ = RateDetail.objects.get_or_create(product_match=match)
        detail.labour_master_id = labour.pk if labour else None
        detail.tech_key = product.tech_key
        detail.make = product.make
        detail.supplier = product.supplier
        detail.base_purchase_rate = product.base_purchase_rate
        detail.discount_percent = product.discount_percent
        detail.net_material_rate = product.net_material_rate
        detail.commercial_material_base = product.commercial_material_base
        detail.accessories_value = product.accessories_value
        detail.handling_value = product.handling_value
        detail.wastage_value = product.wastage_value
        detail.subtotal_before_profit = product.subtotal_before_profit
        detail.profit_value = product.profit_value
        detail.final_expenditure = product.final_expenditure
        detail.final_amount_excl_gst = product.final_amount_excl_gst
        detail.margin_percent_on_selling = product.margin_percent_on_selling
        detail.rate_contribution = self._rate_contribution(match)

        if labour:
            detail.labour_type = labour.labour_type
            detail.labour_state = labour.state
            detail.labour_rate_per_unit = labour.labour_rate_per_unit
            detail.total_labour_per_unit = labour.total_labour_per_unit
            detail.total_labour_with_multiplier = labour.total_labour_with_multiplier
        else:
            detail.labour_type = ""
            detail.labour_state = ""
            detail.labour_rate_per_unit = Decimal("0")
            detail.total_labour_per_unit = Decimal("0")
            detail.total_labour_with_multiplier = Decimal("0")

        detail.save()
        return detail

    def retrieve_run(self, run) -> int:
        """Retrieve details for all matched products in a run."""
        context = self._load_context()
        matches = ProductMatch.objects.filter(boq_item__boq_run=run).select_related(
            "product", "boq_item"
        )
        count = 0
        for match in matches:
            if self.retrieve_item(match, context=context) is not None:
                count += 1
        logger.info("Run %s: retrieved rate/labour details for %s matches", run.pk, count)
        return count
