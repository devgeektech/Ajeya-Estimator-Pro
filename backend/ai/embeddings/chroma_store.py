"""Local Chroma vector index for Product_Helper catalog embeddings.

Chroma stores one vector per Product_Helper row (complete product identity).
Search returns Product_ID; Rate_Master_Output / Labour_master_Output are loaded
from Postgres by that Product_ID for Make/Vendor amounts and labour.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence, cast

import chromadb
from chromadb.api.client import SharedSystemClient
from chromadb.api.types import PyEmbeddings
from chromadb.config import Settings
from django.conf import settings

from apps.database_manager.models import Product_Helper, Rate_Master_Output

logger = logging.getLogger("boq_ai")


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def selection_amount(rate: Rate_Master_Output) -> Decimal:
    """Make & Vendor / lowest-price amount — always Final_Material_Amount."""
    return _to_decimal(rate.Final_Material_Amount)


def _scalar(value: Any):
    if isinstance(value, Decimal):
        return float(value)
    if value is None:
        return ""
    return value


def helper_document_id(helper: Product_Helper) -> str:
    """Stable Chroma document id for a Product_Helper row."""
    return f"product-helper-{helper.pk}"


def resolve_product_id(document_id: str, metadata: dict[str, Any] | None = None) -> str | None:
    """Resolve Product_Helper Product_ID from a Chroma hit id/metadata."""
    if metadata:
        raw = str(metadata.get("product_id") or "").strip()
        if raw:
            return raw
    if document_id.startswith("product-helper-"):
        # Fallback: metadata missing — caller should load by helper pk if needed.
        return None
    return None


def resolve_helper_id(document_id: str, metadata: dict[str, Any] | None = None) -> int | None:
    """Resolve PostgreSQL Product_Helper pk from a Chroma hit."""
    if metadata:
        raw_id = metadata.get("product_helper_id")
        if raw_id is not None:
            try:
                return int(raw_id)
            except (TypeError, ValueError):
                pass
    if document_id.startswith("product-helper-"):
        suffix = document_id.removeprefix("product-helper-")
        try:
            return int(suffix)
        except ValueError:
            return None
    try:
        return int(document_id)
    except ValueError:
        return None


# Kept for callers that still resolve legacy rate-master Chroma ids during transition.
def resolve_rate_master_id(document_id: str, metadata: dict[str, Any] | None = None) -> int | None:
    """Resolve Rate_Master_Output pk from legacy Chroma metadata (compat)."""
    if metadata:
        raw_id = metadata.get("rate_master_id")
        if raw_id is not None:
            try:
                return int(raw_id)
            except (TypeError, ValueError):
                pass
    if document_id.startswith("rate-master-"):
        suffix = document_id.removeprefix("rate-master-")
        try:
            return int(suffix)
        except ValueError:
            return None
    return None


def helper_document(helper: Product_Helper) -> str:
    """Build full Product_Helper text for embedding (no Make/Vendor/rates)."""
    fields = [
        ("Product_ID", helper.Product_ID),
        ("Category", helper.Category),
        ("Sub Category", helper.Sub_Category),
        ("Class", helper.Class),
        ("Size", helper.Size),
        ("Unit", helper.Unit),
        ("Capacity", helper.Capacity),
        ("Attribute", helper.Attribute),
        ("Status", helper.Status),
    ]
    lines = []
    for label, value in fields:
        text = str(value or "").strip()
        if text:
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


# Backward-compatible alias used by older call sites / logs.
rate_document = helper_document


def helper_metadata(helper: Product_Helper) -> dict:
    """Chroma-safe metadata — Product_ID is the join key for rates/labour."""
    return {
        "database_version_id": helper.database_version.pk,
        "product_helper_id": helper.pk,
        "product_id": str(helper.Product_ID or "").strip(),
        "category": helper.Category or "",
        "sub_category": helper.Sub_Category or "",
        "class": helper.Class or "",
        "size": _scalar(helper.Size),
        "unit": helper.Unit or "",
        "capacity": helper.Capacity or "",
        "attribute": helper.Attribute or "",
        "status": helper.Status or "",
        "product_display_key": helper.display_key(),
    }


class ChromaEmbeddingStore:
    """Persistent local Chroma index for Product_Helper embeddings."""

    def __init__(self, path: str | None = None, collection_name: str | None = None):
        self.path = Path(path or settings.CHROMA_PATH)
        self.path.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name or settings.CHROMA_COLLECTION
        self._connect()

    def _connect(self, *, drop_cached_client: bool = False) -> None:
        """
        Open the persistent client and collection handle.

        Chroma caches one system per path per process. A long-lived Celery worker
        therefore keeps serving the segment it opened first, so a database re-import
        (which rewrites every vector) leaves the worker querying ids that no longer
        exist. ``drop_cached_client`` forces a genuinely fresh read of the files.
        """
        if drop_cached_client:
            SharedSystemClient.clear_system_cache()
        self.client = chromadb.PersistentClient(
            path=str(self.path),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def reset_all(self) -> None:
        """Remove all indexed products (active-database-only policy)."""
        existing = self.collection.get(include=[])
        ids = existing.get("ids") or []
        if ids:
            self.collection.delete(ids=ids)

    def reset_version(self, database_version_id: int) -> None:
        """Remove indexed products for one database version."""
        self.collection.delete(where={"database_version_id": int(database_version_id)})

    def query_similar(
        self,
        query_embedding: list[float],
        *,
        limit: int = 20,
        database_version_id: int | None = None,
    ) -> list[dict]:
        """Return nearest Product_Helper hits (Product_ID) by embedding distance."""
        where_filter: Any = (
            {"database_version_id": int(database_version_id)}
            if database_version_id is not None
            else None
        )
        try:
            result = self._query(query_embedding, limit, where_filter)
        except Exception:
            logger.warning("Chroma query failed; reopening the index and retrying")
            self._connect(drop_cached_client=True)
            result = self._query(query_embedding, limit, where_filter)

        ids = (result.get("ids") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]

        hits: list[dict] = []
        for index, doc_id in enumerate(ids):
            metadata = dict(metadatas[index] if index < len(metadatas) else {})
            distance = distances[index] if index < len(distances) else 1.0
            document = documents[index] if index < len(documents) else ""
            product_id = resolve_product_id(str(doc_id), metadata)
            helper_id = resolve_helper_id(str(doc_id), metadata)
            if not product_id and helper_id is None:
                continue
            hits.append(
                {
                    "product_id": product_id or "",
                    "product_helper_id": helper_id,
                    "distance": float(distance),
                    "similarity": max(0.0, 1.0 - float(distance)),
                    "metadata": metadata,
                    "document": document or "",
                }
            )
        return hits

    def _query(self, query_embedding: list[float], limit: int, where_filter: Any):
        return self.collection.query(
            query_embeddings=[query_embedding],
            n_results=max(1, limit),
            where=cast(Any, where_filter),
            include=["metadatas", "distances", "documents"],
        )

    def upsert_helper(self, helper: Product_Helper, embedding: Sequence[float]) -> str:
        """Upsert one Product_Helper row into Chroma."""
        return self.upsert_helpers([helper], [embedding])[0]

    def upsert_helpers(
        self,
        helpers: list[Product_Helper],
        embeddings: Sequence[Sequence[float]],
    ) -> list[str]:
        """Upsert many Product_Helper rows into Chroma, one vector per row."""
        if not helpers:
            return []
        if len(helpers) != len(embeddings):
            raise ValueError("helpers and embeddings must be the same length")

        document_ids = [helper_document_id(helper) for helper in helpers]
        self.collection.upsert(
            ids=document_ids,
            embeddings=cast(PyEmbeddings, embeddings),
            documents=[helper_document(helper) for helper in helpers],
            metadatas=[helper_metadata(helper) for helper in helpers],
        )
        return document_ids

    # Compat aliases — older generator/tests called upsert_rate(s).
    def upsert_rate(self, helper: Product_Helper, embedding: Sequence[float]) -> str:
        return self.upsert_helper(helper, embedding)

    def upsert_rates(
        self,
        helpers: list[Product_Helper],
        embeddings: Sequence[Sequence[float]],
    ) -> list[str]:
        return self.upsert_helpers(helpers, embeddings)
