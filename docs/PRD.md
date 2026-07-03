
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

The platform assists estimation teams in understanding BOQ descriptions, identifying products, selecting vendors, calculating material and execution costs, applying commercial rules, and generating final BOQ outputs while maintaining full human review and approval.

The objective is to reduce manual effort, improve consistency, minimize estimation errors, and increase tender processing capacity.

---

# Business Problem

Current BOQ estimation processes depend heavily on experienced estimators who manually:

* Read BOQ descriptions.
* Understand technical requirements.
* Identify products.
* Apply make restrictions.
* Select vendors.
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
8. Vendor Selection Module
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
* Generate product embeddings.
* Activate imported database.

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

Generate Embeddings

↓

Activate Version

---

# BOQ Workflow

Expert uploads:

* BOQ Excel file.
* Make List Excel file.
* BOQ name.

System creates:

* BOQ record.
* Processing job.

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

---

# Product Matching Workflow

BOQ Description

↓

AI Understanding

↓

Database Search

↓

Embedding Search

↓

Make Filtering

↓

Vendor Selection

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

---

# Make List Processing

The make list acts as the source of truth.

Only approved makes may be selected.

The system shall filter products according to the make list.

---

# Vendor Selection

The system shall support:

## Lowest Cost Vendor

Select lowest priced vendor.

---

## Preferred Vendor

Select predefined vendor.

---

## Custom Vendor Selection

Allow expert to override vendor during review.

---

# Row-Level Vendor Override

Experts may modify vendor selection during review.

The system shall recalculate costs accordingly.

---

# Activity Extraction

The system shall identify:

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

# Internal Review Sheet

Contains:

* Original description.
* Product selected.
* Make selected.
* Vendor selected.
* Purchase rate.
* Labour.
* Transportation.
* Accessories.
* Overheads.
* Profit.
* Final rate.
* Confidence score.

This sheet is used internally.

---

# Client Sheet

Contains:

* Original BOQ format.
* Final approved rates.
* Final amounts.

Values are linked to the internal sheet.

Changes in the internal sheet update the client sheet.

---

# Review Workflow

Expert:

* Reviews results.
* Modifies products.
* Modifies vendors.
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

# Future Scope

* Multiple AI providers.
* Advanced analytics.
* Dashboard reporting.
* Cost forecasting.
* Vendor analytics.
* Approval workflows.
* Multi-company support.

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
