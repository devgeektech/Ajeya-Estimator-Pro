# Project

BOQ_AI

---

# Version

1.0

---

# Purpose

This document defines the overall application architecture, component boundaries, service responsibilities, processing workflows, and deployment architecture of BOQ_AI.

This document serves as the primary architectural reference for developers and AI coding agents.

---

# Architecture Principles

The system is designed using the following principles:

* Modular architecture.
* Service-oriented design.
* Business logic separation.
* Background processing.
* Human-in-the-loop workflows.
* Database versioning.
* AI-assisted decision making.
* Auditability.
* Scalability.

---

# High-Level System Architecture

```text
+-----------------------+
|      Expert User      |
+-----------------------+
            |
+-----------------------+
|      Web Interface    |
| Django + HTMX + Alpine|
+-----------------------+
            |
+-----------------------+
|    Django Backend     |
+-----------------------+
            |
+-----------+-----------+
|           |           |
AI      Business     Export
Layer    Services    Engine
|           |           |
+-----------+-----------+
            |
+-----------------------+
|     PostgreSQL        |
+-----------------------+
            |
+-----------------------+
|   Celery + Redis      |
+-----------------------+
```

---

# System Layers

## Presentation Layer

Technologies:

* Django Templates
* HTMX
* Alpine.js

Responsibilities:

* User interaction.
* Forms.
* Tables.
* Review screens.
* Status tracking.
* Dashboard.

---

## Application Layer

Technology:

* Django

Responsibilities:

* Request handling.
* Authentication.
* Permissions.
* Session management.
* Routing.

---

## Service Layer

Responsibilities:

* BOQ processing.
* Lowest final-amount rate selection.
* Cost calculation.
* Confidence scoring.
* Review logic.

---

## AI Layer

Technology:

* OpenAI

Responsibilities:

* BOQ understanding.
* Product extraction.
* Activity extraction.
* AI validation.

---

## Data Layer

Technology:

* PostgreSQL

Responsibilities:

* Master database.
* BOQ storage.
* Results.
* History.
* Versioning.

---

## Background Processing Layer

Technologies:

* Celery
* Redis

Responsibilities:

* BOQ jobs.
* AI jobs.
* Export jobs.
* Notifications.

---

# Application Modules

## accounts

Responsibilities:

* Login.
* Password reset.
* Roles.
* Sessions.

---

## users

Responsibilities:

* User management.
* Role assignment.

---

## database_manager

Responsibilities:

* Database upload.
* Validation.
* Rollback.
* Version management.

---

## boq

Responsibilities:

* BOQ management.
* BOQ files.
* Status.

---

## make_list

Responsibilities:

* Make list processing.
* Make filtering.

---

## processing

Responsibilities:

* Processing jobs.
* Status updates.

---

## ai_engine

Responsibilities:

* OpenAI communication.
* Extraction.
* Validation.

---

## matching

Responsibilities:

* Product search.
* Alias search.
* Confidence.

---

## costing

Responsibilities:

* Labour.
* Material.
* Profit.
* Overheads.

---

## review

Responsibilities:

* Expert modifications.
* Approval.

---

## exports

Responsibilities:

* Excel generation.
* Internal sheet.
* Client sheet.

---

## pending_products

Responsibilities:

* Unknown items.
* Product approval.

---

# BOQ Processing Architecture

```text
Upload BOQ
        |
Upload Make List
        |
Create Job
        |
Queue Job
        |
AI Analysis
        |
Product Matching
        |
Lowest Final Amount Rate Selection
        |
Cost Calculation
        |
Confidence Scoring
        |
Generate Results
```

---

# AI Architecture

OpenAI is used only for:

* Description understanding.
* Product extraction.
* Activity extraction.
* Validation.

AI never performs:

* Pricing.
* Calculations.
* Vendor selection.
* Commercial logic.

---

# AI Workflow

```text
Grouped BOQ Row JSON
        |
OpenAI + Active Database Context
        |
Structured Data
        |
Database Search
        |
Confidence Calculation
```

The BOQ parser creates one structured JSON payload per business row. A
serial-numbered row and its inherited blank-serial child/detail rows are kept
together in that payload. The AI layer receives that JSON plus compact active
database vocabulary from Rate_Master, Labour_Master, and TOR_Labour.

