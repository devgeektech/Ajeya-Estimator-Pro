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

### 2026-07-20 — Compact BOQ Detail Tab Bar

Completed: Tabs first with tight spacing; status + summary + Match on one row
below tabs on Analysis (Match right-aligned).
Pending: Hard-refresh BOQ detail; check all tabs.
Issues: —
Next: —

### 2026-07-20 — Analysis Scroll Performance + Match UI

Completed: Scroll lag fixes (content-visibility, no textarea resize, no input
transitions); inline db match summary; Make/Tech key hidden on product card;
Additional Attributes as horizontal chips.
Pending: Hard-refresh Analysis tab; scroll a long BOQ list to confirm smoothness.
Issues: —
Next: —

### 2026-07-20 — Product Tab Action Row

Completed: Tabs show Product 1/2/…; Add + Re-analyse + Remove on one row;
removed Product title/confidence header under the tabs.
Pending: Hard-refresh Analysis tab.
Issues: —
Next: —

### 2026-07-20 — Compact Analysis Product Cards

Completed: Densified Analysis UI (padding, fields, tabs, db match) and
scrollable attributes so a product card fits in the viewport.
Pending: Hard-refresh Analysis; verify on typical laptop height.
Issues: —
Next: —

### 2026-07-20 — Product Tabs on Analysis Cards

Completed: Multi-product BOQ lines use numbered tabs inside one card; Add
product sits after the tab numbers.
Pending: Hard-refresh Analysis tab.
Issues: —
Next: —

### 2026-07-20 — Analysis Card Actions Cleanup

Completed: Removed Save product; + Add product sits beside the product card
number on the last card of each line (autosave unchanged).
Pending: Hard-refresh Analysis tab.
Issues: —
Next: —

### 2026-07-20 — Silent Re-analyse + Scroll Restore

Completed: Re-analyse returns line HTML and swaps the row in place (no full
reload); detail page restores scroll position after refresh via sessionStorage.
Pending: Hard-refresh BOQ detail; try Re-analyse on a mid-page product.
Issues: —
Next: —

### 2026-07-20 — Material Maps to Class

Completed: Material from BOQ fills product Class (Rate_Master Class), not
Additional Attributes. Prompt + promote attributes.material→class with MS/SS/CI
aliases. Soft-fixed on display/save/rematch.
Pending: Hard-refresh Analysis; Re-analyse to persist.
Issues: —
Next: —

### 2026-07-20 — Product Unit vs BOQ Quantity UOM

Completed: Analysis product Unit is Rate_Master measurement (mm/cm/NB), not BOQ
Each. BOQ UOM maps to quantity_unit; size like 63mm derives unit mm. Soft-fixed
on display/save/rematch for existing analyses.
Pending: Hard-refresh Analysis tab; Re-analyse rows to persist corrected units.
Issues: —
Next: —

### 2026-07-17 — Category-Wise Make on Make & Vendor

Completed: Make & Vendor tab has Category makes panel — pick approved make per
category and Apply to all products in that category (then exact-match + rates).
Pending: Hard-refresh Make & Vendor tab.
Issues: —
Next: —

### 2026-07-17 — Make & Vendor Selection Tab

Completed: New Make & Vendor tab after Analysis. Expert selects make/supplier;
system exact-matches Rate_Master with analysis product fields + selection, then
loads material/labour rates via Tech_Key (`MakeVendorSelectionService`).
Pending: Hard-refresh BOQ detail; run Analyse then open Make & Vendor.
Issues: —
Next: Optionally feed vendor_selection into Match Results / export.

### 2026-07-17 — Confidence ≥80% Green

Completed: Confidence badges use green for scores 80% and above.
Pending: Hard-refresh Analysis tab.
Issues: —
Next: —

### 2026-07-17 — Flatten Nested AI Attributes in UI

Completed: Nested/stringified AI attribute blobs (e.g. ``attributes:
{'material': '...'}``) are coerced to normal key/value pairs for display,
extraction, mapping, and save.
Pending: Hard-refresh Analysis tab; optional Re-analyse to rewrite stored JSON.
Issues: —
Next: —

### 2026-07-17 — Unit Field After Capacity

Completed: Product card shows Unit after Capacity again. Extraction copies BOQ
row unit/qty onto products when AI leaves them blank; prompt clarifies row UOM.
Pending: Re-run Analyse on existing BOQs to refresh unit values.
Issues: —
Next: —

### 2026-07-17 — Auto Status Refresh + Product Autosave

Completed: Analyse/Match AJAX start with live status badge polling on detail;
BOQ list status column auto-updates while Analysing/Matching. Product fields
auto-save as typed; Re-analyse saves first then refreshes confidence.
Pending: Hard-refresh BOQ list + Analysis tab.
Issues: —
Next: —

