# Project

BOQ_AI

---

# Version

1.0

---

# Purpose

This document serves as the active memory system for the BOQ_AI project.

AI agents, developers, and future contributors must read this file before starting development.

This document tracks:

* Current state.
* Completed work.
* Pending work.
* Blockers.
* Next tasks.
* Architecture decisions.

This file is updated after every development session.

---

# Project Status

Status:

Active Development

Development Started:

Yes (2026-06-22)

Production Status:

Production preparation in progress.

---

# Current Development Phase

Phase:

Production hardening and implementation.

Status:

Core foundation delivered. Active work now targets production-ready behavior
against PostgreSQL and real client data.

---

# Completed Documents

| Document                 | Status   |
| ------------------------ | -------- |
| PRD.md                   | Complete |
| TRD.md                   | Complete |
| ARCHITECTURE.md          | Complete |
| DATABASE_ARCHITECTURE.md | Complete |
| PROJECT_STRUCTURE.md     | Complete |
| AGENTS.md                | Complete |

---

# Pending Documents

(none)

Created:

* DEVELOPMENT_ROADMAP.md
* CHANGELOG.md

---

# Technical Decisions

## Backend

Django

---

## API

No public API is active. The current product surface is Django Templates + HTMX.

---

## Frontend

* Django Templates
* HTMX
* Alpine.js

---

## Database

PostgreSQL

---

## Queue

Celery

---

## Broker

Redis

---

## AI Provider

OpenAI

---

## Hosting

AWS EC2

---

# User Roles

## Super Admin

Permissions:

* User management.
* Database management.
* Product approval.
* System administration.
* All BOQs.

---

## Expert

Permissions:

* Own BOQs.
* Review.
* Export.

Restrictions:

* No database changes.
* No user management.

---

# Authentication

* Email login.
* Password reset.
* No public registration.
* User creation by Super Admin.

---

# Database Status

Status:

Provisional Version 1.

Source:

Client Excel Workbook.

Current Sheets:

* Rate_Master
* Labour_Master
* TOR_Main
* TOR_Labour
* TOR_Accessories
* State_Control_List



# User Roles

## Super Admin

Permissions:

* User management.
* Database management.
* Product approval.
* System administration.
* All BOQs.

---

## Expert

Permissions:

* Own BOQs.
* Review.
* Export.

Restrictions:

* No database changes.
* No user management.

---

# Authentication

* Email login.
* Password reset.
* No public registration.
* User creation by Super Admin.

---

# Database Status

Status:

Provisional Version 1.

Source:

Client Excel Workbook.

Current Sheets:

* Rate_Master
* Labour_Master
* TOR_Main
* TOR_Labour
* TOR_Accessories
* State_Control_List

# Database Strategy

```text id="utjb2y"
Upload

↓

Validate

↓

Backup

↓

Import

↓

Embeddings

↓

Activate
```

Retention:

* Current active version.
* Up to 9 previous archived versions (10 total retained).

---

# AI Strategy

OpenAI is responsible for:

* Product extraction.
* Activity extraction.
* Description understanding.
* Validation.

AI does not:

* Calculate pricing.
* Select vendors.
* Apply profit.

---

# Confidence Rules

| Confidence | Action          |
| ---------- | --------------- |
| >90        | Green           |
| 80-90      | Yellow          |
| 70-80      | Orange          |
| 30-70      | Red             |
| <30        | Pending Product |

---

# Unknown Product Workflow

Below 30% confidence:

* Leave row blank.
* Create pending product.
* Super Admin approval required.

---

# Rate Selection

Active rule:

* Select the matching Rate_Master row with the lowest
  `Final_Amount_(Excl GST)`.

Vendor selection modes are not part of the active processing pipeline.

---

# BOQ Workflow

```text id="5dl7yv"
Upload

↓

Processing

↓

Completed

↓

Under Review

↓

Approved

↓

Exported
```

---

# Output Strategy

Sheet 1:

Internal Review.

Sheet 2:

Client BOQ.

Both sheets remain linked.

---

# Background Processing

Technology:

* Celery.
* Redis.

All BOQ processing must be asynchronous.

---

# File Storage

```text id="khxmv0"
media/

database/

boq/

make_lists/

exports/

outputs/
```

---

# Architecture Status

Status:

Frozen.

Changes require:

* Architecture review.
* Documentation update.

---

# Database Status

Status:

Semi-final.

Existing BOQs must remain unaffected.

---

# Development Rules

* Thin views.
* Fat services.
* Background processing.
* Documentation first.
* Business logic in services.

---

# Current Blockers

None.

---

# Known Risks

## Database Evolution

The client database may evolve.

Mitigation:

* Import layer.
* Versioning.

---

## Product Matching Accuracy

Some descriptions may vary.

Mitigation:

* Alias system.
* Embeddings.
* Human review.

---

## Unknown Products

New products may appear.

Mitigation:

* Pending Product Queue.

---

# Current Sprint

All 24 Sprints — Complete.

Delivered (Sprints 1 & 2):

* Django project scaffolding, single settings module, Celery/Redis, logging.
* All 13 app data models + migrations.
* Email-based custom User, roles, auth (login/logout/password reset).
* Super-Admin user management. Responsive dashboard + layout.

Delivered (Sprints 3 & 4):

* Excel row reader; DatabaseImportService (validate/backup/import/activate +
  retention); DatabaseRollbackService; synchronous import workflow;
  Super-Admin database UI (list/upload/rollback).

Delivered (Sprint 5):

* BOQ + make-list parsing (tolerant header matching).
* BOQCreationService (BOQ + run 1 + items + make entries, owned by uploader).
* BOQ UI: ownership-scoped list, upload, detail (items/makes/run status).
* Live dashboard metrics.

Delivered (Sprint 6):

* boq_processing workflow (staged progress + status transitions).
* ProcessingJobService (queue, dispatch on commit, reprocess via new run).
* Processing views: start, HTMX status polling, processing dashboard.
* BOQ detail Process/Reprocess button + live progress panel.

Delivered (Sprint 7):

* AIService over OpenAI Chat Completions (prompt loading/formatting, JSON mode,
  error normalization, logging without secrets).
* is_configured() placeholder-aware key detection; configurable model/timeout.
* AI-analysis stage wired into processing, guarded by is_enabled().
* Placeholder key in env files.

Delivered (Sprints 8 & 9):

* product_extractor (product/size/material/make) + activity_extractor
  (allowed-activity filtering) using AIService.
