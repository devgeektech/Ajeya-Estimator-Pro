# BOQ_AI — Operations

Local development, testing, and EC2 go-live. Update when infrastructure or
commands change.

---

## Environment

| Item | Value |
| --- | --- |
| EC2 host | `13.205.90.58` (ap-south-1) |
| App path | `/srv/boq_ai` |
| App user | `boq_ai` (group `www-data`) |
| Database | PostgreSQL `boq_db` / user `boq_user` on `localhost` |
| Settings | `config.settings` |
| Gunicorn | `backend/config/gunicorn.conf.py` |
| Secrets | `.env` locally; `/srv/boq_ai/.env` on server — never commit |

---

## Go live on EC2

Do these **in order** on a fresh Ubuntu 22.04/24.04 instance. Skip a step only
if it is already done (for example PostgreSQL already created).

The app is HTTP on the public IP until a domain and TLS exist. Do not set
`SECURE_SSL_REDIRECT=True` yet.

### 1. AWS

- Inbound security group: **22** (your IP), **80** (users). Do **not** open
  5432, 6379, or 8000.
- Instance: 2 vCPU / 4 GB RAM or larger (database import + Chroma + Celery).
- Attach an Elastic IP if the public IP must stay `13.205.90.58`.

### 2. Packages and app user

```bash
sudo apt update
sudo apt install -y python3-venv python3-dev build-essential \
  postgresql postgresql-contrib redis-server nginx git
sudo useradd --system --create-home --shell /usr/sbin/nologin boq_ai
sudo mkdir -p /srv/boq_ai
sudo chown boq_ai:www-data /srv/boq_ai
sudo chmod 750 /srv/boq_ai
```

Use **Python 3.12+**. `requirements.txt` was pinned on 3.14; if `pip install`
fails on the AMI Python, install a 3.12+ package and recreate the venv with it.

### 3. Clone the repo

Private GitHub needs a deploy key as `boq_ai` before clone.

```bash
sudo -u boq_ai git clone <repo-url> /srv/boq_ai
cd /srv/boq_ai
```

If the tree was cloned as `ubuntu`, fix ownership: `sudo chown -R boq_ai:www-data /srv/boq_ai`.

### 4. Python venv

```bash
cd /srv/boq_ai
sudo -u boq_ai python3 -m venv .venv
sudo -u boq_ai .venv/bin/pip install -U pip
sudo -u boq_ai .venv/bin/pip install -r requirements.txt
```

### 5. PostgreSQL

```bash
sudo systemctl enable --now postgresql
sudo -u postgres psql
```

```sql
CREATE USER boq_user WITH PASSWORD '<strong-password>';
CREATE DATABASE boq_db OWNER boq_user;
GRANT ALL PRIVILEGES ON DATABASE boq_db TO boq_user;
\c boq_db
GRANT ALL ON SCHEMA public TO boq_user;
GRANT CREATE ON SCHEMA public TO boq_user;
```

Leave PostgreSQL listening on `localhost` only (Ubuntu default). If the password
contains `@`, `:`, `/`, or `%`, URL-encode it in `DATABASE_URL`.

### 6. Redis

Ubuntu's `redis-server` already binds `127.0.0.1`. Confirm and enable:

```bash
sudo systemctl enable --now redis-server
redis-cli ping   # PONG
```

### 7. Runtime directories and `.env`

```bash
sudo -u boq_ai mkdir -p /srv/boq_ai/media/chroma \
  /srv/boq_ai/media/job_progress /srv/boq_ai/logs /srv/boq_ai/staticfiles
sudo -u boq_ai cp /srv/boq_ai/.env.example /srv/boq_ai/.env
sudo nano /srv/boq_ai/.env
sudo chown boq_ai:www-data /srv/boq_ai/.env
sudo chmod 600 /srv/boq_ai/.env
```

Required production values (no blanks):

| Key | Value |
| --- | --- |
| `SECRET_KEY` | Generate (command below) |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `13.205.90.58` |
| `CSRF_TRUSTED_ORIGINS` | `http://13.205.90.58` |
| `DATABASE_URL` | `postgres://boq_user:<password>@localhost:5432/boq_db` |
| `CELERY_TASK_ALWAYS_EAGER` | `False` |
| `OPENAI_API_KEY` | Real key (Analyse will fail without it) |
| `AI_INSTRUCTION_LOGGING` | `False` |
| `SECURE_SSL_REDIRECT` | `False` |
| `GUNICORN_TIMEOUT` | `600` |

