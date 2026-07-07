# Changelog

## 2026-07-07 — Synchronous Database Upload

- Changed database uploads to run synchronously from the upload request.
- Removed the unused Celery database import task and moved database embedding
  generation into a synchronous AI embedding helper.
- Stopped queuing `generate_embeddings_task`, fixing unregistered Celery task
  errors after database upload.

## 2026-07-07 — Final Validation and Cleanup

- Ran the final validation sweep for the current BOQ upload, grouped JSON,
  processing, lowest final-amount matching, and export flow.
- Fixed reprocessing so cloned BOQ runs preserve `row_json` grouped source
  context.
- Replaced stale scaffold helpers with working implementations and cleaned
  misleading comments/future-scope language from active documentation.
- Confirmed the breakdown export includes the product-focused `Confidence`
  column.

## 2026-07-07 — BOQ Measured Child Row Parsing

- Updated BOQ row grouping so parent/specification rows without unit or
  quantity are carried as context for measured child rows instead of becoming
  standalone processing items.
- Preserved child rows with their own unit or quantity as the processing/export
  target rows so client BOQ exports fill Rate and Amount where the original
  BOQ expects them.
- Fixed serial classification so parenthesized child letters such as `(A)` and
  `(D)` are not treated as Roman-numeral section headings.
- Added parser regression coverage for child quantity rows and serial
  specification rows.

## 2026-07-07 — Make List Category Pair Extraction

- Fixed make-list parsing so the same approved make is preserved separately for
  each material/category instead of being removed after its first occurrence.
- Improved make splitting for slash-delimited manufacturer cells so names like
  `Jindal, Hissar` remain one make when they appear inside slash-separated
  lists.
- Added parser regression coverage for `Make/Manufacturers Name` style sheets
  with repeated makes across different materials.

## 2026-07-07 — Export Download and BOQ Layout Preservation

- Added authenticated export download endpoints for the client BOQ and
  breakdown list files.
- Changed the internal export sheet to a `Breakdown List` matching the provided
  19-column format.
- Changed client BOQ export to preserve the uploaded BOQ worksheet where
  available and fill only Unit, Quantity, Rate, and Amount.
- Preserved existing Unit and Quantity cells and placed Rate/Amount on child
  rows when child rows carry the product unit or quantity.
- Tightened product extraction instructions so AI does not force products from
  headings, notes, or execution-only rows.

## 2026-07-07 — Runtime AI Instruction Logs

- Added `logs/ai_instructions.log` for structured runtime AI instruction
  entries.
- Logged every rendered AI prompt before the provider call with model,
  template name, JSON-mode flag, and full instruction text.

## 2026-07-07 — Explicit AI Row JSON Logging

- Added explicit `fetched_row_json` and `ai_output_json` fields to row-level AI
  extraction logs so the grouped BOQ JSON fetched from each row and the AI
  extraction result are visible in `logs/ai_extractions.log`.

## 2026-07-07 — Grouped BOQ Row JSON and Database-Aware Extraction

- Added grouped BOQ row JSON so serial-numbered BOQ rows and inherited
  blank-serial child rows are processed as one structured item.
- Added active database context for AI prompts so product and activity
  extraction stays close to Rate_Master, Labour_Master, and TOR_Labour
  terminology.
- Expanded product extraction to preserve per-row product candidates and
  database hints for matching.
- Updated product matching to search the original BOQ text first, then extracted
  product candidates and database hints.

## 2026-07-07 — Lowest Final Amount Rate Selection

- Removed the standalone vendor-selection processing stage and service.
- Added `RateMaster.final_amount_excl_gst` and import mapping for
  `Final_Amount_(Excl GST)` from the updated Rate_Master workbook.
- Changed product matching to select the lowest final-amount Rate_Master row
  when multiple rows match the same product.
- Added product embedding generation to the database import workflow.
- Renamed the BOQ detail action to `Calculate BOQ` / `Recalculate BOQ`.

## 2026-07-06 — Row-Level AI Extraction Logging

- Added a dedicated `logs/ai_extractions.log` file for structured BOQ row AI
  extraction payloads during processing.
- Logged each successfully analyzed row with BOQ/run/item IDs, Excel row number,
  source description, product extraction JSON, and extracted activities.
- Logged row-level AI extraction failures to the same file so failed rows can be
  audited without stopping the whole BOQ run.

## 2026-07-06 — Sample-Driven BOQ and Database Import Hardening

- Improved make-list Excel extraction to scan all workbook sheets and read
  merged/continued approved-make columns, fixing real formats like `Make_1`.
- Added make-list aliases for `Materials` and make/manufacturer headers so
  client make categories and makes are preserved across formats.
