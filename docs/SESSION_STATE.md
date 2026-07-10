# BOQ_AI Session State

Compact active memory. Full spec: `docs/PRODUCT.md`. Schema: `docs/DATABASE.md`.

## Current Status

- **Phase:** BOQ pipeline rebuild (upload-only base; master DB import active)
- **Tests:** 74 passing
- **Runtime:** `config.settings`, PostgreSQL, Django templates + HTMX
- **Active apps:** accounts, users, database_manager, boq, dashboard, notifications, audit
- **Removed:** processing, matching, costing, review, exports, make_list, `workflows/`

## Active Workflows

**Database:** upload → validate → import → activate → embeddings (sync, via `DatabaseImportService`)

**BOQ:** upload workbook (+ optional make list) → stored → dashboard

## Pending

- Rebuild BOQ parse → process → match → review → export
- Run `manage.py migrate` on envs missing `boq.0003` / `database_manager.0010`

## Verify

```powershell
.venv\Scripts\python.exe backend\manage.py check
.venv\Scripts\python.exe backend\manage.py test tests
```

## Session Log

### 2026-07-10 — Lean Docs + Remove workflows/

Completed:

- Removed `workflows/database_import.py`; view calls `DatabaseImportService` directly.
- Consolidated 8 long docs into `PRODUCT.md`, `DATABASE.md`, `OPS.md`.
- Deleted PRD, TRD, ARCHITECTURE, PROJECT_STRUCTURE, DATABASE_ARCHITECTURE, RUN, DEPLOY, ROADMAP.
- Updated `AGENTS.md`, `README.md`, `CHANGELOG.md`.
- 74 tests passing.

Pending:

- Extend `PRODUCT.md` / `DATABASE.md` as BOQ pipeline is rebuilt.

Next:

- Implement BOQ parsing on fresh design.

### 2026-07-10 — BOQ Pipeline Reset + Cleanup

- Upload-only BOQ; pipeline apps removed; logs/cache cleared.
- See `CHANGELOG.md` for details.
