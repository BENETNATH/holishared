# Holishared

Planification de vacances / événements en groupe. Chaque événement est totalement
isolé : le créateur invite des proches qui rejoignent via un lien + un code
personnel, sans compte ni mot de passe.

## Stack

- **Flask 3.x** — WSGI app
- **HTMX 1.9** — HTML over HTTP (pas de SPA)
- **Alpine.js 3.x** — interactivité légère
- **Waitress** — serveur WSGI de production
- **Nginx** — reverse proxy, TLS, headers de sécurité
- **Redis 7** — rate limiting (Flask-Limiter)
- **SQLite** — base de données (volume Docker)
- **Babel** — i18n (FR / EN)

## Modules

Chaque module est activable via `ENABLED_MODULES` (freemium) :

- `planning` — grille d'activités (déjeuner 12h, dîner 19h) + RSVP
- `lists` — listes de courses partagées (3 états : non réclamé / réclamé / couvert)
- `logistics` — infos pratiques collaboratives
- `voting` — sondages
- `media` — partage de médias (quota par créateur)
- `chat` — chat intégré par événement
- `costs` — partage des frais par « groupe » (pondération adulte/enfant)

## Déploiement Docker (recommandé)

```bash
cp .env.example .env
# Éditer .env : SECRET_KEY, SUPERADMIN_EMAIL, SUPERADMIN_PASSWORD, NGINX_PORT
docker compose up -d --build
```

Trois services sur le réseau `saas_net` :

- `nginx` — port `${NGINX_PORT:-8080}:80`
- `redis` — 7-alpine, 64 Mo LRU
- `app` — Waitress sur 8400 (interne uniquement)

Volumes : `holishared_data` (SQLite), `holishared_logs`, `holishared_redis`.

## Déploiement local (dev)

```bash
python manage.py init      # venv + deps + DB
python manage.py run       # serveur dev (localhost, sans debug)
```

## CLI

```
python manage.py init         # venv + deps + DB
python manage.py run          # serveur dev (localhost, sans debug)
python manage.py start        # production (Waitress)
python manage.py stop         # arrêter le serveur
python manage.py status       # état du serveur
python manage.py db-init      # créer les tables
python manage.py migrate      # appliquer les migrations de schéma
python manage.py fk-check     # rapport des lignes orphelines (lecture seule, sans réparation)
python manage.py db-shell     # shell SQLite
python manage.py deploy       # nginx + systemd (hors Docker, nécessite root)
python manage.py logs         # tail des logs
python manage.py reset-admin  # générer un nouveau mot de passe superadmin
```

## Sauvegardes avant migration et restauration

Avant une migration qui écrit des lignes existantes, l'application copie la base dans
`instance/backups/pre-<étape>-<horodatage>.db` (étapes : `pre-meals`, `pre-lists`, `pre-costs`,
`pre-polls`, `pre-identity` ; fichiers en droits 0600). Rotation par étape : les 3 plus récentes de
chaque préfixe sont conservées, et aucune sauvegarde de moins de 30 jours n'est jamais supprimée.

Restaurer l'état d'avant la mise à jour :

```bash
# 1. arrêter le service (docker compose stop app, ou python manage.py stop)
# 2. choisir la sauvegarde la plus ancienne de la mise à jour (ex. pre-meals-…)
ls -1 instance/backups/
# 3. remplacer la base et supprimer les fichiers WAL résiduels
cp instance/backups/pre-meals-<horodatage>.db instance/holishared.db
rm -f instance/holishared.db-wal instance/holishared.db-shm
# 4. redémarrer avec l'ancienne version du code
```

## Modèle d'authentification

- **Superadmin** — seul login (email + mot de passe), voit tous les événements.
- **Créateur** — lien de vérification par email (3 jours) → définit un code
  personnel (4-8 caractères) + pseudo + invitations → événement actif.
- **Invité** — lien d'événement + code personnel. Aucun mot de passe.

Cycle de vie : un événement non vérifié est auto-supprimé après 3 jours ; un
événement terminé est auto-supprimé après 30 jours (purge au démarrage de l'app).

## Confidentialité des emails

Par défaut, les emails ne sont **pas** conservés. Le créateur peut cocher
« conserver mon email » à la vérification pour activer la récupération de code
(`/recover`). Les emails d'invitation sont envoyés puis effacés.

## Structure

```
saas/
├── .env / .env.example   # configuration
├── manage.py             # CLI
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── app/
│   ├── __init__.py       # app factory + purge des événements expirés
│   ├── extensions.py     # DB, Login, Limiter
│   ├── models.py         # 17 modèles
│   ├── freemium.py       # limites + quota médias
│   ├── auth/             # login superadmin
│   ├── main/             # landing, dashboard
│   ├── events/           # création, vérification, dashboard, join
│   ├── planning/ lists/ logistics/ voting/ media/ chat/ costs/
│   ├── templates/        # Jinja2 + HTMX + Alpine
│   └── static/
├── nginx/saas.conf       # reverse proxy
├── systemd/saas.service  # unit (déploiement hors Docker)
├── translations/         # i18n FR/EN
└── tests/                # 215 tests
```
