# BOQ_AI Session State

This file is the compact active memory for BOQ_AI. Detailed product and
architecture rules live in PRD, TRD, ARCHITECTURE, DATABASE_ARCHITECTURE,
PROJECT_STRUCTURE, and AGENTS.

## Current Status

- Phase: production hardening and UAT with real client data.
- Roadmap: all 24 original sprints delivered.
- Runtime: single Django settings module, `config.settings`.
- UI: Django Templates, HTMX, Alpine.js.
- Database: PostgreSQL only.
- Queue: Celery + Redis for BOQ processing and other long-running jobs.
- Database upload: synchronous request flow.
- AI provider: OpenAI.
- Default chat model: `gpt-5-mini`.
- GPT-5/o-series chat requests omit custom `temperature` and use model default.
- Embedding model: `text-embedding-3-small`.
- Embedding storage/search: local Chroma persistent index at `CHROMA_PATH`.
- Test status: 192 tests passing, verified 2026-07-08.
- Active master sheets: Rate_Master, Labour_Master, TOR_Main,
  Labour_Structure_Source, TOR_Labour, TOR_Accessories, State_Control_List.

## Active Workflow

Database upload:

```text
Upload workbook -> Validate -> Import -> Activate -> Generate embeddings
```

Database import does not queue Celery tasks. Embeddings are generated inline
after activation and skipped cleanly when AI is disabled.
Embeddings are built from active-version Rate_Master product/specification
fields such as category, sub_category, class, size_mm, make, capacity, unit,
supplier, and descriptive technical columns. Deprecated lookup keys are
not used.

BOQ processing:

```text
Upload BOQ -> status Uploaded -> Open BOQ -> Process BOQ
-> Celery processing -> AI row extraction -> matching -> rate/labour retrieval
-> confidence -> review -> approval -> export
```

BOQ row handling:

- BOQ parser preserves original workbook rows and client sheet layout.
- Parent/specification rows without unit or quantity become context.
- Measured child rows with unit or quantity are processing/export target rows.
- Each BOQItem stores `target_excel_row` so export can map selected output back
  to the original workbook row.
- `BOQItem.row_json` uses `boq_row_group_v1`.
- Analyzer normalizes missing/malformed `row_json` into a traversable
  `source_row.rows[]` payload before AI extraction.

AI extraction:

- One AI call per configurable batch of grouped BOQ items.
- Target extraction batch size is 10 finalized grouped BOQ items.
- If a batch extraction request fails or times out, the analyzer retries by
  splitting the batch into smaller row groups before skipping individual failed
  rows.
- Prompt: `backend/ai/prompts/boq_row_batch_extraction.txt`.
- Extractor: `backend/ai/extractors/row_extractor.py`.
- Batch size setting: `AI_ROW_EXTRACTION_BATCH_SIZE` should target 10 for the
  restructured flow.
- OpenAI completion timeout defaults to 120 seconds with
  `OPENAI_MAX_RETRIES=1`; application-level fallback handles splitting timed
  out extraction batches.
- `ai/context.py` caches the compact database context by active
  DatabaseVersion and renders it before variable BOQ row JSON.
- Database import and rollback invalidate the AI database-context cache after
  activation changes so retained master database versions rebuild context when
  made active.
- AI token usage logs include provider returned cached token counts when
  present.
- Log file: `logs/ai_extractions.log`.
- Instruction log: `logs/ai_instructions.log`.
- Log shape: `source_row` plus `extraction`.
- `source_row` preserves the complete grouped description, top-level
  serial_number, unit, quantity, excel row numbers, and per-row canonical BOQ
  data when available.
- Extraction result includes `database_products[]`, `missing_products[]`, and
  `activities[]`.
- A grouped BOQ row can extract multiple products/equipment/components; each
  product candidate is matched independently.
- Product fields: product_name, category, sub_category, class, size_mm, make,
  capacity, unit, height, working_pressure, test_pressure, temperature, throw,
  k_factor, head, supplier, product_quantity, product_unit, quantity_basis, and
  quantity_source.
