# BOQ_AI

AI-assisted BOQ estimation for Fire Protection and MEP. **Currently active:**
master database import and BOQ file upload. Processing, matching, review, and
export are being rebuilt.

## Stack

Django · PostgreSQL · HTMX · Celery/Redis (reserved) · OpenAI + Chroma (optional)

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
