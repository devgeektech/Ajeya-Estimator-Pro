# Changelog

Meaningful product and technical changes only. Older history is in git.

## 2026-07-22 — Analysis Spinner Fix (Small CSS Spinner)

- Replaced the broken large SVG ring with a small animated CSS spinner, live
  percentage, and title “Analysing BOQ And Extracting Products”.

## 2026-07-21 — Analysis Loading Spinner + Percent

- Analysis loading panel shows progress percent and status label while Analyse
  runs (progress from extraction + DB mapping batches).

## 2026-07-21 — Analysis Stay + Next Prefills Lowest Make/Vendor

- After Analyse completes, stay on the **Analysis** tab (no auto-jump to Make & Vendor).
- Re-analyse restores scroll to the same line position (row-relative offset).
- **Next** on Analysis runs `apply_lowest_defaults` (lowest approved make/vendor on all
  products), then opens Make & Vendor. Cascade shows filter preview + applied filters list.

## 2026-07-21 — Make & Vendor Client Approach Doc

- Added `docs/MAKE_VENDOR_APPROACH.md` for client review of the experimental
  Make & Vendor cascade (rules, demo script, decision checklist).

## 2026-07-21 — Align Category to Matched DB Product

- After Analysis DB mapping, product `category` / `sub_category` are aligned to the
  matched or suggested Rate_Master row so Make & Vendor taxonomy matches the DB product.
- Re-analyse affected rows (or the full BOQ) to refresh existing extractions.

## 2026-07-21 — Make & Vendor Sub-category Cascade

- Make & Vendor tab: cascade **category → sub-category → approved make → supplier**
  (lists limited to categories/sub-categories from Analysis extraction).
- Apply to sub-category updates all products in that sub-category; default matching uses
  lowest price among approved makes (make list is source of truth for makes).
- Stored in `analysis_data.subcategory_make_selections`.

## 2026-07-21 — Serial-lineage Extraction Sections

- Analysis/extraction groups by serial lineage: parent item (e.g. ``1``) plus
  children (``1.1``, ``1.2``, specs) form one section so shared description is
  available when extracting multiple products.
- Amounts still come only from filled Unit/Qty cells inside the section
  (``0`` and ``Rate Only`` / ``boq_rate`` preserved per qty line).
- Re-run Analyse after deploy (re-upload if hierarchy is stale).

## 2026-07-21 — Quantity-block Extraction

- Superseded by serial-lineage sections (same-day correction).

## 2026-07-20 — Category + Sub-category Taxonomy Mapping

- Database context for extraction includes `sub_categories_by_category`.
- Make-list AI mapping and Analysis extraction prefer Rate_Master Category /
  Sub_Category labels; values are snapped to existing DB labels after mapping.

## 2026-07-20 — Next on Analysis, Match on Make & Vendor

- Analysis toolbar shows blue **Next** (opens Make & Vendor).
- Red **Match** button moved to the Make & Vendor toolbar.

## 2026-07-20 — Row-wise Analysis (No Merged Variants)

- Lettered BOQ lines (`a)`, `(A)`, sized variants) are separate Analysis anchors
  instead of being combined into the parent item.
- Section romans (`I`/`II`/`III`…) stay top-level; blank Speed/Head/Capacity specs
  nest under the nearest product/structural item.
- Re-upload the BOQ (or upload a new copy) so stored hierarchy is rebuilt, then
  run Analyse again.

## 2026-07-20 — Additional Attributes Layout + Attribute Labels

- Additional Attributes: bold heading (not chip), hint on the right, name/value
  inputs on the heading row, chips on the row below.
- Attributes hint text: “Attributes found in Database — AI-mapped values filled
  where found”.

## 2026-07-20 — Compact BOQ Detail Tab Bar

- Tabs sit at the top with minimal padding; status, tab summary, and actions share
  one row below the tabs. On Analysis: status badge, product/activity summary, and
  Match button aligned on the right.

## 2026-07-20 — Analysis Scroll Performance + Match UI