- `quantity_basis` is `per_boq_unit`, `total_for_boq_row`, or `unknown`.
- BOQ item unit/quantity are client billing/export values and must not be
  blindly applied to every extracted product/component.
- Extracted product candidates are deduplicated before storage.
- Matching writes `database_products[]` for extracted candidates found in
  Rate_Master and `missing_products[]` for candidates not found in the active
  database.
- AI's database/missing split is advisory; PostgreSQL matching is authoritative.
- AI does not calculate costs, choose prices, or select suppliers.

Matching and rate/labour retrieval:

- Structured AI product candidates are searched first, one candidate at a time.
- Original BOQ description is used as fallback when no product candidate is
  extracted.
- Exact, alias, and embedding matching are active.
- Deprecated lookup keys are removed from the active matching workflow.
- Embedding matching queries Chroma, then resolves hits back to PostgreSQL
  Rate_Master rows.
- If multiple Rate_Master rows match, select the lowest
  `Final_Amount_(Excl GST)`.
- BOQ detail hides selected rates and amounts while the latest run is still
  processing; pricing appears after the run reaches completed/review state.
- Master database models now use only the shared client schema columns; old
  compatibility master columns such as product_code, purchase_rate,
  subcategory, spec_json, legacy TOR codes, and state_name are removed.
- The selected RateMaster row supplies precomputed material, commercial,
  supplier, make, and final amount fields.
- RateMaster.tech_key links to LabourMaster so processing can retrieve
  corresponding precomputed labour charge details.
- LabourStructureSource may be used only as a lookup fallback to resolve a
  RateMaster category/sub_category/size row to a LabourMaster tech_key.
- ProductMatch and review audit store supplier, not vendor-selection fields.
- Standalone supplier-selection workflow is not active.
- The app does not recalculate workbook costing formulas, including material,
  labour, transportation, accessories, overheads, profit, commercial
  percentages, supplier selection, or final rate.
- Confidence is product-focused and shown in the breakdown sheet.
- `ProductMatch.extraction_index` links each match back to its extracted
  product candidate.

Export:

- Internal sheet name: `Breakdown List`.
- Breakdown List writes one row per matched product/equipment.
- Hidden products/components extracted from one BOQ row appear as separate
  Breakdown List rows, including missing/pending rows when no confident match is
  found.
- Client sheet preserves uploaded BOQ format when possible.
- Client sheet fills only Unit, Quantity, Rate, and Amount.
- Existing Unit and Quantity are preserved.
- Child/detail rows receive Rate and Amount when they are the measured rows.
- If one BOQ item has multiple product matches, client export uses selected
  precomputed final amount fields according to documented export rules.
- Client export writes output to each BOQItem `target_excel_row` and preserves
  unrelated workbook content as closely as possible.

## Current Files Of Interest

- `backend/ai/extractors/analyzer.py`
- `backend/ai/extractors/row_extractor.py`
- `backend/ai/prompts/boq_row_extraction.txt`
- `backend/ai/prompts/boq_row_batch_extraction.txt`
- `backend/ai/context.py`
- `backend/apps/boq/services/parser.py`
- `backend/apps/matching/services/matching_service.py`
- `backend/apps/matching/services/confidence.py`
- `backend/apps/costing/services/rate_detail.py`
- `backend/apps/database_manager/services/importer.py`
- `backend/ai/embeddings/generate_database_embeddings.py`
- `backend/exports/internal_sheet.py`
- `backend/exports/client_sheet.py`

## Recent Completed Work

2026-07-07:

- Fixed analyzer row payload normalization so AI always receives traversable
  `source_row.rows[]`.
- Combined product and activity AI extraction into one row-level AI call.
- Refactored AI extraction logs to remove duplicate JSON fields.
- Changed product extraction toward database-shaped product candidates.
- Changed default OpenAI chat model to `gpt-5-mini`.
- Stopped sending `temperature=0` to `gpt-5-mini`.
- Changed embeddings from PostgreSQL JSON/Python cosine to local Chroma search.
- Made database upload/import synchronous and removed old Celery import tasks.
- Added first-class database fields for the provided master schema and imported
  Labour_Structure_Source.
