# Project Name

BOQ_AI

---

# Version

1.0

---

# Document Status

Approved

---

# Purpose

This document defines the technical architecture, implementation approach, system components, integrations, processing workflows, and technical constraints for the BOQ_AI platform.

This document serves as the primary technical reference for developers, AI coding agents, and future maintainers.

---

# Technology Stack

## Backend

* Django

---

## Frontend

* Django Templates
* HTMX
* Alpine.js

---

## Database

* PostgreSQL

---

## AI Provider

* OpenAI API

---

## Background Processing

* Celery
* Redis

---

## File Processing

* Pandas
* OpenPyXL
* PyPDF (for Make List PDF extraction)

---

## Deployment

* AWS EC2
* Nginx
* Gunicorn

---

# High-Level Architecture

```text
User
    ↓
Frontend
    ↓
Django Application
    ↓
Business Services
    ↓
AI Services
    ↓
PostgreSQL
    ↓
Background Workers
```

---

# System Components

## Authentication Service

Responsible for:

* Login
* Logout
* Password reset
* Session management

---

## User Management Service

Responsible for:

* User creation
* Role assignment
* User permissions

---

## Database Management Service

Responsible for:

* Database upload
* Validation
* Import
* Versioning
* Rollback

---

## BOQ Management Service

Responsible for:

* BOQ upload
* Make list upload
* BOQ status
* Processing history

---

## AI Service

Responsible for:

* Description understanding
* Product extraction
* Activity extraction
* Confidence generation

---

## Matching Service

Responsible for:

* Product search
* Alias search
* Embedding search
* Make filtering

---

## Rate Selection Service

Responsible for:

* Selecting the lowest `Final_Amount_(Excl GST)` Rate_Master row among matched
  product candidates.
* Preserving make/supplier data from the selected Rate_Master row for review and
  audit.

---

## Rate And Labour Detail Retrieval Service

Responsible for:

* Reading selected Rate_Master precomputed rate and commercial fields.
* Fetching Labour_Master details through `Rate_Master.tech_key`.
* Copying required database values into processing results, review screens, and
  exports.
* Preserving imported workbook values without recalculating client costing
  formulas.

---

## Export Service

Responsible for:

* Internal review sheet
* Client BOQ sheet
* Linked formulas

---

# User Roles

## Super Admin

Access:

* Entire system.
* All BOQs.
* User management.
* Database management.
* Pending products.

---

## Expert

Access:

* Own BOQs.
* Processing.
* Review.
* Export.

---

# Authentication Flow

```text
Login
    ↓
Session Creation
    ↓
Role Validation
    ↓
Dashboard
```

---

# Database Import Flow

```text
Upload Excel
    ↓
Validation
    ↓
Backup Existing Database
    ↓
Import New Data
    ↓
Activate Version
    ↓
Generate Embeddings
```

Database upload/import runs synchronously through the database import service.
No Celery task is queued for database import or database embedding generation.

---

# Database Versioning

System maintains:

* Active Version
* Previous Version 1
* Previous Version 2

New upload:

* Archives oldest version.
* Activates newest version.

---

# BOQ Processing Workflow

```text
Upload BOQ
    ↓
Upload Make List
    ↓
Create Processing Job
    ↓
Queue Job
    ↓
AI Processing
    ↓
Product Matching
    ↓
Lowest Final Amount Rate Selection
    ↓
Rate And Labour Detail Retrieval
    ↓
Confidence Scoring
    ↓
Generate Results
```

BOQ Excel parsing keeps original worksheet row numbers and groups structural
parent/specification rows into the JSON context of measured child rows. Rows
with the actual unit or quantity are the rows processed for matching and the
rows targeted by client-sheet rate/amount fills.

Each BOQItem stores a backend grouped-row payload with parent row, child/detail
rows, original Excel row numbers, canonical source fields, and
`target_excel_row`. The uploaded workbook remains the UI/audit/export source;
the grouped payload is the processing source.

---

# Background Job Architecture

Celery workers process:

* BOQ jobs.
* AI requests.
* Export generation.
* Notifications.

Redis is used as the message broker.

---

# AI Processing Workflow

BOQ Row Batch

↓

Build grouped BOQ row JSON payloads

↓

Single OpenAI batch analysis with compact active database context

↓

Extract:

* `database_products[]` candidates that appear represented in active database
  context.
* `missing_products[]` candidates not represented in active database context.
* `activities[]` context shaped by active labour/activity vocabulary.

↓

Return structured data.

Extraction preserves all purchasable product/equipment candidates from the BOQ
row. Final database presence is confirmed by PostgreSQL matching; AI context
classification is advisory and reviewable.

