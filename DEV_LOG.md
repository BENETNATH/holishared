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
| — | **B003 Planning** | `app/planning/__init__.py`, `app/utils.py`, `app/models.py` (ActivityLog), `app/templates/planning/` | 5 routes (index/create/edit/delete/rsvp), helper log_action(), 45 tests verts |

### 2026-10-06 — B017 Socle Tailwind, shell mobile & outillage UI

| Action | Fichier(s) | Détail |
|--------|------------|--------|
| Build Tailwind v4 | `package.json`, `app/static/src/*.css`, `app/static/css/app.css` | CSS compilé commité ; `main.css` → `src/legacy.css` (couche `legacy`) |
| Tokens, kit `ui-*`, icônes | `theme.css`, `base.css`, `components.css`, `app/icons.py`, `app/ui.py`, `_components/ui.html` | 71 icônes Lucide, macros `field`/`sheet`/`empty_state` |
| Shell + JS partagé | `app/templates/base.html`, `app/static/js/ui/*.js` | Barre du bas, feuille « Plus », barre latérale, toasts, thème sans flash, `JS_STRINGS` |
| Sécurité | `events/members.html`, `app/ui.py` | Codes personnels visibles du créateur seul ; « Participants » créateur seul |
| PWA | `/sw.js`, `/offline`, `manifest.json`, `pwa.js` | Cache versionné par empreinte, page hors ligne autonome |
| Catalogue | `/_ui`, `main/ui_catalog.html` | Dev uniquement (`UI_CATALOG_ENABLED`) |
| Outillage | `scripts/ui/*` | Graine, serveur de démo, garde CDP (`ui:check`), auto-contrôle (`ui:selftest`) |