- Tightened BOQ extraction so rate/amount subheader rows such as `(Rs.)` are not
  captured as BOQ items when the description column is blank.
- Hardened database import for the March client workbook shape by synthesizing
  product codes from category/subcategory/class/size when key fields are blank,
  importing discounted rates, preserving raw workbook fields in `spec_json`, and
  skipping incomplete master rows.
- Updated costing fallbacks to read normalized commercial keys such as
  `handling`, `profit`, and `accessories` from imported `spec_json`.
- Fixed linked client export formulas so amount cells reference the client
  quantity cell and the internal final-rate cell.

## 2026-07-06 — Make List View Without Pagination

- Removed pagination from the BOQ make-list page so all linked make-list entries
  are visible together.
- Added regression coverage confirming make-list pages show entries beyond the
  previous first page and no longer render pagination controls.

## 2026-07-06 — Robust Make List Extraction and BOQ Isolation

- Improved Excel make-list extraction to detect later header rows and accept
  aliases such as approved make, brand, manufacturer, and OEM.
- Added support for multiple make columns and cells containing multiple makes
  separated by common delimiters.
- Added regression coverage proving two BOQs with the same BOQ name and same
  make-list filename remain separate BOQs with separate make-list entries.

## 2026-07-06 — Canonical BOQ Field Mapping

- Changed BOQ extraction output to map header aliases into a static field set:
  S No, Description, Unit, and Quantity.
- Added aliases for abbreviated BOQ headers such as `SNo`, `QTY`, `un`, and
  `ut`, so differently formatted sheets still populate the correct fields.
- Updated the BOQ detail UI and client BOQ output to use the canonical columns
  instead of arbitrary uploaded workbook columns.

## 2026-07-06 — Robust BOQ Excel Extraction

- Improved BOQ Excel extraction to detect later header rows when workbooks
  include title, project, or tender-reference rows before the actual BOQ table.
- Normalized messy header labels such as `S. No.`, `Sr. No.`, `Qty.`, and
  `UOM` so different BOQ formats map into the same extraction flow.
- Cleaned floating-point display artifacts in preserved BOQ row data, so values
  such as `27.200000000000003` are stored and shown as `27.2` while quantity
  calculations still use the raw numeric cell value.

## 2026-07-06 — Make List Replacement UI

- Removed BOQ item pagination from the BOQ detail page so all captured BOQ rows
  are listed together.
- Removed make-list upload controls from the BOQ detail page.
- Changed the make-list page to show the currently linked make-list filename and
  a replace action; replacement updates that BOQ's single linked make list and
  deletes the previous parsed make-list entries.

## 2026-07-06 — BOQ-Scoped Make List Upload

- Added a BOQ detail make-list upload flow that saves the file to that BOQ and
  replaces entries only on the BOQ's latest run.
- Added service-level validation so empty or unreadable make-list uploads return
  a clear error instead of silently creating zero entries.
- Added tests proving make-list updates on one BOQ do not affect another BOQ.

## 2026-07-06 — Make List PDFs and BOQ Row Preservation

- Allowed PDF uploads for make lists only, updated the BOQ upload UI copy, and
  corrected the make-list extraction prompt to return JSON compatible with the
  AI service.
- Preserved uploaded BOQ worksheet row numbers, original headers, and original
  row cells so nested BOQ rows with blank serial-number cells remain blank in
  the UI and client export.
- Updated the BOQ detail table and client export to start from the original
  workbook columns before appending final rate and amount.

## 2026-07-06 — Runbook Redis and Celery Notes

- Added local Windows guidance for running Redis through WSL and starting the
  Celery worker with the Windows-compatible solo pool.
- Added an EC2 feature-update command sequence that explicitly runs
  `collectstatic --noinput` before restarting Gunicorn and Celery.

## 2026-07-03 — Enhanced BOQ Upload and PDF Make Lists

- Updated `BOQItem` model to store `original_data` for preserving all columns from uploaded Excel while skipping empty rows.
- Added `pypdf` dependency for PDF extraction.
- Implemented AI-powered PDF extraction for Make Lists and integrated it into the parsing logic.
- Added capability to upload Make Lists directly from the BOQ details view.
- Updated BOQ items UI table to display Rate and Amount from cost breakdown dynamically.

## 2026-07-03 — Settings Consolidation and Import Cleanup

- Consolidated Django configuration into the single active settings module
  `config.settings` (`backend/config/settings.py`); removed the old
  `base.py` / `production.py` split.
- Updated Django, ASGI, WSGI, Celery, `.env.example`, README, runbook, deploy
  guide, project structure, and agent docs to reference `config.settings`.
- Moved application and test imports to module scope and added rotating file
  logging for application and error logs.

## 2026-07-03 — Git Initialization & Production Readiness Audit