* BOQItem.ai_extraction JSONField + migration; ActivityMatch persistence.
* analyzer.analyze_run: per-item extraction, error-skip, idempotent reprocess;
  wired into the AI-analysis stage (active with real key, skipped otherwise).
* activity_extraction prompt returns a JSON object for JSON-mode compatibility.

Delivered (Sprint 10):

* Matching engine: exact (code/description), alias (ProductAlias), vector
  (cosine over ProductEmbedding) strategies in priority order.
* ProductMatchingService: query from extraction (fallback to description),
  persists ProductMatch (confidence + reason), idempotent on reprocess.
* Pending-product routing for <30% confidence (blank product + PendingProduct).
* generate_embedding (OpenAI embeddings, guarded); OPENAI_EMBEDDING_MODEL.
* utils.text.normalize; matching stage wired into the pipeline.

Delivered (Sprint 11):

* ConfidenceService: factor-weighted scoring (product/size/material/make),
  exact authoritative, alias/vector blended with factor agreement.
* Match explanations on ProductMatch.ai_explanation; band_for colour bands.
* Optional OpenAI validation enrichment (blends confidence, deterministic when
  AI disabled). Confidence stage wired into the pipeline.

Delivered (Sprint 12):

* Rate selection uses the lowest `Final_Amount_(Excl GST)` Rate_Master row
  among matching product rows.
* ProductMatch stores the selected Rate_Master row plus make/supplier values
  from that row for review and export.
* Standalone vendor-selection modes and services are not active.

Delivered (Sprint 13):

* Material cost = selected Rate_Master purchase_rate (per-unit); zero for pending.
* CostCalculationService: per-item CostBreakdown + final_rate sync; idempotent.
* recompute_final_rate helper; costing stage wired into the pipeline.

Delivered (Sprint 14):

* Labour cost = Σ(TOR_Labour.qty × LabourMaster.rate); accessories cost =
  Σ(TOR_Accessories.qty × accessory purchase_rate). TOR joined by
  tor_code == product_code; unknown codes skipped.
* CostCalculationService preloads an active-version costing context per run and
  populates labour + accessories; final_rate recomputed.

Delivered (Sprint 15):

* Commercial costing: transportation (% material), overhead (% base), profit
  (% base+overhead); tunable percent constants in common/constants.
* StateControl multipliers (labour/transportation) via optional state_name
  (neutral default). All components quantized to 2 dp; final_rate recomputed.
* Cost engine (Phase 7) complete.

Delivered (Sprint 16):

* ReviewService: re-point item match (rate-row/product change), record ReviewItem,
  recalc CostBreakdown, transition BOQ to Under Review. candidate_rates helper.
* Review UI: editable results table with HTMX rate-row dropdown (row swap),
  confidence bands; ownership-scoped views; linked from BOQ detail.

Delivered (Sprint 17):

* ReviewService approve/revise with status guards (Completed/Under Review ->
  Approved; Approved -> Under Review). Invalid transitions raise ValidationError.
* Approve/Revise views + URLs (ownership-scoped) + contextual toolbar buttons.

Delivered (Sprint 18):

* PendingProductService: reject / merge (alias to existing) / add_new (new
  RateMaster + alias). Approved products become available through aliases.
* Super-Admin pending queue UI + actions; nav link; access-controlled.

Delivered (Sprint 19):

* Excel export: internal review sheet (full breakdown + confidence bands) and
  client BOQ (final rate + amount). Internal workbook links the client sheet via
  formulas; standalone client workbook uses computed values.
* ExportService persists both on ExportFile + transitions BOQ to Exported
  (approval-guarded). Export button + download links on the review page.

Delivered (Sprint 20):

* Notification service (notify / unread_count / mark_all_read) wired into
  processing complete-or-failed, BOQ approved, and export-ready events.
* Audit service (record) wired into approve, export, pending-product actions
  (reject/merge/add), and database import/rollback; secrets never logged.
* UI: /notifications/ list + "Mark all read"; Super-Admin /audit/ log; nav
  unread badge + Audit Log link via context processor.

Delivered (Sprints 22 & 24):

* End-to-end workflow integration tests (process -> review -> approve -> export
  + failure path) in workflows/tests.py.
* Production deployment instructions for EC2, Gunicorn, Nginx, Redis, Celery,
  and PostgreSQL are maintained in RUN.md.

Tests:

* 176 tests discovered and passing (verified 2026-07-07).

---

# Next Sprint

None — all 24 roadmap sprints are complete. Remaining activity is production
hardening and live validation on the EC2 instance with real client BOQs only.

---

# Pending Decisions

None.

---

# Development Priority

1. Authentication.
2. User roles.
3. Database upload.
4. BOQ upload.
5. AI extraction.
6. Matching.
7. Costing.
8. Review.
9. Export.

---

# Session Update Rules

Every development session must update:

* Completed work.
* Pending work.
* Issues.
* Next tasks.

---

# Session Log

## 2026-07-07 — Synchronous Database Upload Fix

Completed:

* Changed database upload to call `workflows.database_import.import_database`
  synchronously from the upload view.
* Removed the unused Celery database import task.
* Moved database embedding generation into a synchronous AI embedding helper.
* Stopped queuing `generate_embeddings_task`, fixing the unregistered Celery
  task error after database upload.
* Updated PRD, TRD, architecture, database architecture, project structure,
  AGENTS, session state, and changelog for the synchronous database workflow.
* Updated database-manager tests so OpenAI embeddings are skipped with a
  placeholder key during tests.
* Verified focused database-manager tests: 12 passing.

Pending:

* Restart the Django web process so the upload view uses the new synchronous
  import code.

Issues:

* Existing stale `generate_embeddings_task` messages already in Redis may still
  need to be purged once after deployment.

Next:

* Upload the database workbook again from the Database page and confirm the page
  returns only after the version is active.

## 2026-07-07 — Final Validation and Cleanup

Completed:

* Re-read and aligned PRD, TRD, architecture, database architecture, project
  structure, AGENTS, session state, and changelog for the current implemented
  workflow.
* Removed active future-scope language from product/technical/architecture docs.
* Fixed reprocessing so cloned BOQ runs preserve grouped `row_json` payloads.
* Replaced stale scaffold helpers with working task/validator implementations.
* Cleaned comments and moved processing imports to module scope.
* Verified the updated database sample imports 88 Rate_Master rows and stores
  `Final_Amount_(Excl GST)`.
