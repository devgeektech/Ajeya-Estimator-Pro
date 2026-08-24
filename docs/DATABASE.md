# BOQ_AI — Database Reference

Schema and import rules for PostgreSQL. Update when models or migrations change.

---

## Technology

- **PostgreSQL** — all application data
- **Chroma** — local persistent vectors at `media/chroma` (not in PostgreSQL)
- **Django ORM** — models in `apps/*/models.py`

---

## Upload History

`DatabaseVersion` tracks each master database workbook upload.

- `version_number` — monotonic display sequence
- `is_active` — only one row may be `True` (partial unique constraint)
- Retention: keep the **last 10** uploads for view/download (metadata + workbook file)
- Master sheet rows are stored in PostgreSQL **only for the active** upload;
  inactive versions keep their workbook only
- Stored file is renamed with a datetime stamp
  (`{stem}_{YYYYMMDD_HHMMSS}.xlsx`); download still uses original
  `source_filename`
- **No rollback** — new upload replaces the active database
- **Go live:** after `createsuperuser`, the Superadmin must upload a master
  workbook in the UI before any BOQ can be processed (see `docs/OPS.md` step 14)

---

## Master Workbook Sheets

Uploaded workbooks may contain many sheets. **These three are ingested** into
PostgreSQL (all required). Other sheets are counted for the database detail UI
only.

| Sheet (workbook) | Model / table | Required |
| --- | --- | --- |
| `Product_Helper` | `Product_Helper` | **Yes** |
| `Rate_Master_Output` | `Rate_Master_Output` | **Yes** |
| `Labour_Master_Output` | `Labour_master_Output` | **Yes** |

Aliases: older workbooks titled `Labour_master_Output` are still accepted;
`Product_Master` is accepted as an alias for `Product_Helper`.

**Removed (no longer imported or modeled):** `Rate_Master`, `Labour_Master`,
`TOR_Main`, `TOR_Labour`, `TOR_Accessories`, `Labour_Structure_Source`,
`State_Control_List`.

**Import rules:**

- Validate that all required sheets are present before any DB write.
- Blank / non-numeric formula placeholders (`<<`, `Base_Rate missing`, …) → `NULL`.
- All master rows carry `database_version_id`.
- Model / table names keep historical spellings; workbook sheet titles follow
  the current client file (with aliases above).
- `Product_ID` (all three sheets) and `Rate_ID` are **text** (`varchar(64)`): codes
  like `P1001` and plain numbers like `1001` are both accepted. Whole numbers
  read from Excel as `1001.0` are trimmed to `1001` so rate and labour rows stay
  linked. Rows without a `Product_ID` (plus `Category` for Product_Helper / rates)
  are skipped.
- If a required sheet has rows but **none** are importable, the import fails
  with the offending column names and nothing is activated; the previous active
  version stays intact.

### `Product_Helper`

One catalog product identity (no Make/Vendor). Key fields:

`Product_ID`, `Category`, `Sub_Category`, `Class`, `Size`, `Unit`, `Capacity`,
`Attribute`, `Status` (workbook column **I**).

- **`Product_ID`** — product identity used to load all Make/Vendor rate rows and
  labour. Analysis / Find in DB resolve BOQ extracts onto this sheet first.
- **`Status` = Discontinued** — row is **not imported**. Matching
  `Rate_Master_Output` / `Labour_Master_Output` rows for that `Product_ID` are
  also skipped. Discontinued helpers are never embedded in Chroma (import skip
  plus embed-time Status filter) and cannot appear during Analysis matching.
  Blank Status is imported; Active is preferred for matching.
- **Embeddings:** one Chroma vector per Product_Helper row (complete catalog
  fields). Search returns `Product_ID`; rates and labour load from Postgres.

### `Rate_Master_Output`

One priced Make/Vendor row. Key fields:

`Rate_ID`, `Product_ID`, `Category`, `Sub_Category`, `Class`, `Size`, `Unit`,
`Capacity`, `Attribute`, `Make`, `Vendor`, `Base_Purchase_Rate`, `Last_Updated`,
`Discount`, `Net_Material_Rate`, cost-build columns, **`Final_Material_Amount`**
(amount used by BOQ Make & Vendor / pricing), `Margin_%_on_Selling`
(→ model `Margin_pct_on_Selling`).

