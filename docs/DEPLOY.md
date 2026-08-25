# BOQ_AI — Manual Deploy (No CI/CD)

How to put the app live on EC2 the first time, and how to ship code updates later
with **git push on your PC** and **git pull on the server**. No GitHub Actions.

Canonical environment details and unit-file templates: `docs/OPS.md`.
This file is the day-to-day operator guide.

---

## Environment (current live)

| Item | Value |
| --- | --- |
| EC2 host | `13.205.90.58` |
| App path | `/srv/boq_ai` |
| App user | `boq_ai` (group `www-data`) |
| SSH user | `ubuntu` + key `boq_keypair.pem` |
| Database | PostgreSQL `boq_db` / user `boq_user` on `localhost` |
| Secrets | `/srv/boq_ai/.env` on server — **never commit** |
| Site | http://13.205.90.58/login/ |

### Mental model

```text
Your PC (code)  →  git push  →  GitHub
                                    ↓
EC2 (git pull)  →  migrate / collectstatic / restart  →  live site
```

| Piece | Role |
| --- | --- |
| **Nginx** | Port 80; serves `/static/`; proxies to Gunicorn |
| **Gunicorn** | Django web process |
| **Celery** | Analyse / background jobs |
| **Redis** | Celery broker |
| **PostgreSQL** | App data |
| **`.env`** | Secrets on server only |

AWS security group: open **22** (SSH) and **80** (HTTP). Do **not** open 5432,
6379, or 8000.

---

## Part A — First go-live (fresh server)

Skip steps that are already done. Full package/unit templates: `docs/OPS.md`
sections 1–14.

### 1. SSH in

```bash
ssh -i boq_keypair.pem ubuntu@13.205.90.58
```

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

Use **Python 3.12+** (3.14 is fine if that is the AMI default).

### 3. Clone the repo

Private GitHub: use a **deploy key** for `boq_ai` (preferred) or a short-lived
token. Do not leave personal PATs in shell history longer than needed.

```bash
sudo -u boq_ai git clone <repo-url> /srv/boq_ai
```

If you cloned as `ubuntu`, fix ownership:

```bash
sudo chown -R boq_ai:www-data /srv/boq_ai
```

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
\q
```

If the password contains `@`, `:`, `/`, or `%`, URL-encode it in `DATABASE_URL`.

### 6. Redis

```bash
sudo systemctl enable --now redis-server
redis-cli ping   # PONG
```

### 7. Runtime dirs and `.env`

```bash
sudo -u boq_ai mkdir -p /srv/boq_ai/media/chroma \
  /srv/boq_ai/media/job_progress /srv/boq_ai/logs /srv/boq_ai/staticfiles
sudo -u boq_ai cp /srv/boq_ai/.env.example /srv/boq_ai/.env
sudo nano /srv/boq_ai/.env
sudo chown boq_ai:www-data /srv/boq_ai/.env
sudo chmod 600 /srv/boq_ai/.env
```

Required production values:

| Key | Value |
| --- | --- |
| `SECRET_KEY` | Strong value (prefer letters/digits so bash sourcing is safe) |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `13.205.90.58` |
| `CSRF_TRUSTED_ORIGINS` | `http://13.205.90.58` |
| `DATABASE_URL` | `postgres://boq_user:<password>@localhost:5432/boq_db` |
| `CELERY_TASK_ALWAYS_EAGER` | `False` |
| `OPENAI_API_KEY` | Real key |
| `AI_INSTRUCTION_LOGGING` | `False` |
| `SECURE_SSL_REDIRECT` | `False` |
| `GUNICORN_TIMEOUT` | `600` |

Generate a key:

