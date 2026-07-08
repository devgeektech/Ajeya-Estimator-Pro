
# Project Name

BOQ_AI

---

# Version

1.0

---

# Document Status

Approved

---

# Product Overview

BOQ_AI is an AI-assisted BOQ estimation and tender rate-retrieval platform
designed specifically for Fire Protection and MEP estimation workflows.

The platform assists estimation teams in understanding BOQ descriptions,
identifying products, selecting the correct Rate_Master row, retrieving linked
Labour_Master details, and generating final BOQ outputs while maintaining full
human review and approval. It does not recalculate workbook costing formulas
already supplied in the client database.

The objective is to reduce manual effort, improve consistency, minimize estimation errors, and increase tender processing capacity.

---

# Business Problem

Current BOQ estimation processes depend heavily on experienced estimators who manually:

* Read BOQ descriptions.
* Understand technical requirements.
* Identify products.
* Apply make restrictions.
* Select the lowest final-amount product rate row.
* Read precomputed material and labour values.
* Read transportation, accessory, commercial, margin, and final amount values
  from the client workbook.
* Prepare final tender submissions.

This process is:

* Time consuming.
* Difficult to scale.
* Dependent on individual expertise.
* Error prone.
* Difficult to audit.

BOQ_AI addresses these challenges.

---

# Product Goals

* Reduce manual estimation effort.
* Reduce pricing errors.
* Improve estimation consistency.
* Increase tender processing capacity.
* Reduce dependency on individual experts.
* Preserve organizational knowledge.
* Maintain human approval.
* Provide full auditability.

---

# Target Users

## Super Admin

Responsible for:

* User management.
* Database management.
* Database rollback.
* Product approvals.
* System administration.
* Monitoring all BOQs.

---

## Expert User

Responsible for:

* Uploading BOQs.
* Uploading make lists.
* Processing BOQs.
* Reviewing results.
* Reviewing or modifying selected output values.
* Approving estimates.
* Exporting final BOQs.

---

# User Authentication

* Email-based login.
* Password reset via email.
* No public registration.
* Users created by Super Admin.
* Role-based access.

---

# User Roles

## Super Admin

Permissions:

* Full system access.
* User management.
* Database upload.
* Database rollback.
* Pending product approval.
* Access to all BOQs.
* View all processing jobs.
* View all reports.

---

## Expert

Permissions:

* Own BOQ access.
* BOQ processing.
* Review and editing.
* Report generation.
* Export capabilities.

Restrictions:

* No database modification.
* No user management.

---

# Technology Stack

Backend:

* Django

Frontend:

* Django Templates
* HTMX
* Alpine.js

Database:

* PostgreSQL

Background Jobs:

* Celery
* Redis

AI:

* OpenAI

Hosting:

* AWS EC2

File Processing:

* Pandas
* OpenPyXL

---

# System Modules

1. Authentication Module
2. User Management Module
3. Database Management Module
4. BOQ Management Module
5. Make List Module
6. AI Processing Module
7. Product Matching Module
8. Rate Selection Module
9. Rate And Labour Detail Retrieval Module
10. Confidence Engine
11. Review Workflow Module
12. Export Module
13. Pending Product Module
14. Reporting Module

---

# Database Management

The master database is maintained using Excel files provided by the client.

The system shall:

* Upload database workbook.
* Validate structure.
* Create database version.
* Import data into PostgreSQL.
* Activate imported database.
* Generate product embeddings.

The active master workbook structure is:

* Rate_Master.
* Labour_Master.
* TOR_Main.
* Labour_Structure_Source.
* TOR_Labour.
* TOR_Accessories.
* State_Control_List.

Rate_Master is the primary material table. Product lookup and embeddings use
its category, sub category, class, size, make, capacity, unit, supplier, and
technical/product fields. Deprecated lookup keys are not part of the
active workflow and must not be used for matching. The selected Rate_Master row
is the source of precomputed material,
commercial, supplier, make, and final amount fields. Its `tech_key` links to
Labour_Master so the system can retrieve the corresponding precomputed labour
charge details. Labour_Structure_Source may be used only as a lookup fallback
to resolve a Rate_Master category/sub_category/size row to a Labour_Master
`tech_key`.