```bash
/srv/boq_ai/.venv/bin/python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

Full example:

```ini
SECRET_KEY=<generated>
DEBUG=False
DJANGO_SETTINGS_MODULE=config.settings
ALLOWED_HOSTS=13.205.90.58
CSRF_TRUSTED_ORIGINS=http://13.205.90.58
DATABASE_URL=postgres://boq_user:<password>@localhost:5432/boq_db
CONN_MAX_AGE=60
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
CELERY_TASK_ALWAYS_EAGER=False
OPENAI_API_KEY=<production-key>
OPENAI_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
AI_INSTRUCTION_LOGGING=False
AI_ROW_EXTRACTION_BATCH_SIZE=5
AI_PRODUCT_MAPPING_BATCH_SIZE=4
CHROMA_PATH=media/chroma
CHROMA_COLLECTION=rate_master_products
SECURE_SSL_REDIRECT=False
GUNICORN_BIND=unix:/run/boq_ai/gunicorn.sock
GUNICORN_WORKERS=3
GUNICORN_TIMEOUT=600
```

### 8. Migrate, static files, first user

`createsuperuser` asks for **email** (not username) and creates a Superadmin.

```bash
cd /srv/boq_ai/backend
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py check --deploy'
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py migrate'
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py collectstatic --noinput'
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py createsuperuser'
```

### 9. Gunicorn unit (`/etc/systemd/system/boq_ai-gunicorn.service`)

```ini
[Unit]
Description=BOQ_AI Gunicorn
After=network.target postgresql.service redis-server.service

[Service]
User=boq_ai
Group=www-data
WorkingDirectory=/srv/boq_ai/backend
EnvironmentFile=/srv/boq_ai/.env
Environment=PYTHONUNBUFFERED=1
RuntimeDirectory=boq_ai
ExecStart=/srv/boq_ai/.venv/bin/gunicorn --config /srv/boq_ai/backend/config/gunicorn.conf.py config.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```

If an older unit used `--timeout 120`, replace `ExecStart` with the `--config`
line above. That short timeout kills large master-database imports.

### 10. Celery unit (`/etc/systemd/system/boq_ai-celery.service`)

```ini
[Unit]
Description=BOQ_AI Celery Worker
After=network.target redis-server.service

[Service]
User=boq_ai
Group=www-data
WorkingDirectory=/srv/boq_ai/backend
EnvironmentFile=/srv/boq_ai/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/srv/boq_ai/.venv/bin/celery -A config worker --loglevel=info --concurrency=8
Restart=always