- Updated embeddings, AI context, matching, and costing to use the new
  Rate_Master/Labour_Master/TOR relationship structure.
- Fixed grouped BOQ parsing for parent/context rows and measured child rows.
- Fixed make-list extraction across provided sample formats.
- Fixed export downloads and preserved client BOQ layout.
- Added multi-product BOQ row handling from extraction through matching,
  confidence, breakdown export, and summed client-sheet rates.
- Made BOQ processing tasks skip stale queued run IDs instead of crashing when
  the BOQRun no longer exists.
- Verified full suite: 183 tests passing.

Earlier delivered foundation:

- Authentication, roles, dashboards, user management.
- Database versioning, rollback, retention.
- BOQ upload, make-list upload, processing jobs.
- Matching, confidence, costing, review, approval.
- Pending products, notifications, audit logs.
- Excel exports and deployment runbooks.

## Pending / Next

- Restart Django and Celery after latest code changes.
- Reprocess affected BOQs so stored runs use current row JSON/extraction logic.
- Confirm `logs/ai_extractions.log` contains `source_row.rows[]`.
- Upload the real database workbook again and confirm synchronous import
  completes with embeddings generated or intentionally skipped.
- Run UAT on real BOQs and compare client-sheet exports against source files.

## Known Issues / Notes

- Application migrations are a fresh `0001_initial` baseline generated from the
  current model state.
- Existing databases created from the old migration chain require a reset,
  restore into a compatible clean schema, or reviewed `--fake-initial` plan
  before applying this baseline.
- Chroma vectors are rebuildable from Rate_Master after database upload.
- `ProductEmbedding` is an audit record for Chroma-indexed Rate_Master rows;
  Chroma stores the vectors.
- Existing Redis messages from removed database-import/embedding Celery tasks
  may need a one-time purge if present in an old running environment.
- Already-uploaded BOQs may need re-upload/reprocess to capture the latest
  grouped-row parser output.

## Verification Commands

```powershell
.venv\Scripts\python.exe -m ruff check backend
.venv\Scripts\python.exe backend\manage.py makemigrations --check --dry-run
.venv\Scripts\python.exe backend\manage.py test backend.tests
```

Latest result:

```text
Ruff: passed
Migration check: no changes detected
Tests: 192 passed
```

## Session Log

### 2026-07-08 — Fresh Migration Baseline Cleanup

Completed:

- Removed historical application migration files and regenerated clean
  `0001_initial` migrations for all local apps.
- Confirmed regenerated migrations do not contain removed lookup keys or the
  old cost-breakdown model.
- Removed backend `__pycache__` directories so stale compiled migration/code
  artifacts do not remain in the workspace.
- Updated database architecture, runbook, session state, and changelog with the
  fresh migration baseline rule.
- Verified Ruff, migration dry-run, stale-symbol cleanup scan, and 192 backend
  tests passing.

Pending:

- Reset or explicitly fake-initialize any existing environment database before
  deploying the fresh migration baseline.

Issues:

- Existing data cannot be migrated incrementally from the old app migration
  chain without a reviewed deployment/data migration plan.

Next:

- Deploy only after choosing the database reset or reviewed fake-initial path
  for the target environment.

### 2026-07-08 — BOQ Processing Retrieval Implementation

Completed:

- Implemented grouped BOQ processing with `target_excel_row` mapping from parser
  through client export.
- Updated AI extraction to store `database_products[]`, `missing_products[]`,
  and `activities[]` with product-level quantity, unit, and quantity basis.
- Removed active deprecated lookup key usage from database import,
  matching, confidence, embeddings, admin, pending products, prompts, tests, and
  exports.
