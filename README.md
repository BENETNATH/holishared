# SaaS

Flask + HTMX + Alpine.js SaaS application.

## Quick Start

```bash
# 1. Configure
cp .env.example .env
# Edit .env: SECRET_KEY, SUPERADMIN_EMAIL, SUPERADMIN_PASSWORD, APP_PORT

# 2. Initialize
python manage.py init

# 3. Run (dev)
python manage.py run

# 4. Production
python manage.py start
python manage.py deploy  # nginx + systemd (needs root)
```

## CLI Commands

```
python manage.py init         # venv + deps + DB
python manage.py run          # dev server (Flask debug)
python manage.py start        # production (Waitress)
python manage.py stop         # stop server
python manage.py status       # check status
python manage.py db-init      # create tables
python manage.py db-shell     # SQLite shell
python manage.py deploy       # nginx + systemd
python manage.py logs         # tail logs
python manage.py reset-admin  # new superadmin password
```

## Structure

```
saas/
├── .env                  # Config (port, secrets, admin)
├── manage.py             # CLI management
├── requirements.txt
├── app/
│   ├── __init__.py       # App factory
│   ├── extensions.py     # DB, Login
│   ├── auth/             # Superadmin login
│   ├── main/             # Dashboard
│   ├── templates/        # Jinja2 + HTMX + Alpine
│   └── static/
├── nginx/
│   └── saas.conf         # Nginx reverse proxy
├── systemd/
│   └── saas.service      # Systemd unit
└── logs/
```

## Stack

- **Flask 3.x** — WSGI app
- **HTMX 1.9** — HTML over HTTP (no SPA)
- **Alpine.js 3.x** — lightweight interactivity
- **Waitress** — production WSGI server
- **Nginx** — reverse proxy, TLS, security headers
- **SQLite** — database (swap to PostgreSQL later)
