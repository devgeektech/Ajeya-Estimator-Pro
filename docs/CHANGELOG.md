# Changelog

Meaningful product and technical changes only. Older history is in git.

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