Product and activity extraction are handled in configurable batches of grouped
BOQ items. The batch request sends the shared extraction instruction and active
database context once, then returns row_id-keyed extraction results for each
input row. If a batch extraction request fails or times out, the analyzer
retries by splitting the batch into smaller row groups before skipping any
individual failed rows. The target extraction batch size is 10 finalized grouped
BOQ items, OpenAI completion timeout is 120 seconds, and SDK retries are bounded by
`OPENAI_MAX_RETRIES`.
The active database context is cached per DatabaseVersion and rendered before
the variable row payload so repeated batch requests keep a stable prompt prefix.
Database import and rollback invalidate the context cache after the active
DatabaseVersion changes, so any of the retained master database versions can be
made active without reusing stale AI vocabulary.
AI provider token usage logs include cached prompt token counts when returned.

---

# Product Search Workflow

Priority:

1. Exact Match
2. Alias Match
3. Chroma Embedding Match
4. OpenAI Validation

Search queries are built in this order:

1. Extracted product candidate fields, one candidate at a time.
2. Search variants built from structured fields such as size_mm plus
   sub_category.
3. Original grouped BOQ description, only when no product candidate is
   available.

Each product candidate from `database_products[]` or `missing_products[]` is
matched independently and stored as a separate ProductMatch with its
`extraction_index`. This allows one BOQ item to produce multiple matched
equipment/product lines while activities remain row-level.
The full deduplicated product candidate list remains stored on
BOQItem.ai_extraction across `database_products[]` and `missing_products[]` for
review and pending-product workflows.
Embedding search uses the local Chroma persistent vector index. Chroma returns
candidate Rate_Master metadata, and the matching service resolves candidates
back to PostgreSQL before applying the lowest-final-amount rule.

deprecated lookup keys are removed from the active matching workflow.
Exact matching uses normalized Rate_Master product/specification fields and
`tech_key` only for Rate_Master-to-Labour_Master retrieval.

---

# Confidence Calculation

Factors:

* Category and sub category match.
* Class and size_mm match.
* Make, capacity, unit, and supplier match.

Confidence is evaluated per ProductMatch against the corresponding extracted
product candidate identified by `extraction_index`.

---

# Confidence Thresholds

| Score | Color  | Action          |
| ----- | ------ | --------------- |
| >90   | Green  | Accept          |
| 80-90 | Yellow | Review          |
| 70-80 | Orange | Strong Review   |
| 30-70 | Red    | Manual Review   |
| <30   | Blank  | Pending Product |

---

# Unknown Product Workflow

```text
No Match
    ↓
Pending Queue
    ↓
Super Admin Review
    ↓
Approve Product
```

---

# Make List Processing

The make list acts as a filtering layer.

Only approved makes are eligible for selection.

Products outside the make list are excluded.

Each parsed make-list row is scoped through the target BOQRun, not by visible
BOQ name or uploaded filename. Duplicate BOQ names and duplicate make-list
filenames therefore remain isolated.

Excel make-list parsing detects the real header row when title rows appear
before the table and maps common aliases such as make, approved make, brand,
manufacturer, and OEM into make-list entries.
Parsed make-list entries are deduplicated by make plus category, so repeated
approved makes remain available for every material category where they appear.

---

# Rate Selection

When exact, alias, or embedding search returns multiple Rate_Master rows for
the same product, the active workflow selects the row with the lowest
`Final_Amount_(Excl GST)`.

Supplier selection modes are not part of the active workflow.

---

# Master Database Relationships

The active PostgreSQL master schema follows the client workbook:

```text
Rate_Master.tech_key -> Labour_Master.tech_key
Rate_Master -> Labour_Structure_Source -> Labour_Master
Rate_Master.category -> TOR_Main.category
Rate_Master(category, sub_category, size_mm) -> TOR_Accessories size band
Labour_Master.state -> State_Control_List.state
```

Matching and embeddings use Rate_Master key/specification fields. The selected
Rate_Master row supplies precomputed material, commercial, supplier, make, and
final amount values. `Rate_Master.tech_key` links to Labour_Master so the
system can retrieve the corresponding precomputed labour charge details.
Labour_Structure_Source may be used only as a lookup fallback to resolve a
Rate_Master category/sub_category/size row to a Labour_Master `tech_key`.

---

# Rate And Labour Detail Retrieval

BOQ_AI does not recalculate costing formulas from the imported workbook.

After matching and lowest-final-amount rate selection, the system retrieves and
stores the required fields from:

* Rate_Master.
* Labour_Master, joined by `tech_key`.