* Verified sample parsing counts: `BOQ_1.xlsx` 44 items, `BOQ_2.xlsx` 109
  items, `BOQ_3.xlsx` 109 items; `Make_1.xlsx` 159 entries, `Make_2.xlsx` 136
  entries, `Make_3.xlsx` 109 entries.
* Verified upload creates BOQ status `Uploaded` with grouped `row_json`.
* Verified lowest final-amount matching selects the Rate_Master row with
  `700.00` over `1200.00`.
* Verified exports create `Breakdown List` and `Client BOQ`, with `Confidence`
  present in the breakdown sheet.
* Verified `pip check`, Ruff, Django system check, migration dry-run, and full
  test suite: 176 tests passing.

Pending:

* None for the current final validation pass.

Issues:

* Historical add/remove migrations for old vendor-selection fields remain in
  the migration chain so already-migrated databases can safely reach the
  current schema.

Next:

* Re-upload real BOQs that were uploaded before grouped-row parsing changed so
  their stored BOQRun rows capture the current structure.

## 2026-07-07 — BOQ Measured Child Row Parsing

Completed:

* Analyzed the provided `BOQ_1.xlsx`, `BOQ_2.xlsx`, and `BOQ_3.xlsx` sample
  structures.
* Updated BOQ grouping so structural parent/specification rows become context
  for measured child rows rather than separate processing rows.
* Preserved rows with actual Unit or Quantity as the processing target rows for
  costing and client-sheet Rate/Amount fills.
* Fixed parenthesized child serials such as `(A)` and `(D)` so they are not
  misread as Roman-numeral section headings.
* Verified sample parser smoke counts: `BOQ_1.xlsx` now parses 44 measured
  items, `BOQ_2.xlsx` parses 109 measured items, and `BOQ_3.xlsx` parses 109
  measured items.
* Verified `backend.tests.test_boq`: 24 tests passing.

Pending:

* Re-upload any already-created BOQs that need this corrected row grouping,
  because existing BOQRun rows keep the grouping captured at upload time.

Issues:

* No known parser issues from the provided BOQ samples.

Next:

* Run an end-to-end process/export check using one of the sample BOQs and its
  matching make list after the active database is loaded.

## 2026-07-07 — Make List Category Pair Extraction

Completed:

* Fixed Excel make-list parsing to deduplicate by make plus category instead of
  make name only.
* Preserved repeated approved makes across different material categories in
  formats like `Materials/Makes` and `Make/Manufacturers Name`.
* Improved make splitting so slash-delimited cells keep comma-bearing names
  such as `Jindal, Hissar` together.
* Verified the provided samples: `Make_1.xlsx` extracts 159 entries,
  `Make_2.xlsx` extracts 136 entries, and `Make_3.xlsx` extracts 109 entries.
* Verified `backend.tests.test_boq`: 22 tests passing.

Pending:

* End-to-end matching should be rechecked with a newly uploaded BOQ plus make
  list after the latest parser behavior is active.

Issues:

* No known make-list parser issues from this pass.

Next:

* Re-upload the affected make list on the BOQ page so the BOQRun stores the
  refreshed make/category entries before processing.

## 2026-07-07 — Export Download and BOQ Layout Preservation

Completed:

* Added authenticated download endpoints for exported client BOQ and breakdown
  list workbooks.
* Updated review export buttons to use Django download views instead of raw
  media URLs.
* Changed the internal export workbook sheet to `Breakdown List` with the
  19-column format from the provided sample workbook.
* Changed client BOQ export to copy the uploaded workbook sheet when available
  and only fill/add Unit, Quantity, Rate, and Amount.
* Preserved existing Unit and Quantity values and used them for amount
  calculation.
* Filled Rate and Amount on child/detail rows when child rows contain the
  product unit or quantity.
* Updated AI product extraction instructions to avoid forcing products from
  headings, notes, or execution-only rows.
* Added export tests for downloads, preserved client layout, and child-row
  Rate/Amount placement.

Pending:

* Validate exported BOQ and breakdown list with a real uploaded client BOQ file.

Issues:

* None known.

Next:

* Compare a generated client BOQ export against the original uploaded workbook
  during UAT.

## 2026-07-07 — Runtime AI Instruction Logs

Completed:

* Added structured runtime AI instruction logging from `AIService`.
* Created `logs/ai_instructions.log` as a dedicated rotating log file.
* Logged model, prompt template name, JSON-mode flag, and full rendered
  instruction text before each AI provider call.
* Added tests for direct prompt logging and rendered template instruction
  logging.
* Updated TRD, architecture, project structure, and changelog documentation.

Pending:

* Review log volume during real BOQ processing and tune retention if needed.

Issues:

* None known.

Next:

* Use `logs/ai_instructions.log` together with `logs/ai_extractions.log` during
  UAT to audit exactly what was sent to AI and what came back.

## 2026-07-07 — Explicit AI Row JSON Logging

Completed:

* Added explicit `fetched_row_json` to successful and failed row-level AI
  extraction logs.
* Added `ai_output_json` to successful row-level AI extraction logs, containing
  the product extraction JSON and extracted activities together.
* Kept the existing `row_json`, `product_extraction`, and `activities` fields
  for backward-compatible log reading.
* Updated changelog documentation.

Pending:

* Benchmark real BOQ processing time after running with OpenAI enabled.

Issues:

* None known.

Next:

* Evaluate row-level parallel AI extraction or batch extraction based on real
  BOQ size and OpenAI rate limits.

## 2026-07-07 — Grouped BOQ Row JSON and Database-Aware Extraction

Completed:

* Added `BOQItem.row_json` to store the structured grouped BOQ row payload.
* Changed BOQ parsing so a serial-numbered row and following blank-serial child
  rows are treated as one BOQ item and sent to AI as one JSON payload.
* Added compact active database context for AI prompts from Rate_Master,
  Labour_Master, and TOR_Labour.
* Updated product extraction prompts and services to preserve one or more
  product candidates with database-shaped category, subcategory, and
  database_hint values.
* Updated activity extraction prompts and services to filter activities against
  active database activity terminology when available.
* Updated product matching to search the original grouped BOQ description first,
  then AI product candidates and database hints.
* Updated PRD, TRD, architecture, database architecture, project structure, and
  changelog documentation for grouped-row extraction.
* Verified `python manage.py check`.
* Verified `backend.tests.test_boq backend.tests.test_ai
  backend.tests.test_matching` — 57 tests passing.
* Verified `backend.tests.test_processing backend.tests.test_workflows` — 12
  tests passing.
