# Project

BOQ_AI

---

# Purpose

This document defines the operating instructions for AI coding agents, IDE assistants, developers, and future contributors working on BOQ_AI.

All development work must follow the instructions defined in this document.

---

# Core Principle

The project is:

* Documentation Driven.
* Service Oriented.
* Business Rule Based.
* Human Reviewed.
* AI Assisted.

Code must follow documentation.

Documentation does not follow code.

---

# Required Reading Order

Before performing any development work, agents must read:

1. PRD.md
2. TRD.md
3. ARCHITECTURE.md
4. DATABASE_ARCHITECTURE.md
5. PROJECT_STRUCTURE.md
6. SESSION_STATE.md
7. CURRENT TASK

No development shall begin without reviewing these documents.

---

# Source Of Truth

Priority:

1. PRD.md
2. TRD.md
3. ARCHITECTURE.md
4. DATABASE_ARCHITECTURE.md
5. SESSION_STATE.md
6. Existing Code

If code conflicts with documentation, documentation wins.

---

# Development Principles

* Small changes.
* Isolated changes.
* Document changes.
* Maintain backward compatibility.
* Avoid unnecessary refactoring.
* Before writing code, confirm the change is necessary for the current task.
* Prefer the simplest working implementation that fits the existing architecture.
* Add comments for intent, business constraints, or non-obvious logic only.

---

# Forbidden Practices

Do not:

* Put business logic in views.
* Put AI calls inside views.
* Put calculations inside templates.
* Write large monolithic services.
* Duplicate business rules.
* Modify database directly.
* Bypass review workflows.

---

# Required Architecture

Views:

* Thin.

Services:

* Fat.

Models:

* Simple.

Templates:

* Presentation only.

---

# Business Logic Rules

All business logic belongs inside:

```text id="p48ncs"
services/
```

Examples:

* Product matching.
* Rate_Master row selection.
* Labour_Master detail retrieval by `tech_key`.
* Confidence scoring.

Do not use `match_key` or `source_key` for matching, embeddings, or imports in
the active workflow.

---

# AI Rules

AI shall only:

* Understand descriptions.
* Extract products.
* Extract activities.
* Validate matches.

AI shall never:

* Calculate costs.
* Calculate profits.
* Select vendors/suppliers.
* Determine pricing.

---

# Background Jobs

Long-running BOQ operations must use Celery.

Examples:

* BOQ processing.
* Exports.
* Notifications.

BOQ processing views must never block. Database upload/import is the active
exception: it runs synchronously through the database import service so the
database is active when the upload request completes.

---

# Database Rules

Database modifications:

* Through services only.
* Never inside views.

All imports must:

1. Validate.
2. Backup.
3. Import.
4. Activate.
5. Generate embeddings.

---

# BOQ Rules

Every BOQ must preserve:

* Original file.
* Make list.
* Processing results.
* Exports.
* Review changes.

Never overwrite historical BOQ data.

---

# Review Rules

Experts may modify:

* Product.
* Supplier.
* Selected output values for review/export.

Experts may not:

* Modify master database.
* Approve products.

---

# Pending Product Rules

Confidence below 30:

* No product selected.
* Blank output.
* Create pending item.

Only Super Admin may approve products.

---

# Service Rules

Services must:

* Have single responsibility.
* Be reusable.
* Avoid side effects.
* Return structured results.

---

# Naming Rules

Services:

```text id="12hdnm"
ProductMatchingService

RateDetailRetrievalService
```

Tasks:

```text id="c40fjm"
process_boq_task
```

Models:

```text id="krizdi"
BOQ

BOQItem

ProductMatch
```

---

# Folder Rules

Business logic:

```text id="yyd40f"
services/
```

AI:

```text id="17l3u4"
ai/
```

Tasks:

```text id="mmpq6g"
tasks/
```

Workflows:

```text id="cv5w7d"
workflows/
```

---

# Documentation Rules

Any significant change must update:

* SESSION_STATE.md
* CHANGELOG.md

Architecture changes require:

* TRD update.
* Architecture update.

Database changes require:

* DATABASE_ARCHITECTURE update.

---

# Documentation Update Instructions

Every document has a specific purpose. Follow these rules to keep them current.

## When to Update Each Document

| Document | Update When | What to Write |
| --- | --- | --- |
| `SESSION_STATE.md` | After every development session | Completed work, pending items, issues, next tasks, test counts |
| `CHANGELOG.md` | After every meaningful change | Plain-English list of what changed and why |
| `ARCHITECTURE.md` | When system boundaries or layers change | Updated diagrams, layer responsibilities |
| `DATABASE_ARCHITECTURE.md` | When models or migrations are added/changed | Updated schema tables, relationship descriptions |
| `TRD.md` | When a major technical decision changes | Revised technical requirements or constraints |
| `PRD.md` | When business rules change (human decision only) | Updated feature descriptions or workflow rules |
| `PROJECT_STRUCTURE.md` | When files/folders are added or removed | Updated directory listings and responsibilities |
| `RUN.md` | When server commands or infrastructure changes | Updated runbook steps |
| `DEPLOY.md` | When the deployment process changes | Updated deployment checklist |