The system shall not calculate material cost, labour cost, transportation,
accessories, overheads, profit, commercial percentages, supplier selection, or
final rate. Imported workbook values remain authoritative.

Any future derived value must be documented as a human-approved business rule
before implementation.

---

# BOQ Quantity And Product Quantity

BOQ-level unit and quantity are billing/export fields for the grouped BOQ item.
They must not be blindly applied to every extracted product/component.

Each extracted product candidate shall include:

* `product_quantity`.
* `product_unit`.
* `quantity_basis`: `per_boq_unit`, `total_for_boq_row`, or `unknown`.
* `quantity_source`: BOQ column, grouped child/detail row, AI fallback, or
  review.

Unit and quantity resolution priority:

1. Existing BOQ unit/quantity columns.
2. Parsed child/detail rows inside the grouped BOQ item.
3. AI-extracted fallback.
4. Blank/review-required result.

---

# Internal Review Sheet

Contains:

* Breakdown List workbook sheet.
* Original BOQ description.
* AI interpretation.
* Original source Excel row and target Excel row.
* Extraction index.
* Extracted product/component name.
* Matched database product code.
* Matched Rate_Master row id.
* Match type.
* Approved make and supplier.
* Product quantity, product unit, and quantity basis.
* Selected Rate_Master material/commercial/final amount fields.
* `tech_key`.
* Linked Labour_Master labour charge fields.
* Confidence.
* Review required and missing product flags.

If a BOQ item contains multiple extracted products/equipment, this sheet writes
one breakdown row per extracted product/component candidate. Unmatched
candidates are written as missing/pending rows so hidden products from one BOQ
row remain visible for expert review.

---

# Client Sheet

Contains:

* Uploaded BOQ sheet layout preserved where available.
* Unit.
* Quantity.
* Rate.
* Amount.

If a BOQ item has multiple ProductMatch rows, the client-sheet rate is sourced
from the selected precomputed final amount fields and product-level quantity
basis according to documented export rules. The application does not recompute
workbook cost components.

Linked to internal sheet.

Uploaded BOQ files are preserved for auditability. Client export starts from the
uploaded workbook sheet when available and fills only Unit, Quantity, Rate, and
Amount. Existing Unit and Quantity cells are not overwritten. If the product
details live in a child/inherited row, Rate and Amount are filled on that child
row.

Client export uses each BOQItem's `target_excel_row` to map summarized output
back to the original workbook. If no confident target row exists, the item is
review-required and client output remains blank.

---

# File Storage Structure

```text
media/

    database/

    boq/

    make_lists/

    outputs/

    exports/
```

---

# BOQ Ownership

Each BOQ belongs to one user.

Only:

* Owner.
* Super Admin.

can access it.

---

# Processing History

Each BOQ maintains:

* Original files.
* Processing runs.
* Output files.
* Approval history.

---

# Error Handling

System shall detect:

* Invalid files.
* Missing columns.
* Empty rows.
* Failed AI calls.
* Invalid products.
* Missing rates.

---

# Logging

System logs:

* User actions.
* Processing jobs.
* Runtime AI instructions rendered from prompt templates before provider calls.
* Row-level AI extraction payloads with `source_row` and a single `extraction`
  object containing `database_products[]`, `missing_products[]`, and
  `activities[]`.
* Errors.
* Approvals.
* Database uploads.

---

# Security

* Password hashing.
* Role permissions.
* Session security.
* CSRF protection.
* Audit logs.

---

# Performance Requirements

* Support concurrent BOQs.
* Large Excel processing.
* Background processing.
* Fast search.

---

# Scalability

The architecture supports:

* Multiple experts.
* Larger databases.
* Additional AI providers.
* Multiple workers.

---

# Infrastructure

AWS EC2:

* 2 vCPU
* 8 GB RAM
* 100 GB SSD

Additional services:

* PostgreSQL
* Redis
* Nginx

---

# Technical Constraints

* OpenAI only.
* Excel-based inputs for primary DB/BOQ.
* PDF or Excel based inputs for Make Lists.
* Single company deployment.
* No public registration.
* PostgreSQL is required in every runtime.
* No public REST API is active in V1; the product surface is Django Templates
  with HTMX interactions.

---

# Development Priority

1. Authentication
2. User Management
3. Database Import
4. BOQ Upload
5. AI Processing
6. Product Matching
7. Rate And Labour Detail Retrieval
8. Export System
9. Review Workflow
10. Pending Product Queue

---

# Document Dependencies

This document depends on:

* PRD.md

ARCHITECTURE.md, DATABASE_ARCHITECTURE.md, PROJECT_STRUCTURE.md, and AGENTS.md
shall derive technical decisions from this document.
