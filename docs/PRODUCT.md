# BOQ_AI — Product & Technical Reference

Single source of truth for what the system does, how it is built, and the rules
agents and developers must follow. Update this file when product scope, structure,
or architecture changes.

---

## Overview

BOQ_AI is an AI-assisted BOQ estimation platform for Fire Protection and MEP
work. It imports a client master workbook, stores uploaded BOQ files, and will
rebuild processing (matching, review, export) on a fresh design.

**Current scope (2026-07-10):**

| Feature | Status |
| --- | --- |
| User auth, roles, dashboard | Active |
| Master database upload / history / embeddings | Active |
| Product embeddings (Chroma) after DB import | Active |
| BOQ workbook + make-list upload | Active |
| BOQ parsing, processing, matching, review, export | Phase 1–2 active (analysis, review, export); pending-products flow pending |

**Planned BOQ pipeline (not implemented):** parse workbook → AI extraction →
product matching → rate/labour retrieval → expert review → Excel export.

---

## Users & Roles

| Role | Access |
| --- | --- |
| **Superadmin** | Full access; user management; database management; sees all BOQs |
| **Admin** | User management; database management |
| **Expert** | Upload BOQs; database access only when granted |

Authentication: email login, password reset, no public registration. Users are
created by admins.

---

## Active Workflows

### Master database import

```text
Upload workbook → Validate → Import sheets → Activate version → Generate embeddings
```

- Runs **synchronously** in the upload request (no Celery).
- Only `Rate_Master` is required; other master sheets are optional if absent.
- Exactly **one** active `DatabaseVersion` at a time; Chroma holds embeddings for
  the active database only.
- Last **10** uploads remain visible for view/download (metadata + workbook file).
- Master sheet rows are stored in PostgreSQL only for the **active** upload.
- No rollback — new upload replaces the active database.
- Embeddings skip cleanly when OpenAI is not configured.

Entry point: `DatabaseImportService` in `apps/database_manager/services/importer.py`.
Views call the service directly (thin views).

### BOQ upload

```text
Upload BOQ (+ optional make list) → parse to JSON → store files + hierarchy
```

- BOQ workbook: `.xlsx` / `.xlsm`
- Make list: `.xlsx`, `.xlsm`, or `.pdf`
- **BOQ name must be unique** (case-insensitive) so each upload gets its own
  `media/extract_json/{boq_name}/` folder.
- On upload, rows are normalized by serial number (`1`, `1.1`, `a`, `(a)`, etc.)
  into JSON (`boq_data`, `make_list_data`) while preserving hierarchy for UI,
  AI extraction, and future priced export.
- Normalized JSON is also written to `media/extract_json/{boq_name}/` as
  `boq_data.json` and `make_list_data.json` for downstream AI analysis.
- View page shows **BOQ** and **Make List** tabs with indented sheet layout.

Entry point: `BOQCreationService` in `apps/boq/services/boq_service.py`.

### BOQ analysis — two-step workflow

```text
Step 1 — Analyse:  rows_tree → AI extraction → extracted products/activities (detail page)
Step 2 — Match:    extracted products → DB matching → rates/labour (match results page)
```

**Step 1 — Analyse** (BOQ detail → **Analysis** tab):

- Button: **Analyse** → `POST /boqs/<id>/extract/` via `dispatch_boq_extraction`
- Celery task: `boq.process_extraction`
- Status: `PROCESSING` → `EXTRACTED`
- Shows extracted products and activities in upload row order (no DB matching yet)
- **Interactive review:** users can edit extracted product fields (category, size,
  capacity, attributes, etc.) and select a preferred make from the make list when
  a make-list line matches the BOQ description. Saves via
  `POST /boqs/<id>/extraction/edit/` (`BOQExtractionEditService`). Missing fields
  are highlighted; edits persist in `analysis_data` before **Match** runs.

**Step 2 — Match** (BOQ detail → **Match** button → new page):