```bash
openssl rand -hex 32
# or:
/srv/boq_ai/.venv/bin/python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

Full example block: see `docs/OPS.md` §7.

### 8. Migrate, static files, first user

Login uses **email** (Superadmin), not username.

```bash
cd /srv/boq_ai/backend
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py check --deploy'
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py migrate'
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py collectstatic --noinput'
sudo chown -R boq_ai:www-data /srv/boq_ai/staticfiles
sudo find /srv/boq_ai/staticfiles -type d -exec chmod 2750 {} +
sudo find /srv/boq_ai/staticfiles -type f -exec chmod 640 {} +
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py createsuperuser'
```

**Important:** after every `collectstatic`, fix ownership. Nginx runs as
`www-data`. Without the `chown`/`chmod`, CSS returns **403**.

### 9–11. Gunicorn, Celery, Nginx

Create unit and site files exactly as in `docs/OPS.md` §§9–11:

- `/etc/systemd/system/boq_ai-gunicorn.service`
- `/etc/systemd/system/boq_ai-celery.service`
- `/etc/nginx/sites-available/boq_ai`

Then:

```bash
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sfn /etc/nginx/sites-available/boq_ai /etc/nginx/sites-enabled/boq_ai
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now redis-server postgresql nginx boq_ai-gunicorn boq_ai-celery
sudo systemctl reload nginx
```

### 12. Verify

```bash
systemctl is-active postgresql redis-server nginx boq_ai-gunicorn boq_ai-celery
curl -I http://13.205.90.58/
cd /srv/boq_ai/backend
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py check_celery'
```

Expect HTTP 302 → login (or 200). `check_celery` must show Redis OK and a fresh
worker heartbeat.

Logs if something fails:

```bash
sudo journalctl -u boq_ai-gunicorn -u boq_ai-celery -n 80 --no-pager
```

App logs: `/srv/boq_ai/logs/application.log` and `errors.log`.

### 13. First login (required before any BOQ)

1. Open http://13.205.90.58/login/ and sign in as Superadmin.
2. **Database → Upload** the master workbook (`Product_Helper`,
   `Rate_Master_Output`, `Labour_Master_Output`). Wait until status is active
   (can take several minutes; runs in the web process).
3. Confirm the version is active. Analyse will not match products until this
   succeeds.
4. Create Admin/Expert users as needed.
5. Upload a test BOQ and run Analyse once (confirms Celery + OpenAI).

BOQ upload is refused until an active master database exists.

---

## Part B — Later live updates (manual pull)

No CI/CD. Flow: **push from PC → pull on EC2 → migrate / static / restart**.

### Before you push (on your PC)

- [ ] No secrets in git (`.env`, keys, passwords)
- [ ] `manage.py check` / tests pass locally when practical
- [ ] Migrations committed if models changed
- [ ] `docs/SESSION_STATE.md` and `docs/CHANGELOG.md` updated for meaningful work
- [ ] Server `.env` is **not** overwritten by git (it is gitignored)

```powershell
cd C:\Users\vikas.DESKTOP-61LEE8B\Projects\BOQ_AI
.\.venv\Scripts\python.exe backend\manage.py check
.\.venv\Scripts\python.exe backend\manage.py test tests --no-input

git add .
git commit -m "Describe why this change exists"
git push origin main
```

Push the branch the server tracks (usually `main`).

### On the server after every push

```bash
ssh -i boq_keypair.pem ubuntu@13.205.90.58
```

```bash
cd /srv/boq_ai

# 1) Pull latest code (as boq_ai — keeps ownership correct)
sudo -u boq_ai git pull origin main

# 2) Install any new packages (safe every time)
sudo -u boq_ai .venv/bin/pip install -r requirements.txt

# 3) Safety check
cd backend
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py check --deploy'

# 4) Apply DB migrations
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py migrate'

# 5) Rebuild static files + fix Nginx read permissions
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py collectstatic --noinput'
sudo chown -R boq_ai:www-data /srv/boq_ai/staticfiles
sudo find /srv/boq_ai/staticfiles -type d -exec chmod 2750 {} +
sudo find /srv/boq_ai/staticfiles -type f -exec chmod 640 {} +