- Initialized Git repository for the first-time push milestone.
- Locked all Python dependencies to exact versions via `pip freeze`; replaced
  loose `>=` ranges in `requirements.txt` with fully pinned versions.
- Created `.python-version` file to lock the project runtime to Python 3.14.5.
- Improved `.gitignore`: added `**/__pycache__/` for recursive cache exclusion,
  added `.mypy_cache/`, added inline comments explaining `.env` and
  `staticfiles/` rules.
- Fixed `SESSION_STATE.md`: removed a verbatim duplicate of the Technical
  Decisions section and an incomplete Database Strategy block that had been
  left in the file; updated test count to 149.
- Updated `README.md` with the required Python version and a Local Development
  Quick Start section for new developer onboarding.
- Added a "Documentation Update Instructions" section to `AGENTS.md` so
  developers and agents know which doc to update and when.
- Fixed `PROJECT_STRUCTURE.md`: added `middleware.py` and `mixins.py` to the
  `common/` module listing; corrected the `logs/` section to match actual
  log files; added a note that `staticfiles/` is auto-generated.
- Granted `CREATEDB` privilege to the `boq_user` PostgreSQL role so the test
  suite can create and destroy its temporary test database.
- Confirmed all 149 tests pass with no regressions.

## 2026-07-01 — EC2 Runtime Simplification

- Simplified runtime guidance around a single EC2 settings path
  (`config.settings`) and `/srv/boq_ai/.env`.
- Updated EC2/PostgreSQL documentation to use `boq_db` and `boq_user`.
- Made SMTP optional in production settings so the app can run before a domain
  or mail provider is configured.
- Removed obsolete local/development settings entry points and the local-only
  requirements file.
- Cleaned generated runtime artifacts (`db.sqlite3`, logs, `__pycache__`) from
  the workspace.
- Removed the unused `backend/api/` placeholder and Django REST Framework
  dependency/configuration.
- Consolidated dependencies into root `requirements.txt`.
- Removed tracked deploy templates and ignored `/deploy/`; deployment
  instructions now live in `RUN.md`.
- Removed the stale `pyrightconfig.json`; it was later replaced with a focused
  editor configuration for the current backend layout.
- Updated `.env` for the EC2 production runtime.
- Removed the `seed_demo` management command, its tests, and runtime/sample
  media files so future work uses real production data only.
- Updated all active docs for PostgreSQL-only local and EC2 usage.
- Cleaned stale documentation references to active DRF/API, SQLite fallback,
  split local settings, and old dependency/deploy structures.
- Moved `CHANGELOG.md`, `RUN.md`, and `DEPLOY.md` into `docs/`.
- Removed `/docs/` from `.gitignore`.
- Centralized test modules under `backend/tests/`.
- Restored a focused `pyrightconfig.json` so VS Code/Pylance resolves the
  `backend/` import root without changing the single production runtime.
- Removed the unused Celery debug task from `backend/config/celery.py`.
- Corrected `docs/PROJECT_STRUCTURE.md` to match the app-local service layout.
- Rebuilt the local `.venv`, installed root `requirements.txt`, and verified
  Django/Ruff/Pyright checks.
- Created local PostgreSQL role `boq_user`, aligned local `.env` with
  `boq_user@localhost/boq_db`, and applied all migrations.
- Removed the unused debug-toolbar URL hook from the single runtime URL config.

All notable changes to BOQ_AI are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/). Dates use ISO 8601.

## [Unreleased]

### Added — 2026-06-30 — Platform Enhancements & Client Schema Alignment

**Role Hierarchy (3-tier)**
- Reorganized permission roles to Developer (Django superuser) → Admin (Client admin) → Expert (End users).
- Renamed role `SUPER_ADMIN` to `ADMIN` inside choices and database migrations.
- Added `created_by` field to User model for Admin auditing.
- Renamed mixins and permission classes (`AdminRequiredMixin`, `IsAdmin`).

**Flexible Database Schema & Excel Importer**
- Added `spec_json` JSONField to `RateMaster`, `LabourMaster`, and `TOR` models to dynamically store all extra or evolving spreadsheet columns from client databases.
- Updated `DatabaseImportService` with fallback getters to import custom columns.
- Re-architected costing (labour + accessories) to fall back dynamically to row-specific margins (`handling_%`, `profit_%`, `accessories_%`) and `LabourMaster` prefix matching when standard mapping tables are omitted.

**Forgot Password Flow**
- Configured console email fallback when SMTP is not available and SMTP support
  for production password resets.

**Custom Maker Selection**
- Added `vendor_mode` (LOWEST_COST / CUSTOM) and `custom_maker` fields to `ProductMatch` model.
- Added custom maker overrides in `ReviewService` and an inline text input in the review UI template.