* Verified `python manage.py makemigrations --check --dry-run`.
* Verified Ruff on changed Python files.

Pending:

* Validate grouped-row extraction and matching with a real uploaded BOQ and the
  refreshed active database.

Issues:

* None known.

Next:

* Process a real BOQ with OpenAI enabled and review `logs/ai_extractions.log`
  to confirm products and labour activities align with the active database.

## 2026-07-07 — Lowest Final Amount Rate Selection

Completed:

* Updated the active BOQ processing flow to remove the standalone vendor
  selection stage.
* Added first-class `RateMaster.final_amount_excl_gst` storage for the
  `Final_Amount_(Excl GST)` Rate_Master workbook column.
* Changed product matching to select the lowest final-amount Rate_Master row
  when multiple rows match the same product.
* Added embedding generation to the database import workflow.
* Changed the BOQ detail action text to `Calculate BOQ` / `Recalculate BOQ`.
* Updated PRD, TRD, architecture, database architecture, project structure, and
  changelog documentation for the current flow.
* Verified `python manage.py check`.
* Verified focused tests:
  `backend.tests.test_database_manager backend.tests.test_matching
  backend.tests.test_processing backend.tests.test_workflows
  backend.tests.test_review backend.tests.test_exports` — 64 tests passing.
* Verified `backend.tests.test_matching backend.tests.test_workflows` after
  test hardening — 20 tests passing.
* Verified `python manage.py makemigrations --check --dry-run`.
* Verified Ruff on changed Python files.

Pending:

* Validate the updated import and matching flow with the refreshed March
  database workbook through the UI.

Issues:

* None known.

Next:

* Validate the updated database import and BOQ calculation flow in the UI with
  the refreshed March workbook and real BOQs.

## 2026-07-06 — Row-Level AI Extraction Logging

Completed:

* Added a dedicated `logs/ai_extractions.log` rotating log file.
* Added one structured JSON log line per successfully analyzed BOQ row with
  BOQ id, run id, item id, Excel row number, source description, product
  extraction payload, and extracted activities.
* Added row-level AI extraction failure logs to the same file.
* Added tests proving successful and failed AI row extraction events are logged.
* Updated architecture, technical, project-structure, changelog, and session
  documentation.
* Verified `backend.tests.test_ai`: 18 tests passing.
* Verified Ruff on modified AI logging files.
* Verified `python manage.py check`.

Pending:

* Validate the new log file during a real BOQ processing run with OpenAI enabled.

Issues:

* None known.

Next:

* Use `logs/ai_extractions.log` during UAT to compare source BOQ row text with
  the product and activity extraction payloads.

## 2026-07-06 — Sample-Driven BOQ and Database Import Hardening

Completed:

* Inspected the provided BOQ, make-list, and March client database workbook
  samples.
* Improved Excel make-list extraction to scan every workbook sheet and capture
  merged or continued approved-make columns.
* Added aliases for `Materials` and make/manufacturer headers used in the sample
  make lists.
* Tightened BOQ extraction so rate/amount subheader rows with blank description
  cells are not captured as BOQ items.
* Hardened database import for client rows with blank `Tech_Key` by synthesizing
  stable product codes from category, subcategory, class, and size attributes.
* Imported base-rate-minus-discount values when net rates are blank and kept all
  raw normalized workbook columns in `spec_json`.
* Updated costing fallback keys to use normalized imported names such as
  `handling`, `profit`, and `accessories`.
* Fixed linked client export formulas to reference the internal final-rate cell
  and the client quantity cell.
* Verified the sample parser smoke test: `Make_1.xlsx` now extracts 87 makes
  instead of only the first merged approved-make column, `Make_2.xlsx` now keeps
  `Materials` categories, and `BOQ_2.xlsx` no longer imports the `(Rs.)`
  subheader as a BOQ item.
* Verified `backend.tests.test_boq backend.tests.test_database_manager
  backend.tests.test_exports`: 41 tests passing.
* Verified Ruff on modified parser/import/costing/export/tests.
* Verified `python manage.py check`.

Pending:

* Full end-to-end processing should be validated after the refreshed client
  database is uploaded through the UI.
* Further cost-engine refinement may be needed once the client confirms how
  TOR accessory range rules should be applied.

Issues:

* No known parser/import/export issues from this pass.

Next:

* Upload the fixed March database workbook through the application and process
  the three sample BOQs with their make lists for UAT comparison.

## 2026-07-06 — Make List View Without Pagination

Completed:

* Removed pagination from the BOQ make-list view context.
* Removed pagination controls from the make-list template.
* Added regression coverage proving make-list entries beyond the old first page
  are shown and pagination controls are absent.
* Verified `backend.tests.test_boq`: 20 tests passing.
* Verified Ruff on the modified BOQ view and tests.

Pending:

* Broader full-suite regression can be run before merge.

Issues:

* None known for this change.

Next:

* Validate the full make-list view with a real client make-list during UAT.

## 2026-07-06 — Robust Make List Extraction and BOQ Isolation

Completed:

* Confirmed BOQ identity is ID-based, so duplicate BOQ names and duplicate
  make-list filenames do not link BOQs together.
* Improved Excel make-list parsing to detect real header rows after title rows.
* Added make-list aliases for approved make, brand, manufacturer, OEM, and
  numbered make/brand columns.
* Added support for extracting multiple makes from one cell when separated by
  common delimiters.
* Added tests for messy make-list extraction and two same-name BOQs with the
  same make-list filename remaining isolated.
* Verified `backend.tests.test_boq`: 19 tests passing.
* Verified Ruff on the modified parser and BOQ tests.

Pending:

* Broader full-suite regression can be run before merge.

Issues:

* None known for this change.

Next:

* Validate the make-list alias set against real client make-list files and add
  any newly discovered labels to parser tests.

## 2026-07-06 — Canonical BOQ Field Mapping

Completed:

* Changed BOQ parsing to map source workbook aliases into the canonical fields
  `s_no`, `description`, `unit`, and `quantity`.
* Added support for abbreviated headers such as `SNo`, `QTY`, `un`, and `ut`.
* Updated BOQ detail rendering so the UI always shows S No, Description, Unit,
  and Quantity, regardless of uploaded workbook header names.
* Aligned client BOQ output with the canonical BOQ field order.
* Updated PRD, TRD, database architecture notes, and changelog for the new
  canonical BOQ field rule.
* Verified `backend.tests.test_boq backend.tests.test_exports`: 24 tests
  passing.