# 6) Restart so new code is loaded
sudo systemctl restart boq_ai-gunicorn boq_ai-celery

# 7) Confirm Celery
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py check_celery'
```

Quick verify:

```bash
systemctl is-active boq_ai-gunicorn boq_ai-celery
curl -I http://13.205.90.58/login/
```

Hard-refresh the browser (Ctrl+F5) after CSS changes.

### Cheat sheet (copy/paste every deploy)

```bash
cd /srv/boq_ai
sudo -u boq_ai git pull origin main
sudo -u boq_ai .venv/bin/pip install -r requirements.txt
cd backend
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py migrate'
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py collectstatic --noinput'
sudo chown -R boq_ai:www-data /srv/boq_ai/staticfiles
sudo find /srv/boq_ai/staticfiles -type d -exec chmod 2750 {} +
sudo find /srv/boq_ai/staticfiles -type f -exec chmod 640 {} +
sudo systemctl restart boq_ai-gunicorn boq_ai-celery
```

---

## What to run by change type

| Change type | Extra steps |
| --- | --- |
| Python / views / services only | `git pull` → migrate (if any) → restart gunicorn + celery |
| CSS / static files | `collectstatic` + **chown/chmod** (or CSS 403) |
| `requirements.txt` | `pip install -r requirements.txt` then restart |
| New migrations | `migrate` then restart |
| Server secrets / config | Edit **only** `/srv/boq_ai/.env`, then restart — never via git |
| Gunicorn / Celery unit files | Copy into `/etc/systemd/system/`, `daemon-reload`, restart units |
| Nginx site file | Edit `/etc/nginx/sites-available/boq_ai`, `nginx -t`, `reload nginx` |

If unit or Nginx files changed in the repo, copy them into `/etc/...` before
restart; `git pull` alone does not update systemd or Nginx configs.

---

## Do / don’t

**Do**

- Pull as `sudo -u boq_ai git pull`
- Always restart Gunicorn + Celery after a code pull
- Fix static permissions after every `collectstatic`
- Keep server `.env` separate from local `.env`

**Don’t**

- Don’t open Postgres / Redis / Gunicorn ports publicly
- Don’t set `DEBUG=True` on live
- Don’t `git pull` as root and leave root-owned files under `/srv/boq_ai`
- Don’t expect live to update until you pull **and** restart
- Don’t commit or overwrite `/srv/boq_ai/.env` from git

---

## Troubleshooting

```bash
# Service logs
sudo journalctl -u boq_ai-gunicorn -u boq_ai-celery -n 80 --no-pager

# App logs
sudo tail -n 100 /srv/boq_ai/logs/application.log
sudo tail -n 100 /srv/boq_ai/logs/errors.log

# CSS check (hashed name may differ; login HTML shows the real path)
curl -I http://13.205.90.58/static/css/app.css
curl -s http://13.205.90.58/login/ | grep -Eo 'href="/static/css/[^"]+"'
```

| Symptom | Likely fix |
| --- | --- |
| Site up but no CSS (403) | `chown`/`chmod` on `staticfiles` after `collectstatic` |
| Analyse stuck / no progress | Restart Celery; run `check_celery`; confirm Redis |
| 502 Bad Gateway | Gunicorn down — `systemctl status boq_ai-gunicorn` |
| CSRF / login POST fails | `CSRF_TRUSTED_ORIGINS` must match how users open the site |
| Old Python code still running | Forgot `systemctl restart boq_ai-gunicorn boq_ai-celery` |

---

## Related docs

| Document | Use for |
| --- | --- |
| `docs/OPS.md` | Full go-live templates (systemd, Nginx), local setup, tests |
| `docs/PRODUCT.md` | Product / architecture rules |
| `docs/DATABASE.md` | Schema and import rules |
| `docs/SESSION_STATE.md` | Current session status |
| `docs/CHANGELOG.md` | Change history |
