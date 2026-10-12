# Prompt — Agent de codage : lots B033 (Cartes), B034 (API agent), B035 (XLSX listes)

Tu es l'agent de codage du projet Holishared. Ton contrat est `AGENTS.md` à la
racine du repo : lis-le entièrement avant de coder. Ce prompt est ta spec pour
trois lots. Tu ne devines rien : tout est écrit ici. En cas d'ambiguïté, tu poses
la question avant de coder, tu n'inventes pas de comportement.

Travalle lot par lot, dans l'ordre B033 → B034 → B035. Chaque lot suit le
pipeline de `AGENTS.md` (spec → tests d'abord → code → tests verts → audit →
commit + CHANGELOG/TASKS/DEV_LOG).

## Contexte projet

- **Stack** : Flask 3 (app factory), SQLAlchemy, Flask-Login, Flask-Babel (FR/EN),
  HTMX + JS vanilla (`app/static/js/ui/`), CSS maison (`app/static/css/app.css`),
  SQLite, Waitress. PWA (manifest + service worker).
- **Modules** : blueprints par domaine, enregistrés dans `app/__init__.py` via le
  dict `module_blueprints`, activés par `ENABLED_MODULES` (env var).
- **Auth** : créateur (email) + invités (code, zéro PII). Chaque événement est
  totalement isolé.
- **i18n** : `SUPPORTED_LANGUAGES` (env, défaut `fr,en`), switch via `?lang=`,
  session, catalogs compilés dans `translations/<locale>/LC_MESSAGES/messages.mo`
  (source `.po` à côté). Lis `app/i18n.py` (filtres `label`/`choices`, formats
  Babel) et `app/__init__.py` (locale_selector + `_reset_locale_on_switch`).
- **Conventions** : commits atomiques Conventional Commits, TDD, i18n via `_()`
  sur tout texte utilisateur, WCAG 2.1 AA, rate limiting sur les endpoints de
  création, pas de secret dans le code, `datetime.utcnow()`.

---

# LOT B033 — Module Cartes (maps)

## Objectif

Ajouter un **module « Cartes »** qui permet, pour un événement :
1. de visualiser sur une carte le lieu de l'événement et les lieux des activités ;
2. de rechercher un lieu (nom, adresse, ville) et de l'ajouter à l'événement ;
3. de cliquer sur la carte pour récupérer une adresse (reverse geocoding) et
   pré-remplir un lieu.

## Choix techniques (imposés)

- **Carte** : Leaflet, **auto-hébergé** (`leaflet.js` + `leaflet.css` + assets
  dans `app/static/js/` et `app/static/css/`, pas de CDN).
- **Tuiles** : OpenStreetMap standard (`https://tile.openstreetmap.org/{z}/{x}/{y}.png`),
  attribution OSM obligatoire. Échec de chargement → message d'erreur i18n dans la
  zone carte, pas d'écran blanc.
- **Géocodage** : Nominatim (gratuit, sans clé). **Jamais appelé depuis le client** :
  proxy serveur (endpoint Flask) avec `User-Agent` identifiable (env var
  `MAPS_USER_AGENT`, défaut `holishared/1.0 (self-hosted)`), rate limiting
  (1 req/s par IP), timeout 5 s, **cache en base** (modèle `Place` ci-dessous).
  Erreur Nominatim → JSON d'erreur propre, message i18n côté UI, pas de retry.
- **Aucune clé API, aucun service payant.**

## Modèle de données

Nouveau modèle `Place` dans `app/models.py` :

```
Place
  id            str(32) PK (secrets.token_hex(16))
  event_id      FK events.id, nullable=False, cascade delete
  label         str(200), nullable=False      # nom affiché ("Gîte de Marie")
  address       str(300), default=""          # adresse issue du géocodage
  lat           float, nullable=False
  lng           float, nullable=False
  source        str(20), default="nominatim"  # "nominatim" | "manual"
  created_at    datetime
```

- Relation `Event.places` (backref, `cascade="all, delete-orphan"`).
- Migration idempotente dans `app/migrations.py` (même pattern que les
  migrations existantes — lis-les avant).
- `Event.location` et `Activity.location` (textes libres existants) ne sont PAS
  modifiés : géocodés **à la volée** quand ils ne correspondent à aucune `Place`
  (résultat non persisté sauf ajout explicite).

## Routes (blueprint `maps`, prefix `/e/<event_id>/maps`)

Même pattern d'accès à l'événement que les autres modules (lis `app/context.py`
et `app/planning/__init__.py`).

