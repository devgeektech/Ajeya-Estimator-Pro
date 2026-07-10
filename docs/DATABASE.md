# BOQ_AI — Database Reference

Schema and import rules for PostgreSQL. Update when models or migrations change.

---

## Technology

- **PostgreSQL** — all application data
- **Chroma** — local persistent vectors at `media/chroma` (not in PostgreSQL)
- **Django ORM** — models in `apps/*/models.py`

---

## Upload History

`DatabaseVersion` tracks each master workbook upload.

- `version_number` — monotonic display sequence
- `is_active` — only one row may be `True` (partial unique constraint)
- Retention: keep the **last 10** uploads for view/download; older rows deleted on import
- **No rollback** — archived uploads are read-only (view + download workbook)

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
- Model and table names match workbook sheet names exactly.

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

After each successful import, `generate_embeddings_for_version()` in
`ai/embeddings/generator.py` indexes active `Rate_Master` rows into Chroma.

**Embedded text fields** (structured `Label: value` lines):

Category, Sub Category, Class, Size, Make, Capacity, Unit, Attribute, Supplier,
Tech_Key

**Metadata** mirrors the same fields plus `rate_master_id` and
`database_version_id` for resolving hits back to PostgreSQL.

Only the **active** database has embeddings; the Chroma collection is cleared
before each import indexes the new active rows.

---

## Migrations

Fresh initial migrations (2026-07-10 reset). Each app has a single `0001_initial`:

| App | Migration |
| --- | --- |
| `accounts` | `0001_initial` — `User` |
| `audit` | `0001_initial` — `AuditLog` |
| `boq` | `0001_initial` — `BOQ` |
| `database_manager` | `0001_initial` — `DatabaseVersion` + 7 master tables |
| `notifications` | `0001_initial` — `Notification` |

Apply with:

```bash
cd backend
../.venv/bin/python manage.py migrate
```

On a **new PostgreSQL database** (especially PG 15+), grant schema access before
the first migrate:

```sql
GRANT ALL ON SCHEMA public TO boq_user;
GRANT CREATE ON SCHEMA public TO boq_user;
ALTER DATABASE boq_db OWNER TO boq_user;
```
