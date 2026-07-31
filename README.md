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

Prerequisites: Python 3.11+, PostgreSQL (see [`docs/OPS.md`](docs/OPS.md) for DB
setup), then clone and configure `.env` with `DATABASE_URL` and `SECRET_KEY`.

### Windows (PowerShell)

```powershell
git clone <repo-url> BOQ_AI
cd BOQ_AI
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env   # set DATABASE_URL and SECRET_KEY
cd backend
..\.venv\Scripts\python.exe manage.py migrate
..\.venv\Scripts\python.exe manage.py collectstatic --noinput
..\.venv\Scripts\python.exe manage.py createsuperuser
..\.venv\Scripts\python.exe manage.py runserver
```

### Linux / macOS

```bash
git clone <repo-url> BOQ_AI && cd BOQ_AI
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # set DATABASE_URL and SECRET_KEY
cd backend && ../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py collectstatic --noinput
../.venv/bin/python manage.py createsuperuser
../.venv/bin/python manage.py runserver
```

### BOQ analysis (Celery + Redis)

BOQ analysis runs in the background via Celery. **Production** (`DEBUG=False`):
Redis and a Celery worker must be running; set `CELERY_TASK_ALWAYS_EAGER=False`.

**Local dev without Redis** — set `CELERY_TASK_ALWAYS_EAGER=True` or `DEBUG=True`
(analysis runs inline in the web process).

**Local dev with async worker** — three terminals:

**Windows (PowerShell)**

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

```powershell
# Verify readiness
cd backend
..\.venv\Scripts\python.exe manage.py check_celery
```

**Linux / macOS**

```bash
# 1 — Django
cd backend && ../.venv/bin/python manage.py runserver

# 2 — Redis
redis-server

# 3 — Celery worker
./scripts/run_celery_worker.sh
```

```bash
# Verify readiness
cd backend && ../.venv/bin/python manage.py check_celery
```

The BOQ detail page polls `/boqs/<id>/status/` while analysis is running and reloads
when complete.

**Tests**

```powershell
# Windows
cd backend
..\.venv\Scripts\python.exe manage.py test tests
```

```bash
# Linux / macOS
cd backend && ../.venv/bin/python manage.py test tests
```

Full setup and production deploy: [`docs/OPS.md`](docs/OPS.md).

## Structure

```text
backend/     Django apps, ai/, common/, utils/, tests/
templates/   Django HTML templates
docs/        PRODUCT, DATABASE, OPS, SESSION_STATE, CHANGELOG
media/       Runtime uploads (gitignored)
```

Secrets live in `.env` locally and `/srv/boq_ai/.env` on EC2 — never commit them.