## How to Update SESSION_STATE.md

At the end of every session, add a new entry under `# Session Log` in this format:

```markdown
## YYYY-MM-DD — Brief Title

Completed:

* What was built or fixed.
* What was tested.
* Current test count if it changed.

Pending:

* Unfinished items.

Issues:

* Any known problems or blockers.

Next:

* Planned next tasks.
```

## How to Update CHANGELOG.md

Add a new entry at the top of the file under `# Changelog` in this format:

```markdown
## YYYY-MM-DD — Brief Title

- Short bullet describing what changed and why.
- Another bullet for a different change.
```

## Golden Rule for Documentation

If you change code but do not update the relevant documents, the documentation
is now wrong. Wrong documentation misleads future agents and developers.

Always update documentation in the same session as the code change.

---

# Migration Rules

Before creating migrations:

1. Check documentation.
2. Check existing models.
3. Validate relationships.

Database changes must remain backward compatible.

---

# Error Handling

All services must:

* Catch failures.
* Log errors.
* Return meaningful messages.

Never fail silently.

---

# Logging Rules

Log:

* AI requests.
* BOQ jobs.
* Exports.
* Database imports.
* Errors.

Do not log:

* Passwords.
* Secrets.
* API keys.

---

# Security Rules

Never expose:

* API keys.
* Database credentials.
* Secrets.

Use environment variables.

---

# OpenAI Rules

Prompts must:

* Be reusable.
* Live in prompt files.
* Avoid hardcoded business rules.

Prompt files:

```text id="d9kn5j"
ai/prompts/
```

---

# Testing Rules

Every service requires:

* Unit tests.

Every workflow requires:

* Integration tests.

Critical features require:

* UAT scenarios.

---

# Code Quality Rules

Maximum function size:

100 lines.

Maximum service responsibility:

Single feature.

Avoid:

* Nested logic.
* Duplicate code.
* Large views.
* Clever abstractions without an immediate business reason.
* Comments that merely repeat what the code already says.

Required before code changes:

1. Identify the user-visible or developer-visible problem being solved.
2. Confirm the code change is necessary; choose documentation/config changes when code is not needed.
3. Check the existing service/model/workflow boundary for the correct place to make the change.
4. Make the smallest complete change.
5. Run the relevant check or test command.

---

# Review Checklist

Before merging:

* Tests pass.
* Documentation updated.
* Session state updated.
* No duplicate logic.
* Architecture respected.

---

# Session Rules

At the end of each development session:

Update:

* SESSION_STATE.md
* CHANGELOG.md

Record:

* Completed work.
* Pending work.
* Issues.
* Next tasks.

---

# Agent Workflow

```text id="5vpd3m"
Read Documentation

↓

Read Session State

↓

Implement Task

↓

Run Tests

↓

Update Session

↓

Update Changelog
```

---

# AI Agent Responsibilities

AI agents should:

* Follow documents.
* Implement isolated changes.
* Respect architecture.
* Avoid assumptions.
* Ask for clarification when required.

---

# Human Responsibilities

Humans decide:

* Business rules.
* Database changes.
* Architecture changes.
* Product decisions.

AI implements.

---

# Existing Documentation

All foundation documents are complete:

| Document              | Status   |
| --------------------- | -------- |
| PRD.md                | Complete |
| TRD.md                | Complete |
| ARCHITECTURE.md       | Complete |
| DATABASE_ARCHITECTURE | Complete |
| PROJECT_STRUCTURE.md  | Complete |
| AGENTS.md             | Complete |
| SESSION_STATE.md      | Updated each session |
| CHANGELOG.md          | Maintained each sprint |
| DEVELOPMENT_ROADMAP.md| Complete — all 24 sprints delivered |
| RUN.md                | Complete |
| DEPLOY.md             | Complete |

# Runtime Direction

BOQ_AI currently uses a single EC2 runtime:

* Active settings module: `config.settings`.
* Environment file: `.env` locally and `/srv/boq_ai/.env` on EC2.
* Database: PostgreSQL database `boq_db` with application role `boq_user`.
* Database host: `localhost` in both local development and EC2 deployment.
* SMTP is optional until a domain/mail provider is configured; email falls back
  to Django console logging.
* SQLite, separate development settings, demo seeding, and public REST APIs are
  not part of the active workflow.
* Production-ready work only: use real client data, real PostgreSQL migrations,
  and real operational assumptions.

# Golden Rule

The documentation is the product specification.

The code is the implementation.

If documentation and code disagree, the documentation must be updated first before code changes are made.

No development shall violate documented architecture, workflows, or business rules.
