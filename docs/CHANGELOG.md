# Changelog

This changelog is intentionally compact. It records meaningful product and
technical changes only. Detailed implementation notes belong in the relevant
source-of-truth documents.

## 2026-07-09 — Readable AI Extraction Logs And Cleaner Row Input

- AI extraction logs now record the analyzed description, serial number, and
  only the non-null product fields the model returned, so reviewers can see
  exactly what was fetched from each BOQ row instead of walls of null fields.
- Rows without a stated quantity now send `null` to the model instead of `0`,
  so a heading/section row is not read as a quantity of zero.

## 2026-07-09 — Fix BOQ Serial Display And Processing Progress

- BOQ parser now preserves Excel section serials like `21.0` / `30.0`, flushes
  orphan section rows, and clears consumed grouping context after measured rows.
- BOQ detail expands grouped `row_json.rows` so section headers appear in the
  items table; processing redirects back to the BOQ detail page with live HTMX
  progress polling.


- Deleted the `pending_products` app, templates, tests, and all matching hooks
  that created pending-product queue rows.
- Removed unused `ProductAlias`, `alias_match`, `product_validator`, and unwired
  Celery tasks `export_files_task` / `send_notification_task`.
- Matching now leaves low-confidence rows blank for expert review only.

## 2026-07-09 — Version State Control And Remove Alias/Pending Flow

- Versioned `State_Control_List` imports through `database_version` like the
  other master sheets.
- Removed `ProductAlias`, alias matching, and the inactive pending-products
  workflow wiring from runtime settings, URLs, and matching.

## 2026-07-09 — Removed ProductEmbedding Table

- Removed the redundant `ProductEmbedding` PostgreSQL audit model, admin, and
  import-time writes; Chroma is now the single source of the product vector
  index.
- Dropped `ProductEmbedding` from the `database_manager` initial migration and
  added an idempotent migration to drop the table from existing databases.

## 2026-07-08 — Schema Drift Repair Migrations

- Added idempotent repair migrations for existing PostgreSQL databases whose
  migration history marked the fresh baseline as applied while missing
  `BOQItem.target_excel_row` and current `ProductMatch` review/quantity fields.
- Added an idempotent repair migration to create the missing
  `costing_ratedetail` table in drifted PostgreSQL schemas.
- Applied the repair locally and verified the database model-column drift check
  returns no missing tables or columns.

## 2026-07-08 — Fresh Migration Baseline Cleanup

- Removed historical application migration files and regenerated clean
  model-aligned `0001_initial` migrations for the current schema.
- Removed stale compiled Python cache directories from backend application code.
- Updated documentation to describe the fresh migration baseline and existing
  database reset or reviewed `--fake-initial` requirement.

## 2026-07-08 — BOQ Processing Retrieval Implementation

- Implemented the restructured BOQ processing flow from grouped-row extraction
  through product matching, rate/labour retrieval, review, and export mapping.
- Removed active deprecated lookup keys and old costing-service usage from
  import, matching, embeddings, pending products, admin, prompts, and exports.
- Replaced recalculated cost breakdowns with retrieved Rate_Master and
  Labour_Master detail storage, including product-level quantity basis and
  review-required handling.
- Updated the AI extraction contract to `database_products[]`,
  `missing_products[]`, and `activities[]`, with one Breakdown List row per
  extracted product/component.

## 2026-07-08 — BOQ Extraction And Mapping Rules

- Removed deprecated lookup keys from the active matching, embedding, and
  database import specification.
- Documented grouped BOQ processing with `target_excel_row`, three-segment AI
  extraction (`database_products[]`, `missing_products[]`, `activities[]`),
  product-level quantity/unit, and quantity basis.
- Clarified Breakdown List visibility for hidden products/components and client
  export mapping back to the original workbook row.

## 2026-07-08 — Rate And Labour Retrieval Rule

- Updated product and technical documentation so BOQ_AI retrieves precomputed
  Rate_Master and linked Labour_Master values instead of recalculating client
  workbook costing formulas.
