"""Gunicorn settings for EC2 (systemd EnvironmentFile supplies env vars)."""

import os

bind = os.environ.get("GUNICORN_BIND", "unix:/run/boq_ai/gunicorn.sock")
workers = int(os.environ.get("GUNICORN_WORKERS", "3"))
# Database import + embeddings run in the web process (not Celery).
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "600"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = 5
worker_class = "sync"
accesslog = "-"
errorlog = "-"
capture_output = True
proc_name = "boq_ai"
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "50"))
forwarded_allow_ips = "*"
# Socket 660 so Nginx (group www-data) can proxy to Gunicorn.
umask = 0o007
