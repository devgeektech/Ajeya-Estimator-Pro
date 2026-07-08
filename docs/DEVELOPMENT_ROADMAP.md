# Project

BOQ_AI

---

# Version

1.0

---

# Purpose

This document defines the complete development plan, sprint structure, implementation order, milestones, dependencies, deliverables, and release strategy for BOQ_AI.

This document serves as the official execution plan for the project.

---

# Project Development Strategy

BOQ_AI will be developed using an incremental milestone-based approach.

Each sprint must produce:

* Working functionality.
* Updated documentation.
* Tested features.
* Session updates.

---

# Development Phases

## Phase 0 – Project Foundation

Status:

Completed

Deliverables:

* PRD
* TRD
* Architecture
* Database Architecture
* Project Structure
* Agent Instructions
* Session State

---

# Phase 1 – Core Platform

Estimated:

1 Week

---

## Sprint 1

### Authentication & User Management

Deliverables:

* Django setup.
* PostgreSQL setup.
* Environment configuration.
* User model.
* Role system.
* Email login.
* Password reset.
* Super Admin panel.

Features:

* Login.
* Logout.
* Forgot password.
* User creation.
* Role assignment.

Dependencies:

None.

---

## Sprint 2

### Dashboard & Layout

Deliverables:

* Base templates.
* Dashboard.
* Navigation.
* Sidebar.
* User profile.

Features:

* HTMX integration.
* Alpine.js integration.
* Responsive layout.

---

# Phase 2 – Database Management

Estimated:

1 Week

---

## Sprint 3

### Database Upload Module

Features:

* Upload database Excel.
* Validation.
* Version creation.
* Backup.
* Rollback.

Deliverables:

* Database manager.
* Validation engine.
* Import service.

---

## Sprint 4

### Database Import Engine

Features:

* Sheet parsing.
* Data import.
* Relationships.
* Version activation.

Deliverables:

* Import workflow.
* Import logs.
* Error handling.

---

# Phase 3 – BOQ Management

Estimated:

1 Week

---

## Sprint 5

### BOQ Upload Module

Features:

* BOQ upload.
* Make list upload.
* BOQ naming.
* Status creation.

Deliverables:

* BOQ models.
* Upload UI.
* File storage.

---

## Sprint 6

### Processing Queue

Features:

* Celery integration.
* Redis setup.
* Job creation.
* Progress tracking.

Deliverables:

* Processing dashboard.
* Status updates.

---

# Phase 4 – AI Engine

Estimated:

1 Week

---

## Sprint 7

### OpenAI Integration

Features:

* API integration.
* Prompt management.
* Request handling.

Deliverables:

* AI service.
* Prompt system.

---

## Sprint 8

### Product Extraction

Features:

* Product identification.
* Size extraction.
* Material extraction.

Deliverables:

* Product extractor.

---

## Sprint 9

### Activity Extraction

Features:

* Excavation.
* Installation.
* Testing.
* Commissioning.

Deliverables:

* Activity extractor.

---

# Phase 5 – Product Matching

Estimated:

1 Week

---

## Sprint 10

### Matching Engine

Features:

* Exact matching.
* Alias matching.
* Vector matching.

Deliverables:

* Matching service.

---

## Sprint 11

### Confidence Engine

Features:

* Score generation.
* Color coding.
* Match explanations.

Deliverables:

* Confidence service.

---

# Phase 6 - Rate Selection

Estimated:

3 Days

---

## Sprint 12

Features:

* Lowest Final_Amount_(Excl GST) row.
* Make and supplier traceability.

Deliverables:

* Rate selection inside matching service.

---

# Phase 7 – Rate And Labour Detail Retrieval

Estimated:

1 Week

---

Status:

Superseded by the 2026-07-08 business rule clarification. The active workflow
retrieves precomputed Rate_Master and linked Labour_Master values from the
imported client database. BOQ_AI does not recalculate workbook costing formulas.

## Sprint 13

### Material Rate Fields

Features:

* Selected Rate_Master material fields.
* Selected Rate_Master net material and final amount fields.

---

## Sprint 14

### Labour Detail Fields

Features:

* Labour_Master lookup by `tech_key`.
* Selected Labour_Master labour charge fields.

---

## Sprint 15

### Commercial Rate Fields

Features:

* Selected precomputed commercial fields.
* Selected precomputed profit and final amount fields.

---

# Phase 8 – Review Workflow

Estimated:

1 Week

---

## Sprint 16

### Internal Review

Features:

* Editable rows.
* Product changes.
* Selected-rate/supplier changes.

---

## Sprint 17

### Approval Workflow