* Verified Ruff on the modified parser, BOQ view, client export, and tests.

Pending:

* Broader full-suite regression can be run before merge.

Issues:

* None known for this change.

Next:

* Validate alias coverage with real client BOQs and add any newly discovered
  header variants to the parser tests.

## 2026-07-06 — Robust BOQ Excel Extraction

Completed:

* Improved BOQ Excel parsing to detect the actual BOQ header row when title or
  tender-reference rows appear before the table.
* Normalized common BOQ header variants including serial number, description,
  quantity, and unit labels.
* Preserved cleaned display values for original BOQ row data so serial numbers
  like `27.200000000000003` are kept as `27.2` while raw numeric cells remain
  available for quantity parsing.
* Added focused parser coverage for titled BOQ workbooks, nested rows without
  serial numbers, and cleaned serial-number display values.
* Verified `backend.tests.test_boq`: 16 tests passing.
* Verified Ruff on modified BOQ extraction files and tests.

Pending:

* Broader full-suite regression can be run before merge.

Issues:

* None known for this change.

Next:

* Continue UAT with real client BOQ formats and add fixture tests for any new
  layout variants discovered.

## 2026-07-06 — Make List Replacement UI

Completed:

* Removed pagination from the BOQ detail item listing so uploaded BOQ rows are
  shown together on the BOQ page.
* Removed the make-list upload card from the BOQ detail page.
* Updated the make-list page to show the currently linked make-list filename.
* Changed the make-list page action to replace the single linked make list for
  that BOQ; replacement keeps the existing behavior of deleting old parsed
  `MakeListEntry` rows for that BOQ run before inserting the new parsed makes.
* Added tests for the no-pagination detail page, absence of the detail upload
  card, current filename display, replace button text, and replacement deleting
  old make-list rows for the same BOQ.
* Verified `backend.tests.test_boq` passes (15 tests), Ruff passes on touched
  files, and `python manage.py check` passes.

Pending:

* None for this task.

Issues:

* None found in the make-list replacement UI flow.

Next:

* Validate the replace flow with a real client make-list Excel/PDF file during
  UAT.

---

## 2026-07-06 — BOQ-Scoped Make List Upload

Completed:

* Confirmed BOQ isolation uses `BOQ.id -> BOQRun.boq_id -> BOQItem.boq_run_id`
  and `MakeListEntry.boq_run_id`, so make lists are scoped to a single BOQ run.
* Added `MakeListUploadForm` and `BOQMakeListUploadView` for uploading or
  replacing a make list from an existing BOQ.
* Added `BOQMakeListUploadService` so make-list parsing and replacement happen
  in the service layer, not the view.
* Updated BOQ detail and make-list pages with upload controls.
* Updated `DATABASE_ARCHITECTURE.md` to document `MakeListEntry` ownership.
* Added tests proving a make-list update on one BOQ does not affect another BOQ
  and that non-owners cannot upload a make list to another user's BOQ.
* Verified `backend.tests.test_boq` passes (13 tests), Ruff passes on touched
  files, and `python manage.py check` passes.

Pending:

* None for this task.

Issues:

* None found in the BOQ-scoped make-list upload path.

Next:

* Validate with the real client make-list Excel/PDF files used during UAT.

---

## 2026-07-06 — Make List PDFs and BOQ Row Preservation

Completed:

* Allowed make-list uploads to accept `.pdf` in addition to Excel formats while
  keeping BOQ uploads Excel-only.
* Updated BOQ upload UI text to clearly state that PDF support is only for make
  lists.
* Preserved original BOQ workbook headers, blank serial-number cells, and
  worksheet row numbers during parsing and reprocessing.
* Updated BOQ detail and client export output to use the original uploaded BOQ
  columns before appending final rate and amount.
* Fixed the make-list PDF extraction prompt/ parser to use the AI service's
  JSON-object response shape.
* Verified `backend.tests.test_boq` and `backend.tests.test_exports` pass
  (17 tests), and `python manage.py check` passes.

Pending:

* None for this task.

Issues:

* A broader `backend.tests.test_ai backend.tests.test_processing` run still has
  unrelated pre-existing failures around processing expectations/statuses in
  the current dirty worktree.

Next:

* Validate with a real client BOQ workbook that contains nested rows and blank
  serial-number cells.

---

## 2026-07-06 — Runbook Redis and Celery Notes

Completed:

* Updated `docs/RUN.md` with local Windows Redis-through-WSL setup and the
  Celery worker command using `--pool=solo`.
* Documented that Redis can run as a WSL service, while Django `runserver` and
  the Celery worker terminals should remain open during local development.
* Added EC2 feature-update commands to `docs/RUN.md`, including
  `collectstatic --noinput` before restarting Gunicorn and Celery.
* Updated `docs/CHANGELOG.md`.

Pending:

* None.

Issues:

* None.

Next:

* Use the updated runbook for local Redis/Celery development and EC2 updates.

---

## 2026-07-03 — Enhanced BOQ Upload and PDF Make Lists

Completed:

* Updated `BOQItem` model to store `original_data` for preserving all columns from uploaded Excel.
* Updated `parse_boq_items` to capture the entire row dictionary in `original_data`.
* Added `pypdf` dependency for PDF extraction.
* Added `extract_make_list.txt` prompt for AI-based make list extraction from PDFs.
* Updated `parse_make_list` to support extracting makes from `.pdf` files via `pypdf` and `AIService`.
* Added `MakeListUploadForm` and `BOQMakeListUploadView` to allow uploading Make Lists directly under an existing BOQ run.
* Updated `boq_detail.html` to include a Make List upload form and to display "Rate" and "Amount" columns based on `CostBreakdown`.

Pending:

* None.

Issues:

* None.

Next:

* Check other markdown docs if they are updated as per the code.

---

## 2026-07-03 — Settings Consolidation and Import Cleanup

Completed:

* Consolidated runtime configuration into conventional Django
  `backend/config/settings.py` (`config.settings`).
* Removed the old `config.settings.base` and `config.settings.production` files.
* Updated Django, Celery, ASGI, WSGI, `.env.example`, README, runbook, deploy
  guide, project structure, agent instructions, roadmap, changelog, and session
  state references.
* Moved application and test imports to module scope; Ruff import checks pass.
* Added rotating application/error file handlers and kept existing service
  logging intact.
* Tightened placeholder OpenAI key detection to include `placeholder`.
* Verified Django system checks, Ruff, Pyright, and all tests.

Pending:

* None.

