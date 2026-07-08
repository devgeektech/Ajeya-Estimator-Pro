# Project

BOQ_AI

---

# Version

1.0

---

# Purpose

This document defines the complete source code structure, Django applications, services, utilities, AI modules, background jobs, testing structure, and documentation organization for BOQ_AI.

This document acts as the primary reference for developers and AI coding agents.

---

# Design Principles

The codebase shall follow:

* Modular architecture.
* App-based organization.
* Service-oriented business logic.
* Thin views.
* Reusable services.
* Separation of concerns.
* Agent-friendly structure.
* Documentation-driven development.

---

# Root Structure

```text
boq_ai/

├── backend/
├── docs/
├── media/
├── static/
├── templates/
├── requirements.txt
├── logs/
└── .env
```

---

# Backend Structure

```text
backend/

├── config/
├── apps/
├── ai/
├── workflows/
├── exports/
├── tasks/
├── common/
├── utils/
└── tests/
```

---

# Django Configuration

```text
config/

├── settings.py
├── urls.py
├── celery.py
├── asgi.py
└── wsgi.py
```

---

Runtime note:

* `config.settings` is the single active settings module (`config/settings.py`).
* Environment values are read from `.env` in the project root when present.
* Production safety checks are enabled when `DEBUG=False`.

# Django Applications

```text
apps/

├── accounts/
├── users/
├── database_manager/
├── boq/
├── make_list/
├── processing/
├── matching/
├── costing/
├── review/
├── exports/
├── pending_products/
├── notifications/
└── audit/
```

Migration folders:

* Each local Django app keeps `migrations/__init__.py`.
* Apps with models keep one fresh `migrations/0001_initial.py` generated from
  the current model state.
* Historical app migration files are not part of the active project structure.

---

# accounts

Responsibilities:

* Login.
* Logout.
* Password reset.
* Sessions.

Structure:

```text
accounts/

models.py
views.py
forms.py
urls.py
services.py
templates/
```

---

# users

Responsibilities:

* User management.
* Roles.
* Permissions.

---

# database_manager

Responsibilities:

* Database upload.
* Validation.
* Versioning.
* Rollback.

Submodules:

```text
database_manager/

services/
    importer.py
    validator.py
    rollback.py
```

---

# boq

Responsibilities:

* BOQ upload.
* BOQ management.
* File handling.

---

# make_list

Responsibilities:

* Make list parsing.
* Make validation.

---

# processing

Responsibilities:

* BOQ jobs.
* Status updates.
* Job tracking.

---

# matching

Responsibilities:

* Product search.
* Alias search.
* Confidence.

Services:

```text
matching/services/

exact_match.py
alias_match.py
embedding_match.py
confidence.py
```

Matching also performs lowest `Final_Amount_(Excl GST)` rate-row selection
inside the matching services. A separate supplier-selection service is not active.

---

# costing

Responsibilities:

* Retrieve selected Rate_Master precomputed fields.
* Retrieve linked Labour_Master fields through `tech_key`.
* Preserve imported workbook values for review/export.

Services:

```text
costing/services/

rate_detail.py
labour_detail.py
```

Legacy cost calculation helpers must be retired or refactored during the code
restructure. The active business rule is value retrieval from the imported
client workbook data, not recalculation.

---

# review

Responsibilities:

* User changes.
* Approval.
* Revision.

---

# exports

Responsibilities:

* Excel generation.
* Internal sheets.
* Client sheets.

---

# pending_products

Responsibilities:

* Unknown products.
* Admin approval.

---

# notifications

Responsibilities:

* System notifications.
* Alerts.

---

# audit

Responsibilities:

* Audit logs.
* User actions.

---

# Service Layer

Business logic must never reside inside:

* Views.
* Templates.
* Models.

Business logic belongs inside:

```text
apps/<feature>/services/
workflows/
```

---

# Service Structure

```text
apps/
├── boq/services/
├── database_manager/services/
├── matching/services/
├── costing/services/
├── review/services/
├── exports/services/
├── pending_products/services/
└── processing/services/

workflows/
├── boq_processing.py
├── database_import.py
└── review_workflow.py
```

---

# AI Layer

```text
ai/

openai_client.py
context.py
prompts/
extractors/
validators/
embeddings/
```

---

# Prompt Structure

```text
ai/prompts/

boq_row_extraction.txt

boq_row_batch_extraction.txt

validation.txt
```

---

# Extractors

```text
extractors/

row_extractor.py
```

`ai/context.py` builds compact active database vocabulary for the row extraction
prompt so AI product and activity JSON stays close to Rate_Master,
Labour_Master, and TOR_Labour terminology. AI extraction batches grouped BOQ
items so one provider call extracts database-present product candidates,
missing product candidates, and activities for multiple rows while returning
row_id-keyed results. The target batch size is 10 finalized grouped BOQ items
and remains configurable.
The database context is cached per active DatabaseVersion and rendered before
variable row data to keep extraction prompts cache-friendly.
Database import also reads `Labour_Structure_Source` so retrieval can resolve
category/sub_category/size rows back to Labour_Master `tech_key` rows when a
direct Rate_Master `tech_key` match is not available.
Deprecated lookup keys are not part of the active matching or embedding
workflow.