Features:

* Under review.
* Approved.
* Exported.

---

# Phase 9 – Pending Products

Estimated:

3 Days

---

## Sprint 18

Features:

* Unknown products.
* Pending queue.
* Product approval.

Deliverables:

* Admin review screen.

---

# Phase 10 – Export System

Estimated:

1 Week

---

## Sprint 19

### Internal Sheet

Features:

* Detailed breakdown.
* Confidence colors.

---

## Sprint 20

### Client Sheet

Features:

* Original format.
* Linked formulas.

---

# Phase 11 – Testing

Estimated:

1 Week

---

## Sprint 21

### Unit Testing

Coverage:

* Services.
* Models.

---

## Sprint 22

### Integration Testing

Coverage:

* Workflows.
* Processing.

---

## Sprint 23

### UAT

Coverage:

* Real BOQs.
* Client validation.

---

# Phase 12 – Deployment

Estimated:

3 Days

---

## Sprint 24

Features:

* AWS EC2.
* Gunicorn.
* Nginx.
* Redis.
* PostgreSQL.

Deliverables:

* Production deployment.

---

# Development Dependencies

| Feature                | Depends On             |
| ---------------------- | ---------------------- |
| Authentication         | None                   |
| Database Import        | Authentication         |
| BOQ Upload             | Authentication         |
| AI Engine              | BOQ Upload             |
| Matching               | AI                     |
| Rate/Labour Retrieval  | Matching               |
| Review                 | Rate/Labour Retrieval  |
| Export                 | Review                 |

---

# Milestones

---

## Milestone 1

Core Platform

Deliverables:

* Authentication.
* Dashboard.
* User roles.

---

## Milestone 2

Database System

Deliverables:

* Upload.
* Versioning.
* Rollback.

---

## Milestone 3

BOQ Processing

Deliverables:

* Upload.
* Queue.
* Tracking.

---

## Milestone 4

AI Processing

Deliverables:

* Extraction.
* Matching.
* Confidence.

---

## Milestone 5

Costing System

Deliverables:

* Material.
* Labour.
* Profit.

---

## Milestone 6

Review System

Deliverables:

* Editing.
* Approval.

---

## Milestone 7

Export System

Deliverables:

* Internal sheet.
* Client sheet.

---

## Milestone 8

Production Deployment

Deliverables:

* AWS.
* Testing.
* Production release.

---

# Testing Strategy

Every sprint must include:

* Unit tests.
* Integration tests.

Critical features require:

* Manual testing.

---

# Documentation Rules

Every sprint updates:

* SESSION_STATE.md
* CHANGELOG.md

Architecture changes require:

* TRD updates.
* Architecture updates.

---

# Definition of Done

A feature is complete when:

* Code implemented.
* Tests passing.
* Documentation updated.
* Session updated.
* Reviewed.

---

# Risk Areas

## Database Changes

Mitigation:

* Import layer.

---

## Product Matching

Mitigation:

* Alias system.
* Human review.

---

## Unknown Products

Mitigation:

* Pending queue.

---

# Expected Timeline

| Phase                 | Duration |
| --------------------- | -------- |
| Foundation            | Complete |
| Core Platform         | 1 Week   |
| Database              | 1 Week   |
| BOQ Management        | 1 Week   |
| AI Engine             | 1 Week   |
| Matching              | 1 Week   |
| Rate/Labour Retrieval | 1 Week   |
| Review                | 1 Week   |
| Export                | 1 Week   |
| Testing               | 1 Week   |
| Deployment            | 3 Days   |

---

# Total Estimated Duration

Development:

6–8 Weeks

Production Ready:

8–10 Weeks

Current Runtime Direction:

* PostgreSQL only.
* Single settings module: `config.settings`.
* Local development and EC2 both use PostgreSQL on `localhost`.
* No demo seeding or dummy runtime data.
* No active public REST API in V1.

---

# Release Plan

## Version 1.0

* Single company.
* OpenAI.
* Excel input.
* Excel output.

---

## Future Versions

* Analytics.
* Multiple companies.
* Multiple AI providers.
* APIs.
* ERP integration.

---

# Final Development Sequence

```text id="c8r7u2"
Authentication

↓

Database

↓

BOQ Upload

↓

Queue

↓

AI

↓

Matching

↓

Rate/Labour Retrieval

↓

Review

↓

Export

↓

Testing

↓

Deployment
```

---

# Project Status

Complete.

Development Status:

All 24 sprints delivered.

Risk Level:

Low.

Architecture:

Approved.

Next Action:

Production hardening and live validation on the EC2 instance with real client
BOQs only.