The system shall maintain:

* Active database version.
* Two previous versions.
* Rollback capability.

---

# Database Version Workflow

Upload Database

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

Database upload and import run synchronously from the upload request. When the
request completes, the imported database version is active and embedding
generation has either completed or been skipped because AI is disabled.

---

# BOQ Workflow

Expert uploads:

* BOQ Excel file.
* Make List Excel file.
* BOQ name.

System creates:

* BOQ record.
* First BOQ run.
* BOQ item rows grouped by source serial number.

When a BOQ row has a serial number and following child/detail rows inherit that
serial number by leaving the serial cell blank, the system treats the parent and
children as one BOQ item. That grouped item is stored as structured JSON before
AI processing so the full source context is preserved.

When a parent or section row has no unit and quantity, it is treated as context
for the measured child rows below it. Rows that carry the actual unit or
quantity become the processing rows so final client BOQ exports fill the values
on the same rows where the client expects rates and amounts.

The uploaded BOQ workbook remains the audit source for UI preview and final
export layout. Backend processing uses a structured grouped-row representation
that stores the parent row, child/detail rows, original Excel row numbers,
canonical BOQ fields, and the target Excel row where final rate/amount output
must be written.

---

# BOQ Status

1. Uploaded
2. Processing
3. Completed
4. Under Review
5. Approved
6. Exported

---

# Background Processing

BOQs are processed using background jobs.

Users may:

* Upload multiple BOQs.
* Process multiple BOQs.
* Monitor progress.
* Continue working during processing.

---

# AI Responsibilities

OpenAI is used for:

* BOQ understanding.
* Product identification.
* Specification extraction.
* Activity extraction.
* Product matching validation.
* Match confidence support.

AI is not used for:

* Pricing.
* Labour calculations.
* Commercial calculations.
* Cost, profit, overhead, accessory, transportation, or final-rate
  calculations.
* Supplier selection calculations.

AI extraction shall receive compact database-aware context from the active
master database. Product context is limited to unique Rate_Master vocabulary
from category, sub_category, class, size_mm, make, capacity, unit, supplier, and
other product/specification fields needed for matching. Deprecated lookup keys
are excluded. Activity context is shaped toward Labour_Master and TOR_Labour
terminology. BOQ row extraction shall batch multiple grouped rows
into one AI request so the shared instruction and database context are not
resent for every row. The target batch size is 10 finalized grouped BOQ items
per request and remains configurable.
The active database context shall be cached by database version and placed
before variable BOQ row data so repeated extraction requests can reuse the same
stable instruction/context prefix.

---

# Product Matching Workflow

BOQ Description

↓

Grouped BOQ row JSON

↓

Database-aware AI Understanding

↓

Database Search

↓

Chroma Embedding Search

↓

Lowest Final Amount Rate Selection

↓

Rate And Labour Detail Retrieval

↓

Confidence Scoring

↓

Result Generation

---

# Product Matching Rules

The system shall:

* Understand varying descriptions.
* Recognize aliases.
* Identify equivalent products.
* Match sizes.
* Match specifications.
* Match makes.
* Preserve every product/equipment/component candidate extracted from one
  grouped BOQ row.
* Extract product candidates with Product Name, Category, Sub Category, Class,
  Size MM, Make, Capacity, Unit, Height, Working Pressure, Test Pressure,
  Temperature, Throw, K Factor, Head, Supplier, Product Quantity, Product Unit,
  and Quantity Basis fields.
* When one grouped BOQ row describes multiple equipment/products, extract each
  as a separate product candidate object.
* Preserve extracted products even when they are not present in Rate_Master.
  Matching shall split extracted candidates into `database_products[]` and
  `missing_products[]`.
