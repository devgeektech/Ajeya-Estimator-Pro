# Changelog

Meaningful product and technical changes only. Older history is in git.

## 2026-07-13 — Make List Column Parsing Fix

- Make list ingestion now reads standard `Makes` and `Materials` columns; existing
  BOQ make-list JSON is re-normalized on load when approved makes were empty.

## 2026-07-13 — Analysis Summary Cleanup

- Removed redundant Analysis tab extraction summary so the page shows one
  concise status line.
- Flattened the Analysis tab container to remove the unnecessary outer card.

## 2026-07-13 — Analysis UX: Full Text, Lineage, Simple Attributes

- Analysis rows show full BOQ text (no truncation) and group serial `1` with all
  child lineage rows; make dropdown uses category-based make-list options plus
  custom make; attributes use simple fields instead of JSON.

## 2026-07-13 — Anchor-Level Product Extraction

- Extraction now runs on grouped anchor rows (not every child line), so spec
  lines like Speed/Capacity/Head become attributes instead of separate products.
- Analysis tab shows anchor description with ellipsis and grouped-lines dropdown.

## 2026-07-13 — Two-Sheet Excel Export

- Export workbook now has **BOQ** (original layout with filled rate/amount) and
  **Charge Breakdown** (detailed material/labour columns).

## 2026-07-13 — AI Instruction Logging

- All AI calls (chat completions and embeddings) append full instructions and
  responses to `logs/instructions.log` only.

## 2026-07-13 — Multi-Product Rows + Match Results JSON

- Analysis tab supports multiple products per BOQ row with add/remove controls.
- Matching writes `boq_match_results.json` with full `product_matches` for internal audit.

## 2026-07-13 — Interactive Analysis Tab (Product Edit + Make List)

- Analysis tab shows editable extracted product fields with missing values highlighted.
- Users can save corrections and pick a preferred make from matched make-list lines
  before running Match; matching uses the selected make as a hard filter.

## 2026-07-13 — BOQ Detail Tab Gating + List View Routing

- BOQ list **View** opens the BOQ, Analysis, or Match Results tab based on status.
- Analysis and Match Results tabs stay greyed out until those steps have been run.
- Toolbar actions ordered left-to-right: Re-analyse, Re-match, Export (coloured buttons).

## 2026-07-13 — BOQ List Status Badges

- BOQ list page uses the same color-coded status labels and badge styles as the
  detail page (Uploaded, Analysing, Analysis completed, Matching, etc.).

## 2026-07-13 — Two-Step Analyse + Match Workflow

- **Analyse** on BOQ detail extracts products/activities only (`EXTRACTED` status).
- **Match** button runs database matching and opens a dedicated match results page
  (`PROCESSED` status) with rates, confirm, and export.

## 2026-07-13 — Analysis Preserves Upload Row Order

- Extraction, analysis output, Analysis tab, and Excel export now follow the same
  row order and indentation as the uploaded BOQ sheet (section rows included).

## 2026-07-13 — BOQ Serial Hierarchy Fix

- Fixed parent/child linking for rows without S.No. (continuation lines stay under
  the current `1` / `1.1` section) and for `a)` / `b)` / `c)` rows inferred from
  description text; alpha siblings now share the same structural parent.

## 2026-07-13 — Production Celery + Redis

- BOQ analysis dispatches to Celery when Redis and a worker are available; production
  returns a clear error if either is missing (DEBUG still falls back to sync).
- Added `/boqs/<id>/status/` polling endpoint and auto-reload on the Analysis tab.
- Added `manage.py check_celery` and `scripts/run_celery_worker` helpers.
- Expanded Celery settings and OPS/README for local three-terminal async setup.

## 2026-07-13 — Analysis Loading UI + Broker Fallback

- Added visual separators between BOQ / Make List / Analysis tabs.
- Run analysis button now switches to yellow **Analysing...** state with row-style
  loading placeholders in the Analysis tab.
- Analysis dispatch runs inline in debug/local mode and checks Redis availability
  before queueing Celery, preventing silent no-op clicks when Redis is unavailable.