- Reduced Analysis tab scroll lag: `content-visibility` on lines, removed textarea
  auto-resize and input transitions, dropped scroll listener (scroll restore via
  sessionStorage on reload only).
- Database match shows inline summary next to heading; Make and Tech key removed
  from the product card.
- Additional Attributes use horizontal chips (content-width) like Activities.

## 2026-07-20 — Horizontal Activities Row

- Activities show inline: highlighted **Activities** heading, chips in a row, and
  **+** to add (with remove on each chip when editing).

## 2026-07-20 — Product Tab Action Row

- Tabs labeled Product 1 / Product 2; Add, Re-analyse, and Remove sit on one
  horizontal row. Removed the duplicate Product title + confidence header.

## 2026-07-20 — Compact Analysis Product Cards

- Tightened Analysis card padding/gaps, clamped description to one line, and
  made the attributes block scroll inside the card so one product fits on screen.

## 2026-07-20 — Product Tabs on Analysis Cards

- Multiple products on a BOQ line use numbered tabs (1, 2, 3…) instead of a
  stacked list; + Add product sits beside the tab numbers.

## 2026-07-20 — Analysis Card Actions Cleanup

- Removed Save product button (autosave remains).
- Moved + Add product next to the product card number (last card title).

## 2026-07-20 — Silent Re-analyse + Scroll Restore

- Re-analyse swaps the updated row HTML in place (no full page reload); scroll
  position is preserved.
- Analysis (and other detail tabs) restore scroll from sessionStorage after
  browser reload / refresh.

## 2026-07-20 — Material Maps to Class

- Extraction puts material/construction into product ``class`` (Rate_Master
  ``Class``: MS, SS, CI, …), not Additional Attributes.
- Misplaced ``attributes.material`` is promoted into ``class`` on display/save/
  rematch; common abbreviations normalized (mild steel→MS, etc.).

## 2026-07-20 — Product Unit vs BOQ Quantity UOM

- Product ``unit`` maps to Rate_Master ``Unit`` (mm, cm, NB, …), not BOQ qty UOM.
- BOQ row Each/Nos/Mtr fills ``quantity`` / ``quantity_unit`` only.
- Extraction prompt and backfill updated; qty UOMs misplaced in ``unit`` are
  moved to ``quantity_unit`` and measurement unit is derived from size when
  present (e.g. ``63mm`` → unit ``mm``).

## 2026-07-17 — Category-Wise Make on Make & Vendor

- Category makes panel lists each analysed product category with approved makes
  from the make list.
- **Apply to category** sets that make on every product in the category and loads
  rates via exact Rate_Master match + Tech_Key.

## 2026-07-17 — Make & Vendor Selection Tab

- New **Make & Vendor** tab after Analysis for make/supplier selection.
- ``MakeVendorSelectionService`` combines analysis product fields with the chosen
  make/supplier, exact-matches ``Rate_Master``, and loads rates via ``Tech_Key``.
- AJAX ``POST /boqs/<id>/make-vendor/`` persists ``vendor_selection`` on each product.

## 2026-07-17 — Confidence ≥80% Green

- Confidence color bands: ≥80 green, >70 yellow, >50 orange, else red.

## 2026-07-17 — Flatten Nested AI Attributes in UI

- Coerce nested/stringified attribute payloads so Additional Attributes show
  ``material: thermo plastic…`` instead of ``attributes: {'material': …}``.
- Applied in display, extraction cleanup, AI mapping, enrichment, and save.

## 2026-07-17 — Unit Field After Capacity

- Product card shows Unit after Capacity again.
- Extraction backfills ``unit`` / ``quantity`` / ``quantity_unit`` from the BOQ
  row UOM when the model leaves them blank.

## 2026-07-17 — Auto Status Refresh + Product Autosave

- Analyse/Match start via AJAX; detail status badge polls and reloads when done.
- BOQ list status column polls in-progress jobs and updates without manual refresh.
- Product card autosaves typed fields/attributes; Re-analyse persists first then
  rematches and reloads so confidence reflects filled values.

## 2026-07-17 — Product Card UI Cleanup

