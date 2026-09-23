#!/bin/bash
set -e
cd /srv/boq_ai
sudo -u boq_ai git stash
sudo -u boq_ai git pull origin main
sudo -u boq_ai .venv/bin/pip install -r requirements.txt
cd backend
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py migrate'
sudo -u boq_ai bash -c 'set -a; source ../.env; set +a; ../.venv/bin/python manage.py collectstatic --noinput'
chown -R boq_ai:www-data /srv/boq_ai/staticfiles
find /srv/boq_ai/staticfiles -type d -exec chmod 2750 {} +
find /srv/boq_ai/staticfiles -type f -exec chmod 640 {} +
systemctl restart boq_ai-gunicorn boq_ai-celery
echo "DEPLOYMENT COMPLETE!"
