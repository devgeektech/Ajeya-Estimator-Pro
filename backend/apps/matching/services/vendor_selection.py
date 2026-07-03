"""Vendor selection (Phase 6, Sprint 12).

After a product is matched, multiple master rows can exist for the same
product_code with different makes/vendors/prices. This service picks the vendor
row per the selected mode (docs/PRD.md - Vendor Selection) while honouring the
make list (docs/PRD.md - Make List Processing: only approved makes may be
selected). It is deterministic - no AI and no profit logic here.

Modes:
    LOWEST_COST  - cheapest approved vendor.
    PREFERRED    - first approved make (make-list order), cheapest within it.
    CUSTOM       - an expert-chosen master row (review-time override), with a
                   lowest-cost fallback.

The chosen row is written back onto the item's ProductMatch (product/make/
vendor) so costing reads a single authoritative vendor.
"""
from __future__ import annotations

import logging

from apps.database_manager.models import DatabaseVersion, RateMaster
from apps.make_list.models import MakeListEntry
from common.choices import VendorSelectionMode
from utils.text import normalize

logger = logging.getLogger("boq_ai")


class VendorSelectionService:
    """Select the vendor row for matched items in a run."""

    def __init__(self, mode: str = VendorSelectionMode.LOWEST_COST):
        self.mode = mode
        self._version = DatabaseVersion.objects.filter(is_active=True).first()

    @staticmethod
    def _approved_makes(run) -> list[str]:
        makes = MakeListEntry.objects.filter(boq_run=run).values_list("make", flat=True)
        # Preserve make-list order; PREFERRED mode treats it as preference order.
        ordered: list[str] = []
        for make in makes:
            norm = normalize(make)
            if norm and norm not in ordered:
                ordered.append(norm)
        return ordered

    def _candidates(self, product_code: str) -> list:
        if self._version is None:
            return []
        return list(
            RateMaster.objects.filter(
                database_version=self._version, product_code=product_code
            )
        )

    def _choose(self, candidates: list, approved: list[str], custom_rate):
        if self.mode == VendorSelectionMode.CUSTOM and custom_rate is not None:
            if custom_rate in candidates:
                return custom_rate
            logger.warning("Custom vendor not among candidates; falling back to lowest cost")

        if self.mode == VendorSelectionMode.PREFERRED and approved:
            for make in approved:
                group = [c for c in candidates if normalize(c.make) == make]
                if group:
                    return min(group, key=lambda c: c.purchase_rate)

        return min(candidates, key=lambda c: c.purchase_rate)

    def select_for_item(self, item, *, approved=None, custom_rate=None):
        """Select and persist the vendor row for a single item. Returns the row."""
        match = item.product_matches.first()
        if match is None or match.product is None:
            return None

        if approved is None:
            approved = self._approved_makes(item.boq_run)

        candidates = self._candidates(match.product.product_code)
        if not candidates:
            return None

        if approved:
            compliant = [c for c in candidates if normalize(c.make) in approved]
            if not compliant:
                # No approved make available -> cannot select a compliant vendor.
                logger.info(
                    "Item %s: no approved vendor for %s", item.pk, match.product.product_code
                )
                return None
            candidates = compliant

        chosen = self._choose(candidates, approved, custom_rate)
        if chosen is None:
            return None

        match.product = chosen
        match.make = chosen.make
        match.vendor = chosen.vendor
        match.save(update_fields=["product", "make", "vendor"])
        return chosen

    def select_run(self, run) -> int:
        """Select vendors for every matched item in a run. Returns the count."""
        approved = self._approved_makes(run)
        count = 0
        for item in run.items.all():
            if self.select_for_item(item, approved=approved) is not None:
                count += 1
        logger.info("Run %s: selected vendors for %s items", run.pk, count)
        return count
