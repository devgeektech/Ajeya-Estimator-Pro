# BOQ_AI Session State

Compact active memory. Full spec: `docs/PRODUCT.md`. Schema: `docs/DATABASE.md`.

## Current Status

- **Phase:** BOQ pipeline rebuild (upload-only base; master DB import active)
- **Migrations:** Fresh `0001_initial` per app (reset 2026-07-10); applied to local `boq_db`
- **Tests:** Suite removed — needs restoration
- **Runtime:** `config.settings`, PostgreSQL, Django templates + HTMX
- **Active apps:** accounts, users, database_manager, boq, dashboard, notifications, audit
- **Removed:** processing, matching, costing, review, exports, make_list, pending_products, `workflows/`, `tasks/`, `exports/`, `ai/extractors/`

## Active Workflows

**Database:** upload → validate → import → activate → embeddings (sync). Last 10
uploads visible for view/download; only the active upload keeps master rows in
PostgreSQL.

**BOQ:** upload workbook (+ optional make list) → parse to JSON → view tabs →
run analysis → session confirmations → export Excel

## Pending

- Restore `backend/tests/` suite
- Run fresh migrations on EC2 after deploy (squashed history — new DB or drop + migrate)

## Verify

```powershell
.venv\Scripts\python.exe backend\manage.py check
.venv\Scripts\python.exe backend\manage.py test tests
```

## Session Log

### 2026-07-13 — AI Instruction Logging

Completed:

- `ai/instruction_log.py` appends each AI exchange to `logs/instructions.log`.

### 2026-07-13 — Multi-Product Rows + Match Results JSON

Completed:

- Add/remove products per BOQ row on the Analysis tab; AI prompt asks for
  `description_hint` when a row has multiple products.
- `boq_match_results.json` persisted after Match with full product match snapshots.

### 2026-07-13 — Interactive Analysis Tab

Completed:

- `BOQExtractionEditService` + `POST /boqs/<id>/extraction/edit/` for product field
  edits and make-list make selection on the Analysis tab.
- Missing extraction fields highlighted; matching respects user-selected make.

### 2026-07-13 — BOQ Detail Tab Gating + List View Routing

Completed:

- Status-based **View** links on the BOQ list (`boq` / `analysis` / `match_results` tabs).
- Greyed-out Analysis and Match Results tabs until Analyse / Match have been run.
- Toolbar button order and colours: yellow analyse, red match, green export.

### 2026-07-13 — BOQ List Status Badges

Completed:

- BOQ list page reuses `build_boq_status_display()` for the same labels and badge
  colors as the detail toolbar (including session-based Exported state).

### 2026-07-13 — Two-Step Analyse + Match Workflow

Completed:

- Split pipeline: **Analyse** (AI extraction, `EXTRACTED`) on detail Analysis tab;
  **Match** (DB matching, `PROCESSED`) on `/boqs/<id>/match-results/`.
- New services/views/tasks: `BOQExtractionDisplayService`, extract/match Celery tasks,
  `BOQExtractView`, `BOQMatchView`, `BOQMatchResultsView`.
- Migration `0007_boq_extracted_status`.

Next:

- Re-run Analyse + Match on a test BOQ to verify two-step UX end-to-end.

### 2026-07-13 — Production Celery + Redis

Completed:

- `boq_analysis_dispatch` service: async queue when broker + worker available; clear
  errors in production when Redis/worker missing; DEBUG sync fallback retained.
- `GET /boqs/<id>/status/` JSON endpoint for analysis polling.
- BOQ detail page auto-polls while `PROCESSING` and reloads on completion.
- `manage.py check_celery` health command; `scripts/run_celery_worker.*`.
- Celery production settings (serializers, broker retry, result expiry).
- OPS / README / `.env.example` updated for three-terminal local async setup.

Pending:

- Restore `backend/tests/` suite
- Run fresh migrations on EC2 after deploy

Next:

- End-to-end verify on EC2 with `check_celery` + Run analysis on a real BOQ

### 2026-07-13 — Analysis Loading UI + Broker Fallback

Completed:

- Added tab separators for BOQ / Make List / Analysis.
- Run analysis button switches to yellow **Analysing...** state before submit.
- Analysis tab shows product-row loading placeholders while request is in progress.
- Analysis dispatch runs synchronously in debug/local mode and checks Redis availability
  before queueing to Celery.

### 2026-07-13 — Analysis Dispatch + Extract Flow Fix

Completed:

- Run analysis falls back to synchronous execution when Redis/Celery is unavailable.
- `CELERY_TASK_ALWAYS_EAGER` defaults to `DEBUG` for local dev without a worker.
- BOQ detail view reads stored `boq_data` / `make_list_data` (no re-parse each load).
- Analysis uses stored extract JSON; creates `boq_analysis.json` only (not duplicate parse JSON).