- Clarified that embeddings are generated after database upload/import
  activation as a rebuildable product lookup index while PostgreSQL remains the
  source of truth.
- Standardized database retention to one active version plus two rollback
  versions.

## 2026-07-08 — Complete AI Source Row JSON

- Preserved complete grouped BOQ descriptions and top-level unit, quantity,
  serial number, and row canonical data in AI source-row JSON.
- Added regression coverage so AI extraction logs and batch prompts keep the
  full grouped row context.

## 2026-07-08 — AI Timeout Fallback And Processing Price Display

- Retried failed AI extraction batches by recursively splitting them into
  smaller row groups before skipping individual failed rows.
- Reduced the default extraction batch size to 5, increased the OpenAI timeout
  to 120 seconds, and made SDK retries configurable with `OPENAI_MAX_RETRIES`.
- Hid calculated BOQ detail rates and amounts while the latest run is still in
  `PROCESSING` so prices appear only after processing completes.

## 2026-07-08 — Database Context Cache Invalidation

- Invalidated the AI database-context cache whenever database import or
  rollback changes the active `DatabaseVersion`.
- Added regression coverage for rebuilding AI vocabulary after same-version
  data changes and when switching among three retained database versions.

## 2026-07-08 — CAG-Friendly AI Context Cache

- Cached compact active database context by DatabaseVersion and kept it before
  variable BOQ row JSON in batch extraction prompts.
- Logged provider token usage, including cached prompt token counts when
  returned.
- Tightened the batch extraction JSON contract so every input row id returns
  scoped products and activities.

## 2026-07-08 — Batched AI Row Extraction

- Replaced per-row BOQ extraction calls with configurable batched extraction so
  shared instructions and database context are sent once per batch.
- Added `AI_ROW_EXTRACTION_BATCH_SIZE` and the batch extraction prompt.

## 2026-07-08 — Extraction Deduplication And Missing Products

- Deduplicated AI-extracted product candidates and compacted row extraction logs
  so repeated descriptions are no longer emitted at multiple levels.
- Added `product_name` extraction for products not present in Rate_Master.
- Stored matching results back into extraction JSON as `database_products[]`
  and `missing_products[]`.

## 2026-07-07 — Stale BOQ Task Guard

- Added a Celery task-boundary guard so `process_boq_task` skips missing
  BOQRun ids before entering the processing workflow.
- Added regression coverage for stale queued BOQ processing messages.

## 2026-07-07 — Master Database Schema Update

- Added first-class PostgreSQL fields for the provided Rate_Master,
  Labour_Master, TOR_Main, Labour_Structure_Source, TOR_Labour,
  TOR_Accessories, and State_Control_List structure.
- Updated database import to populate the new columns and require
  `Labour_Structure_Source`.
- Updated embeddings, AI context, exact matching, and costing to use
  `tech_key`, category/sub_category/size, supplier, net material rate, labour
  totals, TOR accessory bands, and state multipliers.
- Removed old duplicate master columns and compatibility fallbacks
  (`product_code`, `purchase_rate`, legacy TOR codes, `spec_json`,
  `state_name`, and related fields).
- Renamed matching/review audit fields from vendor terminology to supplier
  terminology.

## 2026-07-07 — Stale BOQ Task Handling

- Made BOQ processing tasks skip and log stale queued BOQRun ids instead of
  crashing with `BOQRun matching query does not exist`.
- Added regression coverage for the missing-run workflow case.

## 2026-07-07 — Multi-Product BOQ Row Handling

- Matched each extracted product/equipment from a grouped BOQ row
  independently instead of collapsing the row to one product.
- Added `ProductMatch.extraction_index` so confidence and exports map each
  match back to the correct `products[]` candidate.
- Updated the Breakdown List to write one row per matched product/equipment.
- Updated the Client BOQ sheet to sum multiple breakdown final rates back into
  the original BOQ row.