### 2026-07-17 — Product Card UI Cleanup

Completed: Removed Unit and Preferred make from product card. Additional
Attributes no longer duplicate DB schema or product field keys. Re-analyse moved
from row header to product card actions beside Remove.
Pending: Hard-refresh Analysis tab to pick up template changes.
Issues: —
Next: —

### 2026-07-17 — Project Timestamps Use IST

Completed: All app-facing timestamps use Asia/Kolkata (IST). Shared
``utils.timestamps``; AI instruction log, match/confirm ISO stamps, JSON-safe
datetimes, and file/console logging formatters no longer emit UTC or host-local
time. Django ``TIME_ZONE`` / Celery already Kolkata.
Pending: Restart Django/Celery so new log formatter loads.
Issues: —
Next: —

### 2026-07-17 — Fix Analyse Decimal JSON Error

Completed: Product mapping ``db_candidates`` convert Rate_Master Decimal fields
to strings; ``analysis_data`` sanitized via ``utils.json_safe``; psycopg3 JSON
dumps use ``DjangoJSONEncoder`` so Analyse never fails on Decimal Size.
Pending: Restart Celery after pull, then re-run Analyse if status still failed.
Issues: —
Next: —

### 2026-07-17 — BOQ Upload Keep Files on Name Error

Completed: Removed BOQ name help text. Upload button is ``type=button`` + fetch JSON
so duplicate-name validation never reloads the page (file inputs stay selected).
Pending: Hard-refresh ``/boqs/upload/`` once.
Issues: —
Next: —

### 2026-07-17 — Make List → Category Mapping

Completed: Make-list descriptions map to Rate_Master categories (heuristic + AI
``map_make_list_categories``). Stored as ``category_mappings``; Make List tab shows
Mapped Category; Analysis/Match select approved makes by product category.
Pending: Open BOQ detail to persist mappings on existing uploads.
Issues: —
Next: —

### 2026-07-17 — DB-Only Product Match + Rematch

Completed: Analyse no longer force-picks weak Rate_Master rows or invents
Tech_Key; confirmed match only when confidence ≥ 30%. Provisional matches expose
Attribute schema + missing keys for expert fill. Re-analyse rematches with
filled attributes (`rematch_row`). Candidates stored on each product.
Pending: Re-run Analyse on existing BOQs to refresh mapping status.
Issues: —
Next: —

### 2026-07-16 — Make List Exact Sheet Only

Completed: Make-list Excel parse picks only the MAKE LIST sheet (not rate/DMRC
sheets); payload slimmed to S.No / Description / Approved Makes; polluted stored
JSON re-parses from the uploaded file on load; UI prefers MAKE LIST rows when
legacy multi-sheet data is present. Verified BOQ `111111111111111111` → 50 rows.
Pending: Hard-refresh Make List tab if browser cached old page.
Issues: —
Next: —

### 2026-07-16 — Make List Tab Columns Fix

Completed: Make List UI shows only S.No / Description / Approved Makes; Excel
parse no longer merges unrelated sheets; make-column detection excludes rate/qty
noise. Refresh the BOQ detail Make List tab to see the fix.
Pending: —
Issues: —
Next: —
### 2026-07-16 — Extract Category Free-Text; Categories-Only Context

Completed: Extract always outputs category + free-text sub_category; DB context
for extract is categories-only (no subcategory list). Map prompt clarifies
`rate_master_id` = Rate_Master PK and uses extracted category/sub_category.
Pending: Re-run Analyse to pick up prompt/context changes.
Issues: —
Next: —

### 2026-07-16 — BOQ Hierarchy + Analyse Pipeline Hardening

Completed: Hardened upload hierarchy (spec/roman under lettered products, Cont.
serials, indent fallback, multi-sheet merge, fail-loud empty parses); PDF make-list
continuation merge; anchor rules use children_map; extract prompt + MS/DI/CI value
synonyms; refreshed `media/extract_json` for 000/test/1 from BOQ_4/BOQ_1.
Pending: Re-run Analyse on fixture BOQs so analysis_data picks up new lineage.
Issues: —
Next: Estimator re-Analyse on 000/test after hierarchy refresh.

### 2026-07-16 — AI Product + Attribute Mapping on Analyse

Completed: Added `ProductAIMappingService` + `map_product_match` prompt. Analyse
recalls Rate_Master candidates, AI selects product and maps attributes onto DB
schema, service confidence shown with matched product summary on Analysis UI.
Pending: Refresh Analysis tab / re-run Analyse to populate mappings.
Issues: —
Next: —

### 2026-07-16 — Backfill DB Attribute Schema on Analysis

