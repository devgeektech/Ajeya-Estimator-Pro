"""Review service (Phase 8, Sprint 16).

Experts review processing results and may change the selected product/vendor per
row; costs are recalculated immediately (docs/PRD.md - Internal Review Sheet).
Experts may NOT modify the master database (docs/AGENTS.md - Review Rules) - they
only re-point a BOQ item's match at an existing master row.

Every change is recorded as a ReviewItem (audit of original vs revised) and the
BOQ transitions to Under Review.
"""
from __future__ import annotations

import logging

from apps.audit.services import record
from apps.costing.services.cost_service import CostCalculationService
from apps.database_manager.models import DatabaseVersion, RateMaster
from apps.matching.models import ProductMatch
from apps.notifications.services import notify
from apps.review.models import ReviewItem
from common.choices import BOQStatus
from common.exceptions import ValidationError

logger = logging.getLogger("boq_ai")


class ReviewService:
    """Apply expert review changes and keep costs in sync."""

    # Allowed source states for each transition (docs/PRD.md - BOQ Workflow:
    # Completed -> Under Review -> Approved -> Exported).
    _APPROVE_FROM = {BOQStatus.COMPLETED, BOQStatus.UNDER_REVIEW}

    def start_review(self, boq, user=None):
        """Move a BOQ into the Under Review state."""
        if boq.status != BOQStatus.UNDER_REVIEW:
            boq.status = BOQStatus.UNDER_REVIEW
            boq.save(update_fields=["status"])
        logger.info("BOQ %s moved to Under Review", boq.pk)
        return boq

    def approve(self, boq, user=None):
        """Approve a reviewed BOQ (Completed/Under Review -> Approved)."""
        if boq.status not in self._APPROVE_FROM:
            raise ValidationError(
                f"Cannot approve a BOQ in '{boq.get_status_display()}'. "
                "Process and review it first."
            )
        boq.status = BOQStatus.APPROVED
        boq.save(update_fields=["status"])
        logger.info("BOQ %s approved by %s", boq.pk, getattr(user, "pk", None))

        record(user, "approve", "BOQ", boq.pk)
        notify(boq.user, "BOQ approved", f"'{boq.boq_name}' has been approved.")
        return boq

    def revise(self, boq, user=None):
        """Reopen an approved BOQ for further review (Approved -> Under Review)."""
        if boq.status != BOQStatus.APPROVED:
            raise ValidationError(
                f"Only approved BOQs can be reopened (current: '{boq.get_status_display()}')."
            )
        boq.status = BOQStatus.UNDER_REVIEW
        boq.save(update_fields=["status"])
        logger.info("BOQ %s reopened for review by %s", boq.pk, getattr(user, "pk", None))
        return boq

    def candidate_rates(self, item):
        """Master rows the item can be re-pointed to (same product_code first)."""
        version = DatabaseVersion.objects.filter(is_active=True).first()
        if version is None:
            return RateMaster.objects.none()
        match = item.product_matches.first()
        qs = RateMaster.objects.filter(database_version=version)
        if match and match.product:
            return qs.filter(product_code=match.product.product_code)
        return qs

    def apply_selection(self, item, rate, user=None, notes: str = ""):
        """Re-point an item's match at ``rate``; record + recalculate.

        Works for both vendor changes (same product_code) and product changes
        (different product_code).
        """
        if rate is None:
            raise ValidationError("A target product/rate row is required.")

        match = item.product_matches.first()
        if match is None:
            match = ProductMatch(boq_item=item)

        review = ReviewItem.objects.create(
            boq_item=item,
            reviewed_by=user,
            original_product=match.product.product_code if match.product else "",
            revised_product=rate.product_code,
            original_vendor=match.vendor or "",
            revised_vendor=rate.vendor or "",
            notes=notes,
        )

        match.product = rate
        match.vendor = rate.vendor or ""
        match.make = rate.make or ""
        match.match_reason = "manual"
        match.confidence_score = 100  # expert override is authoritative
        match.save()

        CostCalculationService().calculate_item(match)
        # Reviewing implies the BOQ is under review.
        self.start_review(item.boq_run.boq, user)
        logger.info(
            "Item %s re-pointed to %s%s by review",
            item.pk,
            rate.product_code,
            "",
        )
        return review
