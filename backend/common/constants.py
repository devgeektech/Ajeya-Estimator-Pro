"""Project-wide constants."""

# Keep the last N database uploads for view/download (metadata + workbook file).
# Only the active upload keeps master sheet rows in PostgreSQL.
DATABASE_UPLOADS_TO_RETAIN = 10

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