Écarts de spec : textes de démonstration du catalogue traduits au commit du catalogue (pas au commit i18n) ; `.meal-chip` passe en `position: relative` (cause réelle du débordement des pastilles repas : l'input masqué absolu échappait au défilement interne) ; `ruff format --check .` et `mypy app/` n'étaient déjà pas verts sur le dépôt avant le lot (27 fichiers historiques non formatés, 17 erreurs mypy, inchangées par le lot) : seuls les fichiers du lot sont tenus propres.

### 2026-10-06 — B029 Contexte d'événement & identité participant unique

| Action | Fichier(s) | Détail |
|--------|------------|--------|
| Contexte unique | `app/context.py`, `app/__init__.py` | `load_event_context(code, require=…)`, cache sur `g` vidé par `before_request`, droits `can_edit`/`can_delete`, `log_event` |
| Identité unique | `app/utils.py`, `app/migrations.py` | Créateur = `Guest` (sans foyer implicite hors `verify`/`join`) ; migration idempotente, `check_identity` en lecture seule |
| Codes d'accès | `app/access.py`, `app/extensions.py`, `app/events/__init__.py` | Résolution (événement avant créateur), échecs seuls comptés par IP et par (IP, événement), repli mémoire, journal `app.security` sans le code |
| Modules | `events`, `planning`, `meals`, `lists`, `logistics`, `voting`, `chat`, `costs`, `media` | Les 8 copies de helpers supprimées ; réponses d'erreur par gabarits ; F32 corrigé |

**Retour arrière**
1. Code seul : l'ancien code fonctionne sur des données migrées (un `Guest.id` est un identifiant valide partout) ; redéployer la version précédente suffit.
2. Données : arrêter l'application, puis copier la sauvegarde sur la base et redémarrer. Local : `cp instance/backups/pre-identity-<horodatage>.db instance/holishared.db`. Docker : `docker compose stop app`, puis `docker compose run --rm --no-deps --entrypoint sh app -c 'cp /app/instance/backups/pre-identity-<horodatage>.db /app/instance/holishared.db'`, puis `docker compose start app`. La sauvegarde n'existe que si une migration effective a eu lieu.
3. Vérification après déploiement : `docker compose exec app python -m app.migrations check`.

**Rétention des sauvegardes** : au plus 3 fichiers `pre-identity-*.db` dans `instance/backups/` (hors médias et hors export ZIP), et un fichier de plus de 30 jours est supprimé au premier démarrage, `manage.py migrate` ou nouvelle sauvegarde qui suit son 30e jour. Plafond assumé : un processus qui tourne sans redémarrage peut conserver la sauvegarde plus longtemps.

Écarts de spec : `my_code` et `guest_access` passent par `load_event_context(require="none")` dès le commit des codes (D11, D14, D15 actifs un commit plus tôt) ; deux variables d'environnement ajoutées pour l'outillage et les tests, `INSTANCE_PATH` (dossier instance) et `SKIP_STARTUP_MIGRATION` (utilisée par `python -m app.migrations check` pour rester en lecture seule) ; le purge/migration au démarrage partagent le même `try/except` ; nouveaux messages `verify` (code créateur) sans traduction EN compilée (B018).

### 2026-10-06 — B018 Internationalisation complète (FR/EN)

| Zone | Fichiers | Résumé |
|---|---|---|
| Libellés et formats | `app/i18n.py`, `app/__init__.py`, gabarits costs/meals/planning/logistics/events | Registre unique de libellés, filtres Babel (`money`, `number`, `time`, `date_short`…), `strftime` et `"%.2f"` supprimés des gabarits |
| Erreurs par champ | `app/forms.py`, `_components/ui.html`, formulaires events/planning/logistics/voting/lists | `FormErrors` + macros d'accessibilité ; `join` affiche ses erreurs dans la page |
| Messages | modules `events`, `costs`, `media`, `auth`, `planning` | `_()` partout, placeholders, `ngettext` (durée), vouvoiement ; nouveaux messages « Date requise. », « Heure invalide. » |
| E-mails | `app/tasks.py`, `app/events/__init__.py` | `lang="fr"`, `Translations.load`, `EmailMessage` ; l'invitation part dans la langue de l'invitant |
| Catalogue | `scripts/i18n.py`, `babel.cfg`, `translations/` | `extract`/`compile`/`check` ; Babel saute les dossiers en `_` : `_components/` est passé en entrée explicite |
| Tests | `test_i18n*.py`, `test_forms.py`, `test_tasks.py` | Garde i18n sur 31 pages x 2 langues x 2 rôles |

Écarts de spec : pas de migration des acteurs `@creator`/`@system` (caduque depuis B029 : le créateur est un `Guest`) ; le registre du journal ne sert qu'au libellé court (phrases complètes : B020) ; `Media` (libellé de navigation) reste tel quel, des tests du shell l'attendent ; `main/dashboard.html` (gabarit mort) supprimé ; `PaymentRequest.amount` ajouté (bogue préexistant) ; `join` renvoie 429 au-delà de 20 créations/heure/IP.

Requêtes de restauration/vérification : `python scripts/i18n.py check` (catalogue), `python scripts/i18n.py extract && python scripts/i18n.py compile` après tout nouveau texte ; EN : renseigner le `.po` EN (le FR est la langue source, `msgstr` FR vides).

Audit B017/B029 : constats 1 à 6 corrigés (variables `INSTANCE_PATH` et `SKIP_STARTUP_MIGRATION` documentées dans `.env.example`, seule la valeur `1` désactive la migration) ; constat 7 (`ruff format` sur les fichiers préexistants) volontairement ignoré.

### 2026-10-06 — B020 (partie A) Accueil, « Mes événements », menu « Événement »

- `events.dashboard` : `event_status()` (phase + libellés traduits) partagé avec `events.index` ; le tableau de bord ne charge plus que 3 messages (`RECENT_MESSAGES`) et 5 infos (`INFOS_ON_HOME`) ; liens conditionnés par `current_app.blueprints` (aucun `BuildError`).
- « Pour moi » : `lists.home_items(ctx)` (par `Guest.id`) + partial `events/_my_items.html` ; le formulaire HTMX cible `#my-items` (`outerHTML`) ; l'état replié « Déjà pris » se referme après un échange (accepté).
- Partager = `APP_URL` + `events.guest_access` (`/e/<code>/join`), jamais le tableau de bord ; même lien dans le menu (`NavItem.copy`).
- Suppression : confirmation par dialogue `data-confirm` renforcé (titre de l'événement dans le message) ; la route `delete_event` est inchangée.
- Reste pour la partie B : 20.3 Participants, 20.4, 20.5 Journal, 20.6 identité créateur.

### 2026-10-07 — B022 Repas

- `Meal` : `position` + index `ix_meal_cell (event_id, date, slot, position)`, plus d'unicité de case ; `MAX_MEALS_PER_CELL = 6` ; `Meal.ordering()` (jour, midi avant soir, position) utilisé par la grille, le tableau de bord et les chips de listes.
- Migration `meals` : reconstruction de table en une transaction (`BEGIN` manuel sous pysqlite), `ROW_NUMBER()` pour les positions, détection par `PRAGMA index_list/index_info` ; exécutée avant `_purge_expired_events` (la purge charge les repas en cascade).
- Routes : `move` = avant `before_id` sinon fin de case (même case = réordonnancement) ; `swap` exige `can_edit` sur les deux repas ; HTMX : 200/422 + fragment, `HX-Trigger {"meals:message": {message, tone}}` lu par `ui/meals.js` (fetch, pas `hx-*`).
- UI : une seule structure DOM (jours en sections ; < 1024 px un seul visible, sélection côté client), `ui/meals.js` seul module de la page ; poignée `touch-action: none`.
- Garde UI : action `drag` (CDP `Input.dispatchMouseEvent`, id gardé dans `sessionStorage`) ; 359 runs verts.

### À faire (backlog)

| Priorité | Tâche | Statut |
|----------|-------|--------|
| P0 | Blueprint `planning/` (activités + RSVP) | ✅ B003 |
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
