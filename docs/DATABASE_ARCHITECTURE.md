# Project

BOQ_AI

---

# Version

1.0 (Provisional)

---

# Purpose

This document defines the database architecture, table relationships, import strategy, versioning strategy, and data ownership model for BOQ_AI.

The schema is based on the current client database workbook.

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
* product_code (from workbook key fields when present; synthesized from
  category/subcategory/class/size when the client workbook leaves the key blank)
* description (from workbook description/match key, or synthesized from product
  attributes)
* make
* vendor
* purchase_rate
* final_amount_excl_gst (from `Final_Amount_(Excl GST)`)
* unit
* category
* subcategory
* remarks
* spec_json (all normalized raw workbook columns for evolving client fields such
  as discount, handling, accessories, profit, state, and source fields)

Import:

* `Tech_Key`, `product_code`, `Match_Key`, and `Source_Key` are accepted as
  explicit product identifiers.
* If no identifier is supplied, the importer creates a stable product key from
  available attributes such as category, subcategory, class, and size.
* Net/material rates populate `purchase_rate`. `Final_Amount_(Excl GST)` is
  stored separately as `final_amount_excl_gst` and is used to choose the lowest
  final-amount Rate_Master row during product matching.
* Blank or structurally incomplete master rows are skipped instead of creating
  empty product records.

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
* tor_code (from tor_code or category)
* description
* spec_json

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

Import:

* `State` and `state_name` headers are both accepted.
* Missing transportation multipliers default to 1.0.

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
* original_headers (JSON, canonical BOQ display headers)

---

## BOQItem

Purpose:

Original BOQ rows after serial-number grouping.

Fields:

* id
* boq_run
* row_number
* description
* quantity
* unit
* original_data (JSON canonical source values: s_no, description, unit, quantity)
* row_json (JSON grouped source row payload)
* ai_extraction (JSON)

Row grouping:

* If the workbook has no serial numbers, each captured row becomes one BOQItem.
* If serial numbers are present, a serial-numbered row starts a BOQItem and
  following blank-serial child/detail rows are stored inside that item's
  `row_json`.
* `row_json.schema` is `boq_row_group_v1`.
* `row_json.rows` preserves the Excel row number, serial number, description,
  unit, quantity, and canonical source values for each parent/child row.

AI extraction:

* `ai_extraction` stores top-level product fields and a `products` candidate
  list extracted from `row_json`.
* Product candidates may include category, subcategory, make, and
  database_hint values shaped toward active Rate_Master terminology.
* Activity extraction is shaped toward Labour_Master and TOR_Labour terminology.

---

## MakeListEntry

Purpose:

Approved makes scoped to one BOQ processing run.

Fields:

* id
* boq_run
* make
* category

Ownership:

* Each make-list row belongs to exactly one BOQRun.
* Through BOQRun.boq, each make-list row belongs to exactly one BOQ.
* Make-list rows are never global and are never shared across BOQs.

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

Activate

↓

Generate Embeddings

↓

Archive Previous
```

Database imports run synchronously; no Celery task is queued for database import
or database embedding generation.

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

Lowest Final Amount Rate Selection

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

# FINAL NOTES

This schema represents Version 1 and is derived from the March client workbook.

Database updates shall preserve:

* BOQ history.
* Processing history.
* Export history.

Database changes shall never invalidate previously processed BOQs.
