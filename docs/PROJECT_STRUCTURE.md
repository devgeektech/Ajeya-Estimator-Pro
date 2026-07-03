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

├── settings/
│   ├── base.py
│   └── production.py
│
├── urls.py
├── celery.py
├── asgi.py
└── wsgi.py
```

---

Runtime note:

* `config.settings.production` is the single active settings module.
* `base.py` contains shared Django configuration used by production settings.
* Environment values are read from `/srv/boq_ai/.env` on the EC2 server.

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

---

# costing

Responsibilities:

* Labour.
* Material.
* Transportation.
* Overheads.
* Profit.

Services:

```text
costing/services/

material.py
labour.py
transport.py
profit.py
```

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
prompts/
extractors/
validators/
embeddings/
```

---

# Prompt Structure

```text
ai/prompts/

product_extraction.txt

activity_extraction.txt

validation.txt
```

---

# Extractors

```text
extractors/

product_extractor.py

activity_extractor.py
```

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

search.py
```

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

AI

↓

Matching

↓

Costing

↓

Review

↓

Export
```

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

generate_embeddings.py

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
ProductMatch
```

Services:

```text
ProductMatchingService
CostCalculationService
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

Embeddings

↓

Activate
```

---

# Processing Rules

BOQ processing:

* Must be asynchronous.
* Must be resumable.
* Must log errors.

---

# Future Expansion

The structure supports:

* Additional AI providers.
* APIs.
* Mobile apps.
* Multiple companies.
* ERP integrations.

---

# Architecture Dependencies

This document depends upon:

* PRD.md
* TRD.md
* ARCHITECTURE.md
* DATABASE_ARCHITECTURE.md

All future code generation shall follow this structure.
