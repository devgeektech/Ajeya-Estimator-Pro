"""Cost calculation orchestration (Phase 7).

CostCalculationService builds the per-unit cost breakdown for each matched item
and keeps final_rate in sync (docs/DATABASE_ARCHITECTURE.md - CostBreakdown):

    final_rate = material + labour + transportation + accessories + overhead + profit

Sprint 13 fills material_cost; Sprint 14 adds labour_cost + accessories_cost
from the TOR tables; Sprint 15 adds transportation, overheads and profit
(commercial costing) plus StateControl multipliers. Items with no selected
product (pending/blank) get no breakdown so their output row stays blank. All
deterministic - AI never costs (docs/AGENTS.md - AI Rules).

State multipliers apply only when a state_name is supplied to calculate_run /
calculate_item; the pipeline currently has no BOQ-level state, so multipliers
default to 1 (a BOQ state field is a future enhancement).
"""
from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal

from utils.text import normalize

from apps.costing.services import labour as labour_service
from apps.costing.services import material as material_service
from apps.costing.services import profit as profit_service
from apps.costing.services import transport as transport_service

logger = logging.getLogger("boq_ai")

_CENTS = Decimal("0.01")


def _q2(value) -> Decimal:
    """Quantize to 2 decimal places (currency)."""
    return Decimal(value).quantize(_CENTS, rounding=ROUND_HALF_UP)

COMPONENT_FIELDS = (
    "material_cost",
    "labour_cost",
    "transportation_cost",
    "accessories_cost",
    "overhead_cost",
    "profit",
)


def recompute_final_rate(breakdown) -> Decimal:
    """Sum the components into final_rate and return it."""
    total = sum((getattr(breakdown, field) or Decimal("0")) for field in COMPONENT_FIELDS)
    breakdown.final_rate = total
    return total


class CostCalculationService:
    """Calculate and persist cost breakdowns for a run."""

    @staticmethod
    def _load_context() -> dict:
        """Preload active-version cost lookups (labour rates, TOR rows)."""
        from apps.database_manager.models import (
            DatabaseVersion,
            LabourMaster,
            RateMaster,
            TORAccessories,
            TORLabour,
        )

        version = DatabaseVersion.objects.filter(is_active=True).first()
        if version is None:
            logger.warning("No active database version; labour/accessories are zero")
            return {"labour_rates": {}, "tor_labour": {}, "tor_accessories": {}, "accessory_rates": {}}

        labour_rates = {
            normalize(row.labour_code): row
            for row in LabourMaster.objects.filter(database_version=version)
        }
        accessory_rates = {
            normalize(row.product_code): row
            for row in RateMaster.objects.filter(database_version=version)
        }
        tor_labour: dict[str, list] = {}
        for row in TORLabour.objects.filter(database_version=version):
            tor_labour.setdefault(normalize(row.tor_code), []).append(row)
        tor_accessories: dict[str, list] = {}
        for row in TORAccessories.objects.filter(database_version=version):
            tor_accessories.setdefault(normalize(row.tor_code), []).append(row)

        return {
            "labour_rates": labour_rates,
            "tor_labour": tor_labour,
            "tor_accessories": tor_accessories,
            "accessory_rates": accessory_rates,
        }

    @staticmethod
    def _state_multipliers(state_name: str | None) -> tuple[Decimal, Decimal]:
        """Return (labour_multiplier, transportation_multiplier) for a state."""
        if not state_name:
            return Decimal("1"), Decimal("1")
        from apps.database_manager.models import StateControl

        state = StateControl.objects.filter(state_name__iexact=state_name).first()
        if state is None:
            return Decimal("1"), Decimal("1")
        return Decimal(state.labour_multiplier), Decimal(state.transportation_multiplier)

    def calculate_item(self, match, context: dict | None = None, multipliers=None):
        """Create/update the CostBreakdown for one ProductMatch.

        Returns the breakdown, or None when the item has no selected product.
        """
        from apps.costing.models import CostBreakdown

        if match.product is None:
            CostBreakdown.objects.filter(product_match=match).delete()
            return None

        if context is None:
            context = self._load_context()
        labour_mult, transport_mult = multipliers or (Decimal("1"), Decimal("1"))

        material = material_service.material_cost(match)
        labour = labour_service.labour_cost(
            match.product, context["labour_rates"], context["tor_labour"]
        ) * labour_mult
        accessories = labour_service.accessories_cost(
            match.product, context["tor_accessories"], context["accessory_rates"]
        )
        transportation = transport_service.transportation_cost(material, transport_mult)

        base = material + labour + accessories + transportation
        overhead = profit_service.overhead_cost(base, match.product)
        margin = profit_service.profit(base + overhead, match.product)

        breakdown, _ = CostBreakdown.objects.get_or_create(product_match=match)
        breakdown.material_cost = _q2(material)
        breakdown.labour_cost = _q2(labour)
        breakdown.accessories_cost = _q2(accessories)
        breakdown.transportation_cost = _q2(transportation)
        breakdown.overhead_cost = _q2(overhead)
        breakdown.profit = _q2(margin)
        recompute_final_rate(breakdown)
        breakdown.save()
        return breakdown

    def calculate_run(self, run, state_name: str | None = None) -> int:
        """Calculate breakdowns for all matched items. Returns the count."""
        from apps.matching.models import ProductMatch

        context = self._load_context()
        multipliers = self._state_multipliers(state_name)
        matches = ProductMatch.objects.filter(
            boq_item__boq_run=run
        ).select_related("product", "boq_item")
        count = 0
        for match in matches:
            if self.calculate_item(match, context=context, multipliers=multipliers) is not None:
                count += 1
        logger.info("Run %s: costed %s items", run.pk, count)
        return count
