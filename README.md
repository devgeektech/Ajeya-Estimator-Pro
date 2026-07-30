# BOQ_AI

AI-assisted BOQ estimation for Fire Protection and MEP. **Currently active:**
master database import and BOQ file upload. Processing, matching, review, and
export are being rebuilt.

## Stack

Django · PostgreSQL · HTMX · Celery/Redis · OpenAI + Chroma (optional)

## Docs

| File | Purpose |
| --- | --- |
| [`docs/PRODUCT.md`](docs/PRODUCT.md) | Product scope, architecture, code structure |
| [`docs/DATABASE.md`](docs/DATABASE.md) | Schema and import rules |
| [`docs/OPS.md`](docs/OPS.md) | Local setup and EC2 deployment |
| [`docs/SESSION_STATE.md`](docs/SESSION_STATE.md) | Current session status |
| [`AGENTS.md`](AGENTS.md) | Instructions for AI agents |

## Quick Start

```bash
git clone <repo-url> BOQ_AI && cd BOQ_AI
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # set DATABASE_URL and SECRET_KEY
cd backend && ../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py createsuperuser
../.venv/bin/python manage.py runserver
```

### BOQ analysis (Celery + Redis)

BOQ analysis runs in the background via Celery. **Production** (`DEBUG=False`):
Redis and a Celery worker must be running; set `CELERY_TASK_ALWAYS_EAGER=False`.

**Local dev without Redis** — set `CELERY_TASK_ALWAYS_EAGER=True` or `DEBUG=True`
(analysis runs inline in the web process).

**Local dev with async worker** — three terminals:

```powershell
# 1 — Django
cd backend
..\.venv\Scripts\python.exe manage.py runserver

# 2 — Redis (WSL or native install)
redis-server
# or: .\scripts\run_redis.ps1

# 3 — Celery worker
.\scripts\run_celery_worker.ps1
# or: cd backend && ..\.venv\Scripts\python.exe -m celery -A config worker --loglevel=info --pool=solo
```

Verify readiness:

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py check_celery
```

Linux / macOS: use `scripts/run_celery_worker.sh` instead of the `.ps1` script.

The BOQ detail page polls `/boqs/<id>/status/` while analysis is running and reloads
when complete.

Tests: `../.venv/bin/python manage.py test tests`

Full setup and production deploy: [`docs/OPS.md`](docs/OPS.md).

## Structure

```text
backend/     Django apps, ai/, common/, utils/, tests/
templates/   Django HTML templates
docs/        PRODUCT, DATABASE, OPS, SESSION_STATE, CHANGELOG
media/       Runtime uploads (gitignored)
```

Secrets live in `.env` locally and `/srv/boq_ai/.env` on EC2 — never commit them.
