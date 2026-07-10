# BOQ_AI Session State

Compact active memory. Full spec: `docs/PRODUCT.md`. Schema: `docs/DATABASE.md`.

## Current Status

- **Phase:** BOQ pipeline rebuild (upload-only base; master DB import active)
- **Migrations:** Fresh `0001_initial` per app (reset 2026-07-10); applied to local `boq_db`
- **Tests:** Suite removed — needs restoration
- **Runtime:** `config.settings`, PostgreSQL, Django templates + HTMX
- **Active apps:** accounts, users, database_manager, boq, dashboard, notifications, audit
- **Removed:** processing, matching, costing, review, exports, make_list, `workflows/`

## Active Workflows

**Database:** upload → validate → import → activate → embeddings (sync). Last 10
uploads visible; no rollback.

**BOQ:** upload workbook (+ optional make list) → stored → dashboard

## Pending

- Rebuild BOQ parse → process → match → review → export
- Restore `backend/tests/` suite
- Run fresh migrations on EC2 after deploy (squashed history — new DB or drop + migrate)

## Verify

```powershell
.venv\Scripts\python.exe backend\manage.py check
.venv\Scripts\python.exe backend\manage.py test tests
```

## Session Log

### 2026-07-10 — Canonical Master Sheet Names

Completed:

- Removed workflow model aliases (`MaterialRate`, `LabourMaster`, `CategoryConfig`, etc.).
- Updated AI context and embedding modules to use canonical sheet/model names.
- Chroma metadata now uses `rate_master_id` (reads legacy `material_rate_id`).

Next:

- `createsuperuser`; import master workbook; rebuild BOQ pipeline.

### 2026-07-10 — Remove Rollback; Embedding Consolidation

Completed:

- Removed rollback service, URL, view, and UI.
- Retention: last 10 uploads for view/download; Chroma active-only embeddings.
- Merged embedding modules into `ai/embeddings/generator.py`.
- Structured embedding document + metadata for product search fields.

Next:

- `createsuperuser`; import master workbook; rebuild BOQ pipeline.

### 2026-07-10 — Migration Reset (Fresh DB)

Completed:

- Deleted all prior migrations (16 files across 5 apps).
- Regenerated single `0001_initial` per app from current models.
- Granted PG 15+ `public` schema permissions; `migrate` applied successfully.
- `manage.py check` passes.

Pending:

- `createsuperuser` on fresh local DB.
- EC2 migration reset when deploying squashed history.

Next:

- Create superuser; import master workbook; restore tests.

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