* Return extraction JSON in three reviewable segments:
  `database_products[]` for products that appear present in the active database
  context, `missing_products[]` for products not represented in the active
  database context, and `activities[]` for activity/execution context. Final
  database presence is still confirmed by PostgreSQL matching.
* Batch extraction must return one fixed JSON extraction object for every input
  grouped BOQ row id, including empty product/activity lists when no extraction
  is possible.
* Search Rate_Master independently for each extracted product candidate. If no
  candidate is extracted, fall back to the grouped BOQ description.

BOQ-level unit and quantity are not automatically applied to every extracted
product. Each product candidate shall carry its own `product_quantity`,
`product_unit`, and `quantity_basis`:

* `per_boq_unit` means the product quantity is required for each BOQ unit.
* `total_for_boq_row` means the product quantity is the total quantity described
  by the grouped BOQ row.
* `unknown` means review is required before pricing/export can be trusted.

Unit and quantity priority is:

1. Existing BOQ unit/quantity columns.
2. Parsed nearby child/detail rows in the grouped BOQ item.
3. AI-extracted unit/quantity fallback.
4. Blank output with review required.

---

# Make List Processing

The make list acts as the source of truth.

Only approved makes may be selected.

The system shall filter products according to the make list.

Make lists are attached to a specific uploaded BOQ and are never shared by BOQ
name or file name. Two BOQs with the same BOQ name and same make-list filename
must remain separate records with separate make-list entries.

Make-list extraction shall tolerate common client formats, including title rows
before the table, make/brand/manufacturer/OEM header aliases, multiple make
columns, and cells containing multiple makes separated by common delimiters.
The same make may be valid for multiple material categories; the system shall
preserve each unique make and category pair.

---

# Rate Selection

When multiple Rate_Master rows match the same product, the system shall select
the row with the lowest `Final_Amount_(Excl GST)`.

Supplier-specific selection modes, preferred supplier rules, and custom supplier
override are not part of the active processing workflow.

Search priority:

1. Exact structured field search using active DatabaseVersion rows.
2. Alias search.
3. Chroma embedding similarity search over active-version Rate_Master product
   fields.
4. AI validation of top candidates when needed.

Deprecated lookup keys shall not be used in any search priority.

---

# Activity Extraction

The system shall identify labour/execution activities using active
Labour_Master and TOR_Labour terminology, including:

* Excavation.
* Trenching.
* Backfilling.
* Installation.
* Testing.
* Commissioning.
* Painting.
* Supports.

Activities are preserved as review and matching context only. They do not cause
the application to calculate labour, transportation, equipment, overhead, profit,
or final rates.

---

# Rate And Labour Detail Retrieval

The system shall not recalculate cost components already supplied by the client
database workbook.

After product matching and rate selection, the system shall:

* Use the selected Rate_Master row as the source of precomputed rate,
  commercial, supplier, make, and final amount fields.
* Use `Rate_Master.tech_key` to fetch the corresponding Labour_Master row.
* Copy required Rate_Master and Labour_Master columns into processing results,
  review screens, and exports.
* Preserve source database values for audit and human review.

The system shall not calculate:

* Material cost.
* Labour cost.
* Transportation.
* Accessories.
* Equipment.
* Overheads.
* Profit.
* Final rate.

Any future derived value must be documented as a human-approved business rule
before implementation.

---

## Deprecated Cost Calculation Rule

Earlier documentation described a Cost Calculation Engine. That is no longer
the active business rule. BOQ_AI retrieves precomputed values from the imported
client database and does not recompute the workbook's costing logic.

---

# Confidence Scoring

Each matched product/equipment receives a confidence score. A single BOQ row
may therefore have multiple confidence scores in the breakdown sheet.

---

## Above 90%

Green.

Accepted.

---

## 80-90%

Yellow.

Review recommended.

---

## 70-80%

Orange.

Strong review recommended.

---

## 30-70%

Red.

Manual verification required.