---

# Validators

```text
validators/

product_validator.py

confidence_validator.py
```

---

# Embeddings

```text
embeddings/

generator.py

generate_database_embeddings.py

search.py
```

Embedding search uses a local Chroma persistent vector index. PostgreSQL
stores Rate_Master rows and a lightweight `ProductEmbedding` audit record;
Chroma stores the vectors.
Embedding text is built from Rate_Master product/specification fields such as
category, sub_category, class, size_mm, make, capacity, unit, supplier, and
other descriptive technical columns. Deprecated lookup keys are excluded.

---

# Workflow Layer

```text
workflows/

boq_processing.py

database_import.py

review_workflow.py
```

---

# BOQ Workflow

```text
Upload

↓

Parse

↓

Group Rows With target_excel_row

↓

AI

↓

Matching

↓

Lowest Final Amount Rate Selection

↓

Rate And Labour Detail Retrieval

↓

Review

↓

Export
```

BOQ parsing must preserve the uploaded workbook for UI/audit/export while
creating a backend grouped-row payload for processing. Grouped items store
parent rows, child/detail rows, original Excel row numbers, canonical source
fields, and `target_excel_row`.

AI extraction results are logged with one `source_row` and one extraction object
containing `database_products[]`, `missing_products[]`, and `activities[]`.
Product candidates include product-level quantity, unit, quantity basis, and
quantity source so one BOQ row can safely contain multiple hidden components.

---

# Export Layer

```text
exports/

internal_sheet.py

client_sheet.py

formatter.py
```

---

# Celery Tasks

```text
tasks/

process_boq.py

export_files.py

notifications.py
```

---

# Utility Layer

```text
utils/

excel.py

files.py

text.py
```

---

# Common Layer

```text
common/

constants.py

choices.py

exceptions.py

middleware.py

mixins.py

models.py
```

---

# Template Structure

```text
templates/

accounts/

dashboard/

boq/

review/

database/

exports/
```

---

# Static Files

```text
static/           # Source assets — tracked in git

css/

js/

images/
```

Note: `staticfiles/` (the collectstatic output directory) is auto-generated
and is excluded from git via `.gitignore`. Never commit it.

---

# Media Files

```text
media/

database/

boq/

make_lists/

exports/

outputs/
```

---

# Logs

```text
logs/

application.log    # All INFO+ events (app + root logger)

errors.log         # ERROR+ events only

ai_extractions.log # One structured JSON log line per BOQ row with source_row + extraction

ai_instructions.log # One structured JSON log line per rendered AI instruction
```

Note: log files are runtime-generated and are excluded from git via `.gitignore`.

---

# Documentation Structure

```text
docs/

PRD.md

TRD.md

ARCHITECTURE.md

DATABASE_ARCHITECTURE.md

PROJECT_STRUCTURE.md

AGENTS.md

SESSION_STATE.md

DEVELOPMENT_ROADMAP.md

CHANGELOG.md

RUN.md

DEPLOY.md
```

---

# Test Structure

```text
backend/tests/

test_accounts.py

test_users.py

test_database_manager.py

test_boq.py

test_processing.py

test_ai.py

test_matching.py

test_costing.py

test_review.py

test_exports.py

test_pending_products.py

test_notifications.py

test_audit.py

test_workflows.py
```

---

# Testing Types

* Unit Tests.
* Service Tests.
* Integration Tests.
* Workflow Tests.
* UAT Tests.

---

# Naming Conventions

Models:

```text
BOQ
BOQItem
LabourStructureSource
ProductMatch
```

Services:

```text
ProductMatchingService
RateDetailRetrievalService
```

Tasks:

```text
process_boq_task
```

---

# Environment Variables

```text
SECRET_KEY

DATABASE_URL

ALLOWED_HOSTS

OPENAI_API_KEY

OPENAI_TIMEOUT_SECONDS

OPENAI_MAX_RETRIES

AI_ROW_EXTRACTION_BATCH_SIZE

REDIS_URL

CELERY_BROKER_URL

CELERY_RESULT_BACKEND
```

---

# Development Rules

1. Thin views.
2. Fat services.
3. No business logic in templates.
4. No AI calls inside views.
5. Use Celery for heavy processing.
6. Update documentation before major changes.

---

# Import Rules

Database import logic:

```text
Upload

↓

Validate

↓

Backup

↓

Import

↓

Activate

↓

Embeddings
```

Database imports run synchronously in the upload request through
`workflows/database_import.py` and `DatabaseImportService`.

Embeddings are generated after successful import and activation so product
similarity search matches the active DatabaseVersion. PostgreSQL remains the
source of truth; the vector index is rebuildable.

---

# Processing Rules

BOQ processing:

* Must be asynchronous.
* Must be resumable.
* Must log errors.

---

# Architecture Dependencies

This document depends upon:

* PRD.md
* TRD.md
* ARCHITECTURE.md
* DATABASE_ARCHITECTURE.md

All code generation shall follow this structure.