---

# Product Matching Architecture

Search Priority:

1. Exact Match
2. Alias Match
3. Embedding Match
4. AI Validation

Matching searches the original BOQ description first, then database-shaped AI
product candidates and database hints extracted from the grouped row JSON.

---

# Rate Selection Architecture

When product matching returns multiple Rate_Master rows for one product, the
processing workflow selects the row with the lowest `Final_Amount_(Excl GST)`.
Vendor selection modes are not active in the current pipeline.

---

# Confidence Engine

Inputs:

* Product score.
* Make score.
* Size score.
* Activity score.

Output:

* Confidence percentage.

---

# Confidence Rules

| Score | Status  |
| ----- | ------- |
| 90+   | Green   |
| 80-90 | Yellow  |
| 70-80 | Orange  |
| 30-70 | Red     |
| <30   | Pending |

---

# Pending Product Architecture

```text
Unknown Product
        |
Pending Queue
        |
Super Admin
        |
Approve
        |
Database
```

---

# Database Version Architecture

```text
Current Database
        |
Upload New Version
        |
Backup Old Version
        |
Import New Data
        |
Activate
        |
Generate Embeddings
```

Database upload/import is synchronous. Celery is not used for database import or
database embedding generation in the active workflow.

Versions:

* Active
* Previous
* Previous

---

# File Storage Architecture

```text
media/

    database/

    boq/

    make_lists/

    outputs/

    exports/
```

---

# BOQ Ownership Architecture

Expert:

* Own BOQs only.

Super Admin:

* All BOQs.

---

# Status Architecture

```text
Uploaded

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

# Internal Review Architecture

Contains:

* Breakdown List sheet.
* AI interpretation.
* Selected rate row.
* Make and supplier.
* Material/commercial cost values.
* Labour and confidence.

Allows:

* Product changes.
* Vendor changes.
* Price changes.

---

# Export Architecture

Sheet 1:

Breakdown List.

Sheet 2:

Client BOQ.

Both sheets remain linked.

The Client BOQ sheet preserves the uploaded BOQ layout where available and only
fills Unit, Quantity, Rate, and Amount. Existing Unit and Quantity values are
preserved; Rate and Amount are placed on the child/detail row when that row
contains the product unit or quantity.

---

# Background Job Architecture

```text
Django

↓

Redis Queue

↓

Celery Worker

↓

Processing

↓

Results
```

---

# Notification Architecture

Notifications:

* Processing completed.
* Failed jobs.
* Review pending.
* Export completed.

---

# Security Architecture

Authentication:

* Email login.

Authorization:

* Role-based.

Protection:

* CSRF.
* Sessions.
* Permissions.

---

# Deployment Architecture

```text
Internet

↓

Nginx

↓

Gunicorn

↓

Django

↓

PostgreSQL

↓

Redis

↓

Celery
```

---

# AWS Architecture

Services:

* EC2.
* EBS.
* PostgreSQL installed on the same EC2 host for the current single-server setup.
* Redis installed on the same EC2 host for the current single-server setup.
* Backups.

---

# Logging Architecture

Logs:

* User actions.
* BOQ processing.
* Runtime AI instructions.
* Row-level AI extraction results.
* AI calls.
* Errors.
* Exports.

---

# Scalability Strategy

The architecture supports:

* Additional workers.
* Larger databases.
* More users.
* Higher BOQ volume.

---

# Failure Handling

Failures:

* AI failures.
* File failures.
* Import failures.
* Export failures.

Jobs may be retried.

---

# Architecture Decisions

| Decision       | Choice     |
| -------------- | ---------- |
| Framework      | Django     |
| UI             | HTMX       |
| Database       | PostgreSQL |
| AI             | OpenAI     |
| Queue          | Celery     |
| Broker         | Redis      |
| Hosting        | AWS EC2    |
| Export         | Excel      |
| Authentication | Email      |
| Registration   | Admin Only |
| Public API     | Not active |

---

# Architecture Ownership

This document is the authoritative source for:

* Service boundaries.
* Component responsibilities.
* Application structure.
* Technical decisions.

All technical documents shall conform to this architecture.
