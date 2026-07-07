
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

BOQ_AI is an AI-assisted BOQ estimation and tender costing platform designed specifically for Fire Protection and MEP estimation workflows.

The platform assists estimation teams in understanding BOQ descriptions, identifying products, calculating material and execution costs, applying commercial rules, and generating final BOQ outputs while maintaining full human review and approval.

The objective is to reduce manual effort, improve consistency, minimize estimation errors, and increase tender processing capacity.

---

# Business Problem

Current BOQ estimation processes depend heavily on experienced estimators who manually:

* Read BOQ descriptions.
* Understand technical requirements.
* Identify products.
* Apply make restrictions.
* Select the lowest final-amount product rate row.
* Calculate material costs.
* Calculate labour costs.
* Apply transportation and accessories.
* Calculate commercial margins.
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
* Modifying calculations.
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
9. Cost Calculation Engine
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
* Confidence calculation.

AI is not used for:

* Pricing.
* Labour calculations.
* Commercial calculations.
* Vendor calculations.

AI extraction shall receive database-aware context from the active master
database so product and activity names are shaped toward Rate_Master,
Labour_Master, and TOR_Labour terminology.

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

Embedding Search

↓

Lowest Final Amount Rate Selection

↓

Confidence Calculation

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
* Preserve product candidates extracted from one grouped BOQ row.
* Search Rate_Master using the original BOQ description first, then extracted
  product candidates and database hints.

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

Vendor-specific selection modes, preferred vendor rules, and custom vendor
override are not part of the active processing workflow.

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

Activities contribute to:

* Labour.
* Transportation.
* Equipment.
* Overheads.

---

# Cost Calculation

The system shall calculate:

* Material cost.
* Labour cost.
* Transportation.
* Accessories.
* Equipment.
* Overheads.
* Profit.

Final rate:

Material + Labour + Accessories + Overheads + Profit

---

# Confidence Scoring

Each BOQ row receives a confidence score.

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
* Original BOQ description.
* AI interpretation.
* Matched database serial/product code.
* Approved make.
* Supplier.
* Purchase/material/commercial breakdown values.
* Profit and final amount excluding GST.
* Labour per-unit value.
* Confidence score.

This sheet is used internally as the breakdown list.

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
uploaded BOQ, the existing value is preserved and used for amount calculation.
When a parent row contains only a heading/description and a child row contains
the product unit/quantity, Rate and Amount are filled on the child row.

Changes in the internal sheet update the client sheet.

---

# Review Workflow

Expert:

* Reviews results.
* Modifies products.
* Modifies matched products/rate rows.
* Modifies calculations.

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
