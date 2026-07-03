"""Transportation cost (Phase 7, Sprint 15).

Rule-based: a percentage of material cost, scaled by the state's
transportation multiplier when a state is known
(docs/DATABASE_ARCHITECTURE.md - StateControl). No AI
(docs/AGENTS.md - AI Rules).
"""
from __future__ import annotations

from decimal import Decimal

from common.constants import TRANSPORTATION_PERCENT


def transportation_cost(material: Decimal, multiplier: Decimal = Decimal("1")) -> Decimal:
    """Per-unit transportation cost from material cost."""
    return Decimal(material) * TRANSPORTATION_PERCENT / Decimal("100") * Decimal(multiplier)