- Replaced old costing services and the old cost-breakdown model with
  `RateDetailRetrievalService` and `RateDetail`, which retrieve precomputed
  Rate_Master values and linked Labour_Master details.
- Updated Breakdown List export to write one row per extracted product,
  component, or missing product, including quantity basis and review flags.
- Updated client export to write rates back to the original target workbook row
  and leave pricing blank when review is required or a missing product exists.
- Standardized database version retention to three versions and default AI
  extraction batch size to 10.
- Verified Ruff, migration dry-run, and 192 tests passing.

Pending:

- Restart Django and Celery before running the new flow in the live app.
- Re-upload/import the master database so active Chroma embeddings match the new
  Rate_Master product context.
- Reprocess existing BOQs because prior runs used older extraction/result
  shapes.

Issues:

- Superseded by the fresh migration baseline cleanup; historical app migration
  files were removed after this implementation.

Next:

- Run UAT with a real BOQ row that contains one main item and hidden products
  with different product-level quantities/units.

### 2026-07-08 — BOQ Extraction And Mapping Rules

Completed:

- Removed deprecated lookup keys from the active documentation for
  matching, embeddings, and imports.
- Documented BOQ grouped-row processing with `target_excel_row` for export
  mapping back to the original workbook.
- Updated extraction rules to produce `database_products[]`,
  `missing_products[]`, and `activities[]` with product-level quantity, unit,
  quantity basis, and quantity source.
- Documented Breakdown List visibility for hidden products/components from one
  BOQ row, including missing/pending rows when matching fails.

Pending:

- Implement the documented data model, extraction prompt, matching, retrieval,
  Breakdown List, and client export changes.

Issues:

- Existing code still contains legacy fields and service behavior until the
  implementation pass.

Next:

- Start code restructure from database models/importer and BOQ parser so later
  AI, matching, and export changes have the required fields.

### 2026-07-08 — Rate And Labour Retrieval Rule

Completed:

- Updated PRD, TRD, architecture, database architecture, project structure, and
  agent rules so the active business rule is retrieval of precomputed
  Rate_Master and linked Labour_Master values.
- Documented that BOQ_AI must not recalculate material, labour, transportation,
  accessories, overheads, profit, commercial percentages, supplier selection, or
  final rate from workbook components.
- Clarified embeddings are generated after successful database upload/import
  activation as a rebuildable active-version product lookup index.
- Standardized database retention to one active version plus two rollback
  versions.

Pending:

- Completed by the later BOQ Processing Retrieval Implementation session.

Issues:

- None; legacy calculation behavior was removed from active services.

Next:

- Run UAT on real BOQs after restarting Django and Celery.

### 2026-07-08 — Complete AI Source Row JSON

Completed:

- Restored complete grouped description and top-level BOQ parameters in
  `source_row` JSON sent to AI and written to extraction logs.
- Preserved per-row `canonical` data inside grouped source rows when available.
- Added regression coverage for grouped source row description, serial number,
  unit, quantity, and canonical fields.
- Verified Ruff, migration dry-run, and 197 backend tests.

Pending:

- Restart Django and Celery before reprocessing affected BOQs.

Issues:

- None known.

Next:

- Reprocess the uploaded BOQ and confirm `logs/ai_extractions.log` includes the
  full grouped source row context.

### 2026-07-08 — AI Timeout Fallback And Processing Price Display

Completed:

- Added recursive AI batch fallback so timed-out batch extraction retries as
  smaller row groups before individual rows are skipped.
- Reduced default AI extraction batch size from 10 to 5 and increased OpenAI
  timeout from 30 to 120 seconds.
- Added `OPENAI_MAX_RETRIES` so SDK retries stay bounded before app-level batch
  splitting takes over.
- Hid calculated BOQ detail rates and amounts while the latest run is still in
  processing state.
- Added focused tests for AI batch retry and processing-state price hiding.
- Verified Ruff, migration dry-run, and 195 backend tests.
- Added OpenAI client config coverage and verified Ruff, migration dry-run, and
  196 backend tests after timeout/default changes.