### 2026-07-13 — Session Confirmations + Labour Column Mapping

Completed:

- Replaced DB-backed review overrides with session-only **Confirm** flow (all users).
- Labour charges gathered by `Tech_Key` with explicit `Labour_Master` column mapping;
  effective rate uses `Total_Labour_per_unit_with_labour_Multipler` fallback chain.
- Removed `BOQ.review_data`; export includes labour component breakdown columns.

### 2026-07-13 — BOQ Analysis Phase 2 (Enrichment, Review, Export)

Completed:

- `RateDetailRetrievalService` and `LabourDetailRetrievalService` (Tech_Key linkage).
- `BOQLineOutputService`, `BOQAnalysisEnrichmentService` (schema v2 analysis).
- **Analysis** tab on BOQ detail; session confirmation flow for selected products.
- `BOQExportService` + **Export Excel** download.

Pending:

- Pending products approval flow; labour-by-activity matching; tests.

Next:

- Run end-to-end on `test` BOQ; tune matching thresholds.

### 2026-07-13 — BOQ Analysis Pipeline (Phase 1)

Completed:

- Rebuilt `ai/context.py`, `ai/service.py`, and `ai/prompts/extract_products.txt`.
- Added `utils/attribute_parser.py`, extraction/matching/make-list constraint services,
  `BOQAnalysisService`, and `boq_analysis.json` persistence.
- Chroma `query_similar` for retrieval; `BOQ.analysis_data` + status
  (`PROCESSING` / `PROCESSED` / `ANALYSIS_FAILED`).
- BOQ detail **Run analysis** button; Celery task `boq.process_analysis`.

Pending:

- Analysis results tab in UI; confirmation workflow; labour linkage; export.

Next:

- Run analysis on `test` BOQ with active DB + OpenAI key; add unit tests.

### 2026-07-10 — Remove Unused AI Code

Completed:

- Deleted unused `ai/service.py`, `ai/context.py`, and `ai/prompts/test_json.txt`.
- Trimmed dead Chroma `query` API and AI instruction logging config.

### 2026-07-13 — Unique BOQ Names

Completed:

- Case-insensitive unique constraint on `boq_name`; upload form rejects duplicates.

### 2026-07-13 — Dynamic PDF Parsing + extract_json Storage

Completed:

- Dynamic make/description splitting via `utils/text_boundary.py` (no hardcoded
  material word lists).
- `media/extract_json/{boq_name}/boq_data.json` and `make_list_data.json` written
  on upload and refreshed on View.

### 2026-07-13 — Make List PDF Description Fix

Completed:

- Fixed PDF make-list parsing where description text was merged into Approved Makes
  (empty Description column in UI for rows like "M.S Pipes TATA/...").

### 2026-07-10 — PDF Make List + Robust Excel Parsing

Completed:

- Structured PDF make-list parser (`pdf_make_list_parser.py`) with column layout
  matching Excel output.
- Excel reader scans all sheets and up to 50 rows for header detection; BOQ uses
  `expand_columns` for wide sheets.

### 2026-07-10 — BOQ Normalized JSON + View Tabs

Completed:

- `boq_data` / `make_list_data` JSON on upload with serial-based hierarchy.
- View page tabs (BOQ, Make List); PDF make-list support.

### 2026-07-10 — Active-Only Master Data Retention

Completed:

- Version history and Excel files are retained; inactive master rows are purged
  after each import.
- Cleaned `database_manager/models.py` (removed aliases/properties).

### 2026-07-10 — Single Active Database Retention

Completed:

- Import now purges all previous database versions and master rows; only the
  active upload is retained.

### 2026-07-10 — BOQs List Page

Completed:

- BOQs list at `/boqs/` with toolbar count, `+ Upload BOQ`, and table columns
  (Name, Owner, Status, Created, Actions).
- Sidebar nav renamed to BOQs; upload at `/boqs/upload/`; detail view for Open.

### 2026-07-10 — Batched Embedding Generation

Completed:

- Batched OpenAI embedding API calls and Chroma upserts (default 500 rows).
- Row-wise storage unchanged: each `Rate_Master` row keeps its own vector and
  `tech_key` metadata for search resolution.

### 2026-07-10 — Remove Orphan Folders

Completed:

- Deleted empty removed-app shells under `backend/apps/` (costing, processing,
  matching, review, exports, make_list, pending_products).
- Deleted leftover `backend/workflows/`, `backend/tasks/`, `backend/exports/`,
  and `backend/ai/extractors/` (`__pycache__` only).

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