- Removed Unit and Preferred make fields from the Analysis product card.
- Additional Attributes exclude keys already shown in the product grid or DB
  attribute schema (fixes duplicate size/description/material entries).
- Re-analyse button moved next to Remove on each product card.

## 2026-07-17 — Project Timestamps Use IST

- App ISO timestamps (instruction log, match results, confirmations) and
  ``json_safe`` datetimes now use Asia/Kolkata via ``utils.timestamps``.
- Application / error / instruction file logging ``asctime`` uses IST
  (``common.logging_formatters.LocalTimeFormatter``), not host-local or UTC.
- DB still stores UTC with ``USE_TZ=True``; UI already rendered in ``TIME_ZONE``.

## 2026-07-17 — Fix Analyse Decimal JSON Error

- ``db_candidates`` now stores Rate_Master ``Size`` as JSON-safe strings (was
  Decimal, broke ``analysis_data`` save during Analyse).
- All ``analysis_data`` writes pass through ``utils.json_safe`` before PostgreSQL
  JSONField save.
- Register ``DjangoJSONEncoder`` with psycopg3 JSON dumps so Decimal never
  crashes Analyse persistence.

## 2026-07-17 — BOQ Upload Keep Files on Name Error

- Duplicate BOQ name validation no longer clears selected workbook/make-list files
  (AJAX submit + name check). Change the name and retry without re-selecting files.

## 2026-07-17 — Make List → Category Mapping

- Map make-list free-text descriptions onto Rate_Master categories (heuristic + AI).
- Store ``category_mappings`` on make-list JSON; show Mapped Category on Make List tab.
- Preferred-make dropdown and Match filter use category-mapped approved makes.

## 2026-07-17 — DB-Only Product Match + Attribute Rematch

- Stopped forced top-candidate attach; Tech_Key / ``db_product_id`` only when
  blended confidence ≥ 30%.
- Provisional / unmatched statuses expose Attribute schema gaps for expert fill.
- Per-row Re-analyse rematches existing products with filled attributes
  (``rematch_row``); no invented catalog products.
- Analysis UI shows match status, missing attributes, and top DB candidates.

## 2026-07-16 — Make List Parser: Only Real Make Sheet

- Sheet scoring prefers ``MAKE LIST`` / make columns; no longer picks huge rate sheets.
- Payload slimmed to S.No + Description + Approved Makes; junk header rows dropped.
- Polluted stored make-list JSON re-parses from the uploaded file on page load
  (multi-sheet / rate-header detection, not only header/row counts).
- Make List UI prefers MAKE LIST sheet rows when legacy mixed-sheet JSON remains.

## 2026-07-16 — Make List Tab Columns Fix

- Make-list Excel parse uses the single best sheet (no multi-sheet merge).
- Make List UI shows only S.No, Description/Material, Approved Makes.
- Stricter make-column detection excludes rate/qty/unit/dia noise columns.

## 2026-07-16 — Map Uses Rate_Master.id (Not a rate_master_id Column)

- Clarified AI map payload: candidate `id` = Django `Rate_Master.id` PK.
  There is no `rate_master_id` column on Rate_Master; that name was only a JSON alias.
- `PRODUCTS_PAYLOAD` is built at runtime in `ProductAIMappingService._run_ai_batches`.

## 2026-07-16 — Extract Category Free-Text; Categories-Only DB Context

- Extract prompt always fills category + sub_category from BOQ meaning; subcategory
  may be free-text (not limited to DB lists). Map step reconciles to Rate_Master.
- `build_database_context` sends categories + attribute_keys + activities only
  (no huge subcategory dump). `rate_master_id` documented as Rate_Master PK.

## 2026-07-16 — BOQ Hierarchy + Analyse Pipeline Hardening

- Upload hierarchy: Operating Temp / roman lines nest under lettered products;
  `1.1 Cont` treated as sibling serial; indent fallback; duplicate serial parents
  use nearest prior; multi-sheet BOQ merge with `sheets` metadata.