**PostgreSQL Enforcement**
- Added an `ImproperlyConfigured` guard in production settings to mandate
  PostgreSQL setup.
- Updated `.env.example` and `RUN.md` documentation.

### Added — 2026-06-23 — Phase 11/12: Integration Tests + Deployment (Sprints 22 & 24)

**Sprint 22 — End-to-end integration tests**
- `backend/workflows/tests.py`: full-pipeline tests with AI disabled — process a
  BOQ run (match -> cost -> confidence) and assert run/BOQ status, `ProductMatch`,
  `CostBreakdown`, `ProcessingJob` progress and the completion notification; plus
  the failure path (stage raises -> run FAILED + failure notification) and the
  review -> approve -> export chain (status transitions, audit entries, export
  files, export-ready notification, pre-approval export guard). 4 new tests;
  full suite now **131 passing**.

**Sprint 24 — Production deployment (AWS EC2 + Gunicorn + Nginx + Redis + PostgreSQL)**
- Production deployment guidance was created for EC2. The tracked deploy
  templates were later removed, and the active instructions now live in
  `RUN.md`.

### Added — 2026-06-23 — Phase 11: Notifications + Audit (Sprint 20)

**Sprint 20 — Notifications & Audit Logging**
- `apps/notifications/services.py`: `notify()`, `unread_count()`, `mark_all_read()`
  — defensive helpers (notification failures never break core flows)
  (docs/PRD.md - Notifications).
- Event notifications wired in:
  - processing complete / failed (`workflows/boq_processing.py`),
  - BOQ approved (`review_service.approve`),
  - export ready (`export_service.export_run`).
- `apps/audit/services.record()`: never-raising audit writer; secrets/passwords
  are never logged (docs/PRD.md - Security Requirements). Wired into approve,
  export, pending-product actions (reject/merge/add), and database
  import/rollback.
- Views/URLs: `/notifications/` (list + Mark all read) for all users;
  `/audit/` (Super Admin only) audit log list.
- Context processor + nav: unread badge on the Notifications link;
  Audit Log link for Super Admins.

**Tests**
- `apps/notifications/tests.py` (6) + `apps/audit/tests.py` (4): service create /
  unread / mark-read, list + mark-all-read views, login guard; audit record
  (user + anonymous), Super-Admin-only access. Full suite now **127 passing**.

### Added — 2026-06-23 — Phase 10: Export System (Sprint 19)

**Sprint 19 — Excel Export**
- `exports/internal_sheet.py`: per-row internal review sheet (full cost
  breakdown + confidence colour bands) (docs/PRD.md - Internal Review Sheet).
- `exports/client_sheet.py`: client BOQ (final rate + amount). When generated
  with the internal sheet, rate/amount cells are Excel formulas linked to the
  internal sheet ("values are linked"); standalone client files use computed
  values.
- `exports/formatter.py`: styled headers + confidence band fills.
- `apps/exports/services/export_service.ExportService`: builds a two-sheet
  internal workbook (Internal Review + linked Client BOQ) plus a standalone
  client workbook, persists both on `ExportFile`, and transitions the BOQ to
  Exported. Requires an approved BOQ.
- Views/URLs (`/exports/`): ownership-scoped `GenerateExportView`; Export button
  + internal/client download links on the review page.

**Tests**
- `apps/exports/tests.py` — 6 tests: files created + status Exported, two-sheet
  internal workbook content, standalone client computed amount, approval guard,
  view export (owner) and access control (non-owner). Full suite now
  **117 passing**.

### Added — 2026-06-23 — Phase 9: Pending Products (Sprint 18)

**Sprint 18 — Pending Product Approval**
- `apps/pending_products/services/pending_service.PendingProductService`:
  Super-Admin resolution of below-threshold items (docs/PRD.md - Pending Product
  Workflow):
  - `reject()` — dismiss the entry.
  - `merge()` — map the description to an EXISTING master product (creates a
    `ProductAlias` so future BOQs match automatically; validates the code).
  - `add_new()` — create a NEW `RateMaster` row in the active version, then
    alias to it (validates against duplicates).
  Approved/merged products become available for future BOQs via the alias / new
  row. Database changes are Super-Admin only (docs/AGENTS.md).
- Views/URLs (`/pending/`): `PendingProductListView` (pending queue) and
  Super-Admin-only reject/merge/add actions with friendly error handling.
- UI: `templates/pending/list.html` with inline Alpine.js merge/add forms and a
  "Pending Products" nav link for Super Admins.

**Tests**
- `apps/pending_products/tests.py` — 9 tests: reject, merge (+alias, unknown
  code), add-new (+rate/alias, duplicate), plus view access control
  (admin vs expert) and merge via view. Full suite now **111 passing**.