Completed: Attribute enrichment uses SQL-first Rate_Master lookup; Analysis page
backfills missing `attribute_schema` so DB Attribute keys show (empty when AI
missed them) and AI-only keys stay under Additional Attributes.
Pending: —
Issues: —
Next: Refresh Analysis tab on BOQ 000 to attach schemas.

### 2026-07-16 — DB Schema Attributes UI

Completed: Attributes section shows full DB schema (empty or filled); AI-only
keys listed under Additional Attributes.
Pending: Re-run Analyse to refresh attribute_schema on existing products.
Issues: —
Next: —

### 2026-07-16 — Fix Analysis Confidence + Row Mapping + Extraction

Completed: Attribute confidence no longer defaults to 100% without a DB schema;
qty reads Total/Ground/Basement; lettered priced lines become anchors; resolve
anchor stops at nearest real anchor; consolidate uses group_ids only.
Pending: Re-run Analyse on affected BOQs to refresh analysis_data.
Issues: —
Next: —

### 2026-07-16 — Heuristic Make-List Column Roles

Completed: Make-list columns are resolved from header + cell-content scores so
unknown labels (Material/Description/Item vs Make/Name/Manufacturer) still map
correctly; `column_roles` stored on make_list_data.
Pending: —
Issues: —
Next: —

### 2026-07-16 — Make List Column + Separator Parsing

Completed: Recognized `Make/Manufacturers Name` (and similar) columns; split
makes on `/`, `,`, `;`, `|` into `approved_makes_list`; re-normalize stale empty
lists on BOQ load.
Pending: —
Issues: —
Next: Open BOQ detail so DB make_list_data persists the fix if still empty.

### 2026-07-16 — Dynamic Analyse Attributes + Confidence

Completed: Analyse now searches Rate_Master after AI extract, drives attribute
fields from the matched product's Attribute keys, fills extracted values, and
shows attribute-fill confidence with green/yellow/orange/red bands.
Pending: Re-run Analyse on an existing BOQ to refresh attribute schemas.
Issues: —
Next: Verify Analyse UI on a real BOQ with active master DB.

### 2026-07-16 — Fix is_anchor_row Type Annotation

Completed: Typed `children_map` as `dict[str, list[str]] | None` so the default
`None` is valid for basedpyright.
Pending: —
Issues: —
Next: —

### 2026-07-14 — Analysis Product Actions Layout

Completed:

- Moved **+ Add product** beside **Save product**; renamed Other details to
  **Additional Attributes** with **+ Add attribute**.

### 2026-07-14 — Optional Product Fields + Filled-Only Matching

Completed:

- Class, size, capacity, unit, and related product fields are optional in Analysis UI.
- Matching uses only filled properties for Chroma query, structured score, and SQL
  fallback (null/blank omitted).
- Extraction prompt tightened for evidence-based fields and correct products.

### 2026-07-14 — Match Results Icons + Extraction Fixes

Completed:

- Match Results: compact icon Confirm / Re-match; hide lineage stub rows.
- Spec filter no longer drops products like "Pressure switch" / "Flow switch".
- Extraction activities use work verbs (Installation, Testing, …), not Labour_Type.

### 2026-07-14 — Per-Row Re-analyse / Re-match

Completed:

- Top toolbar no longer shows full-BOQ Re-analyse / Re-match; use per-row actions.
  First-time **Analyse BOQ** and **Match** remain when needed.

### 2026-07-14 — Preferred Make Lowest Price Option

Completed:

- Added Preferred make **Lowest price** option; matching selects cheapest Rate_Master
  among approved makes.

### 2026-07-13 — Make List Column Parsing Fix

Completed:

- Make list parser now reads `Makes` / `Materials` columns (not only
  `approved_makes*`); stale BOQ make-list JSON is normalized on load.

### 2026-07-13 — Analysis Summary Cleanup

Completed:

- Removed duplicate Analysis tab summary; top of page now shows one extraction
  summary line.
- Removed the redundant outer panel styling from the Analysis tab while keeping
  individual product-group cards.

### 2026-07-13 — Analysis Tab Inline Editing

Completed:

- Product description uses wrapped textarea; make auto-saves on selection.
- Specifications use + Add for other details without page reload.
- Save product uses AJAX and preserves scroll position.

### 2026-07-13 — Anchor-Level Product Extraction

Completed:

- Grouped anchor extraction + spec-line filter; Analysis UI shows short
  description with ellipsis and grouped-lines dropdown.
- Display merges products from all grouped lineage rows (fixes anchor/child mismatch).
- Extraction consolidates AI products onto anchor row_id.

Pending:

- Re-run **Analyse** on existing BOQs to refresh extraction results.

### 2026-07-13 — Two-Sheet Excel Export

Completed:

- `BOQExportService` writes **BOQ** + **Charge Breakdown** sheets on export.

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
