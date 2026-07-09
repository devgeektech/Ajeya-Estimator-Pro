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
* Rate and labour detail retrieval.
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

* Retrieve selected Rate_Master precomputed fields.
* Retrieve linked Labour_Master fields through `tech_key`.
* Preserve imported workbook values for review and export.

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
Rate And Labour Detail Retrieval
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
* Supplier selection.
* Commercial logic.

---

# AI Workflow

```text
Grouped BOQ Row JSON Batch
        |
Single OpenAI Batch Extraction + Active Database Context
        |
Structured Data
        |
Database Search
        |
Confidence Calculation
```

The BOQ parser creates one structured JSON payload per business row. A
serial-numbered row and its inherited blank-serial child/detail rows are kept
together in that payload. The payload preserves parent/detail rows, original
Excel row numbers, canonical source fields, and `target_excel_row` for export
mapping. The AI layer receives that JSON plus compact active database
vocabulary. Product vocabulary is limited to unique Rate_Master category,
sub_category, class, size_mm, make, capacity, unit, supplier, and other
product/specification fields required for matching; deprecated lookup keys are
not used. Activity vocabulary comes from Labour_Master and TOR_Labour.
One AI call returns row_id-keyed product candidates and activities for a batch
of grouped BOQ items so the shared instruction and database context are sent
once per batch instead of once per row.
If a provider request fails or times out, the analyzer retries the failed batch
as smaller row groups before marking individual rows as failed.
The database-aware context is cached by active database version and rendered as
a stable prefix before variable row JSON to reduce repeated prompt construction
and improve prompt-cache reuse. Database import and rollback invalidate this
cache after activation changes so switching among retained PostgreSQL database
versions rebuilds AI vocabulary from the newly active master data.
The extractor returns reviewable `database_products[]`, `missing_products[]`,
and `activities[]` segments. The database/missing split is based on compact AI
context and remains advisory until PostgreSQL matching confirms it. The
extractor keeps deduplicated product/equipment/component candidates even when
they are not found in the active database.

---

# Product Matching Architecture

Search Priority:

1. Exact Match
2. Chroma Embedding Match
3. OpenAI Validation

Matching searches each database-shaped AI product candidate extracted from the
grouped row JSON. If no product candidate exists, matching falls back to the
original grouped BOQ description.
Each extracted product/equipment candidate creates its own ProductMatch and
stores the candidate position as `extraction_index`; activities stay attached
to the BOQ item as row-level execution context.
After matching, candidates with a selected RateMaster row are recorded under
`database_products[]`, while unresolved candidates are recorded under
`missing_products[]` for expert review in the breakdown sheet.
Embedding search is executed through the local Chroma vector index and resolved
back to PostgreSQL Rate_Master rows before rate selection.

Exact matching uses normalized RateMaster product/specification fields. The
active workflow must not use deprecated lookup keys.

---

# Rate Selection Architecture

When product matching returns multiple Rate_Master rows for one product, the
processing workflow selects the row with the lowest `Final_Amount_(Excl GST)`.
Supplier selection modes are not active in the current pipeline.

Master database joins:

```text
RateMaster.tech_key -> LabourMaster.tech_key
RateMaster(category, sub_category, size_mm, unit)
    -> LabourStructureSource -> LabourMaster.tech_key
```

Embeddings are created from RateMaster product/specification fields and Chroma
hits resolve back to PostgreSQL RateMaster rows before the lowest-final-amount
rule is applied.

The selected RateMaster row supplies precomputed material, commercial, supplier,
make, and final amount fields. The linked LabourMaster row supplies precomputed
labour charge details. TOR and state-control tables are imported for reference
and traceability, but the active pipeline does not recompute workbook costing
formulas from them.

---

# Rate And Labour Detail Retrieval Architecture

BOQ_AI retrieves official values from the imported client database instead of
recalculating cost components.

The retrieval flow is:

```text
Selected RateMaster row
        |
RateMaster.tech_key
        |
Linked LabourMaster row
        |
Selected database fields copied to results/review/export
```

The application shall not calculate material cost, labour cost, transportation,
accessories, overheads, profit, commercial percentages, supplier selection, or
final rate unless a future human-approved rule is documented first.

---

# Quantity Architecture

BOQ item unit/quantity and product/component unit/quantity are separate
concepts.

```text
BOQItem quantity/unit
        |
Client billing/export quantity

Extracted product quantity/unit
        |
Component quantity for selected RateMaster retrieval
```

Each extracted product candidate stores `product_quantity`, `product_unit`,
`quantity_basis`, and `quantity_source`. `quantity_basis` is one of
`per_boq_unit`, `total_for_boq_row`, or `unknown`. Items with unknown quantity
basis require expert review before client export can be trusted.

---

# Confidence Engine

Inputs:

* Category and sub category score.
* Class and size_mm score.
* Make, capacity, unit, and supplier score.

Output:

* Confidence percentage per ProductMatch.

---

# Confidence Rules

| Score | Status  |
| ----- | ------- |
| 90+   | Green   |
| 80-90 | Yellow  |
| 70-80 | Orange  |
| 30-70 | Red     |
| <30   | Blank (review required) |

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
* Source Excel row and target Excel row.
* Extraction index.
* Extracted product/component name.
* Selected rate row.
* Match type.
* Make and supplier.
* Product quantity, product unit, and quantity basis.
* Selected Rate_Master precomputed material/commercial/final amount fields.
* `tech_key`.
* Linked Labour_Master labour charge fields.
* Confidence.
* Review required and missing product flags.

One BOQ item may appear as multiple Breakdown List rows when the AI extraction
finds multiple products/equipment/components in the same grouped row. Unmatched
or low-confidence candidates also appear in the Breakdown List as
missing/pending rows so hidden products are reviewable.

Allows:

* Product changes.
* Selected-rate/supplier changes.
* Selected output value changes for review/export when required.

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
When a BOQ item has multiple breakdown rows, the client Rate is sourced from
selected precomputed final amount fields and product-level quantity basis. The
export service maps output back to the original workbook using
`BOQItem.target_excel_row`.

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
