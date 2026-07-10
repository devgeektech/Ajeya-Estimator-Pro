"""Local Chroma vector index for MaterialRate product embeddings."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings
from django.conf import settings

from apps.database_manager.models import MaterialRate


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def selection_amount(rate: MaterialRate) -> Decimal:
    """Amount used when comparing MaterialRate rows."""
    value = rate.final_amount_excl_gst
    if value is not None:
        return _to_decimal(value)
    return _to_decimal(rate.net_material_rate)


@dataclass(frozen=True)
class ChromaMatch:
    """One vector-search hit resolved from Chroma metadata."""

    material_rate_id: int
    tech_key: str
    similarity: float


def _scalar(value: Any):
    if isinstance(value, Decimal):
        return float(value)
    if value is None:
        return ""
    return value


def rate_document_id(rate: MaterialRate) -> str:
    """Return the stable Chroma document id for a MaterialRate row."""
    return f"material-rate-{rate.pk}"


def rate_document(rate: MaterialRate) -> str:
    """Build the text embedded for vector product search."""
    parts = [
        rate.tech_key,
        rate.category,
        rate.sub_category,
        rate.material_class,
        rate.size,
        rate.capacity,
        rate.make,
        rate.supplier,
        rate.unit,
        rate.attribute,
    ]
    return " ".join(str(part).strip() for part in parts if str(part or "").strip())


def rate_metadata(rate: MaterialRate) -> dict:
    """Return Chroma-safe metadata for resolving vector hits back to PostgreSQL."""
    return {
        "database_version_id": rate.database_version.pk,
        "material_rate_id": rate.pk,
        "tech_key": rate.tech_key,
        "make": rate.make or "",
        "supplier": rate.supplier or "",
        "unit": rate.unit or "",
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

    def reset_version(self, database_version_id: int) -> None:
        """Remove indexed products for one database version."""
        self.collection.delete(where={"database_version_id": int(database_version_id)})

    def upsert_rate(self, rate: MaterialRate, embedding: list[float]) -> str:
        """Upsert one MaterialRate row into Chroma and return its document id."""
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
            material_rate_id = metadata.get("material_rate_id") or metadata.get(
                "rate_master_id"
            )
            if not material_rate_id:
                continue
            similarity = max(0.0, 1.0 - float(distance or 0.0))
            matches.append(
                ChromaMatch(
                    material_rate_id=int(str(material_rate_id)),
                    tech_key=str(metadata.get("tech_key") or ""),
                    similarity=similarity,
                )
            )
        return matches