Pending:

- Restart Django and Celery before reprocessing affected BOQs.

Issues:

- None known.

Next:

- Reprocess the uploaded BOQ and confirm timeout batches retry in smaller
  chunks instead of dropping the full batch.

### 2026-07-08 — Database Context Cache Invalidation

Completed:

- Added AI database-context cache invalidation for successful database import
  activation and rollback activation.
- Added cache epoching so stale context keys become unreachable without
  clearing unrelated application cache entries.
- Added tests for rebuilding same-version context and switching among three
  retained database versions.
- Verified Ruff, migration dry-run, and 192 backend tests.

Pending:

- Restart Django and Celery before reprocessing affected BOQs.

Issues:

- None known.

Next:

- Reprocess a BOQ after switching the active database version and confirm the
  extracted products/activities use the new active master data.

### 2026-07-08 — CAG-Friendly AI Context Cache

Completed:

- Cached compact active database context by DatabaseVersion for extraction
  prompts.
- Kept batch extraction prompts stable by placing instructions and database
  context before variable BOQ row JSON.
- Logged provider token usage including cached prompt tokens when present.
- Tightened batch prompt rules so every input row id returns fixed JSON with
  products and activities scoped to that row.
- Verified Ruff, migration dry-run, and 190 backend tests.

Pending:

- Restart Django and Celery before reprocessing affected BOQs.

Issues:

- Provider-side prompt cache benefits depend on repeated requests staying close
  together in time and using the same stable prompt prefix.

Next:

- Reprocess a real BOQ and confirm `ai_instructions.log` shows cached token
  usage on later extraction batches.

### 2026-07-08 — Batched AI Row Extraction

Completed:

- Changed BOQ AI analysis from one provider request per grouped row to
  configurable batched row extraction.
- Added `boq_row_batch_extraction.txt` so shared instructions and database
  context are sent once per batch.
- Added `AI_ROW_EXTRACTION_BATCH_SIZE` with a default of 10.
- Verified Ruff, migration dry-run, and 187 backend tests.

Pending:

- Restart Django and Celery before reprocessing affected BOQs.

Issues:

- Existing BOQ runs need reprocessing to benefit from batched extraction.

Next:

- Tune `AI_ROW_EXTRACTION_BATCH_SIZE` during UAT if model output quality or
  latency requires smaller or larger batches.

### 2026-07-08 — Extraction Deduplication And Missing Products

Completed:

- Deduplicated extracted product candidates before storing AI extraction JSON.
- Added `product_name` so products absent from Rate_Master can still be
  preserved as extracted candidates.
- Added matching-time `database_products[]` and `missing_products[]` split on
  stored extraction JSON.
- Compacted AI row source logs so descriptions are not repeated at multiple
  levels.
- Verified Ruff, migration dry-run, and 186 backend tests.

Pending:

- Restart Django and Celery before reprocessing affected BOQs.

Issues:

- Existing BOQ runs need reprocessing to populate the new split keys.

Next:

- Reprocess the affected BOQ and review `ai_extraction` plus pending products.

### 2026-07-07 — Stale BOQ Task Guard

Completed:

- Added a `process_boq_task` guard that checks whether the BOQRun exists before
  calling the processing workflow.
- Added task-level regression coverage for stale queued BOQRun ids.
- Verified focused workflow tests and Ruff for the touched files.

Pending:

- Restart Celery workers so the updated task module is loaded.

Issues:

- Existing workers running old code can still throw this traceback until they
  are restarted; old queued Redis messages may also need a one-time purge.

Next:

- Restart Celery and retry BOQ processing.

### 2026-07-07 — Master Database Schema Update

Completed:

- Added the provided Rate_Master, Labour_Master, TOR_Main,
  Labour_Structure_Source, TOR_Labour, TOR_Accessories, and State_Control_List
  fields to the Django models.
- Updated import, AI context, Chroma embedding text, exact matching, costing,
  admin, tests, and docs for the new structure.