| Excel type (typical) | Model field type |
| --- | --- |
| `Rate_ID` / `Product_ID` int or text | `CharField(64)` |
| Category / Sub_Category / Class / Unit / Make / Vendor | `CharField` |
| `Size` number | `DecimalField(12,2)` |
| `Capacity` / `Attribute` text | `CharField` / `TextField` |
| Rate / amount columns | `DecimalField(18,2)` (`Discount` 6 dp, margin 8 dp) |
| `Last_Updated` datetime | `DateTimeField` |

- **`Product_ID`** — product identity (text); link to labour (1 labour row per
  product). Not a database FK — matched on the string value.
- **`Rate_ID`** — identity of this priced rate row (text; Make/Vendor variant).
  Internal references (`rate_master_id`, `db_product_id`) use the integer PK and
  are unaffected by the text IDs.
- UI display key (not stored as Tech_Key):  
  `Category|Sub_Category|Class|Size|Unit|Capacity|Attribute` via `product_display_key()`.
- Embeddings are **not** built from this sheet. Analysis finds Product_ID via
  Product_Helper Chroma vectors; rates/Make/Vendor load here by Product_ID.

### `Labour_Master_Output`

One labour row per `Product_ID`. Taxonomy fields plus labour charges. BOQ Auto
labour uses **`Labour_With_State_Multiplier`** / model
`Total_Labour_per_unit_with_labour_Multipler` (falls back to
`Total_Labour_Per_Unit`, then `Labour_Rate_Per_unit` when blank). Category-wise
labour % remains a Labour-page UI feature (not this sheet).

| Excel column | Model field |
| --- | --- |
| `Labour_Rate_Per_Unit` | `Labour_Rate_Per_unit` |
| `Total_Labour_Per_Unit` | `Total_Labour_per_Unit` |
| `Labour_With_State_Multiplier` | `Total_Labour_per_unit_with_labour_Multipler` |

`Attribute` is optional on this sheet (nullable in the model).

---

## BOQ Tables (current)

### `BOQ`

| Field | Notes |
| --- | --- |
| `user` | Owner |
| `boq_name` | Display name; **unique** (case-insensitive) — maps to `media/extract_json/{boq_name}/` |
| `status` | `UPLOADED`, `PROCESSING`, `EXTRACTED`, `MAKE_VENDOR`, `LABOUR`, … |
| `uploaded_file` | Original workbook |
| `make_list_file` | Optional (Excel or PDF) |
| `boq_data` | Normalized BOQ JSON (headers + hierarchical rows) |
| `make_list_data` | Normalized make-list JSON |
| `analysis_data` | AI extraction + matching + rate/labour enrichment |
| `created_at` | Timestamp |

**`boq_data` / `make_list_data` row shape (flat list, hierarchy via fields):**

| Field | Purpose |
| --- | --- |
| `row_id` | Stable id (`r{excel_row}`) |
| `serial` | Raw serial text from sheet |
| `depth` | Indent level (0 = section root) |
| `parent_row_id` | Parent row link |
| `excel_row_number` | Original worksheet row |
| `display_values` | UI-safe cell values keyed by normalized header |
| `values` | Raw parsed cell values |

---

## System Tables

- **`accounts.User`** — email auth, `role` (`SUPERADMIN` / `ADMIN` / `EXPERT`)
- **`audit.*`** — action log
- **`notifications.*`** — in-app notifications

---

## Embeddings

After each successful import, `generate_embeddings_for_version()` indexes active
`Product_Helper` rows into Chroma (one vector per helper row). Discontinued
Status and blank Product_ID rows are skipped. Rate_Master / Labour stay in
PostgreSQL and are joined by Product_ID after search.

**Embedded text fields (Product_Helper):** Product_ID, Category, Sub Category,
Class, Size, Unit, Capacity, Attribute, Status.

Taxonomy for AI extract/map comes from distinct Category / Sub_Category / Class on
`Rate_Master_Output` (`classes_by_category_sub_category` plus a deduped `classes`
list in the extract DB context). Class `0` is a real token (valves).

---

## Pricing (active rule)

For a selected rate row and its labour row (`Product_ID`):

```text
(Final_Material_Amount + Labour_With_State_Multiplier) × Qty
```

(`Labour_With_State_Multiplier` is stored as
`Total_Labour_per_unit_with_labour_Multipler`; falls back to
`Total_Labour_per_Unit`, then `Labour_Rate_Per_unit` when blank.)

Category labour % on the Labour page is applied separately in UI/config.