- Button: **Match** → `POST /boqs/<id>/match/` → redirect to `/boqs/<id>/match-results/`
- Celery task: `boq.process_matching`
- Status: `PROCESSING` → `PROCESSED`
- Match results page: rates, labour, confirm, export

Poll `GET /boqs/<id>/status/?expect=extract|match` while `PROCESSING`.

**Output:** `media/extract_json/{boq_name}/boq_analysis.json` plus `BOQ.analysis_data`
JSONField (`phase`: `extracted` | `matched`). After matching, a dedicated
`boq_match_results.json` in the same folder stores full `product_matches` snapshots
(candidates, scores, rate/labour enrichment) for internal tracking even when the
live analysis is edited before re-match.

**Services:**

| Service | Role |
| --- | --- |
| `BOQExtractionService` | AI multi-product extraction from `rows_tree` |
| `ProductMatchingService` | Chroma recall + structured `Rate_Master` scoring |
| `MakeListConstraintService` | Map BOQ lines to `approved_makes_list`; hard Make filter |
| `BOQAnalysisService` | Orchestrator |
| `utils/attribute_parser.py` | Parse/normalize dynamic `Attribute` key-value text |

**Input:** `boq_data.json` → `rows_tree` (`fields` per row).

**Decisions (2026-07-13):**

| Topic | Decision |
| --- | --- |
| Products per BOQ row | **Multiple** — one row may yield several extracted products |
| Make list constraint | **Hard filter** when a make-list material maps to the row |
| Section rows | **Skip matching** (context only) when depth 0 / no qty |
| Attribute keys | **Learn aliases from DB** over time; normalize `Attribute` text in code |
| Matching | **Structured product match** on `Rate_Master` columns + attributes, not vector/text alone |

**Make list:** slash-separated makes (`TATA/JINDAL/SURYA`) are split into
`approved_makes_list` on each row at parse time.

**Matching layer (three passes):**

1. **Retrieval** — Chroma narrows candidates from description (recall).
2. **Structured scoring** — rank by Category, Sub_Category, Class, Size, Unit, Make,
   and parsed Attribute key-value overlap (precision).
3. **Make list filter** — drop candidates whose `Make` is not in `approved_makes_list`
   when the row maps to a make-list material.

Confidence &lt; 30% → pending product, no auto selection. AI extracts only; services
match and filter.

### BOQ analysis phase 2 — enrichment, confirmation, export

```text
matched products → rate + labour lookup → line output → session confirm → Excel export
```

**After phase 1 matching:**

1. `RateDetailRetrievalService` — read precomputed `Rate_Master` values for selected product.
2. `LabourDetailRetrievalService` — link labour via `Tech_Key` (size-aware when possible).
3. `BOQLineOutputService` — qty × per-unit material/labour from master DB (no formula
   recalculation).
4. `BOQAnalysisDisplayService` — shapes rows for the **Analysis** tab.

**Expert confirmation (session only):**

- Any logged-in user with access to the BOQ can **Confirm** lines on the Analysis tab.
- Confirmations are stored in the **user session only** — not written to PostgreSQL.
- Pending lines require picking a candidate product before confirm; matched lines confirm the auto-selection.
- Re-running analysis does not clear session confirmations (user may undo per line).

**Labour charges:** `LabourDetailRetrievalService` links `Rate_Master.Tech_Key` → `Labour_Master`
rows (size-aware when multiple rows share a key). Per-unit labour uses precomputed workbook columns:
`Total_Labour_per_unit_with_labour_Multipler` → `Total_Labour_per_Unit` → `Labour_Rate_Per_unit`.
Component breakdown (testing, scaffolding, consumables, painting, buffer) is exposed for export.

**Export:** `BOQExportService` → Excel download; applies session confirmations when present.

## Business Rules (stable)

- **No recalculation** of client workbook formulas — read precomputed values from
  `Rate_Master` / `Labour_Master` when the pipeline returns.