- Added the schema change to the application schema at that time.
- Verified 183 tests passing plus ruff, migration dry-run, and Django check.

Pending:

- Restart Django and Celery after deploying the migration.
- Re-upload the master database workbook so all new columns and embeddings are
  populated.

Issues:

- Existing database versions imported before this migration do not have
  populated new columns; re-upload is required for accurate new-schema costing.
- Old compatibility master columns were removed and supplier naming was aligned
  across matching/review during the strict schema cleanup.

Next:

- Run BOQ processing against the re-uploaded master database.

### 2026-07-07 — Strict Master Schema Cleanup

Completed:

- Removed old duplicate master columns from Rate_Master, Labour_Master,
  TOR_Main, Labour_Structure_Source, TOR_Labour, TOR_Accessories, and
  State_Control_List models.
- Updated importer, AI context, Chroma embeddings, matching, costing, pending
  product approval, review, admin, templates, exports, and tests to use
  tech_key/supplier/net_material_rate and the shared schema only.
- Renamed ProductAlias/ProductEmbedding audit keys to `tech_key`.
- Renamed ProductMatch and ReviewItem supplier fields away from vendor wording.
- Added the strict schema cleanup to the application schema at that time.
- Verified full backend suite: 183 tests passing, plus Ruff, Django check, and
  migration dry-run.

Pending:

- Re-upload the master database workbook so active data is populated only with
  the strict schema columns.

Issues:

- None from validation.

Next:

- Restart Django/Celery and re-upload the master database workbook before UAT
  BOQ processing.

### 2026-07-07 — Stale BOQ Task Handling

Completed:

- Fixed `process_boq_run` to log and skip when a queued BOQRun id no longer
  exists.
- Added regression coverage for missing-run Celery workflow handling.

Pending:

- Restart Celery workers so the updated task handling is active.

Issues:

- Old Redis messages created before this fix may still exist until consumed or
  purged.

Next:

- Retry BOQ processing after worker restart.

### 2026-07-07 — Multi-Product Row Handling

Completed:

- Added per-product matching for BOQ rows that extract multiple equipment items.
- Added `ProductMatch.extraction_index` to link matches to extracted product
  candidates.
- Updated confidence, Breakdown List, and Client BOQ exports for multiple
  product matches from one BOQ item.
- Updated PRD, TRD, architecture, database architecture, session, and changelog.
- Verified 182 tests passing plus ruff, migration dry-run, Django check, and
  whitespace diff check.

Pending:

- Restart Django and Celery before processing new BOQs.
- Reprocess existing BOQs to regenerate extraction and matching rows.

Issues:

- None known from validation.

Next:

- Run UAT on real multi-equipment BOQ rows.

### 2026-07-07 — Chroma Embedding Search

Completed:

- Replaced PostgreSQL vector-extension direction with local Chroma persistent
  vector indexing.
- Updated embedding generation, matching, and reusable search to use Chroma.
- Updated database, architecture, runbook, deployment, session, and changelog docs.

Pending:

- Restart Django and Celery before using the updated Chroma flow.

Issues:

- None currently.

Next:

- Upload the database and regenerate Chroma embeddings.

### 2026-07-07 — GPT-5 Mini Temperature Fix

Completed:

- Omitted custom temperature for GPT-5/o-series chat requests.
- Added regression coverage for GPT-5 mini and older model request kwargs.
- Verified Ruff, migration dry-run, focused AI tests, and full suite.

Pending:

- Restart Django and Celery before reprocessing affected BOQs.

Issues:

- None.

Next:

- Reprocess the failed BOQ run with the updated AI service.

### 2026-07-07 — Documentation Compaction

Completed:

- Heavily condensed `SESSION_STATE.md` into active state, workflows, files,
  recent completed work, pending items, and verification commands.
- Removed long historical sprint logs from session memory.

Pending:

- None.

Issues:

- None.

Next:

- Keep future entries short and move detailed rules into the source-of-truth
  documents instead of expanding session state.