- Empty BOQ/make-list parses fail the upload instead of storing empty JSON.
- PDF make-list parser merges wrapped continuation lines into the prior item.
- Analyse anchors use `children_map`; extract prompt requires every evidenced
  product; attribute values normalize MS/DI/CI/GI/SS abbreviations.

## 2026-07-16 — AI Product + Attribute Mapping on Analyse

- New AI mapping layer after extract: candidate recall → AI selects Rate_Master
  product and maps extracted attributes onto DB Attribute keys.
- Analysis page shows matched DB product summary, blended confidence, DB schema
  fields (filled/empty), and AI-only Additional Attributes.

## 2026-07-16 — Backfill DB Attribute Schema on Analysis

- Attribute enrichment prefers SQL Rate_Master lookup (Chroma fallback).
- Analysis page backfills missing `attribute_schema` so DB Attribute keys appear
  (empty when AI did not find them); AI-only keys stay under Additional Attributes.

## 2026-07-16 — DB Schema Attributes + AI Additional Attributes

- Analysis Attributes grid always shows matched Rate_Master Attribute keys
  (filled when AI found a value, empty when not).
- AI-only keys render under Additional Attributes.

## 2026-07-16 — Fix Analysis Confidence + Row Mapping + Extraction

- Attribute confidence scored only against DB Attribute schema (0 when none).
- Quantity detection includes Total/Ground/Basement columns.
- Lettered priced lines (a/b/c…) are extractable anchors; Re-analyse resolves to
  the nearest real anchor; product consolidate uses group_ids (not ancestors).

## 2026-07-16 — Heuristic Make-List Column Roles

- Make vs material columns inferred from headers + cell content (not fixed names).
- Supports unknown labels like Description/Name, Material/Make Manufacturers, Item/Make.
- Stores `column_roles` on make-list JSON; constraint matching prefers material keys.

## 2026-07-16 — Make List Column + Separator Parsing

- Make-list parser recognizes `Make/Manufacturers Name` and similar columns.
- Splits approved makes on `/`, `,`, `;`, `|` (keeps spaced names like `ESS ESS`).
- Empty `approved_makes_list` on stored BOQs is rebuilt on load when make cells exist.

## 2026-07-16 — Dynamic Analyse Attributes + Confidence

- Analyse enriches each extracted product from the best Rate_Master hit: DB
  Attribute keys become the UI schema; extracted values fill matching keys.
- Attribute confidence = filled schema keys / total schema keys (0–100).
- Confidence badge colors: >90 green, >80 yellow, >70 orange, else red.
- Static common attribute grid removed in favor of dynamic DB-driven fields.

## 2026-07-16 — Fix is_anchor_row Optional Param Type

- `is_anchor_row(..., children_map=None)` annotated as
  `dict[str, list[str]] | None` to clear basedpyright `reportArgumentType`.

## 2026-07-14 — Analysis Product Actions Layout

- **+ Add product** sits next to **Save product**; extra attrs labeled
  **Additional Attributes** with **+ Add attribute**.

## 2026-07-14 — Optional Product Fields + Filled-Only Matching

- Product fields (class, size, capacity, unit, etc.) are all optional.
- Match/search sends only filled properties; null/blank values are omitted.
- Extraction prompt is stricter: fill only evidenced fields; prefer null over guesses.

## 2026-07-14 — Match Results Icons + Extraction Fixes

- Compact icon actions on Match Results; hide lineage child stubs from the table.
- Spec-label filter only drops true label rows (keeps Pressure/Flow switch products).
- AI activity list uses installation work verbs instead of Labour_Type codes.

## 2026-07-14 — Per-Row Re-analyse / Re-match

- Analysis tab: per-row **Re-analyse**.
- Match Results tab: per-row **Re-match** only after Match has completed.
- Top toolbar keeps first-time Analyse/Match only; full-BOQ Re-analyse/Re-match removed.

## 2026-07-14 — Preferred Make Lowest Price Option

- Preferred make dropdown includes **Lowest price**; Match then picks the cheapest
  Rate_Master among allowed makes (`Final_Amount_Excl_GST`).

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