### Added — 2026-06-23 — Phase 8: Review Workflow (Sprint 17)

**Sprint 17 — Approval Workflow**
- `ReviewService.approve()` / `revise()`: status-guarded transitions per the BOQ
  workflow (docs/PRD.md): Completed/Under Review -> Approved, and Approved ->
  Under Review (reopen). Invalid transitions raise `ValidationError`.
- Views/URLs: `ApproveView`, `ReviseView` (ownership-scoped; friendly error
  messages on invalid transitions). Approve / Reopen buttons in the review
  toolbar, shown contextually by status.

**Tests**
- `apps/review/tests.py` — 7 tests: approve from completed/under-review, invalid
  approve, revise reopen, revise guard; view-level approve (owner) and access
  control (non-owner). Full suite now **102 passing**.

### Added — 2026-06-23 — Phase 8: Review Workflow (Sprint 16)

**Sprint 16 — Internal Review**
- `apps/review/services/review_service.ReviewService`: experts re-point a BOQ
  item's match at an existing master row (vendor or product change), recording a
  `ReviewItem` (original vs revised) and recalculating that item's
  `CostBreakdown` immediately. Experts never modify the master DB
  (docs/AGENTS.md - Review Rules); manual overrides set confidence to 100.
  `candidate_rates()` lists same-product_code vendor alternatives;
  `start_review()` transitions the BOQ to Under Review.
- Review UI (`templates/review/`): editable results table with per-row vendor
  dropdown applied via HTMX (row swap), confidence colour bands, and a
  "Start review" action. Linked from the BOQ detail page once a run completes.
- Views/URLs (`apps/review/`): ownership-scoped `ReviewView`, `ApplyReviewView`
  (HTMX, 403 for non-owners), `StartReviewView`. Registered under `/review/`.
- CSS: confidence band badges (yellow/orange/blank), select inputs, review-row
  accents.

**Tests**
- `apps/review/tests.py` — 9 tests: candidate rates, apply changes vendor +
  recalcs cost, records ReviewItem, status transition; view access control
  (owner/non-owner) and HTMX apply. Full suite now **95 passing**.

### Added — 2026-06-23 — Phase 7: Cost Engine (Sprint 15)

**Sprint 15 — Commercial Costing**
- `apps/costing/services/transport.transportation_cost()`: % of material
  (default 2%), scaled by the state transportation multiplier.
- `apps/costing/services/profit.py`: `overhead_cost()` (% of the cost base) and
  `profit()` (% of base+overhead). Defaults 10%/10%.
- Commercial percentage constants in `common/constants.py`
  (`TRANSPORTATION_PERCENT`, `OVERHEAD_PERCENT`, `PROFIT_PERCENT`) — tunable, as
  the docs defer exact values to commercial rules.
- `CostCalculationService` now computes the full breakdown
  (material + labour + accessories + transportation + overhead + profit),
  quantizes every component to 2 dp, and recomputes `final_rate`.
- `StateControl` multipliers applied via an optional `state_name` on
  `calculate_run`/`calculate_item` (labour × labour_multiplier, transportation ×
  transportation_multiplier). Defaults to neutral (1.0); a BOQ-level state field
  is a future enhancement. Still fully deterministic — no AI pricing.

**Tests**
- `apps/costing/tests.py` — 3 commercial tests (default components + final rate,
  state multipliers, unknown-state neutral) and updated existing cost tests to
  sum-of-component assertions. Full suite now **86 passing**.

### Added — 2026-06-23 — Phase 7: Cost Engine (Sprint 14)

**Sprint 14 — Labour Cost**
- `apps/costing/services/labour.py`: expands execution costs from the TOR tables
  for the matched product (docs/DATABASE_ARCHITECTURE.md - TOR tables):
  - `labour_cost()` = Σ(`TOR_Labour.quantity` × `LabourMaster.labour_rate`).
  - `accessories_cost()` = Σ(`TOR_Accessories.quantity` × accessory
    `RateMaster.purchase_rate`).
  - TOR rows are joined by `tor_code == product_code`; unknown labour/accessory
    codes are skipped.
- `CostCalculationService` now preloads an active-version costing context
  (labour rates, TOR labour/accessory rows, accessory prices) once per run and
  populates `labour_cost` + `accessories_cost`, recomputing `final_rate`.
  Transportation/overheads/profit still default to 0 (Sprint 15).

**Tests**
- `apps/costing/tests.py` — 4 labour tests: labour from TOR, accessories from
  TOR, combined final-rate sum, unknown-code skipping. Full suite now
  **83 passing**.

### Added — 2026-06-23 — Phase 7: Cost Engine (Sprint 13)

