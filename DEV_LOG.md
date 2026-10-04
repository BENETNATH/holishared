# holishared — Suivi de développement

Fichier unique de référence. Tout ce qui concerne le projet vit ici.

---

## 1. Spécifications

| Item | Détail |
|------|--------|
| Nom | holishared |
| Type | SaaS de planification de vacances / événements en groupe |
| Stack | Flask + HTMX + Alpine.js, Waitress, Nginx, SQLite |
| Port | 8400 |
| Déploiement | `/opt/saas` sur `serv-ics-testing` |
| i18n | FR / EN (Flask-Babel) |
| Responsive | Mobile-first, PWA (manifest + service worker) |
| Accessibilité | WCAG 2.1 AA |
| Paiement | AUCUN (hooks freemium uniquement) |
| Notifications | Web Push (hooks, pas d'implémentation) |
| Chat | Intégré par événement (module `chat`) |
| Isolation | Chaque événement est totalement isolé |

---

## 2. Modèle d'authentification

- **Créateur** : valide par email (bloc des domaines jetables via `BLOCKED_EMAIL_DOMAINS`).
- **Invités** : accès via lien événement + code perso (8 caractères). Zéro donnée personnelle stockée.
- **Superadmin** : gestion du site (config, stats).
- Pas de compte invité persistant — le code perso suffit.

---

## 3. Architecture

```
saas/
├── app/
│   ├── __init__.py          # App factory, config, blueprints
│   ├── extensions.py        # db, login_manager, babel
│   ├── models.py            # Tous les modèles SQLAlchemy
│   ├── freemium.py          # Feature flags & limites
│   ├── auth/                # Blueprint /admin (superadmin + login)
│   ├── events/              # Blueprint /e (CRUD, invites, guest access)
│   ├── planning/            # Blueprint (activités, RSVP)
│   ├── lists/               # Blueprint (listes partagées)
│   ├── logistics/           # Blueprint (infos pratiques)
│   ├── voting/              # Blueprint (sondages)
│   ├── chat/                # Blueprint (chat par événement)
│   ├── static/
│   │   ├── css/
│   │   └── js/
│   └── templates/
│       ├── base.html
│       ├── auth/
│       ├── events/
│       ├── main/
│       └── errors/
├── nginx/saas.conf
├── systemd/saas.service
├── manage.py
├── requirements.txt
├── .env / .env.example
└── instance/                # SQLite DB
```

### Blueprints & URLs

| Blueprint | Préfixe | Rôle |
|-----------|---------|------|
| `auth` | `/admin` | Login superadmin, gestion site |
| `events` | `/e` | Création, dashboard, invites, guest join |
| `planning` | — | Activités + RSVP |
| `lists` | — | Listes partagées (courses, packing…) |
| `logistics` | — | Infos pratiques (adresse, accès…) |
| `voting` | — | Sondages / votes |
| `chat` | — | Chat par événement |

---

## 4. Modèles (models.py)

| Modèle | Table | Rôle |
|--------|-------|------|
| `Creator` | `creators` | Créateur validé par email |
| `Event` | `events` | Événement (code 6 chars, dates, lieu) |
| `Guest` | `guests` | Invité (code 8 chars, display_name, zéro PII) |
| `Activity` | `activities` | Activité planifiée (date, heure, lieu, min_headcount) |
| `ActivityRSVP` | `activity_rsvps` | RSVP (yes/no/maybe) |
| `SharedList` | `shared_lists` | Liste partagée (type: shopping, packing…) |
| `ListItem` | `list_items` | Item dans une liste (qty, assigned_to, is_done) |
| `Poll` | `polls` | Sondage (question, is_closed) |
| `PollOption` | `poll_options` | Option de sondage |
| `PollVote` | `poll_votes` | Vote (1 vote / invité / option) |
| `LogisticsItem` | `logistics_items` | Info pratique (catégorie, ordre) |
| `MediaItem` | `media_items` | Photo/vidéo + GPS + date prise |
| `MediaQuota` | `media_quotas` | Quota stockage par créateur (tier) |
| `ActivityLog` | `activity_logs` | **Tracabilité** — chaque action, visible par tous |

### ActivityLog (tracabilité)

- `actor_name` : nom d'affichage ou "Créateur"
- `actor_type` : `creator` | `guest` | `system`
- `action` : ex. `activity.created`, `guest.joined`, `poll.closed`
- `target` : ce qui a été affecté (titre, nom…)
- `details` : info complémentaire optionnelle
- `created_at` : horodatage
- **Visible par tous les participants** (créateur + invités)

---

## 5. Freemium

| Paramètre | Défaut | Env var |
|-----------|--------|---------|
| Max invités / événement | 10 | `MAX_GUESTS_PER_EVENT` |
| Max durée (jours) | 30 | `MAX_DURATION_DAYS` |
| Max événements / créateur | 3 | `MAX_EVENTS_PER_CREATOR` |
| Modules activés | planning,lists,logistics,voting | `ENABLED_MODULES` |

Fonctions dans `app/freemium.py` :
- `can_add_guest(event)`
- `can_create_event(creator)`
- `max_duration_days()`
- `is_module_enabled(name)`
- `get_limits()`
- `get_media_quota(creator)` — get/create quota
- `can_upload_media(creator, size_bytes)` — check quota
- `consume_media_quota(creator, size_bytes)` — incrément
- `release_media_quota(creator, size_bytes)` — décrément
- `set_media_tier(creator, tier)` — changement de tier

### Quota media par tier

| Tier | Quota | Prix (futur) |
|------|-------|-------------|
| free | 500 MB | 0 € |
| basic | 5 GB | 2 €/mois |
| premium | 50 GB | 5 €/mois |

---

## 6. Anti-abus

- Bloc domaines jetables (`DISPOSABLE_DOMAINS` + `BLOCKED_EMAIL_DOMAINS`)
- Rate limit création : `RATE_LIMIT_CREATE` (5/hour par défaut)
- Validation email obligatoire pour le créateur
- Code événement court (6 chars) → non-guessable
- Code invité (8 chars) → accès sans compte

---

## 7. Déploiement

| Item | Valeur |
|------|--------|
| Host | `serv-ics-testing` |
| Chemin | `/opt/saas` |
| Port | 8400 |
| WSGI | Waitress |
| Reverse proxy | Nginx (`nginx/saas.conf`) |
| Service | systemd (`systemd/saas.service`) |
| DB | SQLite (`instance/holishared.db`) |
| Logs | `logs/waitress.log` |

---

## 8. Journal des commits / ajouts

### 2026-10-04

| Heure | Action | Fichier(s) | Détail |
|-------|--------|------------|--------|
| — | Création initiale | `app/__init__.py`, `app/extensions.py`, `app/models.py`, `.env` | App factory, extensions, 11 modèles, config |
| — | Blueprint auth | `app/auth/__init__.py` | Login superadmin, bloc jetables, user_loader |
| — | Blueprint events | `app/events/__init__.py` | CRUD, dashboard, guest join, verify email, invite |
| — | Module freemium | `app/freemium.py` | 5 fonctions de contrôle |
| — | Templates base | `app/templates/base.html`, `auth/login.html`, `main/dashboard.html` | Structure HTML |
| — | Infra | `nginx/saas.conf`, `systemd/saas.service`, `manage.py`, `requirements.txt` | Déploiement |
| — | **Tracabilité** | `app/models.py` (ActivityLog) | Log de chaque action, visible par tous |
| — | **Media + quota** | `app/models.py` (MediaItem, MediaQuota), `app/freemium.py` | Partage photos/vidéos + GPS + datation, quota par tier |

### À faire (backlog)

| Priorité | Tâche | Statut |
|----------|-------|--------|
| P0 | Blueprint `planning/` (activités + RSVP) | ⬜ |
| P0 | Blueprint `lists/` (listes partagées) | ⬜ |
| P0 | Blueprint `logistics/` (infos pratiques) | ⬜ |
| P0 | Blueprint `voting/` (sondages) | ⬜ |
| P0 | Blueprint `chat/` (chat par événement) | ⬜ |
| P0 | Templates événements (dashboard, create, join, invite, mycode) | ⬜ |
| P0 | Intégrer ActivityLog dans chaque blueprint (log à chaque action) | ⬜ |
| P0 | Route `/e/<code>/log` — affichage du log de tracabilité | ⬜ |
| P1 | PWA : manifest.json + service worker | ⬜ |
| P1 | i18n : fichiers JSON fr/en | ⬜ |
| P1 | CSS responsive + WCAG 2.1 AA | ⬜ |
| P1 | Web Push hooks (notification quand activité créée) | ⬜ |
| P2 | Tests (pytest) | ⬜ |
| P2 | CI/CD | ⬜ |
| P2 | Migration SQLite → PostgreSQL (si scale) | ⬜ |

---

## 9. Décisions

| Date | Décision | Raison |
|------|----------|--------|
| 2026-10-04 | SQLite (pas Postgres) | Simplicité, un seul fichier, pas de scale initial |
| 2026-10-04 | Pas de paiement | Hooks freemium uniquement, monétisation plus tard |
| 2026-10-04 | Code invité 8 chars, zéro PII | Privacy-first, pas de compte invité |
| 2026-10-04 | HTMX + Alpine (pas React/Vue) | Léger, pas de build step, SSR natif |
| 2026-10-04 | Waitress (pas Gunicorn) | Natif Python, pas de dépendance C |
| 2026-10-04 | Tracabilité : ActivityLog dans la DB | Visible par tous, pas de log externe, auditable |

---

## 10. Variables d'environnement (.env)

```env
SECRET_KEY=
APP_DOMAIN=
APP_URL=http://localhost:8400
DATABASE_URL=sqlite:///holishared.db
SUPERADMIN_EMAIL=
SUPERADMIN_PASSWORD=
MAX_GUESTS_PER_EVENT=10
MAX_DURATION_DAYS=30
MAX_EVENTS_PER_CREATOR=3
ENABLED_MODULES=planning,lists,logistics,voting,chat
RATE_LIMIT_CREATE=5/hour
BLOCKED_EMAIL_DOMAINS=
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=
DEFAULT_LANGUAGE=fr
SUPPORTED_LANGUAGES=fr,en
SESSION_COOKIE_SECURE=false
PERMANENT_SESSION_LIFETIME=86400
```

---

## 11. Prochaines étapes immédiates

1. Écrire les 5 blueprints manquants (planning, lists, logistics, voting, chat)
2. Intégrer `ActivityLog` dans chaque blueprint (helper `log_action()`)
3. Route `/e/<code>/log` pour afficher le log de tracabilité
4. Templates événements (dashboard, create, join, invite, mycode, log)
5. PWA manifest + service worker
6. i18n fichiers
7. CSS responsive + accessibilité
