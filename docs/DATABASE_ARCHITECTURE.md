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

* Chroma local persistent vector index

ORM:

* Django ORM

Migration baseline:

* Application migrations are a fresh model-aligned `0001_initial` baseline.
* Historical app migration files were intentionally removed during the July 8,
  2026 cleanup after the schema was restructured.
* Existing non-empty PostgreSQL databases must not apply this baseline as a
  normal incremental migration. Reset the database, restore into a compatible
  clean schema, or use a reviewed `--fake-initial` deployment plan.

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
* Two previous archived versions for rollback

---

# MASTER TABLES

---

## RateMaster

Source:

Rate_Master sheet.

Fields:

* id
* database_version
* category
* sub_category
* product_class (`class` column)
* size_mm
* make
* capacity
* unit
* height
* working_pressure
* test_pressure
* temperature
* throw_distance
* k_factor
* head
* supplier
* base_purchase_rate
* discount_percent
* net_material_rate
* accessories_percent
* handling_percent
* wastage_percent
* profit_percent
* tech_key
* status
* last_updated
* procurement_percent
* procurement_value
* commercial_material_base
* accessories_value
* handling_value
* wastage_value
* subtotal_before_profit
* profit_value
* final_expenditure
* final_amount_excl_gst
* margin_percent_on_selling

Import:

* `Tech_Key` is stored directly and indexed for Rate_Master to Labour_Master
  retrieval.
* If no key is supplied, the importer synthesizes a stable code from category,
  sub_category, class, and size.
* `Net Material Rate` populates `net_material_rate`.
* `Final_Amount_(Excl GST)` is stored as `final_amount_excl_gst` and remains
  the rate-selection amount.
* Blank or structurally incomplete master rows are skipped instead of creating
  empty product records.
* Deprecated lookup keys are not part of the active schema or matching
  workflow.

---

## LabourMaster

Source:

Labour_Master sheet.

Fields:

* id
* database_version
* tech_key
* state
* category
* sub_category
* size
* unit
* labour_type
* base_rate
* size_factor
* labour_rate_per_unit
* testing_percent
* scaffolding_percent
* consumables_percent
* painting_rate
* testing_labour_value
* scaffolding_labour_value
* consumables_labour_value
* painting_labour_value
* labour_buffer_percent
* labour_buffer_value
* total_labour_per_unit
* labour_multiplier
* total_labour_with_multiplier

---

## TORMain

Source:

TOR_Main.

Fields:

* id
* database_version
* category
* handling_percent
* wastage_percent
* profit_percent
* procurement_percent
* risk_buffer_percent
* project_state

---

## LabourStructureSource

Source:

Labour_Structure_Source.

Fields:

* id
* database_version
* category
* sub_category
* size
* unit
* tech_key

---

## TORLabour

Source:

TOR_Labour.

Fields:

* id
* database_version
* testing_percent
* scaffolding_percent
* consumables_percent
* painting_rate
* labour_buffer_percent

---

## TORAccessories

Source:

TOR_Accessories.

Fields:

* id
* database_version
* category
* sub_category
* min_size
* max_size
* accessories_percent

---

## StateControl

Source:

State_Control_List.

Fields:

* id
* state
* labour_multiplier

Import:

* `State` is stored as `state`.
* State control affects labour multiplier only in the active schema.

---

# MASTER RELATIONSHIPS

```text
RateMaster.tech_key
    -> LabourMaster.tech_key

RateMaster(category, sub_category, size_mm, unit)
    -> LabourStructureSource(category, sub_category, size, unit)
    -> LabourMaster.tech_key

RateMaster.category
    -> TORMain.category

RateMaster(category, sub_category, size_mm)
    -> TORAccessories(category, sub_category, min_size, max_size)

LabourMaster.state
    -> StateControl.state
```

Rate selection still chooses the matched RateMaster row with the lowest
`final_amount_excl_gst`.

The selected RateMaster row is the source of precomputed material, commercial,
supplier, make, and final amount values. The selected row's `tech_key` links to
LabourMaster so the system can retrieve corresponding precomputed labour charge
details. TOR and StateControl tables are imported for reference, traceability,
and future approved rules, but the active pipeline does not recalculate workbook
costing formulas from them.

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
* tech_key

---

## ProductEmbedding

Purpose:

Audit record for Rate_Master rows indexed in the local Chroma vector store.
Chroma stores the vectors; PostgreSQL remains the source of truth.