1. `GET /e/<event_id>/maps` — page carte : marqueurs (lieu de l'événement,
   `Place`, activités avec `location`), panneau latéral (liste sous la carte en
   mobile) avec label/adresse/lien activité, barre de recherche (debounce 300 ms,
   min 3 caractères), bouton « Ajouter ce lieu » sur chaque résultat, clic carte →
   reverse geocoding → popup + bouton d'ajout.
2. `GET /e/<event_id>/maps/search?q=<query>` — JSON : max 5 résultats
   `{label, address, lat, lng}` ; `q` < 3 caractères → `{"results": []}`.
3. `POST /e/<event_id>/maps/places` — crée une `Place` (CSRF, rate limité).
   Validation : label non vide, lat ∈ [-90, 90], lng ∈ [-180, 180].
4. `GET /e/<event_id>/maps/reverse?lat=..&lng=..` — JSON : 1 résultat
   `{label, address, lat, lng}`.
5. `DELETE /e/<event_id>/maps/places/<place_id>` — supprime (CSRF, rate limité),
   réservée au créateur (pattern de droits des autres modules).

Enregistrement dans `module_blueprints` (`"maps": maps_bp`) + `"maps"` dans
`ENABLED_MODULES` par défaut (`.env`, `.env.example`, défaut `app/__init__.py`) +
lien dans `app/templates/_event_nav.html` (icône, pattern des autres modules).

## Front-end

- `app/static/js/ui/maps.js` (pattern de `planning.js` / `meals.js`).
- `fitBounds` sur les marqueurs ; marqueurs différenciés **sans recourir à la
  couleur seule** (WCAG) ; popups accessibles (focus clavier, `aria-label`).
- Responsive : carte pleine largeur en mobile, panneau en dessous.
- Tout texte utilisateur via `_()` ; chaînes ajoutées dans les catalogs FR et EN
  (puis compilation `.mo` selon le pattern du projet).

## Tests (TDD, aucun appel réseau — Nominatim mocké)

`tests/test_maps.py` (fixtures `conftest.py`) :
- `Place` : création, cascade delete, migration idempotente (pattern
  `test_costs_migration.py`).
- Page `/maps` : 200 participant ; 404/403 inconnu (pattern existant) ; module
  désactivé → route inexistante (pattern `test_module_gating.py`).
- `/search` : q < 3 → vide ; mock → ≤ 5 résultats ; Nominatim en erreur → JSON
  d'erreur propre (pas de 500).
- `POST /places` : création valide ; lat hors bornes → rejet ; CSRF absent →
  rejet ; rate limit → 429.
- `DELETE /places/<id>` : créateur OK, invité non ; inexistante → 404.
- `/reverse` : mock → adresse ; coordonnées invalides → erreur propre.
- i18n : chaînes présentes dans les catalogs FR et EN (pattern
  `test_i18n_catalog.py` / `test_i18n_guard.py`).

## Hors périmètre B033

Pas d'itinéraires/distances, pas de cache de tuiles, pas de géocodage alternatif,
pas de modification de `Event.location`/`Activity.location`, pas de nouvelle
dépendance Python si le client HTTP déjà utilisé suffit (vérifie `requirements.txt`).

---

# LOT B034 — Clés API par utilisateur d'événement (accès agent)

## Objectif

Permettre à **l'agent de l'utilisateur** (IA / script) d'interagir avec
**toutes les fonctions** de l'application via l'API REST, avec une **clé API
par utilisateur d'événement** (créateur OU invité). L'API est le premier
client visé : elle doit être découvrable et utilisable par un agent sans
connaître le code.

Chaque utilisateur d'un événement peut générer des clés API qui lui donnent
un accès programmatique (REST JSON) à toutes les fonctions de l'événement,
avec les mêmes droits que son rôle dans l'UI.

### Modèle de données

```
ApiKey
  id              str(32) PK
  event_id        FK events.id, nullable=False, ondelete CASCADE
  owner_guest_id  FK guests.id, nullable=True, ondelete CASCADE   (clé d'un invité)
  owner_creator_id FK creators.id, nullable=True, ondelete CASCADE (clé du créateur)
  key_hash        str(64), unique, nullable=False  (sha256 hex de la clé)
  key_prefix      str(12), nullable=False          (préfixe affiché, ex. "hs_ab12cd34…")
  label           str(100), default=""             (libellé choisi par l'utilisateur)
  created_at      datetime
  last_used_at    datetime, nullable
  revoked_at      datetime, nullable
```

