# B034 — Clés API par utilisateur d'événement (accès agent)

- **Statut** : spec à valider (lot B034 du programme `specs/prompt-lots-B033-B035.md`)
- **Références** : `AGENTS.md` (contrat, pipeline, définition de « terminé ») ; section « LOT B034 » de `specs/prompt-lots-B033-B035.md` (source spec)
- **Lecteur visé** : un agent de codage au contexte vierge. Il ne voit que cette spec, les tests du lot et `AGENTS.md`. Tout ce qu'il faut est ici.
- **Périmètre** : B034 uniquement — clés API + API REST. **Hors périmètre** : B033 (cartes) et B035 (XLSX).

> **Note de lecture** : cette spec est le contrat. Chaque exigence est concrète et testable.
> Les ambiguïtés de la source spec sont résolues et documentées au §12. Les fichiers et
> fonctions cités existent dans le code actuel ; l'agent localise par le **texte cité**
> (nom de fonction, variable, libellé), jamais par un numéro de ligne.

---

## 1. Contexte, objectifs, périmètre

### 1.1 Objectifs

1. **Clé API par utilisateur d'événement** : le créateur OU un invité d'un événement peut
   générer des clés API qui lui donnent un accès programmatique (REST JSON) à toutes les
   fonctions de l'événement, **avec les mêmes droits que son rôle dans l'UI**.
2. **API découvrable** : un agent (IA / script) doit pouvoir découvrir et utiliser l'API
   sans connaître le code : index des endpoints, résumé d'auth, health.
3. **Sécurité** : hash-only storage, clé montrée une seule fois, isolation stricte entre
   événements, pas de HTML, validation stricte, rate limiting par clé, jamais de 500 sur
   une clé orpheline.

### 1.2 Constats (vérifiés dans le code)

1. **Modèles** (`app/models.py`) : `Creator`, `Event`, `Guest` existent. `Event.id` est un
   `str(32)` (`secrets.token_hex(16)`) ; `Event.code` est un `str(6)` unique
   (`generate_event_code`). `Guest.id` est un `str(32)` ; `Guest.creator_id` (nullable)
   identifie le participant créateur ; `Guest.is_active` (bool) porte le retrait
   (désactivation, pas de suppression physique). `PushSubscription` (`app/models.py`) est
   le modèle de référence pour les FK `ondelete="CASCADE"` + `index=True` et la cascade
   ORM `cascade="all, delete-orphan"`.
