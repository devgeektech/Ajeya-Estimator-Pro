"""Session-only line confirmations (no database persistence)."""
from __future__ import annotations

from typing import Any

from django.contrib.sessions.backends.base import SessionBase

from apps.boq.models import BOQ
from apps.boq.services.boq_line_output_service import BOQLineOutputService
from apps.boq.services.labour_detail_retrieval_service import LabourDetailRetrievalService
from apps.boq.services.rate_detail_retrieval_service import RateDetailRetrievalService
from common.exceptions import BOQAIError, ValidationError
from utils.timestamps import now_local_iso


def confirmation_session_key(boq_id: int) -> str:
    return f"boq_confirmations_{boq_id}"


def resolve_confirmed_line(
    boq_id: int,
    item: dict[str, Any],
    confirmation: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply session confirmation to one product match for display/export."""
    if not confirmation or not confirmation.get("confirmed"):
        return {
            "rate_detail": item.get("rate_detail"),
            "labour_detail": item.get("labour_detail"),
            "line_output": item.get("line_output") or {},
            "status": _base_match_status(item),
            "confirmed": False,
        }

    boq = BOQ.objects.get(pk=boq_id)
    database_version_id = int((boq.analysis_data or {}).get("database_version_id") or 0)
    rate_service = RateDetailRetrievalService(database_version_id)
    labour_service = LabourDetailRetrievalService(database_version_id)

    rate_master_id = int(confirmation["rate_master_id"])
    rate_detail = rate_service.get_by_id(rate_master_id)
    if not rate_detail:
        return {
            "rate_detail": item.get("rate_detail"),
            "labour_detail": item.get("labour_detail"),
            "line_output": item.get("line_output") or {},
            "status": _base_match_status(item),
            "confirmed": False,
        }

    labour_detail = labour_service.get_by_tech_key(
        rate_detail.get("tech_key"),
        size=rate_detail.get("size"),
    )
    extracted = item.get("extracted") or {}
    line_output = BOQLineOutputService.build(
        quantity=extracted.get("quantity"),
        rate_detail=rate_detail,
        labour_detail=labour_detail,
        is_pending=False,
        rate_only=bool(extracted.get("rate_only") or item.get("rate_only")),
    )
    return {
        "rate_detail": rate_detail,
        "labour_detail": labour_detail,
        "line_output": line_output,
        "status": "confirmed",
        "confirmed": True,
    }


def _base_match_status(item: dict[str, Any]) -> str:
    from common.constants import MATCH_CONFIDENCE_THRESHOLD

    match = item.get("match") or {}
    confidence = float(match.get("confidence") or 0)
    if match.get("status") == "matched" and confidence >= MATCH_CONFIDENCE_THRESHOLD:
        return "matched"
    return "pending"


class BOQConfirmationService:
    """Confirm analysis lines per user session — available to all logged-in users."""

    def __init__(self, boq_id: int, session: SessionBase):
        self.boq_id = boq_id
        self.session = session
        self._key = confirmation_session_key(boq_id)

    def all(self) -> dict[str, dict[str, Any]]:
        return dict(self.session.get(self._key) or {})

    def get(self, line_key: str) -> dict[str, Any] | None:
        return self.all().get(line_key)

    def is_confirmed(self, line_key: str) -> bool:
        entry = self.get(line_key)
        return bool(entry and entry.get("confirmed"))

    def confirm(
        self,
        *,
        line_key: str,
        rate_master_id: int | None = None,
    ) -> dict[str, Any]:
        boq = BOQ.objects.get(pk=self.boq_id)
        if not self._line_in_analysis(boq, line_key):
            raise ValidationError(f"Unknown analysis line: {line_key}")

        database_version_id = int((boq.analysis_data or {}).get("database_version_id") or 0)
        if not database_version_id:
            raise BOQAIError("Analysis is missing database version context.")

        if rate_master_id is None:
            rate_master_id = self._default_rate_master_id(boq, line_key)
        if rate_master_id is None:
            raise ValidationError("Select a product before confirming this line.")

        rate_service = RateDetailRetrievalService(database_version_id)
        if rate_service.get_by_id(rate_master_id) is None:
            raise ValidationError("Selected product is not in the active database.")

        confirmations = self.all()
        confirmations[line_key] = {
            "confirmed": True,
            "rate_master_id": rate_master_id,
            "confirmed_at": now_local_iso(),
        }
        self.session[self._key] = confirmations
        self.session.modified = True
        return confirmations[line_key]

    def unconfirm(self, line_key: str) -> None:
        confirmations = self.all()
        confirmations.pop(line_key, None)
        self.session[self._key] = confirmations
        self.session.modified = True

    def resolve_line(
        self,
        item: dict[str, Any],
        confirmation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Apply session confirmation to one product match for display/export."""
        return resolve_confirmed_line(self.boq_id, item, confirmation)

    @staticmethod
    def _line_in_analysis(boq: BOQ, line_key: str) -> bool:
        try:
            row_id, product_index_text = line_key.split(":", 1)
            product_index = int(product_index_text)
        except ValueError:
            return False

        for row in (boq.analysis_data or {}).get("rows") or []:
            if row.get("row_id") != row_id:
                continue
            for item in row.get("product_matches") or []:
                if int(item.get("product_index") or 0) == product_index:
                    return True
        return False

    @staticmethod
    def _default_rate_master_id(boq: BOQ, line_key: str) -> int | None:
        try:
            row_id, product_index_text = line_key.split(":", 1)
            product_index = int(product_index_text)
        except ValueError:
            return None

        for row in (boq.analysis_data or {}).get("rows") or []:
            if row.get("row_id") != row_id:
                continue
            for item in row.get("product_matches") or []:
                if int(item.get("product_index") or 0) != product_index:
                    continue
                selected = (item.get("match") or {}).get("selected") or {}
                rate_id = selected.get("rate_master_id")
                return int(rate_id) if rate_id else None
        return None