Fields:

* id
* tech_key
* database_version_id
* rate_master_id
* chroma_id
* embedding_model
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
* target_excel_row
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
* `target_excel_row` identifies the original workbook row where Rate and Amount
  output should be written during client export.

AI extraction:

* `ai_extraction` stores `database_products[]`, `missing_products[]`, and
  `activities[]` extracted from `row_json`.
* One BOQItem can contain multiple product/equipment/component candidates.
* Product candidates use product_name plus database-shaped fields: category,
  sub_category, class, size_mm, make, capacity, unit, height, working_pressure,
  test_pressure, temperature, throw, k_factor, head, supplier,
  product_quantity, product_unit, quantity_basis, and quantity_source.
* Duplicate extracted product candidates are removed before storage.
* AI may initially classify candidates into `database_products[]` and
  `missing_products[]` using compact active database context. PostgreSQL
  matching is authoritative and may update the final split with matched product
  details or pending-product metadata.
* AI extraction requests are batched by grouped BOQ item id. The provider
  returns row_id-keyed extraction objects, and each BOQItem still stores only
  its own extraction result.
* Active database context used for AI extraction is cached by DatabaseVersion;
  uploading and activating a new database version naturally uses a new cache
  key.
* Runtime row extraction logs store one `source_row` object and one
  `extraction` object with `database_products[]`, `missing_products[]`, and
  `activities[]`.
* Activity extraction is shaped toward Labour_Master and TOR_Labour terminology.

Quantity rules:

* BOQItem unit/quantity are client billing/export values.
* Product candidate product_quantity/product_unit are component values.
* `quantity_basis` is `per_boq_unit`, `total_for_boq_row`, or `unknown`.
* `unknown` quantity basis requires review before confident client export.

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
* supplier
* extraction_index
* match_type
* product_quantity
* product_unit
* quantity_basis
* quantity_source
* review_required

Rules:

* One BOQItem may have multiple ProductMatch rows.
* `extraction_index` points to the matching product/equipment/component object
  in `BOQItem.ai_extraction.database_products[]` or
  `BOQItem.ai_extraction.missing_products[]`.
* Confidence and breakdown rows are evaluated per ProductMatch.
* Low-confidence or unresolved candidates are visible in the Breakdown List and
  routed to pending product review when required.

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

# RATE AND LABOUR DETAIL TABLES

---

## RateDetail

Purpose:

Store selected/imported Rate_Master output values and linked Labour_Master
details for a matched product. This record is retrieval output for review and
export, not a costing calculator.

Fields:

* product_match
* labour_master_id
* tech_key
* make
* supplier
* base_purchase_rate
* discount_percent
* net_material_rate
* commercial_material_base
* accessories_value
* handling_value
* wastage_value
* subtotal_before_profit
* profit_value
* final_expenditure
* final_amount_excl_gst
* margin_percent_on_selling
* labour_type
* labour_state
* labour_rate_per_unit
* total_labour_per_unit
* total_labour_with_multiplier
* rate_contribution

Rules:

* Values are copied from the selected RateMaster and linked LabourMaster rows as
  required by the active export/review workflow.
* The application does not calculate material, labour, transportation,
  accessory, overhead, profit, commercial percentage, supplier-selection, or
  final-rate values.
* `rate_contribution` is an export allocation helper derived from the selected
  imported final amount and the extracted product quantity basis. Unknown
  quantity basis or review-required matches must not produce client pricing.
* Any future derived field requires a documented, human-approved business rule.

---

# REVIEW TABLES

---

## ReviewItem

Purpose:

Expert changes.

Fields:

* original_product
* revised_product
* original_supplier
* revised_supplier
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

AI Extraction Into database_products/missing_products/activities

↓

Matching

↓

Lowest Final Amount Rate Selection

↓

Rate And Labour Detail Retrieval

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
* Supplier selection
* Overheads

Embeddings are generated after successful database upload/import and activation
so the search index matches the active DatabaseVersion. PostgreSQL remains the
source of truth; Chroma is a rebuildable product lookup index.

Embedding text is built from Rate_Master product/specification fields such as
category, sub_category, class, size_mm, make, capacity, unit, supplier, and
other descriptive technical columns. Deprecated lookup keys are not used.

---

# SEARCH STRATEGY

Priority:

1. Exact Match
2. Alias Match
3. Chroma vector similarity search
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
* Two previous archived database versions for rollback.

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
