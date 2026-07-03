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

## Vendor Service

Responsible for:

* Vendor selection
* Lowest-cost selection
* Preferred vendor selection
* Manual overrides

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
Generate Embeddings
    ↓
Activate Version
```

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
Cost Calculation
    ↓
Confidence Scoring
    ↓
Generate Results
```

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

OpenAI Analysis

↓

Extract:

* Product
* Size
* Material
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

---

# Confidence Calculation

Factors:

* Product match.
* Size match.
* Make match.
* Activity match.
* Vendor match.

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

---

# Vendor Selection Modes

## Lowest Cost

Select minimum price.

---

## Preferred Vendor

Select configured vendor.

---

## Custom Selection

User selects vendor during review.

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

* BOQ description.
* Product.
* Make.
* Vendor.
* Purchase rate.
* Labour.
* Transportation.
* Accessories.
* Profit.
* Confidence.

---

# Client Sheet

Contains:

* Original BOQ format.
* Final approved rate.
* Amount.

Linked to internal sheet.

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
* Missing vendors.

---

# Logging

System logs:

* User actions.
* Processing jobs.
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
* Excel-based inputs.
* Single company deployment.
* No public registration.
* No PDF support in V1.
* PostgreSQL is required in every runtime.
* No public REST API is active in V1; the product surface is Django Templates
  with HTMX interactions.

---

# Future Technical Scope

* Multi-company support.
* Multiple AI providers.
* Advanced analytics.
* Dashboard reporting.
* API integrations.
* ERP integration.

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

Future documents:

* ARCHITECTURE.md
* DATABASE_ARCHITECTURE.md
* PROJECT_STRUCTURE.md
* AGENTS.md

shall derive technical decisions from this document.
