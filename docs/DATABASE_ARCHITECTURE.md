# Project

BOQ_AI

---

# Version

1.0 (Provisional)

---

# Purpose

This document defines the database architecture, table relationships, import strategy, versioning strategy, and data ownership model for BOQ_AI.

The schema is based on the current client database workbook and may evolve in future versions.

---

# Design Principles

The database shall provide:

* Fast product search.
* AI-assisted matching.
* Version control.
* Historical BOQ preservation.
* Auditability.
* Rollback support.
* Business rule support.

---

# Database Technologies

Database:

* PostgreSQL

Vector Search:

* pgvector

ORM:

* Django ORM

---

# Database Categories

The system database consists of:

1. System Tables
2. Master Database Tables
3. Processing Tables
4. BOQ Tables
5. AI Tables
6. Approval Tables

---

# SYSTEM TABLES

---

## User

Purpose:

System users.

Fields:

* id
* email
* password
* first_name
* last_name
* role
* is_active
* created_at

Roles:

* SUPER_ADMIN
* EXPERT

---

## DatabaseVersion

Purpose:

Track database uploads.

Fields:

* id
* version_number
* name
* uploaded_by
* uploaded_at
* is_active
* source_filename

Retention:

* Current active version
* Up to 9 previous archived versions (10 total)

---

# MASTER TABLES

---

## RateMaster

Source:

Rate_Master sheet.

Fields:

* id
* database_version
* product_code
* description
* make
* vendor
* purchase_rate
* unit
* category
* subcategory
* remarks

---

## LabourMaster

Source:

Labour_Master sheet.

Fields:

* id
* database_version
* labour_code
* labour_name
* labour_rate
* unit

---

## TORMain

Source:

TOR_Main.

Fields:

* id
* database_version
* tor_code
* description

---

## TORLabour

Source:

TOR_Labour.

Fields:

* id
* database_version
* tor_code
* labour_code
* quantity

---

## TORAccessories

Source:

TOR_Accessories.

Fields:

* id
* database_version
* tor_code
* accessory_code
* quantity

---

## StateControl

Source:

State_Control_List.

Fields:

* id
* state_name
* labour_multiplier
* transportation_multiplier

---

# PRODUCT TABLES

---

## ProductAlias

Purpose:

Alternative descriptions.

Examples:

* 150 NB Pipe
* ERW Pipe
* MS Pipe

Fields:

* id
* alias
* product_code

---

## ProductEmbedding

Purpose:

AI search.

Fields:

* id
* product_code
* embedding_vector
* generated_at

---

# PENDING PRODUCTS

---

## PendingProduct

Purpose:

Unknown products.

Fields:

* id
* description
* suggested_product
* confidence_score
* boq_item
* status
* created_by
* reviewed_by

Statuses:

* Pending
* Approved
* Rejected

---

# BOQ TABLES

---

## BOQ

Purpose:

Main BOQ.

Fields:

* id
* user
* boq_name
* status
* uploaded_file
* make_list_file
* created_at

---

## BOQRun

Purpose:

Reprocessing history.

Fields:

* id
* boq
* run_number
* status
* started_at
* completed_at

---

## BOQItem

Purpose:

Original BOQ rows.

Fields:

* id
* boq_run
* row_number
* description
* quantity
* unit

---

# MATCHING TABLES

---

## ProductMatch

Purpose:

Store matching results.

Fields:

* id
* boq_item
* product
* confidence_score
* make
* vendor

---

## ActivityMatch

Purpose:

Store activities.

Fields:

* id
* boq_item
* activity_name
* confidence_score

---

# COST TABLES

---

## CostBreakdown

Fields:

* material_cost
* labour_cost
* transportation_cost
* accessories_cost
* overhead_cost
* profit
* final_rate

---

# REVIEW TABLES

---

## ReviewItem

Purpose:

Expert changes.

Fields:

* original_product
* revised_product
* original_vendor
* revised_vendor
* notes

---

# EXPORT TABLES

---

## ExportFile

Fields:

* boq_run
* internal_sheet
* client_sheet
* exported_by
* exported_at

---

# NOTIFICATION TABLES

---

## Notification

Fields:

* user
* title
* message
* is_read

---

# AUDIT TABLES

---

## AuditLog

Fields:

* user
* action
* entity
* entity_id
* timestamp

---

# DATABASE VERSION WORKFLOW

```text
Upload Database

↓

Validate

↓

Create New Version

↓

Import Data

↓

Generate Embeddings

↓

Activate

↓

Archive Previous
```

---

# BOQ WORKFLOW

```text
BOQ

↓

BOQ Run

↓

BOQ Items

↓

Matching

↓

Costing

↓

Review

↓

Export
```

---

# EMBEDDING STRATEGY

Embeddings are generated for:

* Products
* Product aliases

Embeddings are not generated for:

* Labour
* Costs
* Vendors
* Overheads

---

# SEARCH STRATEGY

Priority:

1. Exact Match
2. Alias Match
3. Vector Search
4. OpenAI Validation

---

# CONFIDENCE STORAGE

Every match stores:

* Confidence score
* Match reason
* AI explanation

---

# UNKNOWN PRODUCT RULE

Confidence:

* Above 30 → show result.
* Below 30 → pending product.

The row remains blank.

Pending product created.

---

# DATA OWNERSHIP

| Data     | Owner       |
| -------- | ----------- |
| Database | Super Admin |
| Users    | Super Admin |
| BOQ      | Expert      |
| Review   | Expert      |
| Approval | Super Admin |

---

# RETENTION POLICY

Keep:

* Current active database.
* Up to 9 previous archived versions (10 total retained).

Keep:

* All BOQs.
* All exports.
* All reviews.

---

# FUTURE DATABASE CHANGES

Future versions may include:

* Vendor master.
* Product master.
* Activity master.
* Rule engine.
* Multi-company support.

---

# FINAL NOTES

This schema represents Version 1 and is derived from the March client workbook.

Future database updates shall preserve:

* BOQ history.
* Processing history.
* Export history.

Database changes shall never invalidate previously processed BOQs.