**Sprint 13 — Material Cost**
- `apps/costing/services/material.material_cost()`: per-unit material cost = the
  selected vendor's `RateMaster.purchase_rate` (docs/PRD.md - Cost Calculation);
  zero when no product/vendor is selected so pending rows stay blank.
- `apps/costing/services/cost_service.CostCalculationService`: creates/updates a
  `CostBreakdown` per matched item and keeps `final_rate` in sync
  (material + labour + transportation + accessories + overhead + profit).
  Labour/transport/overhead/profit default to 0 until later sprints, so
  `final_rate == material_cost` for now. Items without a product get no
  breakdown. Idempotent on reprocess.
- `recompute_final_rate()` helper so later cost sprints just set their component
  and re-sum.
- Costing stage wired into `workflows/boq_processing` (deterministic — no AI).

**Tests**
- `apps/costing/tests.py` — 5 tests: material from purchase rate, final-rate
  sum, pending→no breakdown, idempotency, recompute after a component change.
  Full suite now **79 passing**.

### Added — 2026-06-23 — Phase 6: Vendor Selection (Sprint 12)

**Sprint 12 — Vendor Selection**
- `apps/matching/services/vendor_selection.VendorSelectionService`: picks the
  vendor row among master rows sharing a product_code, honouring the make list
  (docs/PRD.md - Make List Processing) and the selection mode
  (docs/PRD.md - Vendor Selection):
  - `LOWEST_COST` — cheapest approved vendor.
  - `PREFERRED` — first approved make in make-list order, cheapest within it.
  - `CUSTOM` — expert-chosen row (review-time override) with lowest-cost
    fallback.
- Make filtering: only approved makes may be selected; when no approved vendor
  exists the match is left unchanged (no silent non-compliant pick).
- The chosen row is written back onto `ProductMatch` (product/make/vendor) so
  costing reads a single authoritative vendor. Deterministic — no AI, no profit.
- `select_run()` wired into the matching stage of `workflows/boq_processing`
  (runs right after product matching).

**Tests**
- `apps/matching/tests.py` — 6 vendor tests: lowest-cost, make-list restriction,
  preferred order, custom selection, no-approved-vendor, run-level count.
  Full suite now **74 passing**.

### Added — 2026-06-23 — Phase 5: Product Matching (Sprint 11)

**Sprint 11 — Confidence Engine**
- `apps/matching/services/confidence.ConfidenceService`: refines the base match
  score into a factor-weighted confidence (docs/TRD.md - Confidence
  Calculation) using product/size/material/make agreement between the item's AI
  extraction and the matched master product (weights 40/25/15/20). Exact matches
  stay authoritative; alias/vector scores blend base with factor agreement.
- Match explanations persisted to `ProductMatch.ai_explanation` (which factors
  agree/differ). Colour band exposed via `band_for()` (wraps
  `common.constants.confidence_band`).
- Optional OpenAI validation: when AI is enabled the `validation.txt` prompt
  enriches the explanation and blends its confidence (validation only — no
  pricing/vendor). Fully deterministic when AI is disabled.
- `score_run()` scores every match in a run; wired into the confidence stage of
  `workflows/boq_processing`.

**Tests**
- `apps/matching/tests.py` — 6 confidence tests: exact authoritative, no-match
  zero, full/partial factor agreement, AI-validation enrichment (mocked),
  run-level scoring. Full suite now **68 passing**.

### Added — 2026-06-23 — Phase 5: Product Matching (Sprint 10)

**Sprint 10 — Matching Engine**
- `apps/matching/services/` matching engine applying the documented search
  strategy in priority order (docs/DATABASE_ARCHITECTURE.md - Search Strategy):
  - `exact_match.find_exact()` — product_code / normalized-description equality.
  - `alias_match.find_alias()` — `ProductAlias` → product_code (longest alias
    wins), resolved within the active database version.
  - `embedding_match.find_embedding()` — cosine similarity over stored
    `ProductEmbedding` vectors; requires AI + generated embeddings, otherwise
    returns no match.
- `ProductMatchingService` (`matching_service.py`): orchestrates the strategies,
  builds the query from AI extraction (falling back to the raw description),
  persists a `ProductMatch` per item with `confidence_score` + `match_reason`
  (exact=100, alias=90, vector=similarity%), and is idempotent on reprocess.
- Pending-product routing: items scoring below 30% leave the product blank and
  create a `PendingProduct` for Super Admin approval
  (docs/AGENTS.md - Pending Product Rules).
- `ai/embeddings/generator.generate_embedding()` implemented over the OpenAI
  embeddings endpoint (guarded by `is_configured`); `OPENAI_EMBEDDING_MODEL`
  setting added (default `text-embedding-3-small`).
