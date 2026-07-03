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

Future:

* API_SPEC.md
* TEST_PLAN.md

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

Future changes expected.

---

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

# Vendor Selection

Modes:

* Lowest Cost.
* Preferred Vendor.
* Custom.

Experts may override vendors during review.

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

Future improvements allowed.

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
  retention); DatabaseRollbackService; import workflow + Celery task;
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

* VendorSelectionService: lowest-cost / preferred / custom modes with make-list
  filtering (only approved makes selectable).
* Writes chosen vendor row back to ProductMatch (product/make/vendor).
* Wired into the matching stage (runs after product matching).

Delivered (Sprint 13):

* Material cost = selected vendor purchase_rate (per-unit); zero for pending.
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

* ReviewService: re-point item match (vendor/product change), record ReviewItem,
  recalc CostBreakdown, transition BOQ to Under Review. candidate_rates helper.
* Review UI: editable results table with HTMX vendor dropdown (row swap),
  confidence bands; ownership-scoped views; linked from BOQ detail.

Delivered (Sprint 17):

* ReviewService approve/revise with status guards (Completed/Under Review ->
  Approved; Approved -> Under Review). Invalid transitions raise ValidationError.
* Approve/Revise views + URLs (ownership-scoped) + contextual toolbar buttons.

Delivered (Sprint 18):

* PendingProductService: reject / merge (alias to existing) / add_new (new
  RateMaster + alias). Approved products available to future BOQs via aliases.
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

* 149 tests discovered and passing (verified 2026-07-03 after granting CREATEDB privilege to boq_user).

---

# Next Sprint

None — all 24 roadmap sprints are complete. Remaining activity is production
hardening and live validation on the EC2 instance with real client BOQs only.

---

# Future Sprints

Post-UAT (backlog):

* pgvector enablement for embedding search at scale.
* Performance/cost tuning and final production hardening from UAT findings.

---

# Pending Decisions

Future:

* Final database optimization.
* Embedding tuning.
* OpenAI prompt optimization.

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
* Database import workflow + Celery task.
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

149 passing tests across all 13 apps + workflows.

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
* tasks/generate_embeddings.py: replaced `NotImplementedError` scaffold with
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
  - Fixed in `tasks/generate_embeddings.py`: idempotency check and
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