2. **Droits** (`app/context.py`) : la table `_RIGHTS` (type → (règle édition, règle
   suppression, colonne d'auteur)) et `EventContext.can_edit(obj)` / `can_delete(obj)` /
   `is_creator` centralisent les droits. `EventContext` est construit par
   `load_event_context(code, require=...)` à partir de la **session** (flask-login pour le
   créateur, `session["guest_<code>"]` pour l'invité). `actor_for(participant)` et
   `get_or_create_creator_participant(event, creator)` résolvent l'acteur et le participant
   créateur canonique. **C'est ce module que l'API réutilise** (§6.3) : l'API ne
   réimplémente pas les droits, elle construit un `EventContext` depuis l'owner de la clé.
3. **App factory** (`app/__init__.py`) : `create_app()` enregistre les blueprints core
   (`main`, `push`, `auth` sous `/admin`, `events` sous `/e`) puis les **modules** via le
   dict `module_blueprints` filtré par `app.config["ENABLED_MODULES"]` (env, défaut
   `planning,meals,lists,logistics,voting,media,chat,costs`). `limiter.init_app(app)`
   (Flask-Limiter, `app/extensions.py`, `key_func=get_remote_address`,
   `in_memory_fallback_enabled`, `swallow_errors`). Un `/health` (B015) existe déjà
   (JSON `{"status","db","disk","uptime_s"}`) — **distinct** du nouveau `/api/health`.
   Les handlers d'erreur 404/403/500/429 rendent du **HTML** (gabarits `errors/*.html`) —
   l'API doit court-circuiter ce comportement (§6.6).
4. **Pattern de route module** (`app/events/__init__.py`, `app/planning/__init__.py`, …) :
   `Blueprint("<name>", __name__)` ; accès à l'événement via `load_event_context(code)` ;
   création protégée par `@limiter.limit("N per hour")` ; erreurs de formulaire via
   `FormErrors` (`app/forms.py`) + messages `_()` ; journalisation via `log_event(ctx, …)`
   (`app/context.py`) → `log_action` (`app/utils.py`) ; commit unique en fin de vue.
5. **Retrait d'invité** (`app/events/__init__.py`, `_remove_participant`) : le retrait est
   une **désactivation** (`target.is_active = False`), pas une suppression physique. Les
   clés de l'invité doivent donc être supprimées **au niveau application** (la cascade DB
   ne se déclenche que sur suppression physique) — §3.4.
6. **Migrations** (`app/migrations.py`) : pattern idempotent `plan_*` (calcul à blanc,
   aucune écriture) + `migrate_*` (une transaction) + `run_*` (sauvegarde seulement si
   écritures prévues), enregistré dans `app/startup.py` (`default_steps`). `migrate_push`
   (`app/migrations.py`) est le pattern « création de table seule, idempotente, sans
   sauvegarde » — c'est le pattern de la table `api_keys` (§3.5).
7. **Fixtures de test** (`tests/conftest.py`) : `app` (SQLite in-memory,
   `WTF_CSRF_ENABLED=False`, tous modules activés), `db`, `client`, `creator`, `event`,
   `guest`, `creator_guest`, `other_guest_c`, `creator_client`, `guest_client`,
   `app_factory`. Pattern de test HTTP : `tests/test_costs.py` (login par
   `session_transaction`, POST, assert statut + base). Pattern migration :
   `tests/test_costs_migration.py`. Pattern module gating : `tests/test_module_gating.py`.
   Pattern rate limit : `tests/test_chat_b025.py`
   (`test_htmx_send_rate_limited_returns_429_with_toast`), `tests/test_media_b026.py`
   (`test_upload_rate_limit_returns_clean_429_after_200_requests`).

### 1.3 Hors périmètre (décisions fermes)

| Sujet | Décision |
|---|---|
| OAuth, refresh token | Non. Auth par bearer uniquement. |
| Scopes fins par endpoint | Non. **Le rôle fait le scope** (créateur : tous droits ; invité : droits UI). |
| API superadmin / landing | Non. |
| Webhook | Non. |
| Ajout de langue | Non (FR/EN existantes seulement). |
| Module Media dans l'API v1 | Non (pas dans la liste des endpoints v1 de la source spec). |
| B033 (cartes) / B035 (XLSX) | Non (autres lots). |

---

## 2. Décisions d'architecture (documentées)

| # | Décision | Justification |
|---|---|---|
| A1 | **Blueprint `apikeys` (nouveau)** pour la gestion des clés UI, `url_prefix="/e"`. | La source spec laisse le choix (`events` existant ou `apikeys` nouveau). Choix : **nouveau blueprint `apikeys`**. Raisons : (1) séparation des responsabilités — `events` (`app/events/__init__.py`, ~1400 lignes) porte déjà la vie de l'événement (création, vérification, invitations, participants, suppression, export) ; les clés API sont un domaine distinct avec son propre modèle, ses propres routes et ses propres tests ; (2) cohérence avec la structure « un domaine = un blueprint » du projet ; (3) enregistrement **inconditionnel** dans `create_app` (fonctionnalité core, pas un module premium gated par `ENABLED_MODULES`). |
| A2 | **Blueprint `api` (nouveau)** pour l'API REST + découvrabilité, `url_prefix="/api"`. | L'API est JSON-only, auth bearer, rate-limitée par clé : un blueprint dédié isole ces routes des routes HTML. Enregistrement **inconditionnel** dans `create_app`. |
| A3 | **Identifiant d'événement dans les URLs API = `Event.code`** (6 caractères), pas `Event.id` (32 hex). | La source spec écrit `<event_id>` de façon lâche. Les routes UI utilisent `<code>` (`/e/<code>/…`) ; les routes de gestion des clés sont sous `/e/<code>/api-keys`, donc `<event_id>` y est le `code`. Par cohérence, l'API utilise aussi le `code`. Raisons : (1) l'agent reçoit le `code` dans la réponse de création de clé (§4.1) et peut construire les URLs ; (2) le `code` est court et lisible ; (3) la **clé est la frontière de sécurité** (bearer), l'identifiant dans l'URL n'en est pas une (§6.2, §8). |
| A4 | **Droits = réutilisation de `EventContext` + `_RIGHTS`** (`app/context.py`). | L'API construit un `EventContext` depuis l'owner de la clé (§6.3) et appelle les mêmes `can_edit` / `can_delete` / `is_creator` que l'UI. Garantit « mêmes droits que l'UI » sans réimplémentation ni dérive. |
| A5 | **Clé = `hs_` + `secrets.token_hex(24)` = 51 caractères** (pas 49). | La source spec écrit « (49 caractères) » mais la formule imposée est `hs_` (3) + `token_hex(24)` (48 hex) = **51**. La formule fait foi ; le comptage « 49 » est une erreur de la source spec (§12, R1). |
| A6 | **`key_prefix` = les 12 premiers caractères de la clé** (`key[:12]` = `hs_` + 9 hex). | La colonne est `str(12)` ; l'exemple « hs_ab12cd34… » de la source spec est illustratif (troncature d'affichage). Définition déterministe et testable : `key_prefix = key[:12]` (§12, R2). |
| A7 | **`/api/health` renvoie `{"ok": true, "version": APP_VERSION}`** ; `APP_VERSION = "0.1.0"` ajouté dans `app/__init__.py` (aligné sur `pyproject.toml` `version = "0.1.0"`). | Aucun constant de version n'existe dans `app/`. On en définit un unique, source de vérité alignée sur `pyproject.toml`. Distinct du `/health` existant (B015). |
| A8 | **Index généré depuis les routeurs** : chaque vue API porte un attribut `api_meta` (description, schéma requête, forme réponse) ; `GET /api/events/<code>/index` itère `current_app.url_map.iter_rules()` filtré sur le blueprint `api` et lit `view.api_meta`. | « Généré depuis les routeurs, pas dupliqué à la main » : l'index est dérivé du registre de routes réel, pas d'une liste manuelle qui divergerait. |
| A9 | **Retrait d'invité → suppression des clés au niveau application** (dans `_remove_participant`, `app/events/__init__.py`) + garde API (invité inactif → 401). | Le retrait est une désactivation (`is_active=False`), pas une suppression physique : la cascade DB `ondelete="CASCADE"` ne se déclenche pas. La spec exige « retrait → SES clés supprimées ». Double garantie : suppression applicative + rejet API des clés dont l'owner invité est inactif (§3.4, §6.2). |
| A10 | **Rate limiting par clé** via `key_func` dédié qui résout la clé (pas l'IP). | La source spec impose « par clé (60 req/min) ». Le `key_func` par défaut (`get_remote_address`) est par IP ; on le remplace sur les routes API par une fonction qui renvoie l'id de la clé (ou `anon:<ip>` si clé absente/invalides) (§7). |

---

## 3. Modèle `ApiKey`

### 3.1 Champs (exacts)

Nouveau modèle `ApiKey` dans `app/models.py` (pattern des modèles existants : PK
`str(32)` = `secrets.token_hex(16)`, FK `str(32)`, `datetime.utcnow()`).

```
ApiKey
  __tablename__ = "api_keys"

  id               str(32)  PK, default=lambda: secrets.token_hex(16)
  event_id         str(32)  FK events.id, nullable=False, ondelete="CASCADE", index=True
  owner_guest_id   str(32)  FK guests.id, nullable=True, ondelete="CASCADE", index=True
  owner_creator_id str(32)  FK creators.id, nullable=True, ondelete="CASCADE", index=True
  key_hash         str(64)  unique=True, nullable=False   # sha256 hex de la clé complète
  key_prefix       str(12)  nullable=False                # key[:12] (A6)
  label            str(100) default=""                    # libellé choisi par l'utilisateur
  created_at       datetime  default=datetime.utcnow
  last_used_at     datetime  nullable=True
  revoked_at       datetime  nullable=True
```

- **Relations** : `event = db.relationship("Event", backref=db.backref("api_keys", lazy="dynamic", cascade="all, delete-orphan"))` (pattern `PushSubscription.event`, `app/models.py`). Pas de backref owner (résolution par requête, §6.2).
- **Index** : `key_hash` unique (recherche d'auth) ; `event_id`, `owner_guest_id`, `owner_creator_id` indexés (listes + cascades).

### 3.2 Contrainte « exactement un owner »

- **Check en application** (source spec) : à la création, **exactement un** de
  `owner_guest_id` / `owner_creator_id` est renseigné, l'autre est `None`.
- Helper de création (dans `app/apikeys/__init__.py` ou `app/models.py`) :
  `create_api_key(event, *, guest=None, creator=None, label="") -> tuple[ApiKey, str]`
  qui (1) lève `ValueError` si `guest` et `creator` ne sont pas exactement un des deux ;
  (2) génère `key = "hs_" + secrets.token_hex(24)` ; (3) `key_hash =
  hashlib.sha256(key.encode("utf-8")).hexdigest()` ; (4) `key_prefix = key[:12]` ;
  (5) insère la ligne (owner correspondant, l'autre `None`) ; (6) renvoie `(api_key, key)`.
- **Pas de contrainte CHECK en base** (fidèle à la source spec « check en application »).
  La garde API (§6.2) tolère une ligne mal formée sans 500 (owner incohérent → 401).

### 3.3 Stockage hash-only + clé montrée une seule fois

- **La clé complète n'est jamais stockée** : seul `key_hash` (sha256 hex, 64 caractères)
  est persisté. `key_prefix` (12 caractères) sert à l'affichage / l'identification.
- **La clé complète est renvoyée exactement une fois** : dans la réponse de création
  (§4.1). Elle n'apparaît **jamais** dans la liste (§4.2), ni dans aucune autre réponse.
- L'authentification API (§6.2) hache la clé reçue et compare à `key_hash` : la clé
  complète n'est jamais reconstituée ni loggée.

### 3.4 Règles de cascade / nettoyage (règle fondamentale)

La clé est 100 % liée à l'événement **et** à son owner :

| Déclencheur | Effet | Mécanisme |
|---|---|---|
| Suppression de l'événement | Toutes les clés de l'événement supprimées | Cascade DB `event_id ondelete="CASCADE"` + ORM `cascade="all, delete-orphan"` (déclenchée par `db.session.delete(event)` dans `events.delete_event`, `app/events/__init__.py`, et par la purge `purge_expired_events`, `app/startup.py`). |
| **Suppression physique** d'un invité | Ses clés supprimées | Cascade DB `owner_guest_id ondelete="CASCADE"`. |
| **Retrait** d'un invité (`is_active=False`) | Ses clés supprimées | **Application** : `_remove_participant` (`app/events/__init__.py`) supprime les `ApiKey` de l'invité retiré (même transaction que le retrait, avant `db.session.commit()`). (A9) |
| Suppression du créateur | Ses clés supprimées | Cascade DB `owner_creator_id ondelete="CASCADE"`. |

- **Garde API (défense en profondeur)** : même si une clé orpheline subsistait, l'auth
  API renvoie **401** (jamais 500) — §6.2.
- **Invariants testés** (§9) : après suppression de l'événement / retrait d'un invité /
  suppression du créateur, `ApiKey.query.filter_by(event_id=…)` (ou `owner_guest_id=…` /
  `owner_creator_id=…`) est vide, et un appel API avec l'ancienne clé renvoie 401.

### 3.5 Migration idempotente

- Pattern `migrate_push` (`app/migrations.py`) : **création de table seule, idempotente,
  sans sauvegarde** (la table est aussi créée par `db.create_all()`).
- `migrate_api_keys(engine) -> bool` : `table = ApiKey.__table__` ;
  `existed = inspect(conn).has_table(table.name)` ; `table.create(conn, checkfirst=True)` ;
  renvoie `not existed`.
- `run_api_keys_migration(app) -> dict[str, int]` : `{"api_keys_table_created": int(created)}`.
- Enregistrement dans `app/startup.py` (`default_steps`) : `("api_keys", run_api_keys_migration)`.
- **Idempotence** : une seconde exécution ne fait rien (table existante → `created=False`).

---

## 4. Routes de gestion des clés (UI) — blueprint `apikeys`

Blueprint `apikeys` (`app/apikeys/__init__.py`), `url_prefix="/e"`, enregistré
**inconditionnellement** dans `create_app` (`app/__init__.py`, avec les blueprints core,
**pas** dans `module_blueprints` / non gated par `ENABLED_MODULES`). Accès à l'événement
via `load_event_context(code)` (pattern `app/events/__init__.py`).

### 4.1 `POST /e/<code>/api-keys` — créer une clé

- **Droits** : créateur **ou** invité de l'événement (`load_event_context(code)` =
  participant requis ; visiteur → redirection `/mycode` comme l'UI).
- **CSRF** : requis (formulaire POST, pattern `app/events/__init__.py`).
- **Rate limiting** : `@limiter.limit("10 per hour")` (endpoint de création, pattern
  `events.create` `@limiter.limit("10 per hour")`).
- **Corps** (form) : `label` (optionnel, `str`, max 100 ; vide → `""`).
- **Comportement** :
  1. `ctx = load_event_context(code)` (participant requis).
  2. Résolution de l'owner : si `ctx.is_creator` → `creator = current_user`
     (le `Creator` authentifié) ; sinon → `guest = ctx.participant` (l'invité).
  3. `api_key, key = create_api_key(ctx.event, guest=guest, creator=creator, label=label)`.
  4. `log_event(ctx, "api_key.created", target=label or api_key.key_prefix)`.
  5. `db.session.commit()`.
- **Réponse** : la **page de confirmation est rendue directement dans la réponse du POST
  (HTTP 200)** — pas de redirection. Raison : la clé complète n'est **jamais stockée**
  (§3.3) ; une redirection (PRG) la ferait perdre, car la page de liste ne peut pas la
  reconstituer. C'est le pattern « secret montré une seule fois » (rendu direct, pas
  PRG). La page de confirmation affiche :
  - la **clé complète** (une seule fois) ;
  - le `key_prefix` ;
  - l'avertissement i18n « Cette clé ne sera pas réaffichée. Copiez-la maintenant. » ;
  - le `code` de l'événement (pour construire les URLs API, A3) ;
  - un lien vers la liste des clés (`GET /e/<code>/api-keys`).
  - Le libellé de l'avertissement passe par `_()` (FR + EN, catalogs).
- **Note test** : la clé complète n'est lisible que dans cette page de confirmation
  (rendue une fois, dans la réponse du POST) ; elle n'est **pas** dans la liste (§4.2).
  Un re-POST (rafraîchissement) crée une nouvelle clé (comportement acceptable, non
  bloquant) ; la clé précédente reste valable jusqu'à révocation.

### 4.2 `GET /e/<code>/api-keys` — lister SES clés

- **Droits** : créateur ou invité (`load_event_context(code)`).
- **Contenu** : **uniquement les clés de l'appelant** (pas celles des autres) :
  - créateur → `ApiKey.query.filter_by(event_id=…, owner_creator_id=current_user.id)` ;
  - invité → `ApiKey.query.filter_by(event_id=…, owner_guest_id=ctx.participant.id)`.
- **Champs affichés par clé** : `key_prefix`, `label`, `created_at`, `last_used_at`,
  `revoked_at`. **Jamais** `key_hash` ni la clé complète.
- **Ordre** : `created_at` décroissant, puis `id`.
- **Réponse** : page HTML (pattern des pages `events`), liste des clés ; état vide si
  aucune clé.

### 4.3 `DELETE /e/<code>/api-keys/<key_id>` — révoquer SA clé

- **Droits** : créateur ou invité (`load_event_context(code)`).
- **CSRF** : requis (POST/DELETE, pattern `app/events/__init__.py`).
- **Rate limiting** : `@limiter.limit("10 per hour")`.
- **Comportement** :
  1. `ctx = load_event_context(code)`.
  2. Charger la clé **de l'appelant** : `ApiKey.query.filter_by(id=key_id, event_id=ctx.event.id, owner_creator_id=…)` (créateur) ou `owner_guest_id=…` (invité). Si introuvable **ou** appartenant à un autre owner → **404** (ne révèle pas l'existence d'une clé d'autrui).
  3. Si `revoked_at` déjà posé → idempotent (aucune erreur).
  4. `api_key.revoked_at = datetime.utcnow()` ; `log_event(ctx, "api_key.revoked", target=api_key.key_prefix)` ; `db.session.commit()`.
- **Réponse** : redirection 302 vers `GET /e/<code>/api-keys`.
- **Effet** : une clé révoquée renvoie **401** sur l'API (§6.2).

### 4.4 Gabarit

- Nouveau gabarit `app/templates/apikeys/index.html` (liste + formulaire de création +
  page de confirmation avec avertissement). Pattern des gabarits `events`
  (`app/templates/events/*.html`) : inputs avec `<label>` (WCAG), messages via `_()`.

---

## 5. Découvrabilité (pensé pour un agent)

Blueprint `api` (`app/api/__init__.py`), `url_prefix="/api"`, enregistré
**inconditionnellement** dans `create_app`.

### 5.1 `GET /api/events/<code>/index` — index des endpoints

- **Auth** : clé valide de **cet** événement (§6.2) ; sinon 401/404.
- **Réponse** (JSON) :
  ```json
  {
    "event": "<code>",
    "auth": "Authorization: Bearer hs_...",
    "endpoints": [
      {
        "method": "GET",
        "path": "/api/events/<code>",
        "description": "Infos événement",
        "request": null,
        "response": { "…": "…" }
      },
      {
        "method": "POST",
        "path": "/api/events/<code>/activities",
        "description": "Créer une activité",
        "request": { "title": "string, requis, 2-200", "date": "YYYY-MM-DD, requis", "…": "…" },
        "response": { "id": "string", "…": "…" }
      }
    ]
  }
  ```
- **Généré depuis les routeurs** (A8) : l'endpoint itère
  `current_app.url_map.iter_rules()`, sélectionne les règles dont
  `rule.endpoint.startswith("api.")` (et qui ne sont pas `/api/health` ni
  `/api/events/<code>/index`), et pour chaque règle lit
  `current_app.view_functions[rule.endpoint].api_meta` (dict `description`, `request`,
  `response`). Les `method` et `path` viennent de la règle (pas dupliqués). L'ordre est
  stable (tri par `path`).
- **Chaque vue API** porte donc un attribut `api_meta` (posé par un décorateur
  `@api_endpoint(description=…, request=…, response=…)` ou directement). Si une vue API
  n'a pas `api_meta`, elle est **exclue** de l'index (pas d'erreur).

### 5.2 `GET /api/events/<code>` — infos événement + champ `api`

- **Auth** : clé valide de cet événement (§6.2).
- **Réponse** (JSON) : infos événement **et** champ `api` (résumé + rappel d'auth) :
  ```json
  {
    "code": "<code>",
    "title": "…",
    "description": "…",
    "start_date": "2026-12-01",
    "end_date": "2026-12-07",
    "location": "…",
    "participants": [
      { "id": "<guest-id>", "display_name": "…", "is_creator": false }
    ],
    "api": {
      "auth": "Authorization: Bearer hs_...",
      "index": "/api/events/<code>/index",
      "endpoints": ["GET /api/events/<code>", "POST /api/events/<code>/activities", "…"]
    }
  }
  ```
- `participants` : les `Guest` **actifs** de l'événement (`is_active=True`), triés par
  `display_name` ; `is_creator = (guest.creator_id is not None)`. **Le `code` personnel de
  l'invité n'est jamais exposé** (secret d'accès UI).
- `api.endpoints` : liste compacte de chaînes `"METHOD /path"` (même source que l'index,
  A8) ; `api.index` pointe vers l'index complet.

### 5.3 `GET /api/health` — sans auth

- **Auth** : aucune.
- **Réponse** (JSON, 200) : `{"ok": true, "version": "0.1.0"}` (A7).
- Distinct du `/health` existant (B015, `app/__init__.py`) — pas de conflit de route
  (`/health` vs `/api/health`).

---

## 6. API REST — blueprint `api`

### 6.1 Principes

- **JSON uniquement** : toutes les routes `api` renvoient `Content-Type: application/json`
  (via `jsonify`). **Aucun HTML** dans les réponses API (§8).
- **Prefix** `/api`. **Auth** par bearer (§6.2). **Rate limiting** par clé (§7).
- **Erreurs** : JSON `{"error": "…"}` (et `{"error": "…", "detail": "…"}` si utile) avec
  code HTTP explicite : **400** validation, **401** auth, **403** droits, **404** inconnu,
  **429** rate. Les messages d'erreur sont **identiques à l'UI** (mêmes chaînes `_()`),
  renvoyés en JSON.
- **Court-circuit des handlers HTML** : les routes `api` ne laissent jamais tomber dans les
  handlers d'erreur HTML de `app/__init__.py`. Chaque vue API gère ses erreurs et renvoie
  du JSON ; un `abort(404/403/400)` dans une vue API est intercepté par un
  `errorhandler` **spécifique au blueprint `api`** (ou un `before_request`/wrapper) qui
  renvoie `{"error": "…"}` en JSON. Concrètement : un `@api_bp.errorhandler(404/403/400/429)`
  renvoie `jsonify({"error": …})`. (Le handler 500 global reste HTML ; l'API vise à ne
  **jamais** produire de 500 — §8.)

### 6.2 Authentification (bearer → hash → clé → événement + owner)

`before_request` du blueprint `api` (exécuté pour toutes les routes `api` sauf
`/api/health`) :

1. **Parser** l'en-tête `Authorization`. Format attendu : `Bearer hs_<48 hex>`.
   - Absent, mal formé, ou ne commençant pas par `Bearer ` → **401** `{"error": "Clé API requise."}`.
2. **Hacher** : `h = hashlib.sha256(token.encode("utf-8")).hexdigest()`.
3. **Chercher** : `ApiKey.query.filter_by(key_hash=h).first()`.
   - Introuvable (clé inconnue) → **401** `{"error": "Clé API invalide."}`.
4. **Révoquée** : `api_key.revoked_at is not None` → **401** `{"error": "Clé API révoquée."}`.
5. **Événement** : `event = db.session.get(Event, api_key.event_id)`.
   - `event is None` (événement supprimé → clé orpheline) → **401** `{"error": "Clé API invalide."}` (jamais 500).
   - `event.is_active is False` ou `event.verified_at is None` → **404** `{"error": "Événement introuvable."}`.
6. **Isolation** : si le `<code>` de l'URL ≠ `event.code` → **404** `{"error": "Événement introuvable."}` (une clé ne sert QUE son événement ; ne révèle pas l'existence d'un autre événement).
7. **Owner + rôle** :
   - `api_key.owner_creator_id` non nul → `creator = db.session.get(Creator, …)` ; si `None` (orpheline) → **401**. Rôle = **créateur** ; `participant = get_or_create_creator_participant(event, creator)` (`app/context.py`).
   - sinon `api_key.owner_guest_id` non nul → `guest = db.session.get(Guest, …)` ; si `None` (orpheline) → **401** ; si `guest.is_active is False` (retiré) → **401** `{"error": "Clé API invalide."}` (A9). Rôle = **invité** ; `participant = guest`.
   - les deux nuls (ligne mal formée) → **401** (garde §3.2).
8. **Contexte** : `ctx = EventContext(event, participant, is_creator=(rôle == créateur))` ;
   stocké dans `g.api_ctx` (et `g.api_key`, `g.api_event`).
9. **`last_used_at` throttlé** : si `api_key.last_used_at is None` ou
   `(datetime.utcnow() - api_key.last_used_at) > timedelta(seconds=60)` →
   `api_key.last_used_at = datetime.utcnow()` (commit différé / flush). Sinon : aucune
   écriture. (Pas de write à chaque requête.)

> **Ordre des statuts** (priorité) : 401 (clé absente/invalide/révocquée/orpheline) >
> 404 (événement inactif/inconnu/isolation) > 403 (droits) > 400 (validation) > 429 (rate).

### 6.3 Droits = rôle de l'owner (réutilisation de `EventContext`)

- L'API **ne réimplémente pas** les droits : elle construit un `EventContext` (§6.2.8) et
  appelle les mêmes `ctx.can_edit(obj)` / `ctx.can_delete(obj)` / `ctx.is_creator` que
  l'UI (`app/context.py`, table `_RIGHTS`).
- **Créateur** (`owner_creator_id`) : `is_creator=True` → tous les droits (suppression
  créateur-only, foyers, ratio, …).
- **Invité** (`owner_guest_id`) : `is_creator=False`, `participant=guest` → **mêmes droits
  que l'UI** (peut créer activités/repas/listes/logistics/sondages/messages/dépenses,
  voter, RSVP ; ne peut pas supprimer une liste, ajouter un foyer, …).
- **Action non autorisée pour le rôle → 403** `{"error": "Action non autorisée."}`.
- **Acteur du journal** : `log_event(ctx, …)` utilise `ctx.actor` (`actor_for`,
  `app/context.py`) → le journal de l'événement reflète les actions API avec le bon nom
  et type d'acteur (créateur/invité).

### 6.4 Endpoints v1 (miroir des modules)

> Chaque endpoint : méthode, chemin, schéma de requête (identique aux formulaires UI),
> forme de réponse, droits, messages d'erreur (identiques à l'UI). Les schémas ci-dessous
> sont les **contrats** ; l'implémentation réutilise les validateurs UI existants
> (cités) pour garantir l'identité des règles et des messages.

#### 6.4.1 Événement

| Méthode | Chemin | Droits |
|---|---|---|
| GET | `/api/events/<code>` | participant (créateur ou invité) |

- Réponse : §5.2 (infos + `api`).

#### 6.4.2 Activités (miroir `app/planning/__init__.py`)

| Méthode | Chemin | Droits |
|---|---|---|
| GET | `/api/events/<code>/activities` | participant |
| POST | `/api/events/<code>/activities` | participant |
| POST | `/api/events/<code>/activities/<activity_id>/rsvp` | participant (son propre RSVP) |

- **GET** : liste des activités (ordre `date`, `start_time`, `created_at`, `id`), chacune :
  `{id, title, description, date, start_time, end_time, location, min_headcount,
  bring_items, status, created_by, created_at, rsvps: {yes: [noms], maybe: [noms], no: [noms]}}`.
- **POST** — schéma (miroir `_validate_form`, `app/planning/__init__.py`) :
  - `title` : string, **requis**, 2–200 caractères.
  - `description` : string, optionnel, max 2000.
  - `date` : string, **requis**, `YYYY-MM-DD`, dans `[event.start_date, event.end_date]`.
  - `start_time` : string, optionnel, `HH:MM`.
  - `end_time` : string, optionnel, `HH:MM`, `> start_time` si les deux présents.
  - `location` : string, optionnel, max 300.
  - `min_headcount` : integer, optionnel, 1–50, défaut 1.
  - `bring_items` : string, optionnel, max 500.
  - Réponse 201 : objet activité. `created_by = ctx.participant.id`.
  - Erreurs 400 (mêmes messages que l'UI) : « Titre requis (min 2 caractères). »,
    « Description trop longue (max 2000). », « Date requise. », « Format de date invalide
    (AAAA-MM-JJ). », « Date hors de la période de l'événement. », « Heure invalide. »,
    « Heure de fin avant heure de début. », « Lieu trop long (max 300). », « Nombre entre
    1 et 50. », « Champ trop long (max 500). »
- **POST rsvp** — schéma :
  - `status` : string, **requis**, ∈ `{yes, no, maybe, none}` (`RSVP_STATUSES`
    `app/i18n.py` + `RSVP_CLEAR="none"` `app/planning/__init__.py`).
  - Réponse 200 : objet activité (RSVP upsert / retiré si `none`).
  - Erreur 400 : « Statut invalide. »
  - Activité inconnue → 404.

#### 6.4.3 Repas (miroir `app/meals/__init__.py`)

| Méthode | Chemin | Droits |
|---|---|---|
| GET | `/api/events/<code>/meals` | participant |
| POST | `/api/events/<code>/meals` | participant |

- **GET** : liste des repas (ordre `Meal.ordering()`, `app/models.py`), chacun :
  `{id, title, date, slot, position, created_by, created_at}`.
- **POST** — schéma (miroir `meals.create` + `_clean_title` + `_target`) :
  - `title` : string, **requis**, 2–200 caractères.
  - `date` : string, **requis**, `YYYY-MM-DD`, dans la période de l'événement.
  - `slot` : string, **requis**, ∈ `{lunch, dinner}` (`MEAL_SLOTS`, `app/i18n.py`).
  - Réponse 201 : objet repas (`position` = fin de case). `created_by = ctx.participant.id`.
  - Erreurs 400 : « Nom requis (min 2 caractères). », « Nom trop long (max 200). »,
    « Date hors de la période de l'événement. », « Créneau invalide. », « Cette case est
    pleine (6 repas maximum). » (`MAX_MEALS_PER_CELL`, `app/models.py`).

#### 6.4.4 Listes + articles (miroir `app/lists/__init__.py`)

| Méthode | Chemin | Droits |
|---|---|---|
| GET | `/api/events/<code>/lists` | participant |
| POST | `/api/events/<code>/lists` | participant |
| GET | `/api/events/<code>/lists/<list_id>/items` | participant |
| POST | `/api/events/<code>/lists/<list_id>/items` | participant |

- **GET lists** : liste des listes (ordre `created_at`), chacune :
  `{id, title, list_type, created_at, items: [objets article]}`.
- **POST lists** — schéma (miroir `lists.index` POST) :
  - `title` : string, **requis**, 2–200 caractères.
  - `list_type` : string, optionnel, ∈ clés `list_type` (`app/i18n.py` : general, shopping,
    materials, packing, todo, buffet), défaut `general` (invalide → `general`).
  - Réponse 201 : objet liste. Erreurs 400 : « Titre requis (min 2 caractères). »,
    « Titre trop long (max 200). »
- **GET items** : liste des articles de la liste (ordre `created_at`), chacun :
  `{id, name, quantity, section, assigned_to, assigned_to_id, is_done, created_by,
  created_at}`. Liste inconnue → 404.
- **POST items** — schéma (miroir `_parse_item_form`, `app/lists/__init__.py`) :
  - `name` : string, **requis**, 1–300 caractères.
  - `quantity` : string, optionnel, max 50, défaut `"1"`.
  - `section` : string, optionnel, max 100.
  - `assigned_to` : string, optionnel, max 50 (nom d'affichage ; résolu en
    `assigned_to_id` si un seul invité actif correspond, comme l'UI).
  - Réponse 201 : objet article. `created_by = ctx.participant.id`.
  - Erreurs 400 : « Nom requis. », « Nom trop long (max 300). », « Quantité trop longue
    (max 50). », « Section trop longue (max 100). », « Nom trop long (max 50). »

#### 6.4.5 Logistics (miroir `app/logistics/__init__.py`)

| Méthode | Chemin | Droits |
|---|---|---|
| GET | `/api/events/<code>/logistics` | participant |
| POST | `/api/events/<code>/logistics` | participant |

- **GET** : liste des infos pratiques (ordre `ordered_infos`, `app/infos.py`), chacune :
  `{id, title, content, category, order, created_at}`.
- **POST** — schéma (miroir `_validate_form`, `app/logistics/__init__.py`) :
  - `title` : string, **requis**, 2–200 caractères.
  - `content` : string, **requis**, max 5000.
  - `category` : string, optionnel, ∈ clés `info_category` (`app/i18n.py` : address,
    access, timing, docs, notes, general), défaut `general`.
  - Réponse 201 : objet info. Erreurs 400 : « Titre requis (min 2 caractères). »,
    « Titre trop long (max 200). », « Contenu requis. », « Contenu trop long (max 5000). »,
    « Catégorie invalide. »

#### 6.4.6 Sondages + vote (miroir `app/voting/__init__.py`)

| Méthode | Chemin | Droits |
|---|---|---|
| GET | `/api/events/<code>/polls` | participant |
| POST | `/api/events/<code>/polls` | participant |
| POST | `/api/events/<code>/polls/<poll_id>/vote` | participant (son propre vote) |

- **GET** : liste des sondages (ordre `created_at` desc, `id`), chacun (via `poll_views`,
  `app/polls.py`) : `{id, question, kind, is_closed, created_by, created_at,
  voters, show_results, options: [{id, label, order, activity_id, count, fraction,
  winner, mine}]}`.
- **POST** — schéma (miroir `_validate_poll_form`, `app/voting/__init__.py`) :
  - `question` : string, **requis**, 2–300 caractères.
  - `kind` : string, optionnel, ∈ `{free, activities}` (`KINDS`, `app/polls.py`), défaut `free`.
  - `options` : string, optionnel, libellés séparés par des sauts de ligne (sondage
    `free` : 2–10 options, chacune max 200).
  - `activity_ids` : list[string], optionnel (sondage `activities` : ≥ 2 activités de
    l'événement, non écartées).
  - Réponse 201 : objet sondage. `created_by = ctx.participant.id`.
  - Erreurs 400 : « Question requise (min 2 caractères). », « Question trop longue (max
    300 caractères). », « Type de sondage invalide. », « Au moins 2 options requises (une
    par ligne). », « Maximum 10 options (une par ligne). », « Option trop longue (max 200
    caractères). », « Le Planning n'est pas activé : choisissez une question libre. »,
    « Activité introuvable dans cet événement. », « Sélectionnez au moins 2 activités. »,
    « Maximum 10 options (activités comprises). »
- **POST vote** — schéma (miroir `voting.vote`) :
  - `option_id` : string, **requis** (option du sondage).
  - Réponse 200 : objet sondage (vote upsert ; l'ancien vote du participant est remplacé).
  - Sondage clos → 400 « Ce sondage est clos. » ; option inconnue → 404 ; sondage inconnu → 404.

#### 6.4.7 Chat (miroir `app/chat/__init__.py`)

| Méthode | Chemin | Droits |
|---|---|---|
| GET | `/api/events/<code>/chat` | participant |
| POST | `/api/events/<code>/chat` | participant |

- **GET** : les 50 derniers messages (ordre `created_at`, `id`), chacun :
  `{id, content, author_name, author_type, guest_id, created_at}`.
- **POST** — schéma (miroir `chat.send`) :
  - `content` : string, **requis**, 1–2000 caractères (strippé).
  - Réponse 201 : objet message (`author_name`/`author_type` = `ctx.actor`,
    `guest_id = ctx.participant.id`).
  - Erreurs 400 : « Message vide. », « Message trop long (max 2000). »

#### 6.4.8 Frais (miroir `app/costs/__init__.py`)

> **Résolution d'ambiguïté** (R3, §12) : la source spec liste un unique
> `POST /api/events/<event_id>/costs`. Le module Frais a **quatre** sous-ressources
> distinctes (foyers, dépenses, transferts, demandes), chacune avec son formulaire et sa
> validation UI. Pour respecter « mêmes règles de validation que l'UI », l'API les
> **miroite** en quatre sous-endpoints POST (ci-dessous), plus le GET dashboard.

| Méthode | Chemin | Droits |
|---|---|---|
| GET | `/api/events/<code>/costs` | participant |
| POST | `/api/events/<code>/costs/expenses` | participant (dépense personnelle : son foyer) |
| POST | `/api/events/<code>/costs/households` | **créateur** |
| POST | `/api/events/<code>/costs/transfers` | participant (non-créateur : son foyer impliqué) |
| POST | `/api/events/<code>/costs/payment-requests` | participant (non-créateur : depuis son foyer) |

- **GET** — dashboard (miroir `costs.index` / `_page`) :
  ```json
  {
    "households": [{id, name, num_adults, num_children, adult_weight, child_weight, total_weight, guest_id}],
    "expenses": [{id, description, amount_cents, currency, exchange_rate, category, paid_by_household_id, date, is_shared, created_at}],
    "transfers": [{id, from_household_id, to_household_id, amount_cents, note, date, created_at}],
    "payment_requests": [{id, from_household_id, to_household_id, amount_cents, message, is_resolved, created_at}],
    "settlements": [{from, to, amount}],
    "balances": { "<household_id>": <float> }
  }
  ```
  - **Confidentialité** (miroir `_visible`, `app/costs/__init__.py`) : une dépense
    **personnelle** (`is_shared=False`) n'est visible que du propriétaire du foyer payeur
    (ou du créateur) ; les autres ne la voient pas (exclue de `expenses`).
- **POST expenses** — schéma (miroir `_parse_expense`) :
  - `description` : string, **requis**, max 300.
  - `amount` : string, **requis**, > 0, ≤ 1 000 000, ≥ 0,01 après conversion.
  - `currency` : string, optionnel, ∈ `CURRENCIES` (`app/i18n.py`), défaut `EUR`.
  - `exchange_rate` : string, optionnel (requis si `currency != EUR`), 0,0001–10000.
  - `category` : string, optionnel, ∈ clés `expense_category`, défaut `general`.
  - `household_id` : string, **requis** (foyer payeur de l'événement).
  - `is_shared` : boolean, optionnel, défaut `true`.
  - `date` : string, optionnel, `YYYY-MM-DD`, dans `[aujourd'hui-5 ans, aujourd'hui+1 an]`, défaut aujourd'hui.
  - Réponse 201 : objet dépense. `created_by = ctx.participant.id`.
  - Erreurs 400 : « Description requise. », « Description trop longue (max 300). »,
    « Montant invalide. », « Devise invalide. », « Taux de change requis pour cette
    devise. », « Taux de change invalide (0,0001 ≤ taux ≤ 10000). », « Montant trop faible
    une fois converti. », « Catégorie invalide. », « Foyer payeur requis. », « Foyer
    payeur invalide. », « Une dépense personnelle doit être payée par votre foyer. »,
    « Date invalide. », « Date hors limites (5 ans avant à 1 an après aujourd'hui). »
- **POST households** — schéma (miroir `parse_household`) :
  - `name` : string, **requis**, 2–100 caractères.
  - `num_adults` : integer, optionnel, 1–50, défaut 1.
  - `num_children` : integer, optionnel, 0–50, défaut 0.
  - Réponse 201 : objet foyer. **Droits : créateur** (invité → 403).
  - Erreurs 400 : « Nom du foyer requis (min 2 caractères). », « Nom trop long (max 100). »,
    « Valeurs numériques invalides. », « Adultes : entre 1 et 50. », « Enfants : entre 0 et 50. »
- **POST transfers** — schéma (miroir `add_transfer` + `_parse_transfer_households`) :
  - `from_household_id` : string, **requis** (foyer de l'événement).
  - `to_household_id` : string, **requis** (foyer de l'événement, ≠ `from`).
  - `amount` : string, **requis**, > 0.
  - `note` : string, optionnel, max 300.
  - `date` : string, optionnel, `YYYY-MM-DD`.
  - Réponse 201 : objet transfert. `created_by = ctx.participant.id`.
  - **Droits** : participant ; un non-créateur ne peut enregistrer qu'un transfert
    **impliquant son foyer** (sinon 403).
  - Erreurs 400 : « Foyers d'origine et de destination requis. », « Le foyer d'origine et
    de destination doivent différer. », « Foyer invalide pour cet événement. », « Montant
    invalide. », « Note trop longue (max 300). »
- **POST payment-requests** — schéma (miroir `add_payment_request`) :
  - `from_household_id` : string, **requis** (foyer de l'événement ; non-créateur : son foyer).
  - `to_household_id` : string, **requis** (foyer de l'événement, ≠ `from`).
  - `amount` : string, **requis**, > 0.
  - `message` : string, optionnel, max 500.
  - Réponse 201 : objet demande. `created_by = ctx.participant.id`.
  - **Droits** : participant ; un non-créateur ne peut créer que **depuis son foyer**
    (sinon 403).
  - Erreurs 400 : « Foyers requis. », « Les foyers doivent différer. », « Foyer invalide
    pour cet événement. », « Montant invalide. », « Message trop long (max 500). »

### 6.5 Journalisation

- Chaque action API réussie est journalisée via `log_event(ctx, …)` (`app/context.py`)
  avec le **même code d'action** que l'UI (`activity.created`, `meal.created`,
  `list.created`, `list_item.created`, `logistics.created`, `poll.created`, `poll.voted`,
  `chat.message`, `expense.created`, `household.created`, `transfer.created`,
  `payment_request.created`, `rsvp.updated`, …) — le journal de l'événement est donc
  cohérent entre UI et API.

### 6.6 Erreurs JSON (récapitulatif)

| Code | Déclencheur | Corps |
|---|---|---|
| 400 | Validation du corps (schéma §6.4) | `{"error": "<message UI>"}` |
| 401 | Clé absente / mal formée / inconnue / révoquée / orpheline / owner inactif | `{"error": "…"}` |
| 403 | Action non autorisée pour le rôle | `{"error": "Action non autorisée."}` |
| 404 | Événement inactif / inconnu / isolation (clé ≠ événement) / ressource inconnue | `{"error": "…"}` |
| 429 | Rate limit dépassé (§7) | `{"error": "Trop de requêtes. Patientez un instant."}` |

- **Corps JSON invalide** (non-JSON, ou JSON non-objet) → 400 `{"error": "Corps JSON invalide."}`.
- **Champ manquant / type inattendu** → 400 avec le message de validation du champ.

---

## 7. Rate limiting

- **Par clé** : 60 requêtes / minute par clé API ; **429** au-delà (source spec).
- **Mécanisme** : `@limiter.limit("60 per minute", key_func=api_key_func)` sur **toutes**
  les routes `api` (sauf `/api/health`).
- **`api_key_func(request)`** (dans `app/api/__init__.py`) :
  - Résout la clé (helper partagé avec l'auth §6.2, mise en cache dans `g` pour éviter un
    double lookup) ;
  - Clé valide (non révoquée) → renvoie `api_key.id` (budget **par clé**) ;
  - Clé absente / inconnue / révoquée → renvoie `f"anon:{request.remote_addr}"` (budget
    par IP, anti brute-force).
- **Ordre** : le `key_func` du limiter (hook app-level, `app/extensions.py`) s'exécute
  avant le `before_request` du blueprint `api` ; il résout donc la clé lui-même (helper
  partagé, cache `g`), puis l'auth (§6.2) réutilise `g`.
- **429** : renvoyé en JSON `{"error": "Trop de requêtes. Patientez un instant."}`
  (intercepté par le `errorhandler(429)` du blueprint `api`, §6.1) — pas le toast HTMX
  HTML de l'UI.
- **CSRF ne s'applique pas** aux routes API (auth bearer) ; **le rate limiting oui**
  (source spec).

---

## 8. Invariants de sécurité

| # | Invariant | Garantie |
|---|---|---|
| S1 | **Pas de HTML dans les réponses API** | Toutes les routes `api` renvoient `jsonify` (`Content-Type: application/json`) ; les `errorhandler` du blueprint `api` renvoient du JSON (§6.1). Aucun gabarit HTML n'est rendu sur `/api/*`. |
| S2 | **Pas de fuite d'info entre événements** | Une clé ne sert QUE son événement : l'auth charge l'événement **depuis la clé** (§6.2.5) et rejette (404) si le `<code>` de l'URL ≠ `event.code` (§6.2.6). Une clé de l'événement A sur l'événement B → 404, aucune donnée de B n'est lue ni révélée. |
| S3 | **Validation stricte des corps JSON** | Schémas **identiques aux formulaires UI** (§6.4) ; l'implémentation réutilise les validateurs UI (cités) ; corps non-JSON / champ manquant / type inattendu → 400. |
| S4 | **CSRF inapplicable aux routes API** (bearer) ; **rate limiting applicable** | Pas de token CSRF sur `/api/*` ; `@limiter.limit("60 per minute", key_func=api_key_func)` sur toutes les routes `api` (§7). |
| S5 | **Clé orpheline → 401, jamais 500** | Événement supprimé / owner supprimé / owner inactif / ligne mal formée → 401 (§6.2). Aucune exception ne s'échappe : les lookups sont protégés (`db.session.get` → `None` → 401). |
| S6 | **Hash-only, clé montrée une fois** | Seul `key_hash` est stocké (§3.3) ; la clé complète n'apparaît que dans la page de confirmation (§4.1) ; jamais loggée, jamais dans la liste. |
| S7 | **Isolation des clés par owner** | La liste (§4.2) et la révocation (§4.3) ne touchent que les clés de l'appelant ; une clé d'autrui → 404. |

---

## 9. Plan de tests

> TDD : les tests sont écrits **avant** le code et doivent échouer. Chaque test est mappé
> à une exigence de la spec et à un pattern de test existant (cité). Fixtures :
> `tests/conftest.py` (`app`, `db`, `client`, `creator`, `event`, `guest`,
> `creator_guest`, `other_guest_c`, `creator_client`, `guest_client`, `app_factory`).
>
> **Aide commune** (dans chaque fichier) : `make_key(db, event, *, guest=None,
> creator=None, label="") -> tuple[ApiKey, str]` crée une clé via `create_api_key` et
> renvoie `(api_key, key)` ; `auth(key)` renvoie `{"Authorization": f"Bearer {key}"}`.

### 9.1 `tests/test_apikeys.py` — modèle + routes de gestion (UI)

**Modèle** (pattern `tests/test_models.py` — assertions directes sur les modèles) :

| Test | Exigence | Pattern |
|---|---|---|
| `test_apikey_stores_hash_not_key` | §3.3 : `key_hash == sha256(key)`, la clé complète n'est dans aucun champ | `test_models.py` |
| `test_apikey_key_format` | §3.1/A5 : `key` = `hs_` + 48 hex, longueur 51 | `test_models.py` (`TestCodeGeneration`) |
| `test_apikey_key_prefix_is_first_12` | §3.1/A6 : `key_prefix == key[:12]`, longueur 12 | `test_models.py` |
| `test_apikey_exactly_one_owner` | §3.2 : `create_api_key` lève `ValueError` si 0 ou 2 owners ; sinon exactement un non nul | `test_models.py` |
| `test_apikey_cascade_delete_event` | §3.4 : `db.session.delete(event)` → `ApiKey.query.filter_by(event_id=…)` vide | `test_models.py` + `test_costs.py` (suppression) |
| `test_apikey_cascade_delete_guest` | §3.4 : suppression physique d'un `Guest` → ses clés supprimées | `test_models.py` |
| `test_apikey_cascade_delete_creator` | §3.4 : suppression d'un `Creator` → ses clés supprimées | `test_models.py` |
| `test_apikey_migration_idempotent` | §3.5 : `run_api_keys_migration` crée la table ; 2e exécution → `{"api_keys_table_created": 0}`, pas de sauvegarde | `test_costs_migration.py` (plan/migrate/run + idempotence + backups) |

**Routes de gestion** (pattern `tests/test_costs.py` — login par `session_transaction`,
POST/GET/DELETE, assert statut + base) :

| Test | Exigence | Pattern |
|---|---|---|
| `test_create_key_as_creator` | §4.1 : `POST /e/<code>/api-keys` (créateur) → **200** (rendu direct) ; une `ApiKey` avec `owner_creator_id` existe ; la réponse contient la clé complète + `key_prefix` + l'avertissement + le `code` de l'événement | `test_costs.py` (`TestHouseholds.test_add_household_success`) |
| `test_create_key_as_guest` | §4.1 : `POST` (invité) → **200** ; `ApiKey` avec `owner_guest_id` ; la clé complète est dans la réponse | `test_costs.py` |
| `test_create_key_label_optional` | §4.1 : `label` absent → `""` ; `label` présent → stocké | `test_costs.py` |
| `test_create_key_shown_once_not_in_list` | §3.3/§4.2 : la clé complète est dans la page de confirmation mais **absente** de la liste `GET /e/<code>/api-keys` | `test_costs.py` |
| `test_list_keys_only_own` | §4.2 : le créateur ne voit que ses clés ; l'invité ne voit que les siennes (pas celles de l'autre) | `test_costs.py` (`test_delete_expense_forbidden_for_guest`) |
| `test_list_keys_fields` | §4.2 : la liste expose `key_prefix`, `label`, `created_at`, `last_used_at`, `revoked_at` ; **jamais** `key_hash` ni la clé | `test_costs.py` |
| `test_revoke_own_key` | §4.3 : `DELETE /e/<code>/api-keys/<id>` (owner) → 302 ; `revoked_at` posé | `test_costs.py` (`test_delete_expense_as_creator`) |
| `test_revoke_not_own_key_is_404` | §4.3/S7 : `DELETE` d'une clé d'autrui → 404 (pas 403, ne révèle pas) | `test_costs.py` |
| `test_create_key_unknown_event_is_404` | §4.1 : `POST /e/xxxxxx/api-keys` → 404 | `test_costs.py` (`test_index_404_invalid_code`) |
| `test_create_key_no_access_redirects` | §4.1 : visiteur (pas de session) → 302 vers `/mycode` | `test_costs.py` (`test_index_redirects_no_access`) |
| `test_create_key_rate_limited` | §4.1 : 429 après la limite (10/h) | `test_chat_b025.py` (`test_htmx_send_rate_limited_returns_429_with_toast`) |
| `test_create_key_requires_csrf` | §4.1 : `POST` sans token CSRF → rejet (400/401). **Fixture dédiée** `csrf_app` (`WTF_CSRF_ENABLED=True`, pattern `gated_app` de `test_module_gating.py` / `legacy_app` de `test_costs_migration.py`) car `conftest.py` désactive le CSRF | `test_module_gating.py` (fixture app custom) |

### 9.2 `tests/test_api.py` — API REST + découvrabilité

**Découvrabilité** (pattern `tests/test_costs.py` — GET, assert JSON) :

| Test | Exigence | Pattern |
|---|---|---|
| `test_health_no_auth` | §5.3 : `GET /api/health` sans clé → 200 `{"ok": true, "version": "0.1.0"}` | `test_costs.py` |
| `test_index_lists_all_endpoints` | §5.1 : `GET /api/events/<code>/index` (clé valide) → 200 ; `endpoints` contient chaque endpoint v1 (méthode + chemin) ; généré depuis les routeurs (pas de dérive) | `test_costs.py` |
| `test_index_requires_auth` | §5.1 : `GET /index` sans clé → 401 | `test_costs.py` |
| `test_event_info_includes_api_field` | §5.2 : `GET /api/events/<code>` (clé valide) → 200 ; contient `title`, `start_date`, `participants`, et le champ `api` (auth + index + endpoints) | `test_costs.py` |

**Auth API** (pattern `tests/test_costs.py` — statuts 401/404) :

| Test | Exigence | Pattern |
|---|---|---|
| `test_auth_no_header_is_401` | §6.2.1 : `GET /api/events/<code>` sans `Authorization` → 401 | `test_costs.py` |
| `test_auth_malformed_header_is_401` | §6.2.1 : `Authorization: Bearer` (vide) / `Token hs_…` → 401 | `test_costs.py` |
| `test_auth_invalid_key_is_401` | §6.2.3 : clé inconnue (`hs_` + 48 hex aléatoires) → 401 | `test_costs.py` |
| `test_auth_revoked_key_is_401` | §6.2.4 : clé révoquée → 401 | `test_costs.py` |
| `test_auth_unknown_event_is_404` | §6.2.5/6 : clé valide mais `<code>` inconnu/inactif → 404 | `test_costs.py` (`test_index_404_invalid_code`) |
| `test_auth_cross_event_is_404_no_leak` | §6.2.6/S2 : clé de l'événement A sur `/api/events/<code_B>/…` → 404 ; aucune donnée de B (pas de `title` de B dans le corps) | `test_costs.py` |
| `test_orphan_key_event_deleted_is_401_not_500` | §6.2.5/S5 : suppression de l'événement → appel avec l'ancienne clé → 401 (jamais 500) | `test_costs.py` |
| `test_orphan_key_guest_deleted_is_401_not_500` | §6.2.7/S5 : retrait (`is_active=False`) d'un invité → appel avec sa clé → 401 (jamais 500) ; et ses clés sont supprimées (§3.4) | `test_costs.py` |

**Droits** (pattern `tests/test_costs.py` — `test_delete_expense_forbidden_for_guest` /
`test_delete_expense_as_creator`) :

| Test | Exigence | Pattern |
|---|---|---|
| `test_guest_cannot_add_household_is_403` | §6.3/§6.4.8 : clé invité → `POST /api/events/<code>/costs/households` → 403 | `test_costs.py` (`test_delete_household_forbidden_for_guest`) |
| `test_creator_can_add_household` | §6.3/§6.4.8 : clé créateur → `POST …/costs/households` → 201 | `test_costs.py` (`test_add_household_success`) |
| `test_guest_cannot_delete_list_is_403` | §6.3 : clé invité ne peut pas supprimer une liste (droit créateur, `_RIGHTS[SharedList]`) → 403 | `test_costs.py` |
| `test_creator_can_delete_list` | §6.3 : clé créateur → suppression liste → 200 | `test_costs.py` |

**CRUD — un endpoint par module** (pattern `tests/test_costs.py` — création valide +
validation rejetée) :

| Test | Exigence | Pattern |
|---|---|---|
| `test_activities_create_valid` | §6.4.2 : `POST /api/events/<code>/activities` (clé valide, corps valide) → 201 ; l'activité existe en base | `test_costs.py` (`test_add_expense_success`) |
| `test_activities_create_invalid` | §6.4.2 : `title` trop court / `date` hors période → 400 `{"error": …}` (message UI) ; rien en base | `test_costs.py` (`test_add_expense_missing_description`) |
| `test_rsvp_valid` | §6.4.2 : `POST …/activities/<id>/rsvp` `status=yes` → 200 ; RSVP créé | `test_costs.py` |
| `test_meals_create_valid` | §6.4.3 : `POST /api/events/<code>/meals` (valide) → 201 | `test_costs.py` |
| `test_meals_create_invalid` | §6.4.3 : `slot` invalide / case pleine → 400 | `test_costs.py` |
| `test_lists_create_valid` | §6.4.4 : `POST /api/events/<code>/lists` (valide) → 201 | `test_costs.py` |
| `test_lists_create_invalid` | §6.4.4 : `title` absent → 400 | `test_costs.py` |
| `test_list_items_create_valid` | §6.4.4 : `POST …/lists/<id>/items` (valide) → 201 | `test_costs.py` |
| `test_chat_send_valid` | §6.4.7 : `POST /api/events/<code>/chat` (valide) → 201 ; message en base | `test_costs.py` |
| `test_chat_send_invalid` | §6.4.7 : `content` vide / > 2000 → 400 | `test_costs.py` |
| `test_polls_create_valid` | §6.4.6 : `POST /api/events/<code>/polls` (free, 2 options) → 201 | `test_costs.py` |
| `test_vote_valid` | §6.4.6 : `POST …/polls/<id>/vote` `option_id` valide → 200 ; vote créé | `test_costs.py` |
| `test_logistics_create_valid` | §6.4.5 : `POST /api/events/<code>/logistics` (valide) → 201 | `test_costs.py` |
| `test_costs_expense_create_valid` | §6.4.8 : `POST …/costs/expenses` (valide) → 201 | `test_costs.py` (`test_add_expense_success`) |
| `test_costs_expense_create_invalid` | §6.4.8 : `amount` invalide / foyer absent → 400 | `test_costs.py` (`test_add_expense_invalid_amount`) |

**Rate limit** (pattern `tests/test_chat_b025.py` / `tests/test_media_b026.py`) :

| Test | Exigence | Pattern |
|---|---|---|
| `test_api_rate_limit_429_after_60` | §7 : 61 requêtes `GET /api/events/<code>` avec la même clé → les 60 premières 200, la 61e **429** (JSON) | `test_media_b026.py` (`test_upload_rate_limit_returns_clean_429_after_200_requests`) |
| `test_api_rate_limit_per_key` | §7/A10 : deux clés distinctes ont chacune leur budget (l'une saturée n'affecte pas l'autre) | `test_media_b026.py` |

**Sécurité** (pattern `tests/test_costs.py` + assertions sur le corps) :

| Test | Exigence | Pattern |
|---|---|---|
| `test_api_responses_are_json_no_html` | §8/S1 : `Content-Type` = `application/json` sur succès **et** erreur ; le corps ne contient pas `<html`/`<!doctype` | `test_costs.py` |
| `test_api_error_shape` | §6.6 : toute erreur est `{"error": "…"}` (clé `error` présente, string) | `test_costs.py` |
| `test_api_no_cross_event_leak` | §8/S2 : clé A ne lit rien de B (déjà couvert par `test_auth_cross_event_is_404_no_leak`, ici renforcé sur un GET collection) | `test_costs.py` |

### 9.3 Non-régression

- Tous les tests existants restent verts (aucun comportement UI modifié hors l'ajout de la
  suppression des clés dans `_remove_participant`, `app/events/__init__.py` — §3.4/A9).
- `tests/test_module_gating.py` : les routes `apikeys` et `api` sont **inconditionnelles**
  (pas gated par `ENABLED_MODULES`) — un test optionnel vérifie que `/api/health` et
  `/e/<code>/api-keys` existent même si un module est désactivé (pattern
  `test_module_gating.py`).

---

## 10. Fichiers touchés (récapitulatif)

| Fichier | Action |
|---|---|
| `app/models.py` | Ajout du modèle `ApiKey` (+ relation `Event.api_keys`). |
| `app/apikeys/__init__.py` | **Nouveau** : blueprint `apikeys` (routes §4) + `create_api_key`. |
| `app/api/__init__.py` | **Nouveau** : blueprint `api` (auth §6.2, endpoints §6.4, découvrabilité §5, `api_key_func` §7, `api_meta`/`@api_endpoint` A8, `errorhandler` JSON §6.1). |
| `app/__init__.py` | Enregistrement de `apikeys_bp` (prefix `/e`) et `api_bp` (prefix `/api`) **inconditionnellement** ; ajout de `APP_VERSION = "0.1.0"` (A7). |
| `app/migrations.py` | `migrate_api_keys` + `run_api_keys_migration` (pattern `migrate_push`). |
| `app/startup.py` | Ajout de `("api_keys", run_api_keys_migration)` dans `default_steps`. |
| `app/events/__init__.py` | `_remove_participant` : suppression des `ApiKey` de l'invité retiré (même transaction) — §3.4/A9. |
| `app/templates/apikeys/index.html` | **Nouveau** : liste + création + confirmation (avertissement « ne sera pas réaffiché »). |
| `translations/fr/LC_MESSAGES/messages.po` + `.en` | Nouvelles chaînes (avertissement clé, erreurs API réutilisant les chaînes UI existantes). |
| `tests/test_apikeys.py` | **Nouveau** (§9.1). |
| `tests/test_api.py` | **Nouveau** (§9.2). |

> **Pas de nouvelle dépendance Python** (hashlib, secrets, Flask, Flask-Limiter existent
> déjà — `requirements.txt` / `pyproject.toml` inchangés).

---

## 11. Définition de « terminé » (lot B034)

1. `ruff check . && ruff format --check .` → vert.
2. `mypy app/` → vert (strict, `pyproject.toml`).
3. `pytest` → vert (nouveau `test_apikeys.py` + `test_api.py` + régression).
4. `CHANGELOG.md` (section B034), `TASKS.md` (lot B034 → ✅), `DEV_LOG.md` mis à jour.
5. Commits atomiques **Conventional Commits** avec scope **`api`** (ex.
   `feat(api): ajouter le modèle ApiKey et la migration`, `feat(api): routes de gestion
   des clés`, `feat(api): API REST v1 + découvrabilité`, `test(api): couvrir auth,
   droits, rate limit`).
6. Vérification manuelle documentée dans le commit final du lot (parcours créateur +
   invité : créer une clé, l'utiliser sur l'API, la révoquer ; agent découvrant l'API via
   `/index`).

---

## 12. Ambiguïtés de la source spec — résolutions

| # | Ambiguïté (source spec) | Résolution |
|---|---|---|
| R1 | « Format de clé : `hs_` + `secrets.token_hex(24)` **(49 caractères)** » — incohérent : `hs_` (3) + `token_hex(24)` (48 hex) = **51**. | La **formule fait foi** : clé = `hs_` + `secrets.token_hex(24)` = **51 caractères** (A5). Le « 49 » est une erreur de comptage de la source spec. |
| R2 | `key_prefix str(12)` mais l'exemple « hs_ab12cd34… » montre 11 caractères + ellipse. | `key_prefix = key[:12]` (les **12 premiers caractères** de la clé = `hs_` + 9 hex) (A6). L'exemple est illustratif (troncature d'affichage) ; la colonne `str(12)` fait foi. |
| R3 | « `GET\|POST /api/events/<event_id>/costs` » — un unique POST, alors que le module Frais a 4 sous-ressources (foyers, dépenses, transferts, demandes) chacune avec sa validation UI. | L'API **miroite les 4 sous-endpoints** POST (`/costs/expenses`, `/costs/households`, `/costs/transfers`, `/costs/payment-requests`) + le GET dashboard (§6.4.8). C'est la seule lecture compatible avec « mêmes règles de validation que l'UI, mêmes messages d'erreur ». |
| R4 | « `<event_id>` » dans les chemins API et de gestion des clés. | `<event_id>` = **`Event.code`** (6 caractères), pas `Event.id` (32 hex) (A3). Les routes de gestion sont sous `/e/<code>/api-keys` (donc `<event_id>` y est le `code`) ; par cohérence l'API utilise le `code`. La clé est la frontière de sécurité, pas l'identifiant dans l'URL. |
| R5 | « suppression / **retrait** d'un invité → SES clés supprimées (cascade owner_guest_id) » — le retrait est une désactivation (`is_active=False`), pas une suppression physique : la cascade DB ne se déclenche pas. | Double mécanique (A9) : (1) **suppression applicative** des clés dans `_remove_participant` (`app/events/__init__.py`) au retrait ; (2) **garde API** : clé dont l'owner invité est inactif → 401. La cascade DB `ondelete="CASCADE"` reste pour les suppressions physiques. |
| R6 | « `last_used_at` mis à jour (throttlé, pas à chaque requête) » — pas de période précisée. | Mise à jour si `last_used_at is None` ou **> 60 s** depuis la dernière mise à jour (§6.2.9). Période de 60 s (alignée sur la fenêtre de rate limit). |
| R7 | « `GET /api/health` — sans auth : `{"ok": true, "version": "…"}` » — aucune constante de version dans `app/`. | `APP_VERSION = "0.1.0"` ajouté dans `app/__init__.py`, aligné sur `pyproject.toml` (`version = "0.1.0"`) (A7). Distinct du `/health` existant (B015). |
| R8 | « Index … généré depuis les routeurs, pas dupliqué à la main » — mécanisme non précisé. | Chaque vue API porte un attribut `api_meta` (description, schéma requête, forme réponse) ; `GET /index` itère `current_app.url_map.iter_rules()` filtré sur le blueprint `api` et lit `view.api_meta` (A8). Méthode + chemin viennent de la règle (pas dupliqués). |
| R9 | « Contrainte : exactement un des deux owner non nul (check en application) » — pas de contrainte DB. | Check **en application** dans `create_api_key` (lève `ValueError`) (§3.2). Pas de `CHECK` en base (fidèle à la source spec). Garde API : ligne mal formée (les deux nuls) → 401, jamais 500. |
| R10 | Blueprint de gestion des clés : « blueprint existant `events` **ou** nouveau blueprint `apikeys` — ton choix, documente-le ». | **Nouveau blueprint `apikeys`** (`url_prefix="/e"`), enregistré inconditionnellement (A1). Justification : séparation des responsabilités, cohérence « un domaine = un blueprint », fonctionnalité core non gated. |

---

*Fin de la spec B034. Prochaine étape du pipeline : audit de la spec (étape 2), puis
écriture des tests `tests/test_apikeys.py` + `tests/test_api.py` (étape 3, TDD).*