Issues:

* Sandboxed Python launch failed on Windows; verification was run through the
  project virtualenv outside the sandbox.

Next:

* Continue production hardening and EC2 validation with real client data.

---

## 2026-07-03 — Git Initialization & Production Readiness Audit

Completed:

* Initialized Git repository (`git init`) for the first-time push milestone.
* Performed full production readiness audit across all code, services, models,
  workflows, tests, and documentation.
* Locked all Python dependencies to exact versions in `requirements.txt`
  (replaced loose `>=` ranges with `pip freeze` output).
* Created `.python-version` file locking the runtime to Python 3.14.5.
* Fixed `.gitignore` — added `**/__pycache__/` for all-depth cache exclusion,
  added `.mypy_cache/`, clarified comments on `.env` and `staticfiles/`.
* Removed duplicate content block from `SESSION_STATE.md` (Technical Decisions
  section was repeated verbatim; incomplete Database Strategy block cleaned up).
* Updated test count in SESSION_STATE.md (149 tests).
* Added July 3 entry to CHANGELOG.md and SESSION_STATE.md.
* Updated README.md with Python version, quick-start section, and local dev
  commands for new developer onboarding.
* Added Documentation Update Instructions section to AGENTS.md.
* Fixed PROJECT_STRUCTURE.md — added middleware.py/mixins.py to common/,
  corrected logs section, added staticfiles/ auto-generation note.
* Granted CREATEDB privilege to boq_user PostgreSQL role so test suite can run.
* All 149 tests pass. No regressions.

Pending:

* None — project is ready for first Git push.

Next:

* Push to Git remote repository.
* Configure CI/CD if required.

---

## 2026-07-02 — UI Tweaks, Database Naming & 10-Version Retention

Completed:

* Hid pending products from sidebar navigation.
* Fixed UI horizontal scroll issue on User Management table (wrapped long names/emails).
* Fixed stuck upload process on Windows by configuring `CELERY_TASK_ALWAYS_EAGER=True` locally to bypass missing Redis.
* Added `name` field to `DatabaseVersion` schema with a database migration.
* Updated `DatabaseUploadForm` to capture the database name and display a processing spinner via AlpineJS on submit.
* Extended database retention to 10 versions total (1 active, 9 archived).
* Updated Database Management UI to display the new database name, restrict Rollback to the top 2 recent inactive versions, and added view/download placeholder actions.
* Updated `DATABASE_ARCHITECTURE.md` to reflect retention policy changes.

## 2026-06-23 — Sprint 23

Completed:

* UAT preparation work completed during the original sprint.
* The temporary demo seeding command from this sprint was later removed during
  production hardening so only real client data is used going forward.
* 3 command tests; full suite 134 passing.
* All 24 roadmap sprints now complete.

## 2026-06-23 — Sprints 22 & 24 (Integration Tests + Deployment)

Completed:

* End-to-end workflow tests (full pipeline, failure path, review/approve/export).
* Deployment kit: Gunicorn, Nginx, systemd (web + Celery), prod env template,
  EC2 deployment runbook.
* 4 new tests; full suite 131 passing.

## 2026-06-23 — Sprint 20 (Notifications + Audit)

Completed:

* Notification service + event wiring (processing done/failed, approval, export).
* Audit service + wiring (approve, export, pending actions, db import/rollback).
* Notifications list + mark-all-read; Super-Admin audit log; nav unread badge.
* 10 new tests; full suite 127 passing.

## 2026-06-23 — Sprint 19 (Export System)

Completed:

* Internal + client Excel sheets (formatter, confidence bands, linked formulas).
* ExportService: two-sheet internal workbook + standalone client; ExportFile
  persistence; BOQ -> Exported (approval-guarded).
* Export views/urls + review-page export button & download links.
* 6 new tests; full suite 117 passing.

Pending:

* Sprint 20 — notifications + audit.

Issues:

* None.

Next:

* Event notifications + audit logging.

---

## 2026-06-23 — Sprint 18 (Pending Products)

Completed:

* PendingProductService: reject / merge (alias) / add_new (RateMaster + alias).
* Super-Admin pending queue UI + reject/merge/add actions; nav link.
* 9 new tests; full suite 111 passing.

Pending:

* Sprint 19 — export system.

Issues:

* None.

Next:

* Internal + client Excel export; transition BOQ to Exported.

---

## 2026-06-23 — Sprint 17 (Approval Workflow)

Completed:

* ReviewService approve/revise with status guards; ValidationError on invalid.
* Approve/Revise views + URLs (ownership-scoped) + contextual toolbar buttons.
* 7 new tests; full suite 102 passing.

Pending:

* Sprint 18 — pending products admin review.

Issues:

* None.

Next:

* Super Admin pending-product queue (approve/reject/merge/add).

---

## 2026-06-23 — Sprint 16 (Internal Review)

Completed:

* ReviewService: vendor/product re-point + ReviewItem audit + cost recalc.
* Status transition to Under Review; candidate_rates helper.
* HTMX editable review table; ownership-scoped views; BOQ-detail link; CSS.
* 9 new tests; full suite 95 passing.

Pending:

* Sprint 17 — approval workflow.

Issues:

* None.

Next:

* Approve/revise transitions and export preparation.

---

## 2026-06-23 — Sprint 15 (Commercial Costing)

Completed:

* Transportation/overhead/profit services + tunable percent constants.
* StateControl multipliers (optional state_name); 2dp quantization.
* Full CostBreakdown computed + final_rate; cost engine (Phase 7) complete.
* 3 new tests + updated cost assertions; full suite 86 passing.

Pending:

* Sprint 16 — internal review workflow.

Issues:

* Commercial percentages are placeholder defaults (docs defer exact values).
* No BOQ-level state field yet -> multipliers default neutral.

Next:

* Reviewable results UI with editable rows + recalculation.

---

## 2026-06-23 — Sprint 14 (Labour Cost)

Completed:

* Labour + accessories cost from TOR tables (joined by tor_code==product_code).
* CostCalculationService preloads costing context; populates labour/accessories.
* 4 new tests; full suite 83 passing.

Pending:

* Sprint 15 — commercial costing (transport/overheads/profit + state).

Issues:

* TOR linkage assumed tor_code == product_code (only concrete join available).

Next:

* Transportation, overheads, profit + StateControl multipliers.

---

## 2026-06-23 — Sprint 13 (Material Cost)

Completed:

