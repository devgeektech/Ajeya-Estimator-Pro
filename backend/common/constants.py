"""Project-wide constants.

Confidence thresholds and database retention sourced from docs/PRD.md,
docs/TRD.md and docs/DATABASE_ARCHITECTURE.md.
"""
from decimal import Decimal

# Confidence thresholds (percentage).
CONFIDENCE_GREEN = 90  # > 90  -> accept
CONFIDENCE_YELLOW = 80  # 80-90 -> review
CONFIDENCE_ORANGE = 70  # 70-80 -> strong review
CONFIDENCE_RED = 30  # 30-70 -> manual review; < 30 -> pending product
CONFIDENCE_PENDING_THRESHOLD = 30  # below this -> blank row + pending product


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


# Database version retention: active + 9 previous versions (10 total).
DATABASE_VERSIONS_TO_RETAIN = 10


# Commercial costing defaults (percentages). The docs defer exact values to
# commercial rules (docs/PRD.md - Cost Calculation); these are tunable defaults.
# All costing is rule-based - AI never prices (docs/AGENTS.md - AI Rules).
TRANSPORTATION_PERCENT = Decimal("2")  # % of material cost
OVERHEAD_PERCENT = Decimal("10")  # % of (material + labour + accessories + transport)
PROFIT_PERCENT = Decimal("10")  # % of (base + overhead)

# Master workbook sheet names (docs/DATABASE_ARCHITECTURE.md).
MASTER_SHEETS = [
    "Rate_Master",
    "Labour_Master",
    "TOR_Main",
    "TOR_Labour",
    "TOR_Accessories",
    "State_Control_List",
]

# Embedding dimension for OpenAI text-embedding-3-small.
EMBEDDING_DIMENSION = 1536
