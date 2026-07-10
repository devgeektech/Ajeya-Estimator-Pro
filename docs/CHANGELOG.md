# Changelog

Meaningful product and technical changes only. Older history is in git.

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
