"""Project-wide constants."""

# Keep the last N database uploads for view/download (metadata + workbook file).
# Only the active upload keeps master sheet rows in PostgreSQL.
DATABASE_UPLOADS_TO_RETAIN = 10

# Master workbook sheets that are ingested into PostgreSQL (docs/DATABASE.md).
REQUIRED_MASTER_SHEETS = [
    "Rate_Master_Output",
    "Labour_master_Output",
]

# Optional sheets are no longer ingested; other workbook sheets are counted for UI only.
OPTIONAL_MASTER_SHEETS: list[str] = []

MASTER_SHEETS = REQUIRED_MASTER_SHEETS + OPTIONAL_MASTER_SHEETS

# Embedding dimension for OpenAI text-embedding-3-small.
EMBEDDING_DIMENSION = 1536

# Below this score (0-100), no product is auto-selected (pending item).
MATCH_CONFIDENCE_THRESHOLD = 30

# After first DB mapping, rematch weak products until this confidence (or unmatched).
# Mirrors expert Re-analyse gains from taxonomy/schema alignment.
REFINE_MATCH_CONFIDENCE_TARGET = 70
