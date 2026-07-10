# Changelog

Meaningful product and technical changes only. Older history is in git.

## 2026-07-10 — Active-Only Master Data Retention

- `DatabaseVersion` history and workbook files are kept for view/download.
- Master sheet rows in PostgreSQL are kept only for the active upload; inactive
  versions are cleared on each import.
- Removed snake_case aliases and property shims from `database_manager/models.py`.

## 2026-07-10 — Single Active Database Retention

- New master workbook uploads now delete all previous `DatabaseVersion` rows,
  master sheet data, stored workbooks, and stale Chroma vectors.
- Only the current active upload remains in PostgreSQL and the UI.

## 2026-07-10 — BOQs List Page

- Replaced sidebar "Upload BOQ" entry with a BOQs list at `/boqs/` matching the
  dashboard table layout (count, upload button, owner/status/created columns).
- Upload form moved to `/boqs/upload/`; successful uploads redirect to the list.
- Added BOQ detail page for the table "Open" action.

## 2026-07-10 — Batched Embedding Generation

- OpenAI embedding requests and Chroma upserts now run in batches (default 500
  rows) while keeping one vector + metadata record per `Rate_Master` row.
- Upload/import remains synchronous; no Celery task added.

## 2026-07-10 — Remove Orphan Folders

- Deleted empty removed-app shells and stale `__pycache__` trees:
  `costing`, `processing`, `matching`, `review`, `exports`, `make_list`,
  `pending_products`, `workflows/`, `tasks/`, `exports/`, `ai/extractors/`.

## 2026-07-10 — Canonical Master Sheet Names

- Removed workflow aliases (`MaterialRate`, `LabourMaster`, `CategoryConfig`, etc.).
- Code and docs now use only workbook-aligned names: `Rate_Master`, `Labour_Master`,
  `TOR_Main`, `Labour_Structure_Source`, `TOR_Labour`, `TOR_Accessories`,
  `State_Control_List`.
- Chroma metadata key renamed to `rate_master_id`.

## 2026-07-10 — Remove Rollback; Single Active Embeddings

- Removed `DatabaseRollbackService`, rollback URL/view/UI.
- Retention increased to last 10 uploads (view + download only).
- Merged `generate_database_embeddings.py` into `ai/embeddings/generator.py`.
- Structured embedding text/metadata for Category, Sub Category, Class, Size,
  Make, Capacity, Unit, Attribute, Supplier, Tech_Key.
- Chroma holds embeddings for the active database only.

## 2026-07-10 — Squashed Migrations (Fresh DB)

- Removed all prior migration files and regenerated `0001_initial` for accounts,
  audit, boq, database_manager, and notifications from current models.
- Documented PG 15+ `public` schema grants for new databases in `DATABASE.md`.
- **Breaking for existing DBs:** drop and recreate, or reset migration history
  manually — do not apply on databases with old migration rows.

## 2026-07-10 — Lean Docs + Remove workflows/

- Consolidated docs: `PRODUCT.md`, `DATABASE.md`, `OPS.md` replace PRD, TRD,
  ARCHITECTURE, PROJECT_STRUCTURE, DATABASE_ARCHITECTURE, RUN, DEPLOY, and ROADMAP.
- Removed `workflows/`; database upload view calls `DatabaseImportService` directly.
- Updated `AGENTS.md` and `README.md` for the new doc set.

## 2026-07-10 — Codebase Cleanup After BOQ Reset

- Removed leftover pipeline code, stale tests, export modules, AI extractors, logs, cache.
- 74 tests passing.

## 2026-07-10 — BOQ Pipeline Reset (Upload Only)

- Removed processing, matching, costing, review, exports, make_list apps.
- BOQ upload only at `/boqs/upload/`.
- Migrations `boq.0003`, `database_manager.0010`.

## 2026-07-10 — Optional Master Sheets & Nullable Fields

- Only `Rate_Master` required at import; optional sheets skipped if absent.
- Blank workbook cells stored as PostgreSQL `NULL`.

## 2026-07-09 — Workbook-Aligned Master Schema

- PascalCase models matching client workbook tables; `Tech_Key` indexed not unique.
- Migrations `0007`–`0009`.
