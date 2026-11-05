# Holishared

Planification de vacances / événements en groupe. Chaque événement est totalement
isolé : le créateur invite des proches qui rejoignent via un lien + un code
personnel, sans compte ni mot de passe.

> ⚠️ **Ce dépôt n'est plus maintenu activement.**
> Avant tout déploiement en production, il convient de réaliser un **audit de
> sécurité** complet (recherche de CVE sur les dépendances, revue du code,
> configuration TLS, durcissement).

📹 [Voir la démo](https://github.com/BENETNATH/holishared/blob/main/holishared-demo.mp4)

## Licence

**MIT** — usage libre (y compris commercial), seule condition : conserver le
copyright et la notice de licence. Voir [LICENSE](LICENSE).

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
- `meals` — couverture des repas par liste
- `lists` — listes de courses partagées (3 états : non réclamé / réclamé / couvert, import/export XLSX)
- `logistics` — infos pratiques collaboratives
- `voting` — sondages
- `media` — partage de médias (quota par créateur)
- `chat` — chat intégré par événement
- `costs` — partage des frais par « groupe » (pondération adulte/enfant)

Outre l'interface, chaque événement expose une **API REST** (`/api/v1`) en lecture + écriture
limitée, authentifiée par clés par participant (`apikeys`, lot B034), et un **feed iCal** en
lecture (`ics`, lot B037).

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

## Notifications push

Web Push (VAPID) : message de chat, nouveau sondage et demande de remboursement, par appareil, sur
abonnement du participant (« Mon profil » > « Notifications »). Rien n'est demandé au chargement :
la permission du navigateur n'est sollicitée qu'au geste de l'utilisateur.

- **Clés** : `python manage.py init` les génère (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CLAIMS_SUBJECT`
  dans `.env`). Sans clés, la section affiche « Notifications indisponibles sur ce serveur » : aucune erreur.
- **Envoi** : tâche RQ `send_push` (Redis + worker). Sans Redis ou en cas d'erreur, l'envoi est abandonné et journalisé.
  Docker : le service `worker` reçoit `VAPID_PRIVATE_KEY`, `VAPID_CLAIMS_SUBJECT`, `DATABASE_URL` et le volume
  `holishared_data` (suppression des abonnements expirés 404/410), plus `SKIP_STARTUP_MIGRATION=1`.
- **Payload** : nom de l'événement, texte tronqué à 90 caractères (ou « Nouveau message de X » sans aperçu), lien profond.
  Jamais d'e-mail ni de montant.
- **Tester avec Chrome** : HTTPS ou `http://localhost`, ouvrir `/e/<code>/me`, activer l'interrupteur et accepter,
  poster un message avec un autre participant ; DevTools > Application > Service Workers > « Push » pour simuler.
- **iOS** : la permission n'existe que pour l'application installée (iOS 16.4+, Partager > « Sur l'écran d'accueil »),
  la page l'explique ; ce parcours n'est pas testable en CI.

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
│   ├── models.py         # 24 modèles
│   ├── freemium.py       # limites + quota médias
│   ├── context.py        # contexte d'événement + droits centralisés
│   ├── api/              # API REST v1 (clés par participant)
│   ├── ics.py            # feed iCal en lecture
│   ├── push.py           # Web Push (tâche RQ send_push)
│   ├── auth/             # login superadmin
│   ├── main/             # landing, dashboard
│   ├── events/           # création, vérification, dashboard, join
│   ├── planning/ meals/ lists/ logistics/ voting/ media/ chat/ costs/
│   ├── templates/        # Jinja2 + HTMX + Alpine
│   └── static/
├── nginx/saas.conf       # reverse proxy
├── systemd/saas.service  # unit (déploiement hors Docker)
├── translations/         # i18n FR/EN
└── tests/                # 2201 tests
```
