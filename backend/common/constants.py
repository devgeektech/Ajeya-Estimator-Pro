"""Project-wide constants.

Confidence thresholds and database retention sourced from docs/PRD.md,
docs/TRD.md and docs/DATABASE_ARCHITECTURE.md.
"""

# Confidence thresholds (percentage).
CONFIDENCE_GREEN = 90  # > 90  -> accept
CONFIDENCE_YELLOW = 80  # 80-90 -> review
CONFIDENCE_ORANGE = 70  # 70-80 -> strong review
CONFIDENCE_RED = 30  # 30-70 -> manual review
CONFIDENCE_PENDING_THRESHOLD = 30  # below this -> blank row for expert review


def confidence_band(score: float) -> str:
    """Return the colour band label for a confidence score."""
    if score is None:
        return "blank"
    if score > CONFIDENCE_GREEN:
        return "green"
    if score >= CONFIDENCE_YELLOW:
        return "yellow"
    if score >= CONFIDENCE_ORANGE:
        return "orange"
    if score >= CONFIDENCE_PENDING_THRESHOLD:
        return "red"
    return "blank"


# Database version retention: active + two rollback versions.
DATABASE_VERSIONS_TO_RETAIN = 3

# Master workbook sheet names (docs/DATABASE_ARCHITECTURE.md).
MASTER_SHEETS = [
    "Rate_Master",
    "Labour_Master",
    "TOR_Main",
    "Labour_Structure_Source",
    "TOR_Labour",
    "TOR_Accessories",
    "State_Control_List",
]

# Embedding dimension for OpenAI text-embedding-3-small.
EMBEDDING_DIMENSION = 1536