- `utils/text.normalize()` shared comparison helper.
- Matching stage wired into `workflows/boq_processing` (runs with or without AI).

**Tests**
- `apps/matching/tests.py` — 7 tests: exact (description + code), alias, vector
  (mocked embedding), no-match→pending, idempotency, low-confidence routing.
  Full suite now **62 passing**.

### Added — 2026-06-23 — Phase 4: AI Engine (Sprints 8-9)

**Sprint 8 — Product Extraction**
- `ai/extractors/product_extractor.extract_product()`: extracts structured
  `{product, size, material, make}` from a BOQ description via `AIService`
  (understanding/extraction only — no pricing or vendor selection).
- `BOQItem.ai_extraction` (`JSONField`, nullable) persists the extracted
  attributes per item; migration `boq/0002_boqitem_ai_extraction`.

**Sprint 9 — Activity Extraction**
- `ai/extractors/activity_extractor.extract_activities()`: returns recognised
  execution activities, filtered to the allowed set (excavation, trenching,
  backfilling, installation, testing, commissioning, painting, supports).
- `activity_extraction.txt` prompt now returns a JSON object
  (`{"activities": [...]}`) so it is compatible with JSON-mode responses.

**Pipeline**
- `ai/extractors/analyzer.analyze_run()`: runs product + activity extraction for
  every item in a run, persisting `ai_extraction` and `ActivityMatch` rows.
  Per-item failures are logged and skipped (one bad row never fails the run);
  re-running is idempotent (prior activity matches are replaced).
- AI-analysis stage in `workflows/boq_processing` now calls `analyze_run()` when
  `AIService.is_enabled()`, still skipping gracefully with the placeholder key.

**Tests**
- `ai/tests.py` — 7 new tests (product/activity extractors + `analyze_run`
  persistence, failure-skip, idempotency; all mocked, no real API calls).
  Full suite now **55 passing**.

### Added — 2026-06-23 — Phase 4: AI Engine (Sprint 7)

**Sprint 7 — OpenAI Integration**
- `ai/service.py` `AIService`: single entry point over OpenAI Chat Completions
  — prompt loading from `ai/prompts/`, context formatting, plain and JSON-mode
  completions, normalized `AIServiceError` handling, and request logging
  (no secrets logged).
- `ai/openai_client.is_configured()`: treats empty or placeholder keys as
  disabled; client now applies a configurable timeout.
- Settings: `OPENAI_MODEL` (default `gpt-4o-mini`) and `OPENAI_TIMEOUT_SECONDS`;
  `.env`/`.env.example` use a placeholder key (`sk-REPLACE_WITH_YOUR_KEY`).
- Processing workflow's AI-analysis stage is now wired and guarded by
  `AIService.is_enabled()` — active with a real key, skipped gracefully with the
  placeholder (per-item extraction lands in Sprint 8).

**Tests**
- `ai/tests.py` — 9 tests (mocked client, no real API calls): placeholder/real
  key detection, completion, JSON parsing, invalid-JSON and provider-error
  wrapping, missing prompt variable. Full suite now **48 passing**.

### Added — 2026-06-23 — Phase 3: BOQ Management (Sprint 6)

**Sprint 6 — Processing Queue**
- `workflows/boq_processing.process_boq_run`: drives a run through the fixed
  stage pipeline (AI analysis → matching → costing → confidence) updating
  `ProcessingJob` progress and transitioning statuses
  (Uploaded → Processing → Completed; Failed on error). Stage logic is a logged
  no-op until Phases 4-7 fill it in, so the queue/progress/status machinery is
  fully working without fabricating results.
- `ProcessingJobService`: queues a job, transitions the BOQ to Processing, and
  dispatches the Celery task on commit. Reprocessing a finished BOQ creates a
  NEW run and clones its items + approved makes (history preserved).
- Processing views/URLs: start (ownership-checked), HTMX status fragment
  (polls every 2s while active, stops when done), and a processing dashboard
  scoped by ownership. `Processing` nav link added.
- BOQ detail wired with a Process/Reprocess button and a live progress panel;
  progress-bar styling added.

**Tests**
- `apps/processing/tests.py` — 8 tests covering run completion + status
  transitions, eager start-to-completion, reprocess/run-cloning, start-view
  ownership, and the status/list endpoints. Full suite now **39 passing**.

### Added — 2026-06-22 — Phase 3: BOQ Management (Sprint 5)

**Sprint 5 — BOQ Upload Module**
- `utils/excel.read_rows()` now defaults to the active worksheet when no sheet
  name is given.
- BOQ parsing (`apps/boq/services/parser.py`): tolerant header matching for
  BOQ rows (description/quantity/unit) and make lists (make/category), so
  varying client workbook layouts are handled and blank rows skipped.
