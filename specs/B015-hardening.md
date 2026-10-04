# Spec B015 — Hardening & Production

**Statut** : SPEC
**Date** : 2026-10-04
**Lot** : B015
**Dépendances** : Tous les autres lots

---

## 1. Périmètre

Rendre l'application production-ready : sécurité, monitoring, backup, performance.

---

## 2. Tâches

### 2.1 — Security Headers

Dans `app/__init__.py`, ajouter un `@app.after_request` :

```python
@app.after_request
def security_headers(response):
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "  # Alpine.js inline
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "font-src 'self';"
    )
    return response
```

### 2.2 — Rate Limiting

Ajouter `flask-limiter` :

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100 per hour"],
)

# Sur les endpoints de création :
@limiter.limit("20 per hour")
def create_activity(...): ...

@limiter.limit("10 per hour")
def create_event(...): ...
```

### 2.3 — Health Check

```
GET /health
```

- Vérifie : DB accessible (SELECT 1), disque < 90%
- Retourne JSON : `{"status": "ok", "db": true, "disk": true, "uptime_s": 12345}`
- Pas d'auth requise
- Si problème → 503

### 2.4 — Logging Structuré

- En production : JSON logs (via `pythonjsonlogger`)
- En dev : logs texte dans console
- Logger par blueprint : `app.logger`
- Niveau : INFO en prod, DEBUG en dev

### 2.5 — Backup DB

Script `scripts/backup.sh` :
```bash
#!/bin/bash
# Backup SQLite quotidien
DB="instance/holishared.db"
BACKUP_DIR="backups"
mkdir -p "$BACKUP_DIR"
sqlite3 "$DB" ".backup '$BACKUP_DIR/holishared_$(date +%Y%m%d_%H%M%S).db'"
# Garder 7 jours
find "$BACKUP_DIR" -name "*.db" -mtime +7 -delete
```

### 2.6 — Media Cleanup

- Supprimer les fichiers media orphelins (pas de record en DB)
- Script `scripts/cleanup_media.py`

### 2.7 — Nginx Hardening

Dans `nginx/saas.conf` :
- `client_max_body_size 50M;` (limite upload)
- `proxy_read_timeout 60s;`
- Gzip enabled
- Cache static files (30 jours)

---

## 3. Tests (tests/test_hardening.py)

- test_health_check_ok
- test_health_check_db_down
- test_security_headers_present
- test_csp_header
- test_hsts_header
- test_rate_limit_create
- test_media_upload_size_limit

**Total : 7 tests**

---

## 4. Fichiers

| Fichier | Action |
|---------|--------|
| `app/__init__.py` | Security headers, limiter, health check |
| `scripts/backup.sh` | Créer |
| `scripts/cleanup_media.py` | Créer |
| `nginx/saas.conf` | Modifier (hardening) |
| `tests/test_hardening.py` | Créer (7 tests) |
| `pyproject.toml` | Ajouter flask-limiter, pythonjsonlogger |