- Contrainte : exactement un des deux owner non nul (check en application).
- **Nettoyage (règle fondamentale)** : la clé est 100 % liée à l'événement ET
  à son owner —
  - suppression de l'événement → toutes les clés de l'événement supprimées
    (cascade event_id) ;
  - suppression / retrait d'un invité de l'événement → SES clés supprimées
    (cascade owner_guest_id) ;
  - suppression du créateur → ses clés supprimées (cascade owner_creator_id).
  Après chaque suppression, une clé orpheline doit être impossible : un
  appel API avec une clé dont l'owner ou l'événement a disparu renvoie 401
  (hash introuvable), jamais 500.
- Format de clé : `hs_` + `secrets.token_hex(24)` (49 caractères).
- **La clé complète n'est jamais stockée** (hash seul) et n'est affichée
  **qu'une seule fois**, à la création.

### Routes de gestion des clés (UI, blueprint existant `events` ou nouveau
blueprint `apikeys` — ton choix, documente-le)

1. `POST /e/<event_id>/api-keys` — crée une clé (CSRF, rate limité). Créateur ou
   invité de l'événement. Champ optionnel `label`. Réponse : clé complète +
   `key_prefix` (page de confirmation avec avertissement « ne sera pas
   réaffiché »).
2. `GET /e/<event_id>/api-keys` — liste SES clés (pas celles des autres) :
   `key_prefix`, `label`, `created_at`, `last_used_at`, `revoked_at`.
3. `DELETE /e/<event_id>/api-keys/<key_id>` — révoque SA clé (CSRF, rate limité).

### Découvrabilité (pensé pour un agent)

- `GET /api/events/<event_id>/index` — JSON : liste de tous les endpoints de
  l'événement avec méthode, chemin, description courte et schéma des champs
  (généré depuis les routeurs, pas dupliqué à la main).
- `GET /api/events/<event_id>` inclut un champ `api` : résumé des endpoints
  disponibles + rappel du format d'auth.
- Erreurs JSON structurées : `{"error": "…", "detail": "…"}` avec code HTTP
  explicite (400 validation, 401 auth, 403 droits, 404 inconnu, 429 rate).
- `GET /api/health` — sans auth : `{"ok": true, "version": "…"}`.

### API REST (blueprint `api`, JSON uniquement, prefix `/api`)