- `BOQCreationService`: creates a BOQ (owned by the uploader), its first
  `BOQRun` (run 1, status QUEUED), captures original `BOQItem` rows and
  `MakeListEntry` approved makes inside a transaction.
- BOQ UI: list (ownership-scoped — experts see their own, Super Admin sees
  all), multipart upload form, and detail view showing items, approved makes,
  and run status; added `BOQs` nav link.
- Dashboard metrics are now live (BOQ counts by status, ownership-aware).

**Tests**
- `apps/boq/tests.py` — 8 tests covering parsing, BOQ/run/item/make creation,
  optional make list, ownership isolation, and the upload view. Full suite now
  **31 passing**.

### Added — 2026-06-22 — Phase 2: Database Management (Sprints 3 & 4)

**Sprint 3 & 4 — Database Upload + Import Engine**
- `utils/excel.py`: `read_rows()` openpyxl-based sheet reader (header
  normalization, empty-row skipping) — no pandas dependency, installs cleanly.
- `DatabaseImportService` implementing the documented workflow
  (Validate → Backup → Import → Embeddings hook → Activate) inside a single
  transaction; version auto-increment, activation, and retention of the active
  version plus two previous versions. State control rows are upserted by name.
- `DatabaseRollbackService` to re-activate a retained previous version.
- `workflows/database_import.py` orchestration. This was later changed to run
  synchronously from the upload request.
- Super-Admin database management UI: version list, upload (multipart) with
  validation, and rollback action; `Database` nav link added.
- Embedding generation is invoked as a deferred hook (real generation in the
  AI/matching sprints).

**Tests**
- `apps/database_manager/tests.py` — 11 tests covering validation, row reading,
  import (rows/activation/versioning), retention, state-control upsert,
  rollback, and Super-Admin access control. Full suite now **23 passing**.

### Added — 2026-06-22 — Project scaffolding + Sprint 1 & 2

**Foundation**
- Django project scaffolding under `backend/` per `docs/PROJECT_STRUCTURE.md`:
  `config/`, `apps/`, `services`, `ai`, `workflows`, `exports`, `tasks`,
  `common`, and `utils`.
- Settings use environment loading (`django-environ`) with PostgreSQL via
  `DATABASE_URL`.
- Celery app (`config/celery.py`) + Redis configuration; tasks scaffolded in
  `tasks/`.
- Root `requirements.txt`, `.env.example`, `.gitignore`, `README.md`, logging
  configuration.
- `common/` layer: `choices.py`, `constants.py` (confidence bands, retention),
  `exceptions.py`, `models.py` (TimeStampedModel), `mixins.py`
  (`SuperAdminRequiredMixin`).

**Data models (per `docs/DATABASE_ARCHITECTURE.md`)**
- All 13 apps created with models: `accounts` (custom `User`), `users`,
  `database_manager` (DatabaseVersion + master/product tables), `boq`
  (BOQ/BOQRun/BOQItem), `make_list`, `processing` (ProcessingJob), `matching`
  (ProductMatch/ActivityMatch), `costing` (CostBreakdown), `review`
  (ReviewItem), `exports` (ExportFile), `pending_products` (PendingProduct),
  `notifications` (Notification), `audit` (AuditLog).
- Initial migrations generated and applied.

**Sprint 1 — Authentication & User Management**
- Email-based custom `User` model with `SUPER_ADMIN` / `EXPERT` roles and a
  custom manager.
- Login, logout, and password reset flow (email-based, no public registration).
- Super-Admin-only user management: list, create, edit, activate/deactivate.
- Django admin configured for the custom user and all master/domain models.

**Sprint 2 — Dashboard & Layout**
- Responsive base layout (`templates/base.html`) with sidebar navigation,
  top bar, message/alerts area, HTMX + Alpine.js integration.
- Authenticated dashboard with role-aware welcome and metric placeholders.
- Modern stylesheet (`static/css/app.css`).

**AI layer scaffolding**
- `ai/openai_client.py` (lazy client, prompt loader) and prompt templates
  (`product_extraction`, `activity_extraction`, `validation`); extractor,
  validator and embedding module stubs for future sprints.

**Tests**
- `apps/accounts/tests.py` and `apps/users/tests.py` — 12 passing tests
  covering the User model, auth flow and role-based access control.

### Notes
- `ProductEmbedding.embedding_vector` is stored as JSON in V1 to stay
  database-agnostic during scaffolding; it migrates to a `pgvector`
  `VectorField` in the AI/matching sprints.
- Heavy/native dependencies (pandas, openpyxl, psycopg, openai) are imported
  lazily where possible and installed through the root requirements file.
