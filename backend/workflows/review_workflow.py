"""Review workflow shims.

Convenience entry-points that delegate to ``apps/review/services/review_service``
(docs/AGENTS.md - Required Architecture: thin views, fat services). The review
workflow was implemented fully in Sprints 16-17.

Status transitions (docs/PRD.md - Review Workflow):

    Completed → Under Review → Approved → Exported

Direct access to ``ReviewService`` is preferred from services and views; these
helpers exist for workflow-level orchestration consistency.
"""
from __future__ import annotations


def submit_for_review(boq_id: int) -> None:
    """Transition a Completed BOQ to Under Review.

    Delegates to ``ReviewService.start_review(boq)``.
    """
    from apps.review.services.review_service import ReviewService
    from apps.boq.models import BOQ

    boq = BOQ.objects.get(pk=boq_id)
    ReviewService().start_review(boq)


def approve_boq(boq_id: int, approved_by) -> None:
    """Transition an Under Review or Completed BOQ to Approved.

    Delegates to ``ReviewService.approve(boq, user=approved_by)``.
    """
    from apps.review.services.review_service import ReviewService
    from apps.boq.models import BOQ

    boq = BOQ.objects.get(pk=boq_id)
    ReviewService().approve(boq, user=approved_by)


def reopen_for_review(boq_id: int, reopened_by) -> None:
    """Reopen an Approved BOQ back to Under Review.

    Delegates to ``ReviewService.revise(boq, user=reopened_by)``.
    """
    from apps.review.services.review_service import ReviewService
    from apps.boq.models import BOQ

    boq = BOQ.objects.get(pk=boq_id)
    ReviewService().revise(boq, user=reopened_by)
