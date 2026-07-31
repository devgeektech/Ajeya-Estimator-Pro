# BOQ_AI — Operations

Local development, testing, and EC2 deployment. Update when infrastructure or
commands change.

---

## Environment

| Item | Value |
| --- | --- |
| EC2 host | `13.205.90.58` (ap-south-1) |
| App path | `/srv/boq_ai` |
| Database | PostgreSQL `boq_db` / user `boq_user` on `localhost` |
| Settings | `config.settings` |
| Secrets | `.env` locally; `/srv/boq_ai/.env` on server — never commit |

---

## Local Setup

### 1. PostgreSQL

```sql
CREATE USER boq_user WITH PASSWORD 'localpass' CREATEDB;
CREATE DATABASE boq_db OWNER boq_user;
GRANT ALL PRIVILEGES ON DATABASE boq_db TO boq_user;
\c boq_db
GRANT ALL ON SCHEMA public TO boq_user;
GRANT CREATE ON SCHEMA public TO boq_user;
```

`CREATEDB` is required for the test suite. PostgreSQL 15+ restricts `public`
schema creation — the `\c` block above is required before the first `migrate`.

### 2. Python environment

**Windows (PowerShell)**

```powershell
git clone <repo-url> BOQ_AI
cd BOQ_AI
python -m venv .venv
.\.venv\Scripts\pip install -U pip -r requirements.txt
Copy-Item .env.example .env
```

**Linux / macOS**

```bash
git clone <repo-url> BOQ_AI && cd BOQ_AI
python -m venv .venv
.venv/bin/pip install -U pip -r requirements.txt
cp .env.example .env
```

Minimum `.env`:

```ini
DEBUG=True
DJANGO_SETTINGS_MODULE=config.settings
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=postgres://boq_user:localpass@localhost:5432/boq_db
SECRET_KEY=<generate-with-django-get_random_secret_key>
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

### 3. Migrate and run

**Windows (PowerShell)**

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py migrate
..\.venv\Scripts\python.exe manage.py collectstatic --noinput
..\.venv\Scripts\python.exe manage.py createsuperuser
..\.venv\Scripts\python.exe manage.py runserver
```

**Linux / macOS**

```bash
cd backend
../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py collectstatic --noinput
../.venv/bin/python manage.py createsuperuser
../.venv/bin/python manage.py runserver
```

### 4. Tests