* Material cost from selected vendor purchase_rate; CostCalculationService.
* CostBreakdown per item + final_rate sync; recompute helper; idempotent.
* Costing stage wired into processing workflow.
* 5 new tests; full suite 79 passing.

Pending:

* Sprint 14 — labour cost.

Issues:

* None.

Next:

* Labour/accessories cost from Labour_Master + TOR + activities.

---

## 2026-06-23 — Sprint 12 (Vendor Selection)

Completed:

* VendorSelectionService: lowest-cost / preferred / custom + make filtering.
* Writes chosen vendor back to ProductMatch; wired into matching stage.
* 6 new tests; full suite 74 passing.

Pending:

* Sprint 13 — material cost.

Issues:

* None (no compliant vendor -> match left unchanged, logged).

Next:

* Material cost from selected vendor purchase_rate x quantity.

---

## 2026-06-23 — Sprint 11 (Confidence Engine)

Completed:

* ConfidenceService: factor-weighted scoring + colour bands + explanations.
* Optional OpenAI validation enrichment (deterministic when AI disabled).
* Confidence stage wired into processing workflow.
* 6 new tests; full suite 68 passing.

Pending:

* Sprint 12 — cost engine.

Issues:

* None.

Next:

* Material/labour/TOR cost calculation with state multipliers (no AI pricing).

---

## 2026-06-23 — Sprint 10 (Matching Engine)

Completed:

* exact/alias/vector matchers + ProductMatchingService (priority order).
* ProductMatch persistence (confidence + reason); idempotent reprocess.
* Pending-product routing for <30% confidence (blank product).
* generate_embedding (OpenAI, guarded) + OPENAI_EMBEDDING_MODEL; utils.text.
* Matching stage wired into processing workflow.
* 7 new tests (mocked embedding); full suite 62 passing.

Pending:

* Sprint 11 — confidence engine.

Issues:

* None (vector match skipped gracefully when AI disabled / no embeddings).

Next:

* Refined confidence scoring, colour bands, and match explanations.

---

## 2026-06-23 — Sprints 8 & 9 (Product + Activity Extraction)

Completed:

* product_extractor + activity_extractor using AIService.
* BOQItem.ai_extraction JSONField + migration; ActivityMatch persistence.
* analyzer.analyze_run (per-item extraction, error-skip, idempotent); wired into
  AI-analysis stage guarded by is_enabled().
* activity_extraction prompt switched to JSON object output.
* 7 new tests (mocked); full suite 55 passing.

Pending:

* Sprint 10 — matching engine.

Issues:

* None (AI disabled by default via placeholder key).

Next:

* Match extracted products to RateMaster; persist ProductMatch + confidence.

---

## 2026-06-23 — Sprint 7 (OpenAI Integration)

Completed:

* AIService (prompt loading, chat, JSON mode, error handling, logging).
* Placeholder-aware key detection; OPENAI_MODEL/timeout settings.
* AI-analysis stage wired into processing (guarded by is_enabled).
* 9 new tests (mocked client); full suite 48 passing.

Pending:

* Sprint 8 — product extraction.

Issues:

* None (AI disabled by default via placeholder key).

Next:

* Implement product extractor using AIService; persist per-item results.

---

## 2026-06-23 — Sprint 6 (Processing Queue)

Completed:

* boq_processing workflow with staged progress + status transitions.
* ProcessingJobService (queue/dispatch-on-commit/reprocess+clone).
* Processing start view, HTMX status fragment, processing dashboard.
* BOQ detail Process/Reprocess button + live progress panel; progress CSS.
* 8 new tests; full suite 39 passing.

Pending:

* Sprint 7 — OpenAI integration.

Issues:

* None.

Next:

* Implement AI service + prompts; wire the AI analysis stage hook.

---

## 2026-06-22 — Sprint 5 (BOQ Management)

Completed:

* BOQ + make-list parser (tolerant headers, blank-row skipping).
* BOQCreationService (BOQ + run 1 + items + make entries).
* BOQ list/upload/detail views with ownership rules + nav link.
* Live dashboard metrics.
* 8 new tests; full suite 31 passing.

Pending:

* Sprint 6 — processing queue.

Issues:

* None.

Next:

* Celery BOQ processing job + progress tracking + status transitions.

---

## 2026-06-22 — Sprints 3 & 4 (Database Management)

Completed:

* Excel row reader (openpyxl) in utils/excel.py.
* DatabaseImportService (validate/backup/import/activate + retention).
* DatabaseRollbackService.
* Database import workflow.
* Super-Admin database UI (list/upload/rollback) + nav link.
* 11 new tests; full suite 23 passing.

Pending:

* Sprint 5 — BOQ upload module.

Issues:

* None.

Next:

* BOQ + make list upload, ownership, status, list/detail UI.

---

## 2026-06-22 — Sprints 1 & 2

Completed:

* Full project scaffolding per PROJECT_STRUCTURE.md.
* Single settings module (`config.settings`), Celery, logging.
* All 13 app models + initial migrations applied.
* Custom email-based User, roles, login/logout/password reset.
* Super-Admin user management (list/create/edit/activate).
* Responsive dashboard + base layout (HTMX + Alpine.js).
* AI client + prompt scaffolding; service/workflow/task stubs.
* 12 passing tests (accounts + users).

Pending:

* Sprint 3 — database upload + validation + versioning.

Issues:

* None.

Next:

* Implement DatabaseImportService and the database upload UI.

---

# Agent Startup Checklist

Before coding:

1. Read PRD.md.
2. Read TRD.md.
3. Read ARCHITECTURE.md.
4. Read DATABASE_ARCHITECTURE.md.
5. Read PROJECT_STRUCTURE.md.
6. Read AGENTS.md.
7. Read SESSION_STATE.md.

Only then begin development.

---

# Project State Summary

Status:

Deployment Ready — All 24 sprints complete.

Development:

Complete (active maintenance mode — UAT / production hardening).

Architecture:

Frozen.

Database:

Version 1 implemented, migrated; import/rollback engine working; embeddings
generated when AI key is present. pgvector upgrade is post-UAT.

Test Coverage:

176 passing tests across all 13 apps + workflows.

Risk Level:

Low.

Next Milestone:

Production hardening and live validation on EC2 with real client BOQs before
promotion to production.

---

## 2026-06-30 — Documentation & Code Cleanup Session

Completed:

* SESSION_STATE.md updated: corrected stale "Sprints 1-19 complete" headers and
  "Next Milestone: Sprint 20" footer — now accurately reflects all 24 sprints done
  and project in deployment-ready / UAT state.