- **Session confirmation** on the Analysis tab before export (not stored in PostgreSQL).
- **Confidence below 30%** → no auto product selection; user must pick a candidate and confirm.
- **AI** may understand descriptions, extract products/activities, validate matches.
  AI must **not** calculate costs, profits, select suppliers, or set pricing.
- Do **not** use deprecated `match_key` / `source_key` for matching or imports.
- Use **`Tech_Key`** for labour linkage; it is indexed but not globally unique
  (multi-supplier variants).

---

## Architecture

```text
Browser → Django (templates + HTMX) → Services → PostgreSQL
                                      ↘ AI (OpenAI) + Chroma (embeddings)
```

| Layer | Location | Responsibility |
| --- | --- | --- |
| Views | `apps/*/views.py` | HTTP, forms, redirects — **no business logic** |
| Services | `apps/*/services/` | All business logic |
| Models | `apps/*/models.py` | Data shape only |
| Templates | `templates/` | Presentation only |
| AI | `backend/ai/` | Prompts, context, embeddings |
| Shared Django | `backend/common/` | Choices, exceptions, middleware, mixins |
| Helpers | `backend/utils/` | Excel, text, files — no Django models |

Celery + Redis are configured; BOQ analysis runs via `apps/boq/tasks.py`
(`process_boq_analysis_task`).

---

## Code Structure

```text
BOQ_AI/
├── backend/
│   ├── config/           # settings, urls, celery, wsgi
│   ├── apps/
│   │   ├── accounts/     # auth, sessions
│   │   ├── users/        # user CRUD
│   │   ├── database_manager/  # master DB import, versioning
│   │   ├── boq/          # BOQ upload only
│   │   ├── dashboard/
│   │   ├── notifications/
│   │   └── audit/
│   ├── ai/               # OpenAI client + Chroma embeddings
│   ├── common/           # choices, constants, exceptions, middleware, mixins
│   ├── utils/            # excel, text, files
│   └── tests/
├── templates/
├── static/
├── media/                # uploads, chroma index (gitignored)
├── docs/
├── requirements.txt
└── .env
```

**Removed (2026-07-10):** `workflows/`, `tasks/`, `exports/`, `ai/extractors/`, and Django apps
`processing`, `matching`, `costing`, `review`, `exports`, `make_list`, `pending_products`.

---

## Key Files

| Path | Purpose |
| --- | --- |
| `apps/database_manager/services/importer.py` | Master DB import |
| `apps/database_manager/services/activation.py` | Single active upload |
| `apps/database_manager/views.py` | DB upload UI |
| `apps/boq/services/boq_service.py` | BOQ file persistence |
| `apps/boq/services/boq_analysis_service.py` | Analysis orchestrator |
| `apps/boq/services/rate_detail_retrieval_service.py` | Rate_Master snapshot by id |
| `apps/boq/services/labour_detail_retrieval_service.py` | Labour_Master by Tech_Key |
| `apps/boq/services/boq_export_service.py` | Excel export |
| `ai/openai_client.py` | OpenAI client + API key check |
| `ai/embeddings/` | Chroma product index |
| `config/settings.py` | Single settings module |

---

## Development Rules

**Do:**

- Small, isolated changes; logic in services.
- Update `docs/SESSION_STATE.md` and `docs/CHANGELOG.md` each session.
- Update `docs/PRODUCT.md` when scope/structure changes; `docs/DATABASE.md` when
  models change; `docs/OPS.md` when run/deploy steps change.

**Do not:**

- Put business logic in views or templates.
- Call OpenAI from views.
- Modify the database outside services/migrations.
- Commit secrets, `.env`, logs, or `media/` uploads.

**Tests:** `cd backend && ../.venv/Scripts/python manage.py test tests`

---

## Runtime

- Settings: `config.settings` (PostgreSQL only in production).
- Local `.env` at project root; production `/srv/boq_ai/.env`.
- OpenAI default chat model: `gpt-4o-mini` (temperature 0 for deterministic extraction).
- Embeddings: `text-embedding-3-small` → Chroma at `media/chroma`.
- See `docs/OPS.md` for setup and deployment commands.
