"""Pending product service (Phase 9, Sprint 18).

Super Admin resolves products that scored below the confidence threshold
(docs/PRD.md - Pending Product Workflow). Actions:

    reject   - dismiss the pending entry.
    merge    - map the description to an EXISTING master product (creates a
               ProductAlias so future BOQs match automatically).
    add_new  - create a NEW master product in the active version, then alias.

Approved/merged products "become available in future BOQs" via the alias /
new RateMaster row (docs/PRD.md). Only Super Admin may do this
(docs/AGENTS.md - Pending Product Rules; database changes are Super Admin only).
"""
from __future__ import annotations

import logging
from decimal import Decimal

from apps.database_manager.models import DatabaseVersion, ProductAlias, RateMaster
from common.choices import PendingProductStatus
from common.exceptions import ValidationError

logger = logging.getLogger("boq_ai")


class PendingProductService:
    """Approve / reject / merge / add-new for the pending queue."""

    @staticmethod
    def _active_version():
        version = DatabaseVersion.objects.filter(is_active=True).first()
        if version is None:
            raise ValidationError("No active database version.")
        return version

    def reject(self, pending, user=None):
        pending.status = PendingProductStatus.REJECTED
        pending.reviewed_by = user
        pending.save(update_fields=["status", "reviewed_by"])
        logger.info("Pending %s rejected", pending.pk)
        return pending

    def merge(self, pending, product_code: str, user=None):
        """Map the pending description to an existing master product."""
        version = self._active_version()
        code = (product_code or "").strip()
        if not code:
            raise ValidationError("A product code is required to merge.")
        if not RateMaster.objects.filter(database_version=version, product_code=code).exists():
            raise ValidationError(f"No product '{code}' in the active database.")

        ProductAlias.objects.get_or_create(alias=pending.description, product_code=code)
        pending.suggested_product = code
        pending.status = PendingProductStatus.APPROVED
        pending.reviewed_by = user
        pending.save(update_fields=["suggested_product", "status", "reviewed_by"])
        logger.info("Pending %s merged into %s", pending.pk, code)
        return pending

    def add_new(
        self,
        pending,
        *,
        product_code: str,
        description: str = "",
        purchase_rate=Decimal("0"),
        make: str = "",
        vendor: str = "",
        unit: str = "",
        user=None,
    ):
        """Create a new master product (active version) and alias to it."""
        version = self._active_version()
        code = (product_code or "").strip()
        if not code:
            raise ValidationError("A product code is required to add a product.")
        if RateMaster.objects.filter(database_version=version, product_code=code).exists():
            raise ValidationError(f"Product '{code}' already exists; use merge instead.")

        rate = RateMaster.objects.create(
            database_version=version,
            product_code=code,
            description=description or pending.description,
            make=make,
            vendor=vendor,
            purchase_rate=Decimal(purchase_rate or 0),
            unit=unit,
        )
        ProductAlias.objects.get_or_create(alias=pending.description, product_code=code)
        pending.suggested_product = code
        pending.status = PendingProductStatus.APPROVED
        pending.reviewed_by = user
        pending.save(update_fields=["suggested_product", "status", "reviewed_by"])
        logger.info("Pending %s added as new product %s", pending.pk, code)
        return rate
