"""Project-wide constants."""

# Keep the last N database uploads for view/download (metadata + workbook file).
# Only the active upload keeps master sheet rows in PostgreSQL.
DATABASE_UPLOADS_TO_RETAIN = 10

# Master workbook sheets that are ingested into PostgreSQL (docs/DATABASE.md).
# Preferred names match the current client workbook; aliases cover older files.
REQUIRED_MASTER_SHEETS = [
    "Product_Helper",
    "Rate_Master_Output",
    "Labour_Master_Output",
]

# Alternate workbook sheet titles accepted as the same ingested sheet.
MASTER_SHEET_ALIASES: dict[str, tuple[str, ...]] = {
    "Product_Helper": ("Product_Helper", "Product_Master"),
    "Rate_Master_Output": ("Rate_Master_Output",),
    "Labour_Master_Output": (
        "Labour_Master_Output",
        "Labour_master_Output",  # older workbook spelling
    ),
}

# Optional sheets are no longer ingested; other workbook sheets are counted for UI only.
OPTIONAL_MASTER_SHEETS: list[str] = []

MASTER_SHEETS = REQUIRED_MASTER_SHEETS + OPTIONAL_MASTER_SHEETS

# Embedding dimension for OpenAI text-embedding-3-small.
EMBEDDING_DIMENSION = 1536

# Below this score (0-100), no product is auto-selected (pending item).
MATCH_CONFIDENCE_THRESHOLD = 30

# Analysis UI: leave Category/Sub/Class/Size/Unit/Capacity/Attributes empty when
# match confidence is below this (expert fills or Selects a candidate). Confirm /
# provisional rules still use MATCH_CONFIDENCE_THRESHOLD.
ANALYSIS_INPUT_FILL_CONFIDENCE = 50

# Product Id auto-fills only when match % is orange/green (≥90). Red tabs (<90)
# stay without Product Id until expert Select or a high-confidence rematch.
PRODUCT_ID_CONFIRM_CONFIDENCE = 90

# After first DB mapping, rematch weak products until this confidence (or unmatched).
# Mirrors expert Re-analyse gains from taxonomy/schema alignment.
REFINE_MATCH_CONFIDENCE_TARGET = 70
