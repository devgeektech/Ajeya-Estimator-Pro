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
| BOQ parsing, processing, matching, review, export | Removed — rebuild pending |

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
- On upload, rows are normalized by serial number (`1`, `1.1`, `a`, `(a)`, etc.)
  into JSON (`boq_data`, `make_list_data`) while preserving hierarchy for UI,
  AI extraction, and future priced export.
- View page shows **BOQ** and **Make List** tabs with indented sheet layout.

Entry point: `BOQCreationService` in `apps/boq/services/boq_service.py`.

---

## Business Rules (stable)

- **No recalculation** of client workbook formulas — read precomputed values from
  `Rate_Master` / `Labour_Master` when the pipeline returns.
- **Human review** required before final export (when rebuilt).
- **Confidence below 30%** → no auto product selection; pending product flow
  (when rebuilt).
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

Celery + Redis are configured for future background jobs; no BOQ tasks are
registered today.

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
│   ├── ai/               # service, context, embeddings, prompts/
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
| `ai/context.py` | Active DB taxonomy for AI prompts |
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
- OpenAI default chat model: `gpt-5-mini` (no custom temperature on GPT-5/o-series).
- Embeddings: `text-embedding-3-small` → Chroma at `media/chroma`.
- See `docs/OPS.md` for setup and deployment commands.
