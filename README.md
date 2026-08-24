# BOQ_AI

AI-assisted BOQ estimation for Fire Protection and MEP.

**Active pipeline:** master database import → BOQ upload → Analyse → Make &
Vendor → Labour → Review → Excel export.

## Stack

Django · PostgreSQL · Celery/Redis · OpenAI + Chroma · Gunicorn/Nginx (EC2) ·
Django templates + Alpine.js

## Docs

| File | Purpose |
| --- | --- |
| [`docs/PRODUCT.md`](docs/PRODUCT.md) | Product scope, architecture, code structure |
| [`docs/DATABASE.md`](docs/DATABASE.md) | Schema and import rules |
| [`docs/OPS.md`](docs/OPS.md) | Local setup and **EC2 go-live** |
| [`docs/SESSION_STATE.md`](docs/SESSION_STATE.md) | Current session status |
| [`AGENTS.md`](AGENTS.md) | Instructions for AI agents |

**Make it live:** follow [`docs/OPS.md`](docs/OPS.md) **Go live on EC2** from
step 1 through first master-database upload. A `git pull` alone is not enough.

## Quick Start (local)

Prerequisites: Python 3.12+, PostgreSQL (see [`docs/OPS.md`](docs/OPS.md)).

### Windows (PowerShell)

```powershell
git clone <repo-url> BOQ_AI
cd BOQ_AI
python -m venv .venv
.\.venv\Scripts\pip install -U pip -r requirements.txt
Copy-Item .env.example .env   # set DATABASE_URL, SECRET_KEY, OPENAI_API_KEY
cd backend
..\.venv\Scripts\python.exe manage.py migrate
..\.venv\Scripts\python.exe manage.py collectstatic --noinput
..\.venv\Scripts\python.exe manage.py createsuperuser
..\.venv\Scripts\python.exe manage.py runserver
```

### Linux / macOS

```bash
git clone <repo-url> BOQ_AI && cd BOQ_AI
python -m venv .venv && .venv/bin/pip install -U pip -r requirements.txt
cp .env.example .env   # set DATABASE_URL, SECRET_KEY, OPENAI_API_KEY
cd backend && ../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py collectstatic --noinput
../.venv/bin/python manage.py createsuperuser
../.venv/bin/python manage.py runserver
```

Sign in, **upload the master database**, then upload a BOQ. Analyse will not
match products until the master database is active.

### BOQ analysis (Celery + Redis)

**Production** (`DEBUG=False`): Redis and a Celery worker must be running;
`CELERY_TASK_ALWAYS_EAGER=False`. Confirm with `manage.py check_celery`.

**Local without Redis** — `CELERY_TASK_ALWAYS_EAGER=True` or `DEBUG=True`
(analysis runs inline).

**Local with async worker** — three terminals:

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
```

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py check_celery
```

**Linux / macOS**

```bash
cd backend && ../.venv/bin/python manage.py runserver
redis-server
./scripts/run_celery_worker.sh
cd backend && ../.venv/bin/python manage.py check_celery
```

### Tests

The suite is at repo-root `tests/` (run from `backend/`):

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py test tests --no-input
```

```bash
cd backend && ../.venv/bin/python manage.py test tests --no-input
```

## Structure

```text
backend/     Django apps, ai/, common/, utils/, gunicorn.conf.py
tests/       Django test suite (repo root)
templates/   Django HTML templates
docs/        PRODUCT, DATABASE, OPS, SESSION_STATE, CHANGELOG
media/       Runtime uploads + Chroma (gitignored)
```

Secrets live in `.env` locally and `/srv/boq_ai/.env` on EC2 — never commit them.