## 2026-07-07 — Chroma Embedding Search

- Moved vector search to a local Chroma persistent index so PostgreSQL remains
  the source of truth without requiring a vector extension.
- Changed `ProductEmbedding` into a lightweight audit record for Chroma-indexed
  Rate_Master rows.
- Rebuilt embeddings into Chroma after each successful database import.
- Resolved Chroma hits back to PostgreSQL Rate_Master rows before applying the
  lowest-final-amount selection rule.

## 2026-07-07 — GPT-5 Mini Temperature Fix

- Omitted custom `temperature` for GPT-5/o-series chat models so `gpt-5-mini`
  uses the provider default.
- Added regression tests covering GPT-5 mini and older model request kwargs.

## 2026-07-07 — Documentation Compaction

- Condensed `SESSION_STATE.md` and `CHANGELOG.md` to remove long historical
  sprint detail.
- Kept only active workflow, recent changes, verification status, and key
  operational notes.

## 2026-07-07 — AI Extraction Flow

- Combined product and activity extraction into one row-level AI call.
- Added `boq_row_extraction.txt` and `row_extractor.py`.
- Removed separate product/activity extraction prompt and extractor files.
- Refactored row extraction logs to one `source_row` plus one `extraction`
  object.
- Normalized missing or malformed `BOQItem.row_json` into traversable
  `boq_row_group_v1` payloads before AI processing.
- Changed product extraction to database-shaped `products[]` fields.
- Limited product prompt context to Rate_Master vocabulary fields.
- Changed default chat model to `gpt-5-mini`.
- Stopped sending non-default `temperature` for GPT-5/o-series models.

## 2026-07-07 — Database Upload And Embeddings

- Made database upload/import synchronous from the upload request.
- Removed old Celery database import and embedding generation tasks.
- Generate product embeddings inline after database activation.
- Store product vectors in Chroma and record indexed products in
  `ProductEmbedding`.
- Fixed unregistered `generate_embeddings_task` Celery error.

## 2026-07-07 — BOQ Parsing, Matching, And Export

- Grouped parent/specification BOQ rows as context for measured child rows.
- Preserved child/detail rows as the processing/export targets when they carry
  unit or quantity.
- Fixed make-list parsing for multiple client formats and repeated make/category
  pairs.
- Removed active supplier-selection override flow.
- Matching now selects the lowest `Final_Amount_(Excl GST)` Rate_Master row.
- Added authenticated export downloads.
- Internal export sheet is `Breakdown List`.
- Client export preserves uploaded BOQ format and fills only Unit, Quantity,
  Rate, and Amount.
- Breakdown export includes product-focused confidence.

## 2026-07-06 — Real Sample Hardening

- Hardened BOQ parsing for varied headers, title rows, blank rows, nested rows,
  and rate/amount subheaders.
- Hardened make-list parsing for Excel/PDF inputs, multiple make columns, and
  make/header aliases.
- Preserved uploaded worksheet row numbers and original row data for display and
  export.
- Added row-level AI extraction logging.
- Added Windows Redis/Celery runbook notes.

## 2026-07-03 — Production Readiness

- Consolidated runtime to single `config.settings`.
- Cleaned obsolete settings, demo data, generated files, and unused APIs.
- Moved active docs into `docs/`.
- Centralized tests under `backend/tests/`.
- Locked dependencies and Python version.
- Confirmed PostgreSQL-only production direction.

## 2026-06-22 To 2026-06-23 — Core Platform Delivery

- Delivered Django project scaffold, apps, models, migrations, authentication,
  roles, dashboard, database import/versioning/rollback, BOQ upload, make-list
  upload, processing queue, AI service, matching, confidence, costing, review,
  approval, pending products, notifications, audit logs, exports, integration
  tests, and deployment runbooks.

## Current Verification

Latest verified result on 2026-07-07:

```text
Ruff: passed
Migration check: no changes detected
Tests: 183 passed
```
