"""Project-wide constants."""

# Database version retention: active + two rollback versions.
DATABASE_VERSIONS_TO_RETAIN = 3

# Master workbook sheet names (docs/DATABASE.md).
REQUIRED_MASTER_SHEETS = [
    "Rate_Master",
]

OPTIONAL_MASTER_SHEETS = [
    "Labour_Master",
    "TOR_Main",
    "Labour_Structure_Source",
    "TOR_Labour",
    "TOR_Accessories",
    "State_Control_List",
]

MASTER_SHEETS = REQUIRED_MASTER_SHEETS + OPTIONAL_MASTER_SHEETS

# Embedding dimension for OpenAI text-embedding-3-small.
EMBEDDING_DIMENSION = 1536