**Authentification** : header `Authorization: Bearer hs_…` → hash → clé →
événement + owner. Droits = rôle de l'owner dans l'événement (créateur : tous
les droits ; invité : mêmes droits que l'UI). Clé inconnue/révocquée → 401 ;
clé valide mais action non autorisée pour le rôle → 403 ; événement inconnu →
404. `last_used_at` mis à jour (throttlé, pas à chaque requête).

**Endpoints v1** (miroir des modules ; mêmes règles de validation que l'UI,
mêmes messages d'erreur en JSON `{"error": "…"}`) :

- `GET /api/events/<event_id>` — infos événement (titre, dates, lieu, participants)
- `GET|POST /api/events/<event_id>/activities` ;
  `POST /api/events/<event_id>/activities/<activity_id>/rsvp`
- `GET|POST /api/events/<event_id>/meals`
- `GET|POST /api/events/<event_id>/lists` ;
  `GET|POST /api/events/<event_id>/lists/<list_id>/items`
- `GET|POST /api/events/<event_id>/logistics`
- `GET|POST /api/events/<event_id>/polls` ;
  `POST /api/events/<event_id>/polls/<poll_id>/vote`
- `GET|POST /api/events/<event_id>/chat`
- `GET|POST /api/events/<event_id>/costs`

**Rate limiting** : par clé (60 req/min, 429 au-delà).

**Sécurité** : pas de HTML dans les réponses API ; pas de fuite d'info entre
événements (une clé ne sert QUE son événement) ; validation stricte des corps
JSON (schémas identiques aux formulaires UI) ; CSRF ne s'applique pas aux
routes API (auth par bearer), mais le rate limiting oui.

### Tests

`tests/test_apikeys.py` + `tests/test_api.py` :
- Clé : création (créateur et invité), affichée une seule fois, hash stocké,
  révocation, cascade delete avec l'événement, migration idempotente.
- Nettoyage : suppression d'un invité → ses clés disparaissent et ses anciens
  appels renvoient 401 ; suppression de l'événement → toutes les clés
  disparaissent ; aucun état orphelin (pas de 500).
- Découvrabilité : `/index` liste tous les endpoints ; `/health` sans auth.
- Auth API : clé invalide → 401 ; révoquée → 401 ; événement inconnu → 404 ;
  clé de l'événement A sur l'événement B → 404/403 (pas de fuite).
- Droits : invité ne peut pas faire les actions créateur (suppression
  créateur-only) → 403 ; créateur OK.
- CRUD : un endpoint par module (au minimum activities, lists, meals, chat) —
  création valide + validation rejetée.
- Rate limit : 429 après 60 req.

## Hors périmètre B034

Pas d'OAuth, pas de refresh token, pas de scopes fins par endpoint (le rôle
fait le scope), pas d'API pour les superadmin/landing, pas de webhook,
pas d'ajout de langue.

---

# LOT B035 — Import/Export XLSX des listes

## Objectif

Exporter et importer les listes partagées (`SharedList`/`ListItem`) au format
`.xlsx`.

## Export

- `GET /e/<event_id>/lists/export.xlsx` — toutes les listes de l'événement :
  **une feuille par liste** (nom de feuille = titre de la liste, tronqué à 31
  caractères, collisions suffixées `-2`, `-3`…).
- Colonnes (en-tête ligne 1, i18n de l'en-tête selon la langue active) :
  `Section | Item | Quantité | Assigné à | Fait`
  (mapping : `section`, `name`, `quantity`, `assigned_to`, `is_done` →
  « Oui »/« Non » localisés).
- `GET /e/<event_id>/lists/<list_id>/export.xlsx` — une seule liste (1 feuille).
- Contenu UTF-8, accents préservés. Fichier généré en mémoire (BytesIO),
  téléchargement nommé `listes-<code-événement>.xlsx` / `<titre-liste>.xlsx`.

## Import

- `POST /e/<event_id>/lists/import` (multipart : fichier `.xlsx` + champ
  optionnel `title` pour le titre de la nouvelle liste, défaut = nom du fichier
  sans extension).
- Format attendu : même schéma que l'export (en-têtes reconnus FR/EN,
  insensible à la casse et aux accents). Une feuille = une liste (toutes les
  feuilles du classeur sont importées, sauf feuille nommée `README`).
- Lignes : `name` requis (ligne ignorée + comptée sinon), `quantity` défaut
  « 1 », `is_done` reconnu via les valeurs localisées (« oui »/« yes »/« x »/
  « true »…), `assigned_to` texte libre (pas de résolution d'identité).
- **Rapport d'import** : flash i18n récapitulatif (X listes, Y items importés,
  Z lignes ignorées avec numéros).
- Limites : max 500 lignes par feuille, max 20 feuilles, fichier max 2 Mo.
  Dépassement → erreur propre i18n, rien n'est importé (transaction).

## Dépendance

- `openpyxl` (ajout à `requirements.txt` ET `pyproject.toml` — règle AGENTS.md).
- Génération ET lecture via openpyxl (pas d'Excel requis côté client).

## Sécurité / accessibilité

- CSRF + rate limiting sur l'import ; validation du MIME/extension (`.xlsx`
  uniquement, pas de `.xls` legacy) ; pas d'exécution de contenu (pas de
  formules : lire les valeurs, ignorer les cellules formule).
- Input fichier avec `<label>` (WCAG), message d'erreur accessible.
- i18n FR/EN de tous les messages (boutons, flash, en-têtes).

## Tests

`tests/test_lists_xlsx.py` :
- Export : contenu (valeurs, accents, en-têtes localisés), une feuille par
  liste, collisions de noms de feuilles, export single-list.
- Import : round-trip export → import (identique), en-têtes FR/EN,
  lignes invalides ignorées + rapport, `is_done` multi-locale, limites
  (500/20/2 Mo) → rien importé, fichier non-xlsx → rejet, CSRF absent → rejet.
- Droits : participant OK, inconnu 404/403 (pattern existant).
- i18n : messages présents dans les 2 catalogs.

## Hors périmètre B035

Pas d'import/export des autres modules (activités, repas, coûts), pas de
`.csv`, pas de mapping personnalisé de colonnes, pas de mise à jour d'une liste
existante (l'import crée toujours de nouvelles listes).

---

# Définition de « terminé » (par lot)

1. `ruff check . && ruff format --check .` → vert
2. `mypy app/` → vert
3. `pytest` → vert (nouveau + régression)
4. `CHANGELOG.md`, `TASKS.md` (lot ✅), `DEV_LOG.md` mis à jour
5. Commits atomiques Conventional Commits (scopes : `maps`, `i18n`, `api`, `lists`)
6. Vérification manuelle documentée dans le commit final du lot