## 2026-07-13 — Session Confirmations + Labour Column Mapping

- Replaced database review overrides with session-only line confirmation (all users).
- Labour retrieval maps `Labour_Master` charge columns by `Tech_Key` (size-aware);
  effective labour rate uses precomputed total-with-multiplier column when present.
- Removed `BOQ.review_data`; Excel export adds labour component columns.

## 2026-07-13 — BOQ Analysis Phase 2 (Enrichment, Review, Export)

- Rate and labour detail retrieval by `rate_master_id` / `Tech_Key`; priced line output
  from precomputed master values.
- **Analysis** tab on BOQ detail with match status, confidence, and rates.
- Session-only confirmation flow; candidate dropdown per pending line.
- Excel export via `BOQExportService` and `/boqs/<id>/export/`.

## 2026-07-13 — BOQ Analysis Pipeline (Phase 1)

- AI multi-product extraction from `rows_tree` via `gpt-4o-mini`
  (`BOQExtractionService`).
- Structured matching: Chroma recall + column/attribute scoring
  (`ProductMatchingService`); make-list hard filter (`MakeListConstraintService`).
- Results saved to `BOQ.analysis_data` and `media/extract_json/{boq_name}/boq_analysis.json`.
- BOQ detail **Run analysis** action; Celery task `boq.process_analysis`.
- Added `utils/attribute_parser.py`; restored `ai/context.py` and `ai/service.py`.

## 2026-07-10 — Remove Unused AI Code

- Deleted unused `ai/service.py`, `ai/context.py`, and `ai/prompts/test_json.txt`.
- Trimmed dead `load_prompt`, Chroma `query`, and AI instruction logging config.

## 2026-07-13 — Make List Slash Split + Analysis Plan

- Make lists split `A/B/C` make cells into `approved_makes_list` per row (schema v2).
- Documented multi-product extraction and structured matching approach in PRODUCT.md.

## 2026-07-13 — Nested rows_tree for AI Extraction

- Extract JSON now includes `rows_tree`: nested hierarchy with `fields` (from
  `display_values`) and `children` for AI product/activity extraction.

## 2026-07-13 — Unique BOQ Names

- BOQ names are unique (case-insensitive) at upload and in PostgreSQL, preventing
  duplicate `media/extract_json/{boq_name}/` folders.

## 2026-07-13 — Dynamic PDF Parsing + extract_json Storage

- Replaced hardcoded material word lists in PDF make-list parsing with dynamic
  text-boundary heuristics (`utils/text_boundary.py`).
- Normalized BOQ/make-list JSON is persisted under `media/extract_json/{boq_name}/`
  on upload and refreshed when the View page is opened.

## 2026-07-13 — Make List PDF Description Fix

- PDF parser no longer treats fused description+make text as a brand-only column;
  Description cells render correctly for slash-separated make-list PDF rows.

## 2026-07-10 — Default Chat Model → gpt-4o-mini

- Switched default `OPENAI_MODEL` from `gpt-5-mini` to `gpt-4o-mini` for lower-cost,
  low-latency BOQ extraction. Embeddings unchanged (`text-embedding-3-small`).

## 2026-07-10 — PDF Make List + Robust Excel Parsing

- PDF make lists now parse into S. No. / Description / Approved Makes columns instead
  of a single Text column; handles slash-separated makes and fused title lines.
- Excel reader scores all worksheets (up to 50 header-scan rows) and picks the best
  sheet for BOQ and make-list uploads; BOQ also expands spill columns.

## 2026-07-10 — BOQ Sheet Display Cells

- Moved cell value lookup from Django template tags into
  `serial_normalizer.cell_value` / `structure_for_display`; templates render
  pre-built `row.cells` lists.

## 2026-07-10 — BOQ Normalized JSON + View Tabs

- Upload parses BOQ/make list into hierarchical JSON (`boq_data`, `make_list_data`).
- Make list supports PDF; View page has BOQ and Make List tabs with indented rows.
- List action changed from Open link to blue View button.

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
