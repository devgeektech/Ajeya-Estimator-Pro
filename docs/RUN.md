# BOQ_AI Runbook

This project uses PostgreSQL in every runtime. On your development machine,
`localhost` means your local PostgreSQL service. On EC2, `localhost` means the
PostgreSQL service installed on the same EC2 instance.

For the full first-time server setup and future feature deployment checklist,
see `DEPLOY.md`.

## Environment

```text
Host: 13.205.90.58
User: ubuntu
Region: ap-south-1
Database: boq_db
Database user: boq_user
```

## Local Development Setup (For Colleagues)

Follow these steps to quickly get the project running on your local machine.

### 1. PostgreSQL Setup

Ensure you have PostgreSQL installed locally. Open `psql` (or pgAdmin) and run:

```sql
CREATE USER boq_user WITH PASSWORD 'localpass';
CREATE DATABASE boq_db OWNER boq_user;
GRANT ALL PRIVILEGES ON DATABASE boq_db TO boq_user;
ALTER USER boq_user CREATEDB;
```
*(The `CREATEDB` privilege is required to run the test suite natively.)*

### 2. Code & Virtual Environment

Clone the repository and set up your Python environment (Python 3.14.5 recommended):

```bash
git clone <repo-url> BOQ_AI
cd BOQ_AI
python -m venv .venv

# On Windows:
.\.venv\Scripts\activate
# On Mac/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Environment Variables

Create a `.env` file in the root of the project with the following local configuration:

```ini
DEBUG=True
DJANGO_SETTINGS_MODULE=config.settings.base
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=postgres://boq_user:localpass@localhost:5432/boq_db
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
SECRET_KEY=local-dev-secret-key-123
```

### 4. Database Migration & Run

Run the migrations to build the tables, create an admin account, and start the server:

```bash
cd backend
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

You can now access the app at `http://127.0.0.1:8000`.

---

## Production Server Setup (EC2)

## 1. Server Packages

```bash
sudo apt update
sudo apt install -y python3-venv python3-dev build-essential postgresql postgresql-contrib redis-server nginx git
```

## 2. App User and Code

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin boq_ai
sudo mkdir -p /srv/boq_ai
sudo chown boq_ai:www-data /srv/boq_ai
sudo -u boq_ai git clone <repo-url> /srv/boq_ai
cd /srv/boq_ai
sudo -u boq_ai python3 -m venv .venv
sudo -u boq_ai .venv/bin/pip install -U pip
sudo -u boq_ai .venv/bin/pip install -r requirements.txt
```

## 3. PostgreSQL

```bash
sudo -u postgres psql
```

```sql
CREATE USER boq_user WITH PASSWORD 'replace-with-a-new-strong-password';
CREATE DATABASE boq_db OWNER boq_user;
GRANT ALL PRIVILEGES ON DATABASE boq_db TO boq_user;
```

Rotate the password if it was shared anywhere:

```sql
ALTER USER boq_user WITH PASSWORD 'new-strong-password';
```

## 4. Environment File

```bash
sudo -u boq_ai cp .env.example /srv/boq_ai/.env
sudo -u boq_ai chmod 600 /srv/boq_ai/.env
```

Minimum values:

```ini
SECRET_KEY=generate-a-real-secret-key
DEBUG=False
DJANGO_SETTINGS_MODULE=config.settings.production
ALLOWED_HOSTS=13.205.90.58
DATABASE_URL=postgres://boq_user:replace-with-password@localhost:5432/boq_db
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
EMAIL_HOST=
```

Generate `SECRET_KEY`:

```bash
/srv/boq_ai/.venv/bin/python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

## 5. Django

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

Start services:

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

Enable it:

```bash
sudo ln -s /etc/nginx/sites-available/boq_ai /etc/nginx/sites-enabled/boq_ai
sudo nginx -t
sudo systemctl reload nginx
```

## 9. Later: Domain, TLS, SMTP

After buying a domain, install Certbot and enable HTTPS:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

Then update `.env`:

```ini
ALLOWED_HOSTS=13.205.90.58,your-domain.com
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_HSTS_SECONDS=31536000
```
