# BOQ_AI — Database Reference

Schema and import rules for PostgreSQL. Update when models or migrations change.

---

## Technology

- **PostgreSQL** — all application data
- **Chroma** — local persistent vectors at `media/chroma` (not in PostgreSQL)
- **Django ORM** — models in `apps/*/models.py`

---

## Versioning

`DatabaseVersion` tracks each master workbook upload.

- `version_number` — monotonic integer
- `is_active` — only one row may be `True` (partial unique constraint)
- Retention: keep **active + 2** prior versions; older rows are deleted on import
- Rollback reactivates a prior version via `DatabaseRollbackService`

---

## Master Workbook Sheets

Imported into versioned tables (PascalCase ORM fields mirror workbook columns).

| Sheet | Model | Required |
| --- | --- | --- |
| `Rate_Master` | `Rate_Master` | **Yes** |
| `Labour_Master` | `Labour_Master` | No |
| `TOR_Main` | `TOR_Main` | No |
| `Labour_Structure_Source` | `Labour_Structure_Source` | No |
| `TOR_Labour` | `TOR_Labour` | No |
| `TOR_Accessories` | `TOR_Accessories` | No |
| `State_Control_List` | `State_Control_List` | No |

**Import rules:**

- Validate structure before any DB write.
- Blank cells → `NULL` (not empty string / zero).
- Skip optional sheets not present in the workbook.
- All master rows carry `database_version_id`.
- Workflow aliases exist on models (`MaterialRate`, `LabourMaster`, etc.) plus
  snake_case property aliases for services.

**Key fields on `Rate_Master`:** `Category`, `Sub_Category`, `Class`, `Size`,
`Make`, `Capacity`, `Unit`, `Attribute`, `Supplier`, `Tech_Key`, rate columns
(`Base_Purchase_Rate`, `Net_Material_Rate`, `Final_Amount_(Excl GST)`, etc.).

**`Tech_Key`:** indexed, links to `Labour_Master`; not globally unique.

---

## BOQ Tables (current)

### `BOQ`

| Field | Notes |
| --- | --- |
| `user` | Owner |
| `boq_name` | Display name |
| `status` | `UPLOADED` only (for now) |
| `uploaded_file` | Original workbook |
| `make_list_file` | Optional |
| `created_at` | Timestamp |

`BOQRun`, `BOQItem`, `ProductMatch`, and related pipeline tables were dropped
in migration `boq.0003` and `database_manager.0010`.

---

## System Tables

- **`accounts.User`** — email auth, `role` (`SUPERADMIN` / `ADMIN` / `EXPERT`)
- **`audit.*`** — action log
- **`notifications.*`** — in-app notifications

---

## Embeddings

After each successful import, `generate_embeddings_for_version()` indexes active
`Rate_Master` rows into Chroma using product/spec text fields. Rebuild by
re-importing the master workbook or running the management command in
`ai/embeddings/generate_database_embeddings.py`.

---

## Migrations

Apply with:

```bash
cd backend
../.venv/bin/python manage.py migrate
```

Notable recent migrations:

- `database_manager.0009` — nullable master fields
- `database_manager.0010` — prune removed pipeline app tables
- `boq.0003` — remove `BOQRun` / `BOQItem`