* Embedding generation helper: replaced `NotImplementedError` scaffold with
  a real implementation — iterates RateMaster rows for the given DatabaseVersion,
  generates OpenAI embeddings (via ai.embeddings.generator), persists to
  ProductEmbedding; idempotent (skips existing), graceful when AI disabled.
* ai/embeddings/search.py: replaced `NotImplementedError` scaffold with a working
  cosine-similarity vector search over ProductEmbedding rows (pure Python / JSON
  in V1; pgvector upgrade is post-UAT backlog).
* workflows/review_workflow.py: replaced `NotImplementedError` scaffold with
  thin shims delegating to ReviewService (submit_for_review / approve_boq /
  reopen_for_review).
* workflows/boq_processing.py: corrected module docstring — stage order was
  wrong (listed "cost → confidence" but actual order is "costing → confidence");
  removed stale "phases 4-7 pending" comment; updated _run_stage docstring.
* docs/AGENTS.md: corrected "Future Documentation" section — CHANGELOG.md
  was listed as a future document but has existed since Sprint 1. Added a
  current documentation status table.

Pending:

* None — all code and documentation now consistent with project completion state.

Issues found & fixed in-session:

* `ProductEmbedding` model (V1) has only `product_code` (CharField),
  `embedding_vector` (JSONField), `generated_at` — no `rate_master` FK and
  no `database_version` FK as originally assumed.
  - Fixed embedding generation idempotency check and
    `update_or_create` lookup changed from FK kwargs to
    `product_code=product.product_code`.
  - Fixed in `ai/embeddings/search.py`: rewrote to score all ProductEmbedding
    rows by `product_code`, then resolve back to RateMaster via
    `product_code + database_version` join.

Next:

* Staging EC2 deployment per RUN.md.
* UAT with real client BOQs.
* Post-UAT: pgvector migration for production-scale embedding search.

---

## 2026-07-01 — EC2 Runtime Simplification & Repository Cleanup

Completed:

* Standardized the active runtime on `config.settings`.
* Updated `manage.py`, Celery, WSGI/ASGI expectations, systemd, `.env` examples,
  `README.md`, and `RUN.md` for the single EC2 flow.
* Updated PostgreSQL docs to use database `boq_db` and user `boq_user`.
* Made SMTP optional until a domain or mail provider is ready; production falls
  back to Django console email logging when `EMAIL_HOST` is blank.
* Added stricter agent/developer rules in `docs/AGENTS.md`: confirm a code
  change is necessary before writing it, keep code simple, and comment intent
  rather than obvious syntax.
* Removed obsolete local/development settings and local-only requirements.
* Removed generated runtime artifacts from the workspace: `db.sqlite3`, logs,
  and Python `__pycache__` files.

Pending:

* Create or update `/srv/boq_ai/.env` on the EC2 instance with real secrets.
* Rotate the PostgreSQL password if the current one has been shared anywhere
  outside the server.
* Run deployment commands from `RUN.md` on the EC2 instance.

Next:

* Deploy to the EC2 public IP over HTTP for UAT.
* Add domain, TLS, and SMTP later, then enable the HTTPS security flags.

---

## 2026-07-01 — Repository Simplification Follow-up

Completed:

* Removed the unused `backend/api/` placeholder package and Django REST
  Framework dependency/configuration.
* Removed the stale `pyrightconfig.json`; a focused replacement was later added
  when editor diagnostics were standardized around `backend/` as the import
  root.
* Consolidated Python dependencies into root `requirements.txt`.
* Removed tracked deployment template files and added `/deploy/` to `.gitignore`.
* Moved deployment operating instructions into `RUN.md`.

Pending:

* Create server-local systemd and Nginx files from `RUN.md`.
* Keep any future deployment scratch files under ignored `deploy/` if needed.

---

## 2026-07-01 — Production Data Cleanup

Completed:

* Updated local `.env` to the single production EC2 configuration.
* Added a generated Django `SECRET_KEY` to `.env`.
* Added PostgreSQL, Redis, Celery, OpenAI, SMTP, HTTPS, and Gunicorn variables
  to `.env`.
* Removed the `seed_demo` management command and its tests.
* Removed existing runtime/sample files from `media/`.
* Reconfirmed that future work should target production behavior and real
  client data only.

Pending:

* Rotate the PostgreSQL password on EC2 because it was shared outside the
  server context.
* Install dependencies on the local/server environment before running the full
  Django check/test suite.

---

## 2026-07-01 — Documentation Alignment & Residual Cleanup

Completed:

* Updated PRD/TRD/Architecture/Runbook/Agent instructions to reflect the current
  production-ready direction.
* Confirmed PostgreSQL is the only active database path.
* Documented that local development and EC2 both use PostgreSQL on `localhost`.
* Removed stale references to active DRF/API, SQLite fallback, split local
  settings, demo seeding, and old requirements/deploy structures from active
  docs.
* Confirmed OpenAI key handling remains environment-based and secrets must not
  be logged or committed.

Pending:

* Create the local PostgreSQL role/database.
* Install project dependencies in the active Python environment.
* Run `python manage.py check`, migrations, and the relevant test suite once
  PostgreSQL and dependencies are available.

---

## 2026-07-01 — Docs and Test Reorganization

Completed:

* Moved `CHANGELOG.md`, `RUN.md`, and `DEPLOY.md` into `docs/`.
* Removed `/docs/` from `.gitignore` so documentation remains trackable.
* Centralized all test modules under `backend/tests/`.
* Removed app-local `tests.py` files from feature folders.
* Updated test imports that depended on old package-relative locations.
* Restored `pyrightconfig.json` with `backend/` as the import root so editor
  diagnostics match the current Django layout.
* Removed the unused Celery debug task and its debug `print`.
* Updated `docs/PROJECT_STRUCTURE.md` to remove stale standalone
  `backend/services/` and unused utility-file references.
* Rebuilt local `.venv` and installed the root `requirements.txt`.
* Installed local-only lint/type tooling in `.venv` for verification.
* Removed the unused debug-toolbar URL hook.
* Created local PostgreSQL role `boq_user`, granted it ownership/privileges on
  `boq_db`, updated local `.env` for the local password, and applied all
  migrations.

Next:

* Continue adding future tests under `backend/tests/` using
  `test_<module_or_feature>.py` naming.
* Select `.venv\Scripts\python.exe` in VS Code if the problem panel still shows
  stale interpreter diagnostics, then reload the editor window.