[Install]
WantedBy=multi-user.target
```

### 11. Nginx (`/etc/nginx/sites-available/boq_ai`)

```nginx
server {
    listen 80;
    server_name 13.205.90.58;
    client_max_body_size 50M;
    proxy_connect_timeout 10s;
    proxy_send_timeout 600s;
    proxy_read_timeout 600s;

    location /static/ {
        alias /srv/boq_ai/staticfiles/;
        expires 7d;
        add_header Cache-Control "public";
    }
    # Downloads go through authenticated Django views, not public /media/ URLs.
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
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sfn /etc/nginx/sites-available/boq_ai /etc/nginx/sites-enabled/boq_ai
sudo nginx -t && sudo systemctl reload nginx
```

Optional host firewall (security group still required):

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx HTTP'
sudo ufw enable
```

### 12. Start services

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now redis-server postgresql nginx boq_ai-gunicorn boq_ai-celery
```

### 13. Verify

```bash
systemctl is-active postgresql redis-server nginx boq_ai-gunicorn boq_ai-celery
curl -I http://13.205.90.58/
cd /srv/boq_ai/backend
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py check_celery'
```

Expect HTTP 302 to login (or 200). `check_celery` must show Redis OK and a
fresh worker heartbeat. If a unit is failed:

```bash
sudo journalctl -u boq_ai-gunicorn -u boq_ai-celery -n 80 --no-pager
```

App logs: `/srv/boq_ai/logs/application.log` and `errors.log`.

### 14. First login (required before any BOQ)

1. Open `http://13.205.90.58/` and sign in with the Superadmin email.
2. **Database → Upload** the client master workbook (`Product_Helper`,
   `Rate_Master_Output`, `Labour_Master_Output`). This runs in the web process
   (up to 10 minutes). Wait until status is active.
3. Confirm the version shows as active. Embeddings are built during import;
   Analyse will not match products until this step succeeds.
4. Create Admin/Expert users from the Users screen as needed.
5. Upload a test BOQ and run Analyse once to confirm Celery + OpenAI.

BOQ upload is refused until an active master database exists.

---

## Subsequent deploys

Before pushing:

- [ ] No secrets in git
- [ ] `manage.py check --deploy` passes
- [ ] `manage.py test tests` passes
- [ ] Migrations committed if models changed
- [ ] `SESSION_STATE.md` and `CHANGELOG.md` updated
- [ ] EC2 `.env` still has `DEBUG=False`, `CELERY_TASK_ALWAYS_EAGER=False`,
      `AI_INSTRUCTION_LOGGING=False`, and a real `OPENAI_API_KEY`

On EC2 after `git pull`:

```bash
cd /srv/boq_ai
sudo -u boq_ai git pull
sudo -u boq_ai .venv/bin/pip install -r requirements.txt
cd backend
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py check --deploy'
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py migrate'
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py collectstatic --noinput'
sudo systemctl restart boq_ai-gunicorn boq_ai-celery
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py check_celery'
```

If `boq_ai-gunicorn.service`, `boq_ai-celery.service`, or the Nginx site file
changed, copy the new file into `/etc/...`, then `sudo systemctl daemon-reload`
and `sudo nginx -t && sudo systemctl reload nginx` before restart.

Verify:

```bash
systemctl status boq_ai-gunicorn boq_ai-celery redis-server --no-pager
curl -I http://13.205.90.58/
```

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

Minimum local `.env` (`DEBUG=True` allows inline Analyse without Redis):

```ini
DEBUG=True
DJANGO_SETTINGS_MODULE=config.settings
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost,http://127.0.0.1
DATABASE_URL=postgres://boq_user:localpass@localhost:5432/boq_db
SECRET_KEY=<generate-with-django-get_random_secret_key>
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

Set `OPENAI_API_KEY` before running Analyse locally.

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

Then upload the master database in the UI before uploading a BOQ.

### 3b. Dev server log notes

- `- Broken pipe from ('127.0.0.1', <port>)` at INFO is **not** an application
  error (browser cancelled an in-flight request). The Make List tab now loads a
  slim page (~180KB) so cancels are rarer, and `SkipBrokenPipeFilter` hides those
  INFO lines from the console / application log. Still treat a missing or non-200
  request line as a real failure.
- Edited `static/css/app.css` but the browser still shows old styles? Re-run
  `collectstatic`. `ManifestStaticFilesStorage` resolves `{% static %}` through
  `staticfiles/staticfiles.json`, so a stale manifest keeps serving the previous
  hashed build and no `?v=` bump in the template will change that.

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

The `tests/` package lives at the **repo root** (not `backend/tests/`).

### 5. Redis / Celery (BOQ analysis)

BOQ analysis uses Celery. In production (`DEBUG=False`), Redis and the Celery worker
are required. **Analyse will refuse to start** if the worker heartbeat is missing —
it will not queue a job into Redis with nobody consuming it (that used to freeze
the loading UI).

Check readiness:

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

Terminal 3 — Celery worker (**keep this window open**):

```powershell
# Windows (auto-restarts if the worker crashes)
.\scripts\run_celery_worker.ps1
```

```bash
# Linux / macOS
./scripts/run_celery_worker.sh
```

The worker writes `media/job_progress/celery_worker_heartbeat.json`. Analyse
checks that heartbeat before queueing. Worker scripts auto-restart after a crash
so analysis does not stay stuck.

While Analyse runs you should see live ``BOQ Analyse id=… percent=…`` log lines
on:
- the **Django runserver** terminal (``boq_ai`` console logger mirror), and
- the **Celery** terminal (actual AI/matching work).

Same logging as the rest of the app (console handler) — not ``print``.
Keep **one** Celery window; restart it with `.\scripts\run_celery_worker.ps1`
after code changes (worker does not auto-reload).

Default Windows concurrency is **4** (override with `CELERY_WORKER_CONCURRENCY`).
Linux default remains **8**.

If progress stops updating for **2+ minutes** while status is `PROCESSING`, the
status endpoint marks the BOQ failed so Analyse can be started again.

The BOQ detail page polls `GET /boqs/<id>/status/` while status is `PROCESSING` and
reloads when analysis completes or fails.

---

## TLS & SMTP (later)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

Update `.env` with the domain, `ALLOWED_HOSTS`,
`CSRF_TRUSTED_ORIGINS=https://your-domain.com`, `SECURE_SSL_REDIRECT=True`, and
SMTP settings when ready. Session/CSRF cookies then become Secure automatically.
Restart gunicorn after the `.env` change.