**Windows (PowerShell)**

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py check
..\.venv\Scripts\python.exe manage.py test tests --no-input
```

**Linux / macOS**

```bash
cd backend
../.venv/bin/python manage.py check
../.venv/bin/python manage.py test tests --no-input
```

### 5. Redis / Celery (BOQ analysis)

BOQ analysis uses Celery. In production (`DEBUG=False`), Redis and the Celery worker
are required. Check readiness:

**Windows:** `..\.venv\Scripts\python.exe manage.py check_celery`  
**Linux / macOS:** `../.venv/bin/python manage.py check_celery`

**Option A — inline analysis (no Redis/worker):**

```env
DEBUG=True
CELERY_TASK_ALWAYS_EAGER=True
```

**Option B — async analysis (matches production):**

Terminal 1 — Django:

```powershell
# Windows
cd backend
..\.venv\Scripts\python.exe manage.py runserver
```

```bash
# Linux / macOS
cd backend
../.venv/bin/python manage.py runserver
```

Terminal 2 — Redis:

```bash
redis-server
```

On Windows without native Redis, use WSL: `wsl redis-server` or `scripts/run_redis.ps1`.

Terminal 3 — Celery worker:

```powershell
# Windows
.\scripts\run_celery_worker.ps1
```

```bash
# Linux / macOS
./scripts/run_celery_worker.sh
```


Default worker concurrency is **8** (up to 8 BOQs analysing at once). Override:

```powershell
$env:CELERY_WORKER_CONCURRENCY = "12"
.\scripts\run_celery_worker.ps1
```

If progress stops updating for 5+ minutes while status is `PROCESSING`, the status
endpoint marks the BOQ failed so Analyse can be started again.

The BOQ detail page polls `GET /boqs/<id>/status/` while status is `PROCESSING` and
reloads when analysis completes or fails.

Production `.env` on EC2:

```env
DEBUG=False
CELERY_TASK_ALWAYS_EAGER=False
REDIS_URL=redis://localhost:6379/0
```

---

## Deploy Checklist

Before deploying:

- [ ] Scoped change only; no secrets in git
- [ ] `manage.py check` passes
- [ ] `manage.py test tests` passes
- [ ] Migrations committed if models changed
- [ ] `SESSION_STATE.md` and `CHANGELOG.md` updated

On EC2 after `git pull`:

```bash
cd /srv/boq_ai
sudo -u boq_ai .venv/bin/pip install -r requirements.txt
cd backend
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py check'
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py migrate'
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py collectstatic --noinput'
sudo systemctl restart boq_ai-gunicorn boq_ai-celery
```

Verify:

```bash
systemctl status boq_ai-gunicorn boq_ai-celery redis-server
curl -I http://13.205.90.58/
```

---

## First-Time EC2 Setup

```bash
sudo apt update
sudo apt install -y python3-venv python3-dev build-essential postgresql postgresql-contrib redis-server nginx git
sudo useradd --system --create-home --shell /usr/sbin/nologin boq_ai
sudo mkdir -p /srv/boq_ai && sudo chown boq_ai:www-data /srv/boq_ai
sudo -u boq_ai git clone <repo-url> /srv/boq_ai
cd /srv/boq_ai
sudo -u boq_ai python3 -m venv .venv
sudo -u boq_ai .venv/bin/pip install -U pip -r requirements.txt
```

PostgreSQL:

```sql
CREATE USER boq_user WITH PASSWORD '<strong-password>';
CREATE DATABASE boq_db OWNER boq_user;
GRANT ALL PRIVILEGES ON DATABASE boq_db TO boq_user;
```

Production `.env` (`chmod 600`):

```ini
SECRET_KEY=<generated>
DEBUG=False
DJANGO_SETTINGS_MODULE=config.settings
ALLOWED_HOSTS=13.205.90.58
DATABASE_URL=postgres://boq_user:<password>@localhost:5432/boq_db
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
OPENAI_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
# Full prompt/response dumps to logs/instructions.log (set False in production)
AI_INSTRUCTION_LOGGING=True
# Sections per extract_products call / products per map_product_match call
AI_ROW_EXTRACTION_BATCH_SIZE=5
AI_PRODUCT_MAPPING_BATCH_SIZE=4
CHROMA_PATH=media/chroma
CHROMA_COLLECTION=rate_master_products
```

Generate secret:

```bash
/srv/boq_ai/.venv/bin/python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

### Gunicorn (`/etc/systemd/system/boq_ai-gunicorn.service`)

```ini
[Unit]
Description=BOQ_AI Gunicorn
After=network.target

[Service]
User=boq_ai
Group=www-data
WorkingDirectory=/srv/boq_ai/backend
EnvironmentFile=/srv/boq_ai/.env
RuntimeDirectory=boq_ai
ExecStart=/srv/boq_ai/.venv/bin/gunicorn config.wsgi:application --bind unix:/run/boq_ai/gunicorn.sock --workers 3 --timeout 120
Restart=always

[Install]
WantedBy=multi-user.target
```

### Celery (`/etc/systemd/system/boq_ai-celery.service`)

```ini
[Unit]
Description=BOQ_AI Celery Worker
After=network.target redis-server.service

[Service]
User=boq_ai
Group=www-data
WorkingDirectory=/srv/boq_ai/backend
EnvironmentFile=/srv/boq_ai/.env
ExecStart=/srv/boq_ai/.venv/bin/celery -A config worker --loglevel=info --concurrency=8
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now redis-server boq_ai-gunicorn boq_ai-celery
```

### Nginx (`/etc/nginx/sites-available/boq_ai`)

```nginx
server {
    listen 80;
    server_name 13.205.90.58;
    client_max_body_size 50M;

    location /static/ { alias /srv/boq_ai/staticfiles/; }
    location /media/  { internal; alias /srv/boq_ai/media/; }

    location / {
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_pass http://unix:/run/boq_ai/gunicorn.sock;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/boq_ai /etc/nginx/sites-enabled/boq_ai
sudo nginx -t && sudo systemctl reload nginx
```

---

## TLS & SMTP (later)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

Update `.env` with domain, `SECURE_SSL_REDIRECT=True`, and SMTP settings when ready.
