"""Local Chroma vector index for Rate_Master product embeddings."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings
from django.conf import settings

from apps.database_manager.models import Rate_Master


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def selection_amount(rate: Rate_Master) -> Decimal:
    """Amount used when comparing Rate_Master rows."""
    value = rate.final_amount_excl_gst
    if value is not None:
        return _to_decimal(value)
    return _to_decimal(rate.net_material_rate)


@dataclass(frozen=True)
class ChromaMatch:
    """One vector-search hit resolved from Chroma metadata."""

    rate_master_id: int
    tech_key: str
    similarity: float


def _scalar(value: Any):
    if isinstance(value, Decimal):
        return float(value)
    if value is None:
        return ""
    return value


def rate_document_id(rate: Rate_Master) -> str:
    """Return the stable Chroma document id for a Rate_Master row."""
    return f"rate-master-{rate.pk}"


def rate_document(rate: Rate_Master) -> str:
    """Build structured text embedded for vector product search."""
    fields = [
        ("Category", rate.category),
        ("Sub Category", rate.sub_category),
        ("Class", rate.material_class),
        ("Size", rate.size),
        ("Make", rate.make),
        ("Capacity", rate.capacity),
        ("Unit", rate.unit),
        ("Attribute", rate.attribute),
        ("Supplier", rate.supplier),
        ("Tech_Key", rate.tech_key),
    ]
    lines = []
    for label, value in fields:
        text = str(value or "").strip()
        if text:
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


def rate_metadata(rate: Rate_Master) -> dict:
    """Return Chroma-safe metadata for resolving vector hits back to PostgreSQL."""
    return {
        "database_version_id": rate.database_version.pk,
        "rate_master_id": rate.pk,
        "category": rate.category or "",
        "sub_category": rate.sub_category or "",
        "class": rate.material_class or "",
        "size": _scalar(rate.size),
        "make": rate.make or "",
        "capacity": rate.capacity or "",
        "unit": rate.unit or "",
        "attribute": rate.attribute or "",
        "supplier": rate.supplier or "",
        "tech_key": rate.tech_key or "",
        "final_amount_excl_gst": _scalar(rate.final_amount_excl_gst),
        "selection_amount": _scalar(selection_amount(rate)),
    }


class ChromaEmbeddingStore:
    """Persistent local Chroma index for product embeddings."""

    def __init__(self, path: str | None = None, collection_name: str | None = None):
        self.path = Path(path or settings.CHROMA_PATH)
        self.path.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name or settings.CHROMA_COLLECTION
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

    def upsert_rate(self, rate: Rate_Master, embedding: list[float]) -> str:
        """Upsert one Rate_Master row into Chroma and return its document id."""
        document_id = rate_document_id(rate)
        self.collection.upsert(
            ids=[document_id],
            embeddings=[embedding],
            documents=[rate_document(rate)],
            metadatas=[rate_metadata(rate)],
        )
        return document_id

    def query(
        self,
        embedding: list[float],
        *,
        database_version_id: int,
        top_k: int = 5,
    ) -> list[ChromaMatch]:
        """Return vector hits scoped to one database version."""
        result = self.collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            where={"database_version_id": int(database_version_id)},
            include=["metadatas", "distances"],
        )
        metadatas_raw = result.get("metadatas") or []
        distances_raw = result.get("distances") or []
        metadatas = metadatas_raw[0] if metadatas_raw else []
        distances = distances_raw[0] if distances_raw else []
        matches: list[ChromaMatch] = []
        for metadata, distance in zip(metadatas, distances, strict=False):
            if not isinstance(metadata, dict):
                continue
            rate_master_id = metadata.get("rate_master_id") or metadata.get(
                "material_rate_id"
            )
            if not rate_master_id:
                continue
            similarity = max(0.0, 1.0 - float(distance or 0.0))
            matches.append(
                ChromaMatch(
                    rate_master_id=int(str(rate_master_id)),
                    tech_key=str(metadata.get("tech_key") or ""),
                    similarity=similarity,
                )
            )
        return matches
