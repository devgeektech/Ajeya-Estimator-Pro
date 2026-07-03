# BOQ_AI Deployment Guide

Use this guide after a feature is coded, reviewed, and ready to deploy.

## Production Shape

```text
Browser
  -> Nginx
  -> Gunicorn
  -> Django
  -> PostgreSQL on localhost
  -> Redis on localhost
  -> Celery worker
```

The same app settings are used locally and on EC2:

```ini
DJANGO_SETTINGS_MODULE=config.settings.production
DATABASE_URL=postgres://boq_user:<password>@localhost:5432/boq_db
```

## 1. Pre-Deploy Checklist

Before deploying a feature:

- Confirm the code change was necessary and is scoped.
- Confirm no secrets, PEM files, uploads, exports, logs, or cache files are committed.
- Confirm `.env` exists only on the machine running the app.
- Confirm dependencies are listed in `requirements.txt`.
- Run checks/tests locally after PostgreSQL is ready:

```bash
cd backend
python manage.py check
python manage.py test
```

## 2. First-Time EC2 Setup

Install OS packages:

```bash
sudo apt update
sudo apt install -y python3-venv python3-dev build-essential postgresql postgresql-contrib redis-server nginx git
```

Create the service user and app directory:

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin boq_ai
sudo mkdir -p /srv/boq_ai
sudo chown boq_ai:www-data /srv/boq_ai
```

Clone the repository:

```bash
sudo -u boq_ai git clone <repo-url> /srv/boq_ai
cd /srv/boq_ai
```

Create the Python environment:

```bash
sudo -u boq_ai python3 -m venv .venv
sudo -u boq_ai .venv/bin/pip install -U pip
sudo -u boq_ai .venv/bin/pip install -r requirements.txt
```

## 3. PostgreSQL Setup

Open PostgreSQL:

```bash
sudo -u postgres psql
```

Create the role and database:

```sql
CREATE USER boq_user WITH PASSWORD 'replace-with-a-strong-password';
CREATE DATABASE boq_db OWNER boq_user;
GRANT ALL PRIVILEGES ON DATABASE boq_db TO boq_user;
```

If the password was ever shared outside the server, rotate it:

```sql
ALTER USER boq_user WITH PASSWORD 'new-strong-password';
```

## 4. Environment File

Create `/srv/boq_ai/.env`:

```bash
sudo -u boq_ai cp .env.example /srv/boq_ai/.env
sudo -u boq_ai chmod 600 /srv/boq_ai/.env
```

Minimum production values:

```ini
SECRET_KEY=<generated-secret-key>
DEBUG=False
DJANGO_SETTINGS_MODULE=config.settings.production
ALLOWED_HOSTS=13.205.90.58
DATABASE_URL=postgres://boq_user:<password>@localhost:5432/boq_db
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
OPENAI_API_KEY=<production-openai-key>
EMAIL_HOST=
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
```

Generate `SECRET_KEY` on the server:

```bash
/srv/boq_ai/.venv/bin/python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

Leave SMTP blank until the domain/mail provider is ready.

## 5. Django Setup

Run:

```bash
cd /srv/boq_ai/backend
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py check'
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py migrate'
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py collectstatic --noinput'
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py createsuperuser'
```

## 6. Gunicorn Service

Create `/etc/systemd/system/boq_ai-gunicorn.service`:

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

## 7. Celery Service

Create `/etc/systemd/system/boq_ai-celery.service`:

```ini
[Unit]
Description=BOQ_AI Celery Worker
After=network.target redis-server.service

[Service]
User=boq_ai
Group=www-data
WorkingDirectory=/srv/boq_ai/backend
EnvironmentFile=/srv/boq_ai/.env
ExecStart=/srv/boq_ai/.venv/bin/celery -A config worker --loglevel=info --concurrency=2
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable services:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now redis-server boq_ai-gunicorn boq_ai-celery
```

## 8. Nginx

Create `/etc/nginx/sites-available/boq_ai`:

```nginx
server {
    listen 80;
    server_name 13.205.90.58;

    client_max_body_size 50M;

    location /static/ {
        alias /srv/boq_ai/staticfiles/;
    }

    location /media/ {
        internal;
        alias /srv/boq_ai/media/;
    }

    location / {
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_pass http://unix:/run/boq_ai/gunicorn.sock;
    }
}
```

Enable Nginx site:

```bash
sudo ln -s /etc/nginx/sites-available/boq_ai /etc/nginx/sites-enabled/boq_ai
sudo nginx -t
sudo systemctl reload nginx
```

## 9. Deploying Future Feature Updates

After code for a feature is complete:

```bash
cd /srv/boq_ai
sudo -u boq_ai git pull
sudo -u boq_ai .venv/bin/pip install -r requirements.txt
cd backend
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py check'
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py migrate'
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py collectstatic --noinput'
sudo systemctl restart boq_ai-gunicorn boq_ai-celery
```

Verify:

```bash
systemctl status boq_ai-gunicorn boq_ai-celery
journalctl -u boq_ai-gunicorn -n 50 --no-pager
journalctl -u boq_ai-celery -n 50 --no-pager
curl -I http://13.205.90.58/
```

## 10. Domain, TLS, and SMTP Later

After the domain is ready:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

Update `.env`:

```ini
ALLOWED_HOSTS=13.205.90.58,your-domain.com
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_HSTS_SECONDS=31536000
```

Then configure SMTP values when the mail provider is ready.