---

## Below 30%

No product selected.

Output remains blank.

Added to Pending Product Queue.

---

# Pending Product Workflow

Unknown products are added to:

Pending Product Queue.

Super Admin may:

* Approve.
* Reject.
* Merge.
* Add new product.

Approved products become available in future BOQs.

---

# Breakdown List

Contains:

* BOQ serial number.
* Original source Excel row and target Excel row.
* Original BOQ description.
* AI interpretation.
* Extraction index.
* Extracted product/component name.
* Matched database serial/product code.
* Matched Rate_Master row id.
* Match type.
* Approved make.
* Supplier.
* Product quantity.
* Product unit.
* Quantity basis.
* Selected Rate_Master precomputed material/commercial fields.
* Selected final amount excluding GST.
* `tech_key`.
* Linked Labour_Master labour charge fields.
* Confidence score.
* Review required flag.
* Missing product flag.

This sheet is used internally as the breakdown list.

If one BOQ row contains multiple products/equipment, the Breakdown List shows
one line per matched product/equipment while preserving the same original BOQ
description for traceability. Products extracted from hidden wording inside a
single BOQ row must be visible as separate Breakdown List rows.

---

# Client Sheet

Contains:

* The uploaded BOQ sheet layout preserved as closely as possible.
* Unit.
* Quantity.
* Rate.
* Amount.

Values are linked to the internal sheet.

The uploaded BOQ file remains preserved for audit history. Exported client BOQs
start from the uploaded BOQ sheet when available and only fill or add Unit,
Quantity, Rate, and Amount columns. If Unit or Quantity already exists in the
uploaded BOQ, the existing value is preserved and used according to documented
export rules.
When a parent row contains only a heading/description and a child row contains
the product unit/quantity, Rate and Amount are filled on the child row.
When one BOQ row produces multiple breakdown lines, the client Rate is sourced
from the selected precomputed final amount fields and product-level quantity
basis. Any amount handling must preserve the uploaded BOQ layout and use
documented export rules rather than recalculating cost components.

Client export shall reopen the original uploaded workbook, locate or create
Rate and Amount columns, and write output only to each BOQItem's stored
`target_excel_row`. All unrelated workbook content and formatting should be
preserved as closely as possible.

Changes in the internal sheet update the client sheet.

---

# Review Workflow

Expert:

* Reviews results.
* Modifies products.
* Modifies matched products/rate rows.
* Modifies selected output values for review/export when required.

Status changes:

Completed

↓

Under Review

↓

Approved

↓

Exported

---

# BOQ Ownership

Each BOQ belongs to the user who created it.

Experts can only access their own BOQs.

Super Admin can access all BOQs.

---

# Historical Processing

The system shall preserve:

* Original BOQ.
* Make list.
* Processing results.
* Review changes.
* Final output.

Reprocessing creates a new processing run.

---

# Notifications

The system shall provide:

* Processing completion.
* Failed processing.
* Pending review.
* Export completion.

---

# Security Requirements

* Role-based permissions.
* Password hashing.
* Session management.
* Access restrictions.
* Audit logging.

---

# Performance Requirements

* Support multiple concurrent BOQs.
* Background processing.
* Large Excel support.
* Fast search response.
* Responsive interface.

---

# Non-Functional Requirements

* Scalability.
* Reliability.
* Auditability.
* Maintainability.
* Security.
* Performance.

---

# Deployment

Deployment target:

AWS EC2

Recommended server:

* 2 vCPU
* 8 GB RAM
* 100 GB SSD

---

# Success Criteria

The system shall:

* Reduce manual effort.
* Improve consistency.
* Increase processing capacity.
* Reduce pricing errors.
* Preserve expert knowledge.
* Maintain human approval.
* Generate accurate BOQs.

---

# Product Vision

BOQ_AI shall become an intelligent estimation assistant that combines artificial intelligence, business rules, and human expertise to produce reliable, auditable, and scalable tender estimations.
