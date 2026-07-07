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
* Preserving make/vendor data from the selected Rate_Master row for review and
  audit.

---

## Cost Engine

Responsible for:

* Material calculation
* Labour calculation
* Transportation
* Accessories
* Overheads
* Profit

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
Cost Calculation
    ↓
Confidence Scoring
    ↓
Generate Results
```

BOQ Excel parsing keeps original worksheet row numbers and groups structural
parent/specification rows into the JSON context of measured child rows. Rows
with the actual unit or quantity are the rows processed for costing and the
rows targeted by client-sheet rate/amount fills.

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

BOQ Row

↓

Build grouped BOQ row JSON

↓

OpenAI Analysis with active database context

↓

Extract:

* Product
* Size
* Material
* Product candidates
* Activities

↓

Return structured data.

---

# Product Search Workflow

Priority:

1. Exact Match
2. Alias Match
3. Embedding Match
4. OpenAI Validation

Search queries are built in this order:

1. Original grouped BOQ description.
2. Top-level AI extraction fields.
3. Extracted product candidate fields.
4. AI-provided database hints that point toward active Rate_Master terminology.

The original BOQ text remains authoritative and is searched first.

---

# Confidence Calculation

Factors:

* Product match.
* Size match.
* Make match.
* Activity match.

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

Vendor selection modes are not part of the active workflow.

---

# Cost Calculation Engine

Final Rate:

```text
Material
+ Labour
+ Transportation
+ Accessories
+ Overheads
+ Profit
```

The AI system does not perform calculations.

All calculations are rule based.

---

# Internal Review Sheet

Contains:

* Breakdown List workbook sheet.
* Original BOQ description.
* AI interpretation.
* Matched database product code.
* Approved make and supplier.
* Purchase/material/commercial breakdown values.
* Profit, final amount excluding GST, margin, labour, and confidence.

---

# Client Sheet

Contains:

* Uploaded BOQ sheet layout preserved where available.
* Unit.
* Quantity.
* Rate.
* Amount.

Linked to internal sheet.

Uploaded BOQ files are preserved for auditability. Client export starts from the
uploaded workbook sheet when available and fills only Unit, Quantity, Rate, and
Amount. Existing Unit and Quantity cells are not overwritten. If the product
details live in a child/inherited row, Rate and Amount are filled on that child
row.

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
* Row-level AI extraction payloads for BOQ processing review.
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
7. Cost Engine
8. Export System
9. Review Workflow
10. Pending Product Queue

---

# Document Dependencies

This document depends on:

* PRD.md

ARCHITECTURE.md, DATABASE_ARCHITECTURE.md, PROJECT_STRUCTURE.md, and AGENTS.md
shall derive technical decisions from this document.
