# B029 — Contexte d'événement & identité participant unique

- **Statut** : spec corrigée après l'audit et le re-audit `specs/audits/B029-spec.md` (21 constats + N1–N7 traités, voir §11) ; à valider
- **Branche** : `ui/tailwind-refonte`
- **Références** : `TASKS.md` (B029, tâches 29.1–29.6) ; `AUDIT_UI.md` §9 (F01 partiel, F09, F10 partiel, F22 partiel), §11.2 (modèle d'identité), §11.3 (F29, F30 serveur, F32), §11.5 point 1 (identité unique)
- **Base d'inventaire** : commit `06278ee`. B017 s'exécute avant B029 et peut avoir déplacé ou réécrit du HTML : l'agent localise par le **texte cité** (nom de fonction, variable, libellé), jamais par un numéro de ligne.
- **Ordre du programme** (`TASKS.md`) : B017 → **B029** → B030 → B018 → B019 → B020 → B021 → B022 → B023 → B024 → B025 → B026 → B027 → B028. B029 dépend de B017 (dont la spec, `specs/B017-socle-tailwind.md`, fait foi pour `base.html` ; contrat au §3.8) et ne dépend ni de B030 ni de B018.
- **Lecteur visé** : un agent de codage au contexte vierge. Il ne voit que cette spec, les tests du lot et `AGENTS.md`. Tout ce qu'il faut est ici.

---

## 1. Contexte, objectifs, périmètre

### 1.1 Constats (vérifiés dans le code)

1. **Huit copies** des helpers d'accès, avec des variantes silencieuses :
   - `_get_event_or_404` dans planning, meals, lists, logistics, voting, chat. Dans costs, la fonction renvoie `None` et la vue répond par la chaîne brute `"Not found", 404`. Media utilise `first_or_404()` en ligne.
   - `_resolve_actor` dans planning, meals, lists, logistics, voting, chat, costs, media :
     - voting renvoie le `Guest` du créateur via `ensure_creator_guest`, qui écrit en base et fait un commit pendant un GET ;
     - les sept autres renvoient `guest=None` pour le créateur ;
     - costs et media redirigent un visiteur non connecté vers `events.guest_access` (`/join`), les autres vers `events.my_code` (`/mycode`) ;
     - costs donne la priorité à la session invité sur le créateur (`_actor` renvoie l'invité si les deux existent), les autres au créateur.
   - `_actor_name` dans 6 modules et `_actor` dans costs. Ce dernier écrit toujours « Créateur ». Media écrit « Créateur » en dur (`actor_name = guest.display_name if guest else "Créateur"`), et `media.delete` journalise le nom de l'**auteur du média** au lieu de celui de la personne qui supprime.
   - Contrôles ad hoc : `current_user.is_authenticated and current_user.id == event.creator_id` apparaît dans `events` (`dashboard`, `members`, `log`, `_is_event_creator`), `voting.close`, `planning.rsvp`, `freemium._is_event_creator` (code mort) et dans les gabarits `events/dashboard.html`.
2. **Trois représentations du créateur** :
   - `Creator.id` dans `ListItem.assigned_to_id` (`lists.claim_item`) ;
   - `Guest(creator_id=…)` pour les sondages et le foyer des frais ;
   - aucune identité ailleurs : `ChatMessage.guest_id=None`, `Activity.created_by=None`, `Meal.created_by=None`, `MediaItem.uploaded_by=None`.

   Conséquences :
   - `planning.rsvp` refuse le créateur (« Le créateur ne fait pas de RSVP. ») alors qu'il peut voter ;
   - `lists/detail.html` compare `item.assigned_to == actor_name`, donc par nom d'affichage ;
   - `events/dashboard.html` calcule `my_name` avec `current_user.email.split('@').first`, ce qui est faux (`.first` n'existe pas, `email` peut être `None`).
3. **Contexte de gabarit** :
   - `inject_globals` relit l'événement (déduit du chemin `/e/<code>/…`) et l'invité, alors que la vue vient de les charger ;
   - `inject_event_days` lit `g.current_event`, qui n'est jamais défini, et aucun gabarit n'utilise `event_days` : c'est du code mort ;
   - le créateur n'a pas de pastille d'identité dans l'en-tête (`current_guest` vient seulement de la session `guest_<code>`).
4. **Écritures pendant un GET** : `events.dashboard` et `voting._resolve_actor` appellent `ensure_creator_guest`. Cette fonction crée aussi un **foyer**, ce qui change silencieusement les soldes des frais d'un événement ancien.
5. **F32** :
   - `events/dashboard.html` lie le titre d'un repas à `meals.index` sous la condition `"planning" in enabled_modules`. Avec Planning actif et Repas désactivé, on obtient une `BuildError` (500) ;
   - « Planifier les repas » pointe vers `planning.index` ;
   - le formulaire « Mes items » appelle `url_for('lists.toggle_item')` sans condition (`BuildError` si Listes est désactivé et qu'un article m'est attribué).
6. **Événement non vérifié** (`verified_at IS NULL`) : il est joignable (`/e/<code>/join`, `/mycode`), ses modules sont accessibles et son QR est servi. `invite_qr` ne filtre même pas `is_active`.
7. **Codes (F30, F01)** :
   - `access_by_code` exige exactement 8 caractères, alors que `verify` et `join` acceptent 4 à 8 : un créateur dont le code fait 6 caractères ne peut pas se reconnecter depuis l'accueil ;
   - les codes sont choisis par l'utilisateur ;
   - le bouton « Générer » de `join.html` et `verify.html` utilise `Math.random` ;
   - aucune vérification d'unicité du code créateur (`IntegrityError` → 500 si le code est pris) ;
   - la seule protection contre le brute-force est par IP ;
   - `/mycode` n'accepte pas le code du créateur, alors que c'est la page vers laquelle tout visiteur non connecté est redirigé.
8. **Codes d'événement réservés** : `generate_event_code` peut produire `access` ou `verify`. Une route statique (`/e/access`, `/e/verify/<token>`) masquerait alors l'événement.
9. **Migrations** :
   - `manage.py migrate` utilise `.venv/bin/python` : il n'est jamais exécuté dans l'image Docker, où `CMD` lance directement Waitress ;
   - au démarrage, `create_app` fait seulement `db.create_all()` et la purge.

### 1.2 Objectifs

1. **Un seul module** (`app/context.py`) résout l'événement, le participant et le rôle, avec au plus une requête pour l'événement et une pour le participant, mises en cache sur `g` **pour la durée d'une requête** (§3.3). `inject_globals` réutilise ce contexte sans aucune requête.
2. **Le créateur est toujours un participant `Guest`.** `created_by`, `uploaded_by`, `ChatMessage.guest_id`, `ListItem.assigned_to_id`, les RSVP et les votes contiennent toujours un `Guest.id`. Une migration idempotente convertit les anciennes valeurs.
3. **Droits centralisés** : `EventContext.can_edit(obj)` et `EventContext.can_delete(obj)`, plus `ctx.is_creator`. Les règles actuelles restent les mêmes, sauf les changements listés au §3.7.
4. **Réponses homogènes** :
   - visiteur non connecté → `/e/<code>/mycode` partout ;
   - événement inconnu, inactif ou non vérifié → 404 ;
   - action interdite → 403 ;
   - les deux sont rendus par les gabarits d'erreur ;
   - aucun lien vers un module désactivé, donc plus de `BuildError`.
5. **Codes d'accès** :
   - suggestion générée côté serveur (`secrets`) ;
   - nouveaux codes créateur de 8 caractères exactement, les anciens restant valables ;
   - unicité vérifiée ;
   - limitation des **échecs** par IP et par (IP, événement), avec délai progressif, sans aucun compteur global bloquant ;
   - réponses indifférenciées ;
   - journalisation sans le code ;
   - contrat de résolution utilisé par B019.
6. **Non-régression** : comportement externe inchangé hors des changements listés (§3.7, D1–D20). Tous les tests existants restent verts ; ceux qui sont adaptés figurent au §8.9.

### 1.3 Hors périmètre (décisions fermes)

| Sujet | Décision | Lot |
|---|---|---|
| Traduction des messages existants, identifiants neutres `@creator`/`@system` | Aucun message existant n'est modifié ni enveloppé. Les **nouveaux** messages utilisent `_()`. | B018 |
| Droits fins des frais (chacun supprime sa dépense, foyers, ratio) | Règles serveur actuelles conservées. Les écarts UI/serveur sont documentés (§3.6). | B024 |
| Droits fins des articles (suppression par l'auteur, `ListItem.created_by`) | Règle serveur actuelle conservée (§3.6) | B023 |
| Refonte de l'écran d'accueil (champ unique), `recover`, F16, sessions durables (F15) | B029 livre seulement l'API de résolution et l'alignement de `access_by_code` | B019 |
| Pastille d'identité (structure, style, `data-testid="identity-chip"`) | Livrée par B017 ; B029 change seulement la source du nom du créateur en contexte événement (§3.8) | B017 |
| Nom d'affichage éditable (F22), menu « Événement » | Inchangé | B020 |
| Compteur d'invités : `can_add_guest` compte `event.guests.count()` (créateur et inactifs inclus) ; la migration et le secours I3c ajoutent le participant créateur aux événements anciens qui n'en avaient pas, ce qui décale la limite d'une unité pour eux | Effet accepté et documenté (§9.3) ; **transmis à B030** (limites lues depuis le plan) : compter seulement les `Guest` actifs avec `creator_id IS NULL` | B030 |
| Page Invitations à la limite (F02) | Inchangé | B020 |
| `get_media_quota` qui crée la ligne de quota (commit) pendant le GET de la galerie | Inchangé : `MediaQuota` est remplacé par la relation au plan en B030 (D20) | B030 |
| Redirection d'une requête HTMX vers `/mycode` | Traité ici (`HX-Redirect`, §3.3) | — |
| Clôture/suppression de sondage dans l'UI | Inchangé (route `close` conservée) | B025 |
| Échange de repas qui déplace aussi le repas d'un autre auteur | Inchangé | B022 |
| Page 429 dédiée | Réponse par défaut de Flask-Limiter conservée | B019 |
| `events.export_pdf` (`@login_required` + `@require_tier`) | Décorateurs conservés ; seul le chargement de l'événement passe par le contexte (§5.1) | — |
| Fusion des `Guest` créateurs en double | Pas de fusion automatique : signalé par `check-identity` (§4.5) | — |

---

## 2. Modèle d'identité cible

### 2.1 Règles

| # | Règle |
|---|---|
| I1 | Tout acteur d'un événement est un `Guest` de cet événement. Le créateur de l'événement a un `Guest` « participant créateur », reconnaissable à `Guest.creator_id == Event.creator_id`. |
| I2 | **Unicité** : au plus un `Guest` **actif** avec `creator_id IS NOT NULL` par événement. L'application la vise (`ensure_creator_guest` est idempotent et réactive l'existant) et `check-identity` la contrôle. Il n'y a pas d'index unique en base : un index partiel SQLite échouerait sur des doublons hérités, et la migration doit toujours aboutir. **Participant canonique** : le plus ancien actif (`joined_at` croissant, puis `id`) ; toute lecture du participant créateur passe par cette règle. **Plafond assumé (concurrence)** : deux premières requêtes simultanées du même créateur (deux onglets) peuvent chacune insérer un participant, car pysqlite n'ouvre la transaction qu'au premier `INSERT`. Parade : après son commit, `get_or_create_creator_participant` **relit le canonique** et renvoie celui-ci, donc les deux requêtes travaillent sur le même ; le doublon inutilisé est signalé par `check-identity` (`duplicate_creator_guest`). |
| I3 | Le participant créateur est créé : (a) à la vérification de l'événement (`events.verify`, avec son foyer, comme aujourd'hui) ; (b) par la migration pour les événements vérifiés qui n'en ont pas (**sans foyer**) ; (c) en secours, par le contexte, si un créateur connecté n'en a pas (**sans foyer**, journalisé en `WARNING`). Aucune autre route n'en crée. |
| I4 | **Aucun foyer n'est créé implicitement** hors de `verify` et `join`. Ajouter un foyer change la répartition des frais : c'est une décision explicite. |
| I5 | `Guest.code` du participant créateur est un jeton aléatoire de 16 caractères hexadécimaux (`secrets.token_hex(8)`, comportement actuel). Il **ne sert jamais à s'authentifier** : la résolution de code exclut les `Guest` qui ont un `creator_id` (§7.3). |
| I6 | Nom du participant créateur à sa création : `creator.display_name`, ou à défaut `CREATOR_FALLBACK_NAME` (§3.1). Il est ensuite indépendant du `Creator` : un même créateur peut porter un nom différent dans chaque événement. |
| I7 | Un `Guest` dont `creator_id` est renseigné ne peut pas être retiré (`members` action `remove`) : réponse 403 (§3.7, D2). |

### 2.2 Porteurs d'identité dans la session

| Rôle | Porteur | Résolution du participant |
|---|---|---|
| Créateur | Session flask-login (`_user_id` = `Creator.id`), valable pour tous ses événements | `current_user.is_authenticated and current_user.id == event.creator_id` → participant = participant créateur (I2), créé en secours si absent (I3c) |
| Invité | `session["guest_<event.code>"] = Guest.id` | `Guest` actif de l'événement, avec `creator_id IS NULL`. Une session invité qui pointe vers un participant créateur est **ignorée** (personne ne devient créateur sans flask-login). |
| Visiteur | — | `participant = None` |

**Priorité** : si les deux porteurs sont présents, le **créateur** l'emporte (règle actuelle de 7 modules sur 8 ; costs s'aligne, §3.7 D8).

Aucune écriture de session nouvelle pour le créateur : B029 ne pose pas `guest_<code>` pour lui.

### 2.3 Pastille d'en-tête

La pastille est celle de B017 (`<span data-testid="identity-chip" data-role="creator|guest">`, sans attribut `title`, affichée si `event_role` est non nul, ou hors événement pour un créateur connecté). B029 **ne crée aucune seconde pastille** et ne change ni sa structure, ni son `data-testid`, ni sa règle d'affichage. Seul changement : la **source du nom du créateur en contexte événement**. Il devient celui de son participant (`current_participant.display_name`), qui est propre à l'événement (I6). Hors événement, la règle B017 reste inchangée : `current_user.display_name`, ou `_("Créateur")` si le nom est vide. Détail au §3.8.

---

## 3. API du contexte — `app/context.py` (nouveau)

Fichier typé (`mypy app/` sans erreur). Il importe `app.models`, `app.extensions`, `app.utils`, `flask`, `flask_login`. **Aucun module de blueprint ne l'importe en sens inverse.**

### 3.1 Types et constantes

```python
from dataclasses import dataclass
from typing import Literal

Role = Literal["creator", "guest", "visitor"]
ActorType = Literal["creator", "guest", "system"]
Requirement = Literal["participant", "creator", "none"]

SYSTEM_ACTOR_NAME = "Système"      # B018 remplace la valeur par SYSTEM_PLACEHOLDER ("@system")
CREATOR_FALLBACK_NAME = "Créateur"  # B018 remplace la valeur par CREATOR_PLACEHOLDER ("@creator")


@dataclass(frozen=True)
class Actor:
    name: str
    type: ActorType
    guest_id: str | None


SYSTEM_ACTOR = Actor(name=SYSTEM_ACTOR_NAME, type="system", guest_id=None)


def actor_for(participant: Guest | None) -> Actor:
    """None → SYSTEM_ACTOR ; participant créateur → type "creator" ; sinon "guest".
    name = participant.display_name ; guest_id = participant.id."""
```

Ces deux constantes sont les **seules** occurrences des textes « Système » et « Créateur » utilisés comme noms d'acteur dans le code Python après B029. `app/utils.py` (`ensure_creator_guest`) importe `CREATOR_FALLBACK_NAME` depuis `app.context`. Pour éviter un import circulaire, `app.context` importe `ensure_creator_guest` **dans le corps** de `get_or_create_creator_participant`.

### 3.2 `EventContext`

```python
@dataclass
class EventContext:
    event: Event
    participant: Guest | None
    is_creator: bool          # True ⇔ créateur de CET événement, connecté (flask-login)

    @property
    def role(self) -> Role: ...          # "creator" si is_creator, "guest" si participant, sinon "visitor"

    @property
    def actor(self) -> Actor: ...        # actor_for(self.participant)

    def is_author(self, author_id: str | None) -> bool:
        """participant non nul et author_id == participant.id (False si author_id est None)."""

    def can_edit(self, obj: object) -> bool: ...    # table §3.6
    def can_delete(self, obj: object) -> bool: ...  # table §3.6
```

Invariant : `is_creator` implique `participant is not None` et `participant.creator_id == event.creator_id`.

`can_edit` et `can_delete` renvoient `False` si `participant is None`. Elles lèvent `TypeError` pour un type absent de la table §3.6 : une erreur de programmation doit échouer bruyamment.

### 3.3 Chargement

```python
def load_event_context(code: str, *, require: Requirement = "participant") -> EventContext:
```

Algorithme, dans cet ordre :

1. Si `g.event_ctx` existe et que `g.event_ctx.event.code == code`, réutiliser ce contexte et passer directement à l'étape 6. Ce cache vaut **pour une seule requête** : voir « Durée de vie du cache » ci-dessous.
2. `event = Event.query.filter_by(code=code, is_active=True).first()`. Si l'événement est `None` ou si `event.verified_at is None` → `abort(404)`.
3. `is_creator = current_user.is_authenticated and current_user.id == event.creator_id`.
4. Participant :
   - si `is_creator` : `get_or_create_creator_participant(event, current_user)` ;
   - sinon, si `session.get(f"guest_{code}")` : `Guest.query.filter_by(id=…, event_id=event.id, is_active=True, creator_id=None).first()` ;
   - sinon `None`.
5. `ctx = EventContext(event, participant, is_creator)` ; `g.event_ctx = ctx`. Le contexte est posé sur `g` **avant** les refus, pour que les pages 403 et `/mycode` gardent la navigation de l'événement, comme aujourd'hui.
6. Refus :
   - `require != "none"` et `participant is None` :
     - requête HTMX (`request.headers.get("HX-Request") == "true"`) → `abort(Response(status=204, headers={"HX-Redirect": url}))`, où `url = url_for("events.my_code", code=event.code)`. HTMX recharge alors toute la page vers `/mycode`, au lieu d'injecter la page `mycode` complète dans un fragment (polling du chat du tableau de bord) ;
     - sinon → `abort(redirect(url))` (302) ;
   - `require == "creator"` et `not is_creator` (participant présent) → `abort(403)`.
7. Renvoyer `ctx`.

```python
def get_event_context() -> EventContext | None:
    """g.event_ctx s'il existe, sinon None. Aucune requête."""

def reset_event_context() -> None:
    """g.pop("event_ctx", None) ET g.pop("code_attempt_failed", None) (le drapeau d'échec de code, §7, ne doit pas fuir
    entre deux requêtes d'un même test). Enregistrée par create_app : app.before_request(reset_event_context)."""

def get_or_create_creator_participant(event: Event, creator: Creator) -> Guest:
    """Participant créateur canonique (I2). S'il est absent : ensure_creator_guest(event, creator,
    with_household=False), commit, log WARNING "creator participant backfilled event=<code>"
    sur le logger "app.context", puis RELECTURE du canonique (le plus ancien actif), qui est renvoyé."""
```

**Durée de vie du cache (obligatoire).** `g` n'est pas propre à une requête quand un contexte d'application est déjà ouvert. C'est le cas de la fixture `app` des tests (`with app.app_context(): yield app`) : avec Flask 3.1, chaque requête du client de test réutilise ce contexte et donc le même `g`. Le cache est donc **vidé au début de chaque requête** par un hook `@app.before_request` (`reset_event_context`), enregistré dans `create_app` **avant** les blueprints. En production (un contexte d'application par requête), le hook ne change rien. Les tests unitaires du §8.2 qui appellent `load_event_context` directement ouvrent **un `app.test_request_context()` distinct par « requête » simulée** et appellent `reset_event_context()` en entrée de chacun, car `test_request_context` ne déclenche pas `before_request`.

Pourquoi une fonction et pas un décorateur : `abort()` accepte une `Response` (redirection). Chaque vue garde sa signature `(code, …)`, mypy reste simple et il n'y a qu'un seul chemin de code. Pourquoi pas de paramètre `module=` : un module désactivé n'a pas de blueprint enregistré, donc ses routes répondent déjà 404 par le routage (`create_app`, comportement actuel testé par `test_module_gating`).

### 3.4 Journal

```python
def log_event(ctx: EventContext, action: str, target: str | None = None,
              details: str | None = None) -> ActivityLog:
    """log_action(db.session, ctx.event.id, ctx.actor.name, ctx.actor.type, action, target, details). Sans commit."""
```

`app.utils.log_action` reste inchangé : `log_event` l'appelle. Toutes les écritures du journal des vues d'événement passent par `log_event`, y compris dans media, qui construisait des `ActivityLog` à la main.

### 3.5 Intégration aux gabarits — `inject_globals`

`inject_globals` (dans `create_app`, dans sa version livrée par B017) est réécrit **sans aucune requête**. Il conserve toutes les clés que B017 consomme, avec les mêmes noms et la même sémantique (§3.8), et en ajoute deux (`ctx`, `current_participant`) :

```python
ctx = get_event_context()
participant = ctx.participant if ctx else None
return {
    # clés existantes / B017 — noms et sémantique inchangés
    "app_name": "holishared",
    "enabled_modules": [m for m in app.config["ENABLED_MODULES"] if m in app.blueprints],
    "current_lang": ...,                                   # inchangé
    "current_event": ctx.event if ctx else None,
    "current_guest": participant if (ctx and ctx.role == "guest") else None,
    "event_role": ctx.role if (ctx and ctx.role != "visitor") else None,
    # ajouts B029
    "ctx": ctx,
    "current_participant": participant,
}
```

- **`current_guest`** garde la sémantique B017 : l'**invité** (non créateur) de l'événement courant, `None` pour le créateur et le visiteur. **`current_participant`** est le participant quel que soit son rôle (créateur compris).
- **`event_role`** : `"creator"`, `"guest"` ou `None`, priorité au créateur, `None` hors événement. C'est exactement la règle B017 §4.1, désormais calculée par le contexte.
- La détection de l'événement par le chemin (`request.path.split("/")`) est supprimée : chaque page d'événement charge son contexte (§5). Une page d'erreur levée **avant** le chargement (événement inconnu) n'a pas de navigation d'événement : comportement actuel. Les pages `join` et `mycode` d'un visiteur ont un `current_event` non nul et `event_role=None`, donc le contexte de navigation `global` de B017 §4.1 s'applique, comme prévu par B017.
- `enabled_modules` ne contient que les modules dont le blueprint est enregistré. C'est la condition exacte pour que `url_for('<module>.…')` ne lève pas d'erreur.
- `inject_event_days` est supprimé (code mort, §1.1-3).
- Les gabarits de module accèdent à `ctx.participant`, `ctx.is_creator`, `ctx.role`, `ctx.can_edit(x)`, `ctx.can_delete(x)`. Les vues **ne passent plus** `guest=`, `is_creator=`, `can_modify=`, `can_delete=` à `render_template`. Elles continuent de passer `event=ctx.event` et leurs données métier.

### 3.6 Table des droits (actuelle → cible)

« Participant » veut dire `ctx.participant is not None`. « Créateur » veut dire `ctx.is_creator`. « Auteur » veut dire `ctx.is_author(<colonne>)`. Une valeur d'auteur `NULL` héritée ne correspond à personne : seul le créateur garde le droit, ce qui est déjà le cas aujourd'hui.

| Type (`isinstance`) | Action | Règle serveur actuelle | `can_edit` cible | `can_delete` cible | Changement ? |
|---|---|---|---|---|---|
| `Activity` | modifier / supprimer | créateur ou `created_by == guest.id` | créateur ou auteur(`created_by`) | idem | non |
| `Meal` | modifier / supprimer / déplacer | créateur ou `created_by == guest.id` | créateur ou auteur(`created_by`) | idem | non (refus : 403, D6) |
| `ActivityRSVP` (route `rsvp`) | répondre | invités seulement, créateur refusé | — (tout participant répond pour lui-même) | — | **oui, D1** |
| `SharedList` | créer / supprimer / cocher la couverture repas-activité | créer : tous ; supprimer : créateur ; couverture : tous | `False` (pas de route d'édition) | créateur | non |
| `ListItem` | ajouter, cocher, prendre | tous | — | — | non |
| `ListItem` | libérer (`unclaim`) | créateur ou `assigned_to_id == actor_id` | créateur ou auteur(`assigned_to_id`) | — | identifiant : `Guest.id` du créateur au lieu de `Creator.id` (D9) |
| `ListItem` | supprimer | **tous les participants** (aucun contrôle serveur) ; bouton affiché au créateur seulement | (voir ligne au-dessus) | participant | non. Écart UI/serveur conservé : le gabarit garde `ctx.is_creator` pour le bouton. Tranché en B023. |
| `LogisticsItem` | créer / modifier / supprimer | créer, modifier : tous ; supprimer : créateur | participant | créateur | non |
| `Poll` | créer / voter / clore | créer, voter : tous (créateur via son Guest) ; clore : créateur | créateur (clore) | créateur | non (visiteur sur `close` : redirection, D5) |
| `ChatMessage` | envoyer / supprimer | envoyer : tous ; supprimer : créateur ou `guest_id == guest.id` | `False` | créateur ou auteur(`guest_id`) | non |
| `MediaItem` | déposer / supprimer | déposer : tous ; supprimer : créateur ou `uploaded_by == guest_id` | `False` | créateur ou auteur(`uploaded_by`) | non (refus : 403, D6) |
| `Household` | créer / ratio / supprimer | créer, ratio : **tous** (UI : créateur) ; supprimer : créateur | participant | créateur | non. Écart UI conservé (`ctx.is_creator` dans le gabarit). B024. |
| `Expense` | créer / supprimer | créer : tous ; supprimer : créateur | `False` | créateur | non (B024) |
| `Transfer` | créer / supprimer | créer : tous ; supprimer : créateur | `False` | créateur | non |
| `PaymentRequest` | créer / régler / supprimer | créer, régler : tous ; supprimer : créateur | participant (régler) | créateur | non |
| `Guest` (membre) | ajouter / retirer | créateur ; le participant créateur peut être retiré | créateur | créateur **et** `obj.creator_id is None` | **oui, D2** |
| `Event` | inviter, membres (POST), export, suppression, export PDF | créateur | créateur | créateur | réponses homogénéisées (D3, D4) |

### 3.7 Changements de droits et de réponses (exhaustif)

| # | Avant | Après | Justification |
|---|---|---|---|
| D1 | `planning.rsvp` : créateur refusé (flash « Le créateur ne fait pas de RSVP. ») | Le créateur répond comme tout participant. Le RSVP est enregistré sous son `Guest.id`, journal `actor_type="creator"`. La section RSVP de `planning/index.html` s'affiche pour lui. | F10, identité unique |
| D2 | `members` `remove` peut désactiver le participant créateur | 403 si `not ctx.can_delete(target)` | I7 : retirer le créateur casse votes, RSVP et frais |
| D3 | `invite`, `invite_email`, `invite_resend` : visiteur → `/admin/login` (`login_required`) ; invité → `/admin/login` ; autre créateur → 404 | `require="creator"` : visiteur ou autre créateur sans session sur l'événement → `/mycode` ; invité → 403 | réponses homogènes (29.4) |
| D4 | `export_event`, `delete_event` : visiteur → 403 | visiteur → `/mycode` ; invité → 403 (inchangé) | idem |
| D5 | `voting.close` : visiteur → 403 | visiteur → `/mycode` ; invité → 403 (inchangé) | idem |
| D6 | `meals.edit/delete/move` et `media.delete` refusés : flash « Pas autorisé. » + redirection | `abort(403)` (gabarit 403) | réponses homogènes ; le bouton n'est jamais affiché sans le droit, donc seule une requête fabriquée y arrive |
| D7 | `costs.*`, `events.log` : visiteur → `/join` ; événement inconnu → chaîne `"Not found"` ; refus → chaîne `"Pas autorisé."` | `/mycode` ; 404 et 403 rendus par gabarit | F09, 29.4 |
| D8 | `costs` : créateur **et** session invité → l'acteur est l'invité ; créateur seul → nom « Créateur » | l'acteur est le participant créateur, avec son nom d'affichage | priorité créateur (§2.2) |
| D9 | `lists.claim_item` par le créateur : `assigned_to_id = Creator.id` | `assigned_to_id = Guest.id` du participant créateur | identité unique |
| D10 | `media.delete` journalise `item.uploaded_by_name` / type de l'auteur | journalise l'acteur qui supprime (`log_event`) | bogue |
| D11 | Événement non vérifié : `join`, `mycode`, tableau de bord, modules, `log`, `members`, `invite_qr` accessibles | 404 partout. Restent accessibles : `events.verify` (`/e/verify/<token>`) et `events.verify_sent` (`/e/new/sent/<code>`). | un événement non vérifié n'a pas encore d'identité créateur ; il est purgé à J+3 |
| D12 | Événement inconnu sur `dashboard`, `members`, `export_event`, `delete_event`, `guest_access`, `my_code` : flash « Événement introuvable. » + redirection vers `events.index` (qui renvoie un visiteur vers `/admin/login`) | 404 | homogène avec les modules |
| D13 | `invite_qr` sert un QR pour un événement inactif | 404 (contexte `require="none"`) | cohérence |
| D14 | `join` (GET/POST) avec un participant déjà résolu (créateur ou invité) affiche le formulaire, et le créateur peut se créer un second `Guest` | redirection vers le tableau de bord, sans création | I2 |
| D15 | `mycode` (GET **et** POST) avec un participant déjà résolu : formulaire affiché, ou nouvelle résolution du code au POST | redirection vers le tableau de bord, sans résolution du code ni décompte d'échec | cohérence |
| D16 | `mycode` (POST) ne reconnaît que les codes invités | reconnaît aussi le code personnel du **créateur de cet événement** → `login_user(creator)` → tableau de bord | la cible de toutes les redirections doit permettre au créateur de rentrer |
| D17 | `export_pdf` par le créateur d'**un autre** événement : 404 (`filter_by(code, creator_id=…).first_or_404()`) | redirection vers `/mycode` (il n'est pas participant de cet événement), comme toute route `require="creator"` | homogène avec D3 ; l'existence de l'événement n'est pas un secret (son code circule dans les liens) |
| D18 | `invite`, `invite_email`, `invite_resend` sur un événement **inactif** (aucun filtre `is_active`) : servis ; `export_pdf`, `invite*` sur un événement non vérifié : servis | 404 | même règle que D11/D13 : seul un événement actif et vérifié existe |
| D19 | Ordre de chargement variable : objet puis acteur dans `planning.edit/delete`, `meals.edit/delete`, `logistics.edit/delete`, `lists.*` (liste et article), `chat.delete` ; acteur puis objet ailleurs. Un visiteur sur un objet inexistant reçoit 404 dans le premier groupe | **ordre unique partout : contexte → objet → droit**. Un visiteur reçoit toujours la redirection vers `/mycode`, même si l'objet n'existe pas ; un participant sur un objet inexistant reçoit 404 ; un participant sans droit reçoit 403 (y compris costs, §5.8) | une seule règle ; la redirection ne révèle pas l'existence des objets à un non-participant |
| D20 | `media.gallery` appelle `get_media_quota`, qui crée la ligne `MediaQuota` (commit) pendant un GET | **inchangé** (seule écriture GET conservée, hors identité) | `MediaQuota` est remplacé par la relation au plan en B030 ; corriger ici une table que B030 supprime serait du travail jeté |

Aucun autre droit ni aucune autre réponse ne change.

### 3.8 Contrat avec B017

B017 s'exécute avant B029 et `specs/B017-socle-tailwind.md` fait foi pour `base.html`, `app/ui.py` et `build_nav`. B029 ne renomme et ne supprime rien de ce que B017 consomme.

**Clés que `inject_globals` doit continuer à fournir, avec des noms et une sémantique identiques à B017 :**

| Clé | Sémantique (identique à B017) | Source après B029 |
|---|---|---|
| `app_name` | `"holishared"` | inchangée |
| `current_lang` | langue active | inchangée |
| `enabled_modules` | séquence des noms de modules actifs, passée à `build_nav` | `[m for m in ENABLED_MODULES if m in app.blueprints]` : sous-ensemble ordonné de la liste de configuration, qui exclut seulement les noms sans blueprint (aucune différence pour une configuration valide) |
| `current_event` | événement actif de l'URL courante, ou `None` | `ctx.event` (événement actif **et vérifié**, D11) |
| `current_guest` | `Guest` invité du visiteur dans cet événement, ou `None` | `ctx.participant` si `ctx.role == "guest"`, sinon `None` |
| `event_role` | `"creator"` / `"guest"` / `None` (priorité créateur, `None` hors événement) | `ctx.role` sauf `"visitor"` → `None` |

**Globaux Jinja de B017** (`asset_url`, `icon`, `ui_importmap`, `ui_strings`, `build_nav`, enregistrés par `init_ui`) : non touchés. L'appel `build_nav(request.endpoint, enabled_modules, current_event.code if current_event else None, event_role, current_user.is_authenticated)` reste valable tel quel.

**Ajouts B029** (nouveaux noms, sans collision) : `ctx`, `current_participant`.

**Pastille `identity-chip`** : structure, `data-testid`, `data-role`, badge « Créateur » et règle d'affichage B017 inchangés. Une seule modification dans `base.html`, l'expression du **nom** dans la branche créateur :
- avant (B017) : `current_user.display_name or _("Créateur")` ;
- après (B029) : `current_participant.display_name if current_participant else (current_user.display_name or _("Créateur"))`.

En contexte événement, le créateur a toujours un participant (I3c), donc son nom est celui de l'événement. Hors événement, `current_participant` vaut `None` et la règle B017 s'applique. La branche invité (`current_guest.display_name`) est inchangée. Le littéral `_("Créateur")` reste dans le gabarit, comme le prévoit B017.

**Gabarits B017 que B029 modifie** (localisation par variable ou libellé) :
- `events/dashboard.html` : le bloc code personnel de B017 utilise `guest.id` / `guest.code`, qui deviennent `ctx.participant.id` / `ctx.participant.code`, et le bloc est conditionné à `ctx.role == "guest"` (§5.1) ;
- `events/members.html`, `costs/index.html` : remplacement de `is_creator` par `ctx.is_creator` uniquement ;
- `events/join.html`, `events/verify.html` : B017 y laisse explicitement le script de génération `Math.random` à B029, qui le supprime (§7.2).

**Robustesse de B017 face à D11 (décision du coordinateur)** : après B029, un événement non vérifié répond 404 partout sauf `verify` et `verify_sent` (D11). **B017 est rendu robuste de son côté**, dans sa propre spec. Ses tests T16 et T17 et sa graine de démonstration créent leurs événements de navigation avec `verified_at`. Sa scène `ui:check` `event-unverified` est limitée aux pages `verify` / `verify_sent`, et la graine garde un `event.unverified` (T94, T96 inchangés). B029 **ne modifie aucun fichier de B017**, mais a les **obligations** suivantes :
1. le commit qui introduit D11 (commit 6) exécute T16, T17, T94, T96 et `npm run ui:check` et constate qu'ils sont **verts**. Si l'un est rouge parce que B017 n'a pas appliqué cette robustesse, B029 **s'arrête et remonte l'écart** (gate, règle « escalade » d'AGENTS), sans contournement dans B029 ;
2. deux tests B029 exécutent explicitement le scénario : H32 (variante de T16 : `app_factory`, événement **vérifié**, `/planning` → 200) et H33 (variante de T17 : modules vides, `/members` → 200). H10 (`verify_sent` d'un événement non vérifié → 200) et H8 (tableau de bord du même événement → 404) couvrent la scène `event-unverified`.

**Fixtures B017 réutilisées** : `creator_client`, `guest_client`, `app_factory` (`tests/conftest.py`). B029 ne les modifie pas.

---

## 4. Migrations de données — `app/migrations.py` (nouveau)

### 4.1 Mécanisme (vérifié) et décision

Il n'existe aujourd'hui que les ajouts de colonnes de `manage.py migrate`. Ils ne sont jamais exécutés en Docker : `manage.py` utilise `.venv/bin/python`, et le `CMD` de l'image lance Waitress directement. La migration d'identité est **une migration de données sans changement de schéma**. Elle s'exécute :

1. **au démarrage** : dans `create_app`, juste après le bloc de purge et sous le même `try/except` journalisé (l'application démarre même si la migration échoue) ;
2. par `python manage.py migrate` : `print('[OK] identity', run_identity_migration(app))` puis `print('[OK] backups pruned', prune_backups(app.instance_path))` sont ajoutés **à la fin** de la chaîne du `-c`, **après** tous les `add_col` et la reconstruction de `creators`. L'exécution au démarrage déclenchée par le `create_app()` de cette commande peut échouer sur un schéma ancien (colonne manquante) : l'erreur est journalisée puis ignorée, et l'appel explicite final s'exécute sur le schéma à jour ;
3. en **lecture seule**, par `python -m app.migrations check` (point d'entrée `if __name__ == "__main__":` de `app/migrations.py`, qui crée l'app, pousse un contexte et affiche `check_identity`). Ce point d'entrée fonctionne en Docker (`docker compose exec app python -m app.migrations check`) comme en local. `manage.py check-identity` l'appelle avec le Python du venv.

Tests : base `:memory:` vide au démarrage, donc la migration au démarrage ne fait rien.

### 4.2 API

```python
def plan_identity_migration(session) -> dict[str, int]   # calcul à blanc, aucune écriture
def migrate_identity(session) -> dict[str, int]          # applique, un seul commit
def check_identity(session) -> list[str]                 # lecture seule
def backup_sqlite_database(db_uri: str, instance_path: str) -> Path | None
def prune_backups(instance_path: str, *, keep: int = 3, max_age_days: int = 30) -> int
def run_identity_migration(app: Flask) -> dict[str, int]
```

- **Une seule implémentation pour les deux calculs** : `_run_identity_steps(session, *, apply: bool) -> dict[str, int]`. `plan_identity_migration(session)` = `_run_identity_steps(session, apply=False)` ; `migrate_identity(session)` = `_run_identity_steps(session, apply=True)` + commit. Les 8 clés (§4.3) et toutes les conditions sont le **même code** ; seules les écritures sont conditionnées par `apply`.
  - Avec `apply=False`, les étapes 1–2 ne créent ni ne réactivent rien. Elles enregistrent pour chaque événement concerné un **participant prévu** en mémoire (identifiant sentinelle `f"planned:{event.id}"`, nom `(creator.display_name or CREATOR_FALLBACK_NAME)[:50]`, actif).
  - Les étapes 3 à 8 utilisent ce participant prévu comme s'il existait, **y compris dans la comparaison de nom** de `list_items_from_name`. Les compteurs à blanc sont donc **identiques** à ceux de la migration réelle (test M31).
  - Aucune écriture, aucun objet ajouté à la session.
- `run_identity_migration` :
  1. `plan = plan_identity_migration(db.session)` ;
  2. si `sum(plan.values()) == 0` : renvoie `plan` (tous zéros), **sans sauvegarde ni écriture**. C'est le cas de tout démarrage après la première migration, **même si `check_identity` signale des anomalies non corrigeables** (doublons, article étranger) ;
  3. sinon : `backup_sqlite_database(...)`, puis `prune_backups(...)`, puis `migrate_identity(db.session)` ;
  4. log INFO `identity migration <dict> backup=<chemin ou ->` sur le logger `app.migrations`.
- `backup_sqlite_database` :
  - renvoie `None` pour une URI non SQLite ou `sqlite:///:memory:` ;
  - sinon, copie la base avec `sqlite3.connect(src).backup(sqlite3.connect(dst))` (compatible WAL) vers `<instance_path>/backups/pre-identity-<YYYYmmddTHHMMSSZ>.db` (horodatage UTC, dossier créé si besoin, droits `0o600` sur le fichier) et renvoie le chemin.
  - **Emplacement** : `instance/backups/` est distinct de `instance/media/<code>/`. L'export ZIP (`events.export_event`) ne parcourt que `instance/media/<code>/` et ne contient donc jamais de sauvegarde.
- `prune_backups` supprime, parmi les fichiers `pre-identity-*.db` de `<instance_path>/backups/`, ceux dont la date de modification dépasse `max_age_days`, puis tous sauf les `keep` plus récents. Elle renvoie le nombre de fichiers supprimés et ne touche à aucun autre fichier.
- **Rétention** : une sauvegarde contient des données personnelles (pseudos, e-mails conservés, messages). Sa durée de vie est donc alignée sur la purge des événements (30 jours après la fin). `prune_backups` est appelée à **chaque création de sauvegarde** (`run_identity_migration`), à **chaque démarrage** (`_purge_expired_events`) et à **chaque `manage.py migrate`**. Garantie exacte : **au plus 3 fichiers**, et un fichier de plus de 30 jours est supprimé **au premier démarrage, `manage.py migrate` ou nouvelle sauvegarde qui suit son 30e jour**. Plafond assumé : un processus qui tourne sans redémarrage ni migration peut conserver la sauvegarde au-delà. Aucune tâche périodique n'est ajoutée : l'application n'en a pas, et la purge des événements suit la même règle. Cette règle est documentée dans `DEV_LOG.md` à la clôture.
- `migrate_identity` utilise l'ORM uniquement (règle AGENTS : pas de SQL brut hors agrégats). Elle fait **un seul commit** final et renvoie les compteurs. En cas d'exception : `session.rollback()` puis la propagation de l'exception.

### 4.3 Étapes de `migrate_identity` (dans cet ordre)

| Clé du résultat | Règle |
|---|---|
| `creator_guests_reactivated` | Pour chaque événement `is_active` et `verified_at IS NOT NULL` sans `Guest` actif avec `creator_id == event.creator_id` : s'il existe un `Guest` **inactif** avec ce `creator_id`, réactiver le plus récent (`joined_at` décroissant). |
| `creator_guests_created` | Sinon, créer `Guest(code=secrets.token_hex(8), display_name=(creator.display_name or CREATOR_FALLBACK_NAME)[:50], event_id, creator_id=event.creator_id)`. **Sans foyer** (I4). La troncature à 50 caractères est nécessaire : `Guest.display_name` fait 50 caractères, `Creator.display_name` 100. La même troncature s'applique dans `ensure_creator_guest`. |
| — | **`session.flush()`** après les étapes 1–2, pour que les `Guest.id` (valeur par défaut Python) existent avant les étapes 3–8. |
| `list_items_from_creator_id` | `ListItem` dont `assigned_to_id` est l'`id` d'un `Creator` : remplacé par l'id du participant créateur canonique de l'événement de la liste (`item.parent_list.event_id`). Si l'id est celui d'un **autre** créateur que celui de l'événement : inchangé (signalé par `check_identity`). |
| `list_items_from_name` | `ListItem` avec `assigned_to != ""` et `assigned_to_id IS NULL` : s'il existe **exactement un** `Guest` actif de l'événement avec `display_name == assigned_to` (comparaison exacte), poser son id. Zéro ou plusieurs correspondances : cas ambigu, inchangé. |
| `activities_created_by` | `Activity.created_by IS NULL` → id du participant créateur. Justification : le code n'a jamais écrit `NULL` que pour le créateur (`created_by=guest.id if guest is not None else None`, `guest` valant `None` seulement pour lui). |
| `meals_created_by` | `Meal.created_by IS NULL` → id du participant créateur (même justification). |
| `chat_messages_guest_id` | `ChatMessage.guest_id IS NULL AND author_type == "creator"` → id du participant créateur. Un message `author_type == "guest"` sans `guest_id` est ambigu : inchangé. |
| `media_uploaded_by` | `MediaItem.uploaded_by IS NULL` → id du participant créateur (même justification que pour les activités). |

Les étapes 3 à 8 ne concernent que les événements **actifs et vérifiés** qui ont un participant créateur après les étapes 1 et 2 : les événements non vérifiés ne sont pas touchés. Les colonnes dénormalisées (`author_name`, `uploaded_by_name`, `assigned_to`, `ActivityLog.actor_name`) **ne sont pas modifiées** : leur réécriture appartient à B018 (§10).

### 4.4 Idempotence

Chaque étape est conditionnée par la valeur héritée (`NULL`, `Creator.id`, absence de participant). Une seconde exécution renvoie **tous les compteurs à 0**, ne crée aucun `Guest` et, via `run_identity_migration`, **ne crée aucune sauvegarde**.

### 4.5 `check_identity` (script de vérification, lecture seule)

`check_identity` **n'écrit rien, ne corrige rien et ne déclenche aucune sauvegarde**. Elle renvoie une liste triée de chaînes `"<type>:<id>"`. Son périmètre est celui de la migration : les événements **actifs et vérifiés** et leurs objets.

| Type | Condition | Corrigé par `migrate_identity` ? |
|---|---|---|
| `missing_creator_guest` | événement sans participant créateur actif | oui |
| `duplicate_creator_guest` | plus d'un participant créateur actif (id de l'événement) | non (signalement seul) |
| `list_item_creator_id` | `ListItem.assigned_to_id` égal à un `Creator.id` | oui, si c'est le créateur de l'événement ; sinon signalement |
| `list_item_foreign_guest` | `ListItem.assigned_to_id` non nul qui n'est l'id d'aucun `Guest` de l'événement de la liste (et pas un `Creator.id`) | non |
| `activity_null_author` / `meal_null_author` | `created_by IS NULL` | oui |
| `chat_creator_null_guest` | `author_type == "creator"` et `guest_id IS NULL` | oui |
| `media_null_uploader` | `uploaded_by IS NULL` | oui |

`python -m app.migrations check` (et `manage.py check-identity`, ajouté à `COMMANDS` avec la description `Check participant identity consistency`) affiche chaque ligne et sort avec le code 1 s'il y en a, 0 sinon (`[OK] identity consistent`).

### 4.6 Retour arrière (documenté dans `DEV_LOG.md` à la clôture)

1. **Code seul** : l'ancien code fonctionne sur des données migrées. Les anciens contrôles « créateur → tout autorisé » restent vrais, et un `Guest.id` dans `created_by`, `guest_id`, `uploaded_by` ou `assigned_to_id` est un identifiant valide. Redéployer la version précédente suffit.
2. **Données** : arrêter l'application, puis copier la sauvegarde sur la base et redémarrer.
   - Local : `cp instance/backups/pre-identity-<horodatage>.db instance/holishared.db`.
   - Docker : `docker compose stop app`, puis `docker compose run --rm --no-deps --entrypoint sh app -c 'cp /app/instance/backups/pre-identity-<horodatage>.db /app/instance/holishared.db'`, puis `docker compose start app`.
   - La sauvegarde n'existe que si une migration effective a eu lieu, et pendant au plus 30 jours (§4.2).
3. **Vérification** après déploiement : `docker compose exec app python -m app.migrations check`.

---

## 5. Conversion module par module

Règles communes à **toutes** les vues sous `/e/<code>/…` :
- la première instruction est `ctx = load_event_context(code, require=...)` ;
- l'objet métier est chargé ensuite, avec `filter_by(id=..., event_id=ctx.event.id).first()` puis `abort(404)` s'il est absent ;
- le droit est vérifié en dernier : refus par `abort(403)`. L'ordre **contexte → objet → droit** est le même partout (D19) ;
- le journal passe par `log_event(ctx, ...)` ;
- l'auteur est `ctx.participant.id` ;
- les imports devenus inutiles (`session`, `current_user`, `Guest`, `ensure_creator_guest`) sont retirés (ruff).

**Fonctions supprimées partout** : `_get_event_or_404`, `_resolve_actor`, `_actor_name`, `_actor` (costs), `_can_modify` (planning, meals), `_can_delete` (chat), `_is_event_creator` (events **et** `freemium`), `_get_current_guest` (events).

### 5.1 `app/events/__init__.py`

| Vue | `require` | Changements |
|---|---|---|
| `index`, `create`, `verify_sent`, `recover_code` | — | inchangées |
| `access_by_code` | — | §7.4 |
| `verify` | — | §7.5 (dont la conservation du code d'un créateur existant). Appelle `ensure_creator_guest(event, creator, num_adults, num_children)` (avec foyer). Le commit reste celui de la vue ; une `IntegrityError` au commit (course sur `personal_code`) → `db.session.rollback()` et nouveau rendu du formulaire avec l'erreur « déjà utilisé » (§7.5). |
| `dashboard` | `participant` | Suppression de l'appel à `ensure_creator_guest` et du test d'accès en ligne. Ne passe plus `guest=`. Le reste des données est inchangé. |
| `members` | `participant` | `is_creator` → `ctx.is_creator`. POST `add` : inchangé (créateur seulement, POST invité ignoré). POST `remove` : la cible est `Guest.query.filter_by(id=…, event_id=ctx.event.id).first()` ; `None` → 404 ; `not ctx.can_delete(target)` → 403 (D2). Ne passe plus `is_creator=`. |
| `export_event`, `delete_event` | `creator` | suppression de `_is_event_creator` (D4) |
| `export_pdf` | `creator` | décorateurs `@login_required` et `@require_tier("pro")` **conservés et dans le même ordre**. Le corps remplace la requête `filter_by(code=…, creator_id=…).first_or_404()` par `ctx = load_event_context(code, require="creator")` et passe `event=ctx.event` (D17, D18). |
| `invite`, `invite_email`, `invite_resend` | `creator` | suppression de `@login_required` et du filtre `creator_id=current_user.id` (D3, D18). `invite_email` garde son `@limiter.limit("20 per hour")`. |
| `invite_qr` | `none` | D13 |
| `guest_access` (join) | `none` | D11, D12, D14 ; suggestion §7.2 ; refus d'un code égal au code du créateur §7.5 ; limites §7.6. `mark_attempt_failed` est appelé **uniquement** quand le code est refusé (déjà utilisé, ou égal au code du créateur), jamais pour un pseudo, un e-mail, un format de code invalide ou « Événement complet. ». Le rendu des erreurs est inchangé (flash par erreur + formulaire, statut 200). |
| `my_code` | `none` | D15, D16 ; résolution §7.3 ; limites §7.6. **POST** : (1) si `ctx.participant` existe → redirection vers le tableau de bord, sans résolution ni décompte (D15) ; (2) sinon `resolve_event_code(ctx.event, request.form.get("guest_code", ""))` : `"guest"` → `session[f"guest_{code}"] = guest.id` → tableau de bord ; `"creator"` → `login_user(creator)` → tableau de bord ; `None` → `mark_attempt_failed("event", code)`, `flash("Code invalide.", "danger")` (message **existant**, inchangé) et rendu de `events/mycode.html` avec le statut **200**. Un code de mauvais format est un échec comme un autre (même réponse, même décompte). |
| `log` | `participant` | D7 |

Gabarits :
- `events/dashboard.html` :
  - supprimer `{% set is_creator = … %}` et `{% set my_name = … %}` ;
  - remplacer `is_creator` par `ctx.is_creator` ;
  - n'afficher le bloc « code personnel » (dans sa version B017, qui référence `guest.id` / `guest.code`) que si `ctx.role == "guest"`, avec `ctx.participant.id` / `ctx.participant.code` ;
  - « Mes items » : `item.assigned_to_id == ctx.participant.id` (au lieu de la comparaison par nom) ;
  - liens conditionnels §6.2.
- `events/members.html` : `is_creator` → `ctx.is_creator`. La variable locale `is_creator_guest` est conservée. Le bouton « Retirer » reste masqué pour le participant créateur (comportement actuel).
- `events/join.html`, `events/verify.html` : §7.2.

### 5.2 `app/planning/__init__.py`

- `index` (`participant`) : `guest_rsvps` est calculé pour `ctx.participant`. On ne passe plus `guest` ni `can_modify`.
- `create` : `created_by=ctx.participant.id`.
- `edit`, `delete` : `ctx.can_edit(activity)` / `ctx.can_delete(activity)`, sinon 403.
- `rsvp` (`participant`) : suppression du bloc qui refuse le créateur (D1) et de la résolution manuelle de session. Le RSVP utilise `ctx.participant.id`, et `log_event(ctx, "rsvp.updated", target=activity.title, details=status)` remplace l'appel en dur `guest.display_name, "guest"`. L'upsert actuel (`IntegrityError` → mise à jour) est conservé.
- `planning/index.html` : `can_modify(act)` → `ctx.can_edit(act)` ; `{% if guest and activities %}` → `{% if ctx.participant and activities %}`.

### 5.3 `app/meals/__init__.py`

- `create` : `created_by=ctx.participant.id`.
- `edit`, `delete`, `move` : `ctx.can_edit(meal)`, sinon `abort(403)` (D6, au lieu du flash et de la redirection).
- `meals/index.html` : `can_modify(meal)` → `ctx.can_edit(meal)`.

### 5.4 `app/lists/__init__.py`

- `index`, `detail`, rendu d'erreur de `add_item` : ne passent plus `guest` ni `is_creator`.
- `add_item` : si `assigned_to` est non vide, `assigned_to_id` reçoit l'id de l'**unique** `Guest` actif de l'événement dont `display_name == assigned_to`, sinon `None` (même règle que la migration).
- `claim_item` : `assigned_to = ctx.actor.name`, `assigned_to_id = ctx.participant.id` (D9).
- `unclaim_item` : `ctx.can_edit(item)`, sinon 403.
- `delete_item` : pas de contrôle supplémentaire (règle actuelle, §3.6).
- `delete_list` : `ctx.can_delete(shared_list)`, sinon 403.
- `toggle_meal`, `toggle_activity` : contexte, puis liste (404) ; pas de droit supplémentaire.
- Ordre unique (D19) : `claim_item`, `unclaim_item`, `toggle_item`, `delete_item`, `delete_list`, `detail` chargent le contexte **avant** la liste et l'article (aujourd'hui, l'inverse).
- `lists/detail.html` :
  - supprimer `{% set actor_name = … %}` ;
  - « à moi » s'écrit `item.assigned_to_id == ctx.participant.id`, aux deux endroits (classe `mine` et branche `elif`) ;
  - `is_creator` → `ctx.is_creator` (bouton de suppression d'article et zone « Supprimer la liste »).

### 5.5 `app/logistics/__init__.py`

- `delete` : `ctx.can_delete(item)`, sinon 403.
- `logistics/index.html` : `{% if is_creator %}` (lien de suppression) → `{% if ctx.can_delete(item) %}`.

### 5.6 `app/voting/__init__.py`

- `index` et `detail` : `guest_votes` / `guest_vote` sont calculés pour `ctx.participant`. Les noms de variables de gabarit sont conservés.
- `vote` : suppression du test redondant `if guest is None`.
- `close` (`participant`) : `ctx.can_edit(poll)`, sinon 403. `log_event(ctx, "poll.closed", target=poll.question)` (D5).
- `voting/index.html`, `voting/detail.html` : `{% if guest %}` / `{% if guest and … %}` → `ctx.participant`.

### 5.7 `app/chat/__init__.py`

- `send` : `guest_id=ctx.participant.id`, `author_name=ctx.actor.name`, `author_type=ctx.actor.type`.
- `index` et `send` (réponse HTMX) : ne passent plus `can_delete`.
- `delete` : contexte, puis message (404), puis `ctx.can_delete(message)`, sinon 403 (D19 : aujourd'hui, le message est chargé avant l'acteur).
- `chat/_messages.html` : `can_delete(msg)` → `ctx.can_delete(msg)`. Le fragment est rendu par `chat.index`, qui a chargé le contexte, y compris quand il est inclus en HTMX dans le tableau de bord.

### 5.8 `app/costs/__init__.py`

- Toutes les vues :
  - `require="participant"` ;
  - `"Not found", 404` → `abort(404)` ;
  - `"Pas autorisé.", 403` → `abort(403)` (D7) ;
  - les vues de suppression utilisent `ctx.can_delete(obj)` après le chargement de l'objet (expense, household, transfer, payment request) ;
  - l'acteur du journal est `ctx.actor` (D8).
- `index` : `my_household` est le foyer dont `guest_id == ctx.participant.id`. La branche spécifique au créateur est supprimée.
- `costs/index.html`, `costs/household_form.html` : `is_creator` → `ctx.is_creator` ; ne plus passer `guest`.
- Ordre de chargement des vues de suppression : contexte, puis objet (404), puis droit (403) (D19). Aujourd'hui, le droit est testé avant l'objet : pour un invité, un objet inexistant donnait 403 et donne désormais 404 (test H27).

### 5.9 `app/media/__init__.py`

- Toutes les vues (`file`, `gallery`, `upload`, `detail`, `delete`) : `require="participant"`. Plus de `first_or_404()` sur l'événement (D7 : redirection vers `/mycode`).
- `upload` : `uploaded_by=ctx.participant.id`, `uploaded_by_name=ctx.actor.name`, `log_event(ctx, "media.uploaded", …)` avec les mêmes `target` et `details` qu'aujourd'hui.
- `delete` : `ctx.can_delete(item)`, sinon 403 (D6). `log_event(ctx, "media.deleted", target=item.original_name)` (D10).
- `gallery` : la jauge reste réservée à `ctx.is_creator`. L'appel à `get_media_quota` (création de la ligne de quota pendant un GET) est conservé tel quel (D20, B030).
- `media/gallery.html` : `is_creator` → `ctx.is_creator`. `media/detail.html` : condition de suppression → `ctx.can_delete(item)`.

### 5.10 `app/auth/__init__.py`, `app/utils.py`, `app/models.py`, `app/freemium.py`, `app/__init__.py`

- `auth` : inchangé.
- `utils.ensure_creator_guest(event, creator, num_adults=1, num_children=0, *, with_household=True) -> Guest` :
  - **ne fait plus de commit** (seulement `flush`) : l'appelant valide ;
  - réutilise le participant canonique actif, sinon réactive le plus récent inactif, sinon crée (`display_name=(creator.display_name or CREATOR_FALLBACK_NAME)[:50]`) ;
  - crée le foyer seulement si `with_household` est vrai et qu'aucun foyer n'existe pour ce `Guest`.
- `models` : §7.1 (`CODE_ALPHABET`, `generate_guest_code`, `generate_event_code`).
- `freemium` : suppression de `_is_event_creator` (inutilisé).
- `__init__` : §3.3 (`app.before_request(reset_event_context)`), §3.5 (`inject_globals`, suppression de `inject_event_days`), §4.1 (migration au démarrage), §4.2 (`prune_backups` appelé par `_purge_expired_events`).
- `extensions._create_limiter` : ajoute `in_memory_fallback_enabled=True` et `swallow_errors=True` aux arguments du `Limiter` (§7.6, Redis indisponible).

### 5.11 Gabarits d'erreur

`errors/403.html` et `errors/404.html` : l'élément racine du contenu reçoit `data-testid="error-403"` / `data-testid="error-404"`. Le texte est inchangé.

---

## 6. Réponses d'erreur et modules désactivés

### 6.1 Règles

| Cas | Réponse |
|---|---|
| Événement inconnu, inactif ou non vérifié, sous `/e/<code>/…` | 404, gabarit `errors/404.html` |
| Objet inconnu ou d'un autre événement | 404, gabarit |
| Visiteur sans participant sur une page qui en exige un | 302 vers `/e/<code>/mycode` ; en HTMX (`HX-Request: true`), 204 avec l'en-tête `HX-Redirect` vers la même URL (§3.3) |
| Participant sans le droit | 403, gabarit `errors/403.html` |
| Module désactivé | 404 par le routage (blueprint non enregistré) |

Il ne reste dans `app/` aucun `return "Not found"`, `return "Pas autorisé."`, `return _("Pas autorisé."), 403`, ni aucun flash « Pas autorisé. » suivi d'une redirection (test statique T-S3).

### 6.2 Liens conditionnels (F32)

Règle : tout `url_for('<module>.…')` dans un gabarit est entouré de `{% if "<module>" in enabled_modules %}`, où `<module>` est **le blueprint cible du lien**. `events/dashboard.html` :

| Élément | Avant | Après |
|---|---|---|
| « Planifier les repas » | `planning.index` sous condition `planning` | `meals.index` sous condition `meals`, `data-testid="plan-meals-action"` |
| « Ajouter une activité » | `planning.create` sous condition `planning` | inchangé (condition `planning`, propre au lien) |
| Titre d'un repas de la chronologie | `meals.index` sous condition `planning` | `meals.index` sous condition `meals` ; sinon texte simple |
| Titre d'une activité de la chronologie | `planning.index` sous condition `planning` | inchangé |
| Section « Mes items » (formulaire `lists.toggle_item`) | sans condition | section entière sous condition `lists`, `data-testid="my-items"` |
| Autres liens (`voting`, `lists`, `chat`, `logistics`) | déjà conditionnés sur leur module | inchangés |

`base.html` conditionne déjà chaque lien sur son propre module. B029 vérifie seulement qu'il en est toujours ainsi après B017 (test L6).

---

## 7. Codes d'accès (F30 serveur, F01 partiel)

### 7.1 Génération — `app/models.py`

```python
CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # sans 0 1 i l o
RESERVED_EVENT_CODES = frozenset({"access", "verify"})

def generate_guest_code(length: int = 8) -> str      # secrets.choice sur CODE_ALPHABET
def generate_event_code(length: int = 6) -> str      # alphabet actuel inchangé ; recommence tant que le code est dans RESERVED_EVENT_CODES
```

### 7.2 Suggestion au rendu du formulaire (décision : pas d'endpoint)

Pas de route `POST /e/code/suggest`. Le serveur prérenseigne le champ code à chaque rendu du formulaire où il est vide. Cela supprime une surface d'attaque à limiter, et le formulaire fonctionne sans JS.

`app/access.py` (nouveau) :

```python
def suggest_creator_code() -> str:   # generate_guest_code(8) non utilisé par un Creator (5 essais, puis RuntimeError)
def suggest_guest_code(event: Event) -> str:  # generate_guest_code(8) non utilisé par un Guest de l'événement (5 essais, puis RuntimeError)
```

- `verify` (GET et POST en erreur) :
  - **créateur sans code** (`creator.personal_code is None`, cas du premier événement) : `form_data["personal_code"]` vaut la saisie s'il y en a une, sinon `suggest_creator_code()`. Le champ est requis ;
  - **créateur qui a déjà un code** (même e-mail, nouvel événement : `create()` réutilise le `Creator`) : **aucune suggestion**. Le champ est rendu vide, **non requis** (`required` retiré, `minlength` absent), et son aide affiche le nouveau message `_("Votre code créateur actuel est conservé. Laissez ce champ vide pour le garder, ou saisissez un nouveau code de 8 caractères pour le remplacer.")`. L'ancien code n'est **jamais** affiché ni placé dans la page. Le gabarit reçoit `has_existing_code: bool`.
- `guest_access` passe `code=...`, avec la même logique et `suggest_guest_code(ctx.event)`.
- Dans `events/join.html` et `events/verify.html`, le bouton « Générer » (`id="gen-code"`) et son `<script>` `Math.random` sont **supprimés** s'ils existent encore après B017. Les attributs `minlength`/`maxlength`/`pattern` des champs restent `4`/`8`/`[a-z0-9]{4,8}` : le serveur fait foi (§7.5).

### 7.3 Contrat de résolution (utilisé par B019) — `app/access.py`

```python
CodeKind = Literal["event", "creator", "guest"]

@dataclass(frozen=True)
class CodeMatch:
    kind: CodeKind
    event: Event | None      # "event" : l'événement ; "guest"/"creator" via resolve_event_code : l'événement de la page
    creator: Creator | None  # "creator"
    guest: Guest | None      # "guest"

def normalize_code(raw: str) -> str            # raw.strip().lower()
def is_code_format(code: str) -> bool          # 4 <= len <= 8 et re.fullmatch(r"[a-z0-9]+", code)
def resolve_home_code(raw: str) -> CodeMatch | None
def resolve_event_code(event: Event, raw: str) -> CodeMatch | None
```

- `resolve_home_code` (accueil, sans événement) :
  1. normaliser ; si `not is_code_format` → `None` ;
  2. si `len == 6` et qu'un `Event` actif **et vérifié** a ce code → `CodeMatch("event", event, None, None)` ;
  3. si un `Creator` a `personal_code == code` → `CodeMatch("creator", None, creator, None)` ;
  4. sinon `None`.

  **L'événement est testé en premier** : un code d'événement circule dans les liens d'invitation. Un ancien code créateur de 6 caractères identique à un code d'événement ne doit pas ouvrir la session du créateur à qui détient le lien. Ce créateur se reconnecte par `/e/<code>/mycode` (D16).
- `resolve_event_code` (page `/mycode` d'un événement) :
  1. normaliser ; si `not is_code_format` → `None` ;
  2. si `event.creator.personal_code == code` → `CodeMatch("creator", event, event.creator, None)` ;
  3. si un `Guest` existe avec `event_id=event.id`, `code=code`, `is_active=True` et `creator_id IS NULL` → `CodeMatch("guest", event, None, guest)` ;
  4. sinon `None`.
- Comparaisons exactes en base. Aucune fonction ne révèle **pourquoi** elle renvoie `None`.

### 7.4 `access_by_code` (accueil, `POST /e/access`)

- `resolve_home_code(request.form["code"])` :
  - `"creator"` → `login_user(creator)` → `events.index` ;
  - `"event"` → redirection vers `events.my_code` de cet événement ;
  - `None` → `flash("Code non reconnu.", "danger")` → `main.index`.
- **Réponse indifférenciée** : un code de mauvais format et un code inconnu donnent exactement la même redirection et le même flash. Le message « Code invalide (8 caractères). » est supprimé.
- Le GET redirige vers `main.index` (inchangé).

### 7.5 Validation des codes choisis

| Formulaire | Règle |
|---|---|
| `verify` (code créateur) | Après normalisation : (a) **champ vide** et créateur avec un `personal_code` → le code existant est **conservé** (aucune écriture de `personal_code`) ; (b) champ vide et créateur sans code → erreur de format ; (c) code égal au `personal_code` actuel → conservé (un ancien code de 4 à 7 caractères **reste valable**) ; (d) sinon, valide si `len == 8`, `[a-z0-9]{8}` et aucun **autre** `Creator` n'a ce code. Erreurs (nouveaux messages, avec `_()`) : format → `_("Le code créateur doit faire 8 caractères (lettres minuscules et chiffres).")` ; déjà pris → `_("Ce code est déjà utilisé. Choisissez-en un autre.")`. **Course** entre deux `verify` avec le même code : l'`IntegrityError` levée au commit par la contrainte `UNIQUE` est attrapée, suivie de `db.session.rollback()` et d'un nouveau rendu du formulaire (200) avec l'erreur « déjà pris ». L'événement reste non vérifié. Le message actuel « Code perso requis (4 à 8 caractères). » n'est plus utilisé par `verify`. |
| `join` (code invité) | Règles actuelles inchangées : 4 à 8 caractères `[a-z0-9]`, unique dans l'événement. Nouvelle règle : un code égal au `personal_code` du créateur de l'événement est refusé avec le message **existant** « Code déjà utilisé. » (même texte qu'un doublon, pour ne rien révéler de plus). |

Plafond assumé : les codes invités restent choisis (4 à 8 caractères). Ils ne valent que dans un événement et sont protégés par les limites du §7.6. Passer à un code imposé relève de B019.

### 7.6 Limitation (Flask-Limiter 4.x)

**Principes** :
- seuls les **échecs** sont comptés (`deduct_when=attempt_failed`, `methods=["POST"]`) ;
- **aucun compteur global ne bloque** : aucun compteur partagé par tout le site ou par tout un événement ne peut refuser une requête ; les quotas sont par IP et par (IP, cible) ;
- un code correct n'est refusé que si **sa propre IP** a dépassé ses quotas d'échecs.

Constantes dans `app/access.py` :

```python
IP_FAILURE_LIMIT = "20 per 15 minutes;50 per day"                 # par IP, en tout (les 3 routes partagent le compteur)
TARGET_FAILURE_LIMIT = "5 per minute;10 per 15 minutes;15 per hour;30 per day"  # par (IP, cible) : délai progressif par paliers
TARGET_ALERT_THRESHOLD = "50 per hour"                           # alerte par cible, jamais de 429
```

| Route (POST) | Cible | Limites (remplacent les décorateurs `limiter.limit(...)` actuels de ces vues) |
|---|---|---|
| `/e/access` | aucune connue (un code faux ne désigne aucun compte) | `IP_FAILURES` (ci-dessous) |
| `/e/<code>/mycode` | l'événement (ses invités et le compte de son créateur, D16) | `IP_FAILURES` + `EVENT_TARGET_FAILURES` |
| `/e/<code>/join` | l'événement | `IP_FAILURES` + `EVENT_TARGET_FAILURES` : `mycode` et `join` partagent le compteur (IP, événement) |

Les deux décorateurs sont créés **une seule fois** dans `app/access.py` et appliqués aux vues. Un `limiter.limit(...)` non partagé serait indexé par route (trois compteurs distincts) : c'est pourquoi les deux sont des `shared_limit`.

```python
IP_FAILURES = limiter.shared_limit(IP_FAILURE_LIMIT, scope="ip-failures", key_func=get_remote_address,
                                   methods=["POST"], deduct_when=attempt_failed)
EVENT_TARGET_FAILURES = limiter.shared_limit(TARGET_FAILURE_LIMIT, scope="event-target", key_func=ip_event_key,
                                             methods=["POST"], deduct_when=attempt_failed)
```

```python
def ip_event_key() -> str:
    return f"{get_remote_address()}:event:{(request.view_args or {}).get('code', '')}"
def attempt_failed(response: Response) -> bool:
    return bool(g.get("code_attempt_failed", False))
def mark_attempt_failed(scope: Literal["home", "event", "join"], event_code: str | None) -> None:
    """g.code_attempt_failed = True ; log WARNING (§7.7) ; alerte de cible (ci-dessous)."""
```

- **Échecs comptés** :
  - `access_by_code` : résolution nulle ;
  - `my_code` : résolution nulle (§5.1) ;
  - `join` : **uniquement** un code refusé (déjà utilisé ou égal au code du créateur). « Événement complet. », un pseudo, un e-mail ou un format de code invalide ne consomment **aucun** quota de sécurité.
  - Un POST avec un participant déjà résolu n'est pas compté (D15, D14).
- **Délai progressif par cible** : `TARGET_FAILURE_LIMIT` impose des paliers pour une IP sur un événement donné. Après 5 échecs, il faut attendre la minute suivante ; après 10, la fin de la fenêtre de 15 minutes ; après 15, l'heure ; après 30, le jour. Le délai est indexé sur (IP, cible) et non sur la cible seule : un délai par cible seule permettrait à n'importe qui de verrouiller un événement ou un compte créateur pour tous ses participants (DoS).
- **Alerte par cible** : à chaque échec ciblé (`event`, `join`), `mark_attempt_failed` appelle `limiter.limiter.hit(parse(TARGET_ALERT_THRESHOLD), "target-alert", event_code)`, avec `from limits import parse`. Si le résultat est `False` (plus de 50 échecs/h sur cet événement, toutes IP confondues), il journalise `WARNING "code_target_alert event=<code>"`. Cette alerte ne refuse **jamais** de requête. Pour l'accueil, l'alerte utilise la clé `"home"`.
  - **Dépendance déclarée** : `limits` est importé directement, il est donc ajouté explicitement dans `pyproject.toml` (dépendances du projet) et `requirements.txt` sous la forme `limits>=5.0`. Il est déjà installé comme dépendance de Flask-Limiter 4.x ; la règle AGENTS impose de déclarer toute dépendance utilisée.
  - **Protection** : l'appel d'alerte est entouré de `try/except Exception`, qui journalise `WARNING "code_target_alert_failed"` avec `exc_info`. L'appel direct n'est pas couvert par `swallow_errors`, et une panne de stockage ne doit jamais faire échouer la vue (test A46).
- **Ce qui reste possible (plafonds assumés)** :
  - **brute-force distribué** sur beaucoup d'IP. Chaque IP est bornée à 30 échecs par jour et par événement, et à 50 échecs par jour **en tout** (les trois routes partagent le compteur `ip-failures`). Le volume est détectable par l'alerte. Aucune attaque venue d'**autres** IP ne peut empêcher un participant d'utiliser un code correct : il n'y a ni verrou d'événement ni compteur global ;
  - **IP partagée** (box du lieu de séjour, CGNAT mobile). Les participants d'un même séjour partagent souvent une IP publique, et donc ses compteurs. Compromis retenu : le premier palier est relevé à **5 échecs par minute**, donc quelques fautes de frappe dans la maison ne bloquent personne. Au-delà, l'attente reste courte (1 minute après 5 échecs, fin de la fenêtre de 15 minutes après 10). Un blocage d'une heure ou plus n'arrive qu'après 15 échecs d'une même IP sur un même événement, ce qui ne ressemble plus à un usage normal. Abaisser les paliers renforcerait la protection mais bloquerait plus vite une maison entière ; les relever affaiblirait la protection contre un attaquant isolé.
- **Stockage** :
  - **dev / tests** (sans `REDIS_URL`) : compteurs en mémoire, propres au processus, remis à zéro au redémarrage ;
  - **prod** (`REDIS_URL` défini, `docker-compose.yml`) : compteurs dans Redis, partagés entre processus. Redis tourne en `maxmemory-policy allkeys-lru` : un compteur peut être évincé sous pression mémoire, ce qui l'oublie plus tôt. Plafond accepté, car les clés sont petites et la mémoire de 64 Mo largement suffisante pour ce trafic ;
  - **Redis indisponible : échec ouvert vers la mémoire, journalisé.** `_create_limiter` passe `in_memory_fallback_enabled=True` et `swallow_errors=True`. Flask-Limiter bascule alors sur des compteurs en mémoire et journalise l'erreur de stockage. Justification : un échec fermé produirait des 500 sur `access`, `mycode` et `join`, donc empêcherait toute connexion. L'échec ouvert « nu » supprimerait toute protection. Le repli mémoire garde les limites dans l'unique processus Waitress, donc la protection est équivalente.
- **Tests** : la fixture `app` appelle `limiter.reset()` après `create_app()`. Les tests de limitation simulent des IP avec `environ_overrides={"REMOTE_ADDR": "10.0.<n>.<m>"}`.

### 7.7 Journalisation

Logger `app.security` (module `logging`, jamais `print`) :
- échec : `WARNING "code_attempt_failed scope=<home|event|join> event=<code ou -> ip=<IP>"` ;
- alerte de cible : `WARNING "code_target_alert event=<code ou home>"` ;
- succès : `INFO "code_login kind=<creator|guest> event=<code ou ->"`.

**Le code saisi n'est jamais journalisé.** Aucune entrée `ActivityLog` : le journal d'événement est visible par tous les participants.

---

## 8. Plan de tests

Les fixtures sont dans `tests/conftest.py`. Nom des tests : `test_<comportement>_<condition>_<résultat>`. Un test vérifie un comportement avec un assert principal. Les hooks HTML sont des `data-testid`, des URLs ou des statuts, jamais des classes CSS.

### 8.1 Fixtures (`tests/conftest.py`)

| Fixture | Changement / ajout |
|---|---|
| `app` | **modifiée** : `limiter.reset()` après `create_app()` |
| `event` | **modifiée** : `verified_at=datetime(2026, 1, 1)` |
| `unverified_event` | nouvelle : même chose que `event`, mais `verified_at=None` et un autre code, même créateur |
| `creator_guest` | nouvelle : `Guest(code=secrets.token_hex(8), display_name="Test Creator", event_id=event.id, creator_id=creator.id)` |
| `other_guest_c` | nouvelle : second invité « Other Guest » (nom distinct de la fixture locale `other_guest` de certains fichiers, qui reste en place) |
| `creator_client`, `guest_client`, `app_factory` | **fournies par B017**, réutilisées sans modification. `app_factory` sert aux applications avec une autre liste de modules (`app_factory({"ENABLED_MODULES": "planning,lists"})`). Un test qui l'utilise **ne demande pas** les fixtures `app`, `client`, `db`, `creator`, `event` : il crée ses données dans l'application fabriquée et son propre client (`built.test_client()`), pour éviter deux contextes d'application imbriqués. |

Helpers de connexion : les fixtures B017 ci-dessus. Quand un test doit changer d'identité en cours de route, il manipule directement `client.session_transaction()`.

### 8.2 `tests/test_context.py` — contexte (rôles × états)

Tests unitaires dans `app.test_request_context()` (`login_user(...)` et `session[...]`). Chaque « requête » simulée ouvre **son propre** `test_request_context()` et appelle `reset_event_context()` en entrée (§3.3). Les refus sont capturés par `pytest.raises(HTTPException)`, puis lus avec `exc.value.code` (404/403) ou `exc.value.get_response()` (302/204).

| # | Test | Assert |
|---|---|---|
| C1 | `test_load_context_creator_logged_in_role_creator` | `ctx.role == "creator"` |
| C2 | `test_load_context_creator_participant_linked_to_creator` | `ctx.participant.creator_id == creator.id` |
| C3 | `test_load_context_creator_without_participant_creates_one_once` | après deux requêtes, `Guest.query.filter_by(creator_id=creator.id, event_id=event.id).count() == 1` |
| C4 | `test_load_context_creator_fallback_creates_no_household` | `Household.query.filter_by(event_id=event.id).count() == 0` |
| C5 | `test_load_context_creator_existing_participant_reused` | `ctx.participant.id == creator_guest.id` |
| C6 | `test_load_context_guest_session_role_guest` | `ctx.role == "guest"` |
| C7 | `test_load_context_guest_session_participant_is_guest` | `ctx.participant.id == guest.id` |
| C8 | `test_load_context_creator_and_guest_session_creator_wins` | `ctx.role == "creator"` |
| C9 | `test_load_context_inactive_guest_redirects_mycode` | `Location` finit par `/e/<code>/mycode` |
| C10 | `test_load_context_guest_of_other_event_redirects_mycode` | statut 302 |
| C11 | `test_load_context_session_pointing_creator_guest_ignored` | statut 302 (session `guest_<code>` = id de `creator_guest`, sans connexion) |
| C12 | `test_load_context_anonymous_require_none_visitor` | `ctx.role == "visitor"` |
| C13 | `test_load_context_anonymous_redirects_mycode` | `Location` finit par `/e/<code>/mycode` |
| C14 | `test_load_context_unknown_code_404` | `exc.value.code == 404` |
| C15 | `test_load_context_inactive_event_404` | 404 |
| C16 | `test_load_context_unverified_event_404` | 404 |
| C17 | `test_load_context_unverified_event_require_none_404` | 404 |
| C18 | `test_load_context_guest_require_creator_403` | 403 |
| C19 | `test_load_context_other_creator_require_creator_redirects_mycode` | 302 (créateur d'un autre événement) |
| C20 | `test_load_context_second_call_returns_cached_object` | `load_event_context(code) is load_event_context(code)` |
| C21 | `test_actor_creator_uses_participant_name` | `ctx.actor == Actor("Test Creator", "creator", creator_guest.id)` |
| C22 | `test_actor_guest_type_guest` | `ctx.actor.type == "guest"` |
| C23 | `test_actor_visitor_is_system_actor` | `ctx.actor == SYSTEM_ACTOR` |
| C24 | `test_creator_participant_empty_display_name_uses_fallback` | `display_name == CREATOR_FALLBACK_NAME` |
| C25 | `test_ensure_creator_guest_reactivates_inactive_participant` | même `id` et `is_active is True` |
| C26 | `test_ensure_creator_guest_without_household_flag_creates_none` | 0 foyer |
| C27 | `test_reset_event_context_clears_cached_context` | après `load_event_context` puis `reset_event_context()`, `get_event_context() is None` |
| C28 | `test_get_or_create_creator_participant_returns_oldest_on_duplicates` | deux participants créateurs actifs → renvoie celui dont `joined_at` est le plus ancien |
| C29 | `test_load_context_htmx_anonymous_returns_hx_redirect` | réponse 204 avec `HX-Redirect` qui finit par `/e/<code>/mycode` |

### 8.3 `tests/test_context_http.py` — intégration, réponses homogènes, en-tête

| # | Test | Assert |
|---|---|---|
| H1 | `test_planning_page_selects_events_table_once` | fixture `creator_guest` (participant déjà présent, pas de commit de secours) ; via un écouteur `before_cursor_execute`, le nombre de `SELECT` contenant `FROM events` pendant `GET /e/<code>/planning` (créateur) vaut 1 |
| H2 | `test_identity_chip_creator_shows_event_participant_name` | `creator_guest.display_name = "Chef de camp"` (différent de `creator.display_name`) ; `"Chef de camp"` dans `text_of(html, "identity-chip")` (helper B017) |
| H3 | `test_identity_chip_creator_outside_event_uses_account_name` | `creator_client.get("/e/")` : `"Test Creator"` dans `text_of(html, "identity-chip")` |
| H4 | `test_dashboard_unknown_event_404` | statut 404 |
| H5 | `test_join_unknown_event_404` | 404 |
| H6 | `test_mycode_unverified_event_404` | 404 |
| H7 | `test_join_unverified_event_404` | 404 |
| H8 | `test_dashboard_unverified_event_creator_404` | 404 |
| H9 | `test_planning_unverified_event_creator_404` | 404 |
| H10 | `test_verify_sent_unverified_event_200` | 200 |
| H11 | `test_join_with_guest_session_redirects_dashboard` | `Location` finit par `/e/<code>` |
| H12 | `test_join_post_as_creator_creates_no_guest` | nombre de `Guest` inchangé |
| H13 | `test_mycode_with_participant_redirects_dashboard` | `Location` finit par `/e/<code>` |
| H14 | `test_log_anonymous_redirects_mycode` | `"/mycode"` dans `Location` |
| H15 | `test_log_unknown_event_renders_404_template` | `data-testid="error-404"` dans le corps |
| H16 | `test_costs_unknown_event_renders_404_template` | `data-testid="error-404"` |
| H17 | `test_costs_delete_expense_guest_renders_403_template` | `data-testid="error-403"` |
| H18 | `test_voting_close_anonymous_redirects_mycode` | `"/mycode"` dans `Location` |
| H19 | `test_invite_guest_403` | 403 |
| H20 | `test_invite_anonymous_redirects_mycode` | `"/mycode"` dans `Location` |
| H21 | `test_invite_qr_unverified_event_404` | 404 |
| H22 | `test_export_anonymous_redirects_mycode` | `"/mycode"` dans `Location` |
| H23 | `test_meals_edit_other_guest_403` | 403 |
| H24 | `test_planning_edit_other_guest_renders_403_template` | `data-testid="error-403"` |
| H25 | `test_media_file_anonymous_redirects_mycode` | `"/mycode"` dans `Location` |
| H26 | `test_identity_change_between_requests_same_client_uses_new_role` | même client : `GET /e/<code>/planning` en invité (200), puis suppression de `guest_<code>` en session, puis même GET → 302 vers `/mycode` (le contexte de la 1re requête n'est pas réutilisé) |
| H27 | `test_costs_delete_missing_expense_guest_404` | invité, id d'une dépense inexistante → 404 (D19) |
| H28 | `test_chat_htmx_poll_anonymous_returns_hx_redirect` | `GET /e/<code>/chat` avec `HX-Request: true`, sans session → statut 204 et en-tête `HX-Redirect` |
| H29 | `test_export_pdf_other_creator_redirects_mycode` | créateur d'un autre événement → 302 vers `/mycode` (D17) |
| H30 | `test_invite_inactive_event_404` | événement `is_active=False`, créateur → 404 (D18) |
| H31 | `test_lists_claim_missing_item_anonymous_redirects_mycode` | visiteur, article inexistant → `"/mycode"` dans `Location` (D19) |
| H32 | `test_app_factory_verified_event_planning_renders_for_creator` | `app_factory({"ENABLED_MODULES": "planning,voting,chat"})`, créateur et événement **vérifié** créés dans le test, client créateur, `GET /e/{code}/planning` → 200 (scénario de T16 de B017) |
| H33 | `test_app_factory_no_module_verified_event_members_renders` | `app_factory({"ENABLED_MODULES": ""})`, événement vérifié, client créateur, `GET /e/{code}/members` → 200 (scénario de T17 de B017) |

### 8.4 `tests/test_rights.py` — droits

Matrices paramétrées (`pytest.mark.parametrize`, un `id` lisible par cas, un assert booléen par cas) sur un `EventContext` construit directement (`EventContext(event, participant, is_creator)`) :

| # | Test | Cas (objet, rôle, auteur ?) → attendu |
|---|---|---|
| R1 | `test_can_edit_matches_rights_table` | toutes les lignes `can_edit` du §3.6 × {créateur, invité auteur, invité non auteur, visiteur} |
| R2 | `test_can_delete_matches_rights_table` | toutes les lignes `can_delete` du §3.6 × les mêmes rôles, plus `Guest` avec `creator_id` → `False` pour le créateur |
| R3 | `test_can_edit_unknown_type_raises_type_error` | `pytest.raises(TypeError)` |

Tests HTTP :

| # | Test | Assert |
|---|---|---|
| R4 | `test_rsvp_creator_records_rsvp_under_creator_guest` | `ActivityRSVP` (`guest_id=creator_guest.id`) avec `status == "yes"` |
| R5 | `test_rsvp_creator_logs_actor_type_creator` | `ActivityLog` `rsvp.updated` : `actor_type == "creator"` |
| R6 | `test_planning_index_shows_rsvp_form_to_creator` | `f"/planning/{activity.id}/rsvp"` dans la page |
| R7 | `test_chat_other_guest_cannot_delete_creator_message_403` | 403 |
| R8 | `test_media_upload_creator_sets_uploaded_by_creator_guest` | `MediaItem.uploaded_by == creator_guest.id` (JPEG minimal `b"\xff\xd8\xff\xe0" + b"0"*64`, `content_type="image/jpeg"`) |
| R9 | `test_media_delete_by_creator_logs_deleting_actor` | `ActivityLog` `media.deleted` : `actor_name == "Test Creator"` (média déposé par `guest`) |
| R10 | `test_list_claim_creator_sets_creator_guest_id` | `item.assigned_to_id == creator_guest.id` |
| R11 | `test_list_detail_same_name_without_id_not_mine` | article `assigned_to="Test Guest"`, `assigned_to_id=None`, invité « Test Guest » connecté : URL `/unclaim` de l'article absente |
| R12 | `test_add_item_assigned_unique_name_sets_guest_id` | `assigned_to_id == guest.id` |
| R13 | `test_add_item_assigned_ambiguous_name_keeps_none` | deux invités du même nom → `assigned_to_id is None` |
| R14 | `test_dashboard_my_items_matched_by_id` | article `name="Zz-mine"`, `assigned_to="Autre"`, `assigned_to_id=guest.id` : `b"Zz-mine"` présent dans la page |
| R15 | `test_members_remove_creator_participant_403` | 403 et `creator_guest.is_active is True` |
| R16 | `test_costs_creator_log_uses_display_name` | `actor_name == "Test Creator"` |
| R17 | `test_costs_creator_with_guest_session_logs_creator` | `actor_type == "creator"` |
| R18 | `test_vote_creator_creates_no_household` | après le vote, 0 `Household` |
| R19 | `test_dashboard_creator_get_creates_no_household` | 0 `Household` |
| R20 | `test_logistics_delete_guest_403` | 403 |
| R21 | `test_list_delete_item_guest_allowed` | 302 et article supprimé (règle conservée, §3.6) |
| R22 | `test_chat_send_creator_guest_id_is_creator_guest` | `msg.guest_id == creator_guest.id` |

### 8.5 `tests/test_identity_migration.py` — migrations

Les données héritées sont créées directement en ORM (`created_by=None`, `assigned_to_id=creator.id`, etc.), puis `migrate_identity(db.session)` est appelé.

| # | Test | Assert |
|---|---|---|
| M1 | `test_migrate_creates_missing_creator_guest` | `result["creator_guests_created"] == 1` |
| M2 | `test_migrate_created_creator_guest_has_no_household` | 0 `Household` |
| M3 | `test_migrate_skips_unverified_event` | aucun `Guest` créé pour `unverified_event` |
| M4 | `test_migrate_reactivates_inactive_creator_guest` | `result["creator_guests_reactivated"] == 1` |
| M5 | `test_migrate_converts_list_item_creator_id` | `item.assigned_to_id == <id participant créateur>` |
| M6 | `test_migrate_assigns_list_item_by_unique_name` | `item.assigned_to_id == guest.id` |
| M7 | `test_migrate_leaves_ambiguous_name_unassigned` | `item.assigned_to_id is None` |
| M8 | `test_migrate_sets_activity_null_author_to_creator_guest` | `activity.created_by == <id>` |
| M9 | `test_migrate_sets_meal_null_author_to_creator_guest` | `meal.created_by == <id>` |
| M10 | `test_migrate_sets_creator_chat_message_guest_id` | `msg.guest_id == <id>` |
| M11 | `test_migrate_leaves_guest_chat_message_without_id` | `msg.guest_id is None` (`author_type="guest"`) |
| M12 | `test_migrate_sets_media_null_uploader_to_creator_guest` | `item.uploaded_by == <id>` |
| M13 | `test_migrate_does_not_rewrite_denormalized_names` | `msg.author_name == "Créateur"` inchangé |
| M14 | `test_migrate_second_run_reports_all_zero` | `set(result2.values()) == {0}` |
| M15 | `test_migrate_second_run_keeps_single_creator_guest` | 1 participant créateur |
| M16 | `test_check_identity_clean_database_empty` | `check_identity(db.session) == []` |
| M17 | `test_check_identity_reports_duplicate_creator_guests` | `f"duplicate_creator_guest:{event.id}"` dans le résultat |
| M18 | `test_check_identity_reports_null_activity_author` | `f"activity_null_author:{activity.id}"` dans le résultat |
| M19 | `test_check_identity_clean_after_migration` | `[]` |
| M20 | `test_backup_sqlite_database_copies_file` | le fichier renvoyé existe et contient la table `events` (base fichier dans `tmp_path`) |
| M21 | `test_backup_sqlite_database_memory_returns_none` | `None` |
| M22 | `test_startup_runs_identity_migration` | base fichier `tmp_path` : 1er `create_app`, insertion d'un événement vérifié sans participant créateur, 2e `create_app` → participant créateur présent (`monkeypatch` de `DATABASE_URL` et `app.load_dotenv`) |
| M23 | `test_run_identity_migration_noop_creates_no_backup` | base fichier déjà migrée : `run_identity_migration` ne crée aucun fichier dans `instance/backups/` |
| M24 | `test_run_identity_migration_unfixable_anomaly_creates_no_backup` | base fichier avec deux participants créateurs actifs (seule anomalie) : 2 exécutions → `backups/` vide |
| M25 | `test_prune_backups_keeps_three_latest` | 5 fichiers `pre-identity-*.db` récents → 3 restent (les plus récents) |
| M26 | `test_prune_backups_removes_files_older_than_30_days` | un fichier de 31 jours (`os.utime`) → supprimé |
| M27 | `test_plan_identity_migration_writes_nothing` | après le calcul à blanc sur une base héritée : nombre de `Guest` inchangé et `db.session.new` vide |
| M28 | `test_check_identity_ignores_unverified_event_null_author` | activité `created_by=None` dans `unverified_event` → absente du résultat |
| M29 | `test_migrate_truncates_long_creator_name_to_50_chars` | `creator.display_name = "x" * 80` → `len(guest.display_name) == 50` |
| M30 | `test_backup_creation_prunes_backups_older_than_30_days` | base fichier héritée + un ancien `pre-identity-*.db` de 31 jours : `run_identity_migration` crée une nouvelle sauvegarde et l'ancienne n'existe plus |
| M31 | `test_plan_counts_equal_migrate_counts_on_legacy_base` | base héritée incluant un article dont la **seule** correspondance de nom est le futur participant créateur : `plan_identity_migration(...) == migrate_identity(...)` |

### 8.6 `tests/test_access_codes.py` — codes, résolution, limitation

| # | Test | Assert |
|---|---|---|
| A1 | `test_generate_guest_code_length_8` | `len == 8` |
| A2 | `test_generate_guest_code_uses_unambiguous_alphabet` | `set(code) <= set(CODE_ALPHABET)` (sur 200 codes) |
| A3 | `test_generate_event_code_skips_reserved` | avec `secrets.choice` simulé qui produit d'abord `access`, le résultat est différent de `"access"` |
| A4 | `test_is_code_format_accepts_4_chars` | `True` |
| A5 | `test_is_code_format_rejects_9_chars` | `False` |
| A6 | `test_is_code_format_rejects_symbols` | `False` pour `"ab-cd"` |
| A7 | `test_resolve_home_code_event_code_returns_event` | `kind == "event"` |
| A8 | `test_resolve_home_code_creator_code_returns_creator` | `kind == "creator"` |
| A9 | `test_resolve_home_code_event_wins_over_same_creator_code` | `kind == "event"` |
| A10 | `test_resolve_home_code_unverified_event_returns_none` | `None` |
| A11 | `test_resolve_home_code_unknown_returns_none` | `None` |
| A12 | `test_resolve_event_code_guest_returns_guest` | `match.guest.id == guest.id` |
| A13 | `test_resolve_event_code_creator_code_returns_creator` | `kind == "creator"` |
| A14 | `test_resolve_event_code_other_creator_code_returns_none` | `None` |
| A15 | `test_resolve_event_code_creator_guest_token_returns_none` | `None` |
| A16 | `test_resolve_event_code_inactive_guest_returns_none` | `None` |
| A17 | `test_access_six_char_creator_code_logs_in` | `sess["_user_id"] == creator.id` (F01) |
| A18 | `test_access_legacy_four_char_creator_code_logs_in` | idem avec un code de 4 caractères |
| A19 | `test_access_event_code_redirects_mycode` | `Location` finit par `/e/<code>/mycode` |
| A20 | `test_access_bad_format_and_unknown_same_flash` | `_flashes` identiques pour `"ab"` et `"zzzzzzzz"` |
| A21 | `test_mycode_creator_code_logs_in_creator` | `sess["_user_id"] == creator.id` |
| A22 | `test_mycode_sixth_failure_same_ip_event_returns_429` | 6 POST en échec depuis la même IP sur le même événement, dans la même minute : le 6e répond 429 (palier 5/minute) |
| A23 | `test_mycode_successes_do_not_consume_quota` | 10 succès depuis la même IP (session vidée entre chaque), puis 1 échec → statut 200 |
| A24 | `test_join_code_rejection_shares_ip_event_quota_with_mycode` | même IP : 5 échecs `mycode`, puis 1 POST `join` avec un code déjà utilisé → 429 |
| A25 | `test_mycode_correct_code_other_ip_after_attack_succeeds` | 60 échecs depuis 20 IP (3 chacune), puis code correct depuis une 21e IP → 302 vers le tableau de bord (aucun verrou d'événement) |
| A26 | `test_access_failure_log_omits_code` | `caplog` (logger `app.security`) : un enregistrement, sans le code saisi |
| A27 | `test_verify_rejects_seven_char_new_creator_code` | créateur sans code : `creator.personal_code is None` après le POST |
| A28 | `test_verify_accepts_eight_char_creator_code` | `creator.personal_code == "abcd2345"` |
| A29 | `test_verify_rejects_code_of_other_creator` | statut 200 et `event.verified_at is None` |
| A30 | `test_verify_keeps_existing_short_code_of_same_creator` | créateur avec `personal_code="ab12"`, POST `ab12` → `event.verified_at is not None` |
| A31 | `test_verify_form_prefilled_with_server_suggestion` | créateur sans code : la valeur de `name="personal_code"` fait 8 caractères ⊂ `CODE_ALPHABET` |
| A32 | `test_join_form_prefilled_with_server_suggestion` | idem pour `name="code"` |
| A33 | `test_join_rejects_code_equal_to_creator_code` | aucun `Guest` créé |
| A34 | `test_join_page_has_no_math_random` | `b"Math.random"` absent |
| A35 | `test_verify_page_has_no_math_random` | `b"Math.random"` absent |
| A36 | `test_access_twenty_first_failure_same_ip_returns_429` | 21 échecs depuis la même IP en 15 minutes : le 21e répond 429 |
| A37 | `test_access_correct_code_other_ip_after_many_failures_succeeds` | 30 échecs depuis 10 IP, puis code créateur correct depuis une 11e IP → `sess["_user_id"] == creator.id` (aucun compteur global) |
| A38 | `test_join_event_full_does_not_consume_quota` | `MAX_GUESTS_PER_EVENT` atteint, 5 POST `join` valides depuis la même IP → aucun 429 (5 réponses 200) |
| A39 | `test_target_alert_logged_after_threshold` | 51 échecs `mycode` depuis 51 IP → `caplog` contient `code_target_alert` |
| A40 | `test_limiter_created_with_memory_fallback` | `app.extensions.Limiter` remplacé par un faux qui capture ses arguments ; `_create_limiter()` → `kwargs["in_memory_fallback_enabled"] is True` |
| A41 | `test_mycode_failure_renders_page_status_200` | code inconnu → statut 200 (le texte « Code invalide » est vérifié par le test existant `test_my_code_invalid`) |
| A42 | `test_mycode_post_with_participant_redirects_dashboard` | invité déjà en session, POST avec un code faux → 302 vers `/e/<code>` |
| A43 | `test_verify_existing_creator_empty_code_keeps_code` | créateur avec `personal_code="oldc0de1"`, POST avec champ vide → `personal_code == "oldc0de1"` et événement vérifié |
| A44 | `test_verify_existing_creator_page_shows_no_code` | créateur avec code existant : `b"oldc0de1"` absent de la page `verify` et champ `personal_code` sans valeur |
| A45 | `test_verify_integrity_error_renders_code_taken` | `db.session.commit` simulé qui lève `IntegrityError` une fois → statut 200 et `event.verified_at is None` |
| A46 | `test_target_alert_storage_error_does_not_break_view` | `limiter.limiter.hit` simulé qui lève une exception → `POST /mycode` en échec répond 200 et `caplog` contient `code_target_alert_failed` |
| A47 | `test_ip_failure_counter_shared_across_routes` | même IP : 20 échecs sur `/e/access`, puis 1 échec sur `/e/<code>/mycode` → 429 (compteur `ip-failures` en tout) |

### 8.7 `tests/test_module_links.py` — liens conditionnels (F32)

| # | Test | Assert |
|---|---|---|
| L1 | `test_dashboard_planning_without_meals_renders_200` | `app_factory({"ENABLED_MODULES": "planning,lists"})`, repas du jour présent → 200 |
| L2 | `test_dashboard_planning_without_meals_has_no_meals_link` | `"/meals"` absent |
| L3 | `test_dashboard_meals_without_planning_links_meal_title` | `app_factory({"ENABLED_MODULES": "meals"})`, repas du jour → `f"/e/{code}/meals"` présent |
| L4 | `test_dashboard_plan_meals_action_targets_meals` | `data-testid="plan-meals-action"` avec `href` qui finit par `/meals` |
| L5 | `test_dashboard_lists_disabled_with_assigned_item_renders_200` | `app_factory({"ENABLED_MODULES": "planning"})`, article attribué au créateur → 200 |
| L6 | `test_event_pages_render_with_module_disabled` (paramétré sur les 8 modules) | application avec tous les modules sauf un ; créateur ; GET du tableau de bord, de `members`, de `log` et de la page index de chaque module actif → toutes les réponses ont un statut < 500 |

### 8.8 `tests/test_static_guards.py` — gardes statiques

| # | Test | Assert |
|---|---|---|
| T-S1 | `test_no_duplicated_access_helpers_in_app` | aucun `def _resolve_actor`, `def _get_event_or_404`, `def _actor_name`, `def _actor(`, `def _can_modify`, `def _is_event_creator`, `def _get_current_guest` dans `app/**/*.py` |
| T-S2 | `test_templates_do_not_use_guest_or_is_creator_variables` | dans les blocs `{{…}}` et `{%…%}` de `app/templates/**/*.html`, **après suppression des littéraux de chaîne** (`re.sub(r'"[^"]*"|\'[^\']*\'', '""', bloc)`, pour ignorer les msgid comme `_("Add a guest")`) : aucune occurrence de `(?<!["'.])\bguest\b(?!["'])`, de `(?<!ctx\.)\bis_creator\b`, ni de `current_user.id == event.creator_id` |
| T-S3 | `test_no_raw_error_strings_in_views` | aucun `return "Not found"`, `"Pas autorisé.", 403`, `_("Pas autorisé."), 403`, ni `flash("Pas autorisé.` dans `app/**/*.py` |
| T-S4 | `test_no_creator_literal_outside_context` | « Créateur » et « Système » n'apparaissent comme littéraux Python que dans `app/context.py` (hors `.html` et hors `models.py`, qui garde le `default` de `uploaded_by_name`, à la charge de B018) |

### 8.9 Tests existants modifiés (jamais de suppression)

| Fichier :: test | Assertion / donnée actuelle | Nouvelle | Justification |
|---|---|---|---|
| `conftest.py` fixture `app` | — | `limiter.reset()` après `create_app()` | isolation des compteurs entre tests (§7.6) |
| `conftest.py` fixture `event` | `verified_at` absent | `verified_at=datetime(2026, 1, 1)` | D11 : un événement non vérifié répond 404 |
| `test_module_gating.py` `_seed` (ou la fonction qui le remplace après l'adaptation B017) | `Event(...)` sans `verified_at` | ajoute `verified_at=datetime(2026, 1, 1)` | D11 |
| `test_logistics.py::test_edit_404_item_from_other_event` | `other = Event(...)` sans `verified_at` | ajoute `verified_at` | le 404 doit venir de l'article étranger, pas de la non-vérification |
| `test_events.py::test_full_anonymous_flow_email_opt_out` | `"personal_code": "anon42x"` ; `creator.personal_code == "anon42x"` | `"anon42xy"` ; `== "anon42xy"` | §7.5 : nouveau code créateur de 8 caractères |
| `test_events.py::test_full_anonymous_flow_email_kept` | `"personal_code": "keep42x"` | `"keep42xy"` | idem |
| `test_planning.py::test_create_success_as_creator` | `act.created_by is None` | `act.created_by == Guest.query.filter_by(creator_id=creator.id, event_id=event.id).first().id` | identité unique (§5.2) |
| `test_planning.py::TestRSVP::test_rsvp_forbidden_for_creator` | renommé `test_rsvp_allowed_for_creator` ; `b"cr" in resp.data.lower()` | `ActivityRSVP.query.filter_by(activity_id=activity.id, guest_id=<participant créateur>.id).first().status == "yes"` | D1 |
| `test_chat.py::test_send_message_success` | `msg.guest_id is None` | `msg.guest_id == <participant créateur>.id` | §5.7 |
| `test_costs.py::test_index_redirects_no_access` | `"/join" in … or "/mycode" in …` | `"/mycode" in resp.headers["Location"]` | D7 (F09) |
| `test_media.py::test_gallery_redirects_no_access` | idem | `"/mycode" in …` | D7 |
| `test_media.py::test_upload_requires_access` | idem | `"/mycode" in …` | D7 |
| `test_media.py::test_delete_forbidden_for_other_guest` | `resp.status_code == 302` | `resp.status_code == 403` | D6 |

Vérifiés et **inchangés** :
- les redirections `/mycode` de planning, lists, logistics, voting, chat et `test_dashboard_redirects_to_my_code` ;
- les tests 403 de chat, costs, lists, logistics, planning, voting et privacy ;
- `test_events::test_my_code_invalid` : le flash existant « Code invalide. » est conservé (§5.1) ;
- `test_events::test_join_success_with_own_code` et `test_my_code_access` : POST puis redirection suivie dans le même test ; corrects grâce au vidage du cache à chaque requête (§3.3) ;
- `test_models::test_guest_count_*` (la fixture `event` ne crée pas de participant créateur) ;
- `test_voting::test_vote_success_for_creator` (participant créé en secours) ;
- `test_freemium::test_guest_is_not_redirected_to_paywall` (`@login_required` conservé sur `export_pdf`) ;
- `test_freemium::test_cannot_create_event_at_limit` : crée un `Event` sans `verified_at`, mais sans requête HTTP, donc sans effet ;
- les tests de règlement de `test_costs` (aucun foyer implicite, I4) ;
- les tests « forbidden » de `test_meals` (aucun statut vérifié) ;
- les tests B017 de la pastille (`T31`–`T33`) : `data-role` et la présence sont inchangés (§3.8).

Les constats #6 et #8 de l'audit (code créateur existant, échec de `/mycode`) n'entraînent **aucune adaptation supplémentaire** : ils sont couverts par les nouveaux tests A41–A45 et par `test_my_code_invalid`, inchangé.

`test_module_gating::test_nav_hides_disabled_modules` dépend du HTML de B017 et n'est pas touché par B029.

Tests **B017** concernés par D11 (T16, T17, graine T94/T96, scène `event-unverified`) : rendus robustes par B017 lui-même. B029 ne les modifie pas, mais **vérifie qu'ils restent verts** au commit 6 et l'atteste par H32/H33 (§3.8). Ils ne comptent pas parmi les adaptations B029.

**Total prévu** : 29 (C) + 33 (H) + 22 (R, dont 2 matrices paramétrées) + 31 (M) + 47 (A) + 6 (L, dont 1 paramétré ×8) + 4 (T-S) = **172 fonctions de test nouvelles**, plus **13 adaptations**.

---

## 9. Critères d'acceptation, commits, ordre, risques

### 9.1 Critères d'acceptation

1. `app/context.py` expose `Actor`, `SYSTEM_ACTOR`, `SYSTEM_ACTOR_NAME`, `CREATOR_FALLBACK_NAME`, `actor_for`, `EventContext` (avec `role`, `actor`, `is_author`, `can_edit`, `can_delete`), `load_event_context`, `get_event_context`, `reset_event_context`, `get_or_create_creator_participant` et `log_event`, avec les signatures du §3.
2. Toute vue sous `/e/<code>/…` (hors `verify` et `verify_sent`) commence par `load_event_context` (T-S1, C*, H*).
3. Le cache du contexte est vidé à chaque requête (`before_request`). Un changement d'identité entre deux requêtes du même client est pris en compte (C27, H26).
4. Une page d'événement exécute exactement un `SELECT` sur `events` (H1).
5. `inject_globals` ne fait aucune requête. Il fournit les clés du contrat B017 avec des noms et une sémantique inchangés (`app_name`, `current_lang`, `enabled_modules`, `current_event`, `current_guest`, `event_role`), plus `ctx` et `current_participant` (§3.8). `inject_event_days` n'existe plus.
6. Aucune seconde pastille. En contexte événement, la pastille `identity-chip` de B017 affiche le nom du participant créateur ; hors événement, la règle B017 s'applique (H2, H3, T31–T33 de B017 verts).
7. Le créateur connecté a toujours un participant `Guest`. En cas de doublons, le canonique est le plus ancien (C1–C5, C28).
8. Aucune route ne crée de foyer hors de `verify` et `join` (C4, R18, R19, M2).
9. `planning.rsvp` accepte le créateur (R4, R5, R6).
10. `created_by`, `uploaded_by`, `ChatMessage.guest_id` et `ListItem.assigned_to_id` reçoivent un `Guest.id` pour le créateur (R8, R10, R22, test adapté de planning).
11. « À moi » (listes, tableau de bord) se compare par identifiant (R11, R14).
12. La table §3.6 est implémentée telle quelle (R1, R2). Un type inconnu lève `TypeError` (R3).
13. Les changements D1–D20 sont effectifs et aucun autre droit ni aucune autre réponse ne change (H*, R*, adaptations §8.9). L'ordre contexte → objet → droit est le même partout (H27, H31).
14. Visiteur → `/mycode` dans tous les modules, y compris costs, media et log (H14, H18, H20, H22, H25, H29, adaptations). En HTMX : 204 avec `HX-Redirect` (C29, H28).
15. Les 403 et 404 sont rendus par les gabarits d'erreur ; il ne reste aucune chaîne brute (H15–H17, H24, T-S3).
16. Un événement non vérifié, ou inactif, répond 404 partout sauf `verify` et `verify_sent` (C15–C17, H6–H10, H21, H30).
17. Le participant créateur ne peut pas être retiré (R15).
18. Aucune `BuildError` quand un module est désactivé. « Planifier les repas » cible `meals.index` (L1–L6).
19. `migrate_identity` applique les 8 règles du §4.3, avec `flush` intermédiaire et troncature à 50 caractères (M1–M13, M29). Elle est idempotente (M14, M15).
20. `check_identity` est en lecture seule, limitée aux événements actifs et vérifiés, et détecte les anomalies du §4.5 (M16–M19, M28). `python -m app.migrations check` et `manage.py check-identity` sortent avec le code 1 s'il y en a.
21. La migration s'exécute au démarrage et par `manage.py migrate` (après les `add_col`). La sauvegarde n'est faite que si le calcul à blanc annonce au moins une écriture : aucune au démarrage d'une base migrée, même avec des anomalies non corrigeables. Le calcul à blanc partage l'implémentation de la migration, n'écrit rien et donne des compteurs identiques (M20–M24, M27, M31).
22. Les sauvegardes sont stockées dans `instance/backups/`, hors médias et hors export, avec un nom daté. Au plus 3 sont conservées. La purge des fichiers de plus de 30 jours a lieu à chaque nouvelle sauvegarde, à chaque démarrage et à chaque `manage.py migrate` (M25, M26, M30).
23. `generate_guest_code` utilise `CODE_ALPHABET`. `generate_event_code` ne produit jamais un code réservé (A1–A3).
24. `resolve_home_code` et `resolve_event_code` respectent le §7.3 (A7–A16).
25. `access_by_code` accepte les codes de 4 à 8 caractères, avec des réponses indifférenciées (A17–A20).
26. `/mycode` accepte le code du créateur de l'événement (A21). En échec, il garde le flash « Code invalide. » et répond 200 (A41, `test_my_code_invalid`). Un POST avec un participant déjà résolu redirige sans décompte (A42).
27. Seuls les échecs sont comptés : par IP en tout (`shared_limit` sur les trois routes), et par (IP, événement) avec délai progressif à partir de 5 échecs par minute, partagé entre `mycode` et `join`. Aucun compteur global ou par événement entier ne bloque, et un code correct depuis une autre IP passe toujours (A22–A25, A36–A38, A47). L'alerte par cible est journalisée sans jamais bloquer, même en cas de panne de stockage. `limits` est déclaré dans `pyproject.toml` et `requirements.txt` (A39, A46).
28. Redis indisponible : repli en mémoire (`in_memory_fallback_enabled=True`, `swallow_errors=True`) (A40).
29. Les échecs sont journalisés sur `app.security`, sans le code (A26).
30. `verify` impose 8 caractères aux nouveaux codes créateur. Il refuse un code pris sans erreur 500, y compris en cas de course (A45), et accepte l'ancien code du même créateur (A27–A30).
31. Le code d'un créateur existant n'est jamais proposé ni affiché, et un champ vide le conserve (A43, A44).
32. Les formulaires `verify` (créateur sans code) et `join` sont prérenseignés côté serveur. Plus aucun `Math.random` dans ces pages (A31–A35).
33. Un code invité égal au code du créateur est refusé (A33). « Événement complet. » ne consomme aucun quota (A38).
34. Les 13 adaptations du §8.9 sont faites. Aucun test existant n'est supprimé. Les tests B017 T16, T17, T94 et T96 restent verts sans modification par B029 (§3.8, H32, H33).
35. `ruff check . && ruff format --check . && mypy app/ && pytest` sont verts. `npm run ui:check` (B017) est vert, y compris la scène `event-unverified` (limitée par B017 à `verify` / `verify_sent`).
36. Tout nouveau message utilisateur passe par `_()`. Aucun message existant n'est reformulé ; les messages supprimés sont listés au §10.2.

### 9.2 Ordre d'exécution et journal de commits

Les tests du lot sont écrits d'abord (étape 3 du pipeline). Chaque commit embarque les tests nouveaux **et** adaptés qu'il rend verts : aucun commit rouge. Le commit 0, préalable et isolé, modifie seulement la liste des scopes de `AGENTS.md`. Aucun autre commit du lot ne touche à `AGENTS.md`.

0. `docs: ajouter les scopes meals, costs, media, context, ui à AGENTS.md` (liste « Scopes » de la règle 1 seulement)
1. `test(infra): fixtures B029 (événement vérifié, participant créateur, reset du limiteur)` : conftest + adaptations `_seed` et `other` (§8.9 lignes 1–4)
2. `feat(models): alphabet de codes sans ambiguïté et codes d'événement réservés` (A1–A3)
3. `feat(context): module app/context.py (contexte par requête, acteur, droits, journal)` (C*, R1–R3)
4. `feat(models): migration d'identité idempotente, sauvegarde avec rotation et vérification` (M*, `manage.py`)
5. `feat(auth): résolution des codes, limites d'échecs par IP et par cible, codes créateur de 8 caractères` (`app/access.py`, `extensions._create_limiter`, `limits` déclaré dans `pyproject.toml` et `requirements.txt`, `access_by_code`, `my_code`, `guest_access`, `verify`, gabarits join et verify ; A*, adaptations `test_events`)
6. `refactor(events): contexte unique, 404 non vérifié ou inactif, membres et invitations homogènes` (H4–H15, H19–H22, H29, H30, H32, H33, R14, R15, R19) ; gate : T16, T17, T94, T96 et `npm run ui:check` de B017 verts (§3.8)
7. `refactor(planning): contexte unique et RSVP du créateur` (R4–R6, H24, adaptations planning)
8. `refactor(meals): contexte unique et refus en 403` (H23)
9. `refactor(lists): contexte unique, ordre contexte-objet-droit, attribution par identifiant` (R10–R13, R21, H31)
10. `refactor(logistics): contexte unique` (R20)
11. `refactor(voting): contexte unique sans écriture pendant un GET` (H18, R18)
12. `refactor(chat): contexte unique, auteur créateur identifié, redirection HTMX` (R7, R22, H28, adaptation chat)
13. `refactor(costs): contexte unique et réponses d'erreur rendues par gabarit` (H16, H17, H27, R16, R17, adaptation costs)
14. `refactor(media): contexte unique, refus en 403, journal de l'acteur` (H25, R8, R9, adaptations media)
15. `fix(events): liens du tableau de bord conditionnés au module cible (F32)` (L*)
16. `refactor(ui): inject_globals sans requête (contrat B017), nom du créateur dans la pastille, suppression du code mort` (H1–H3, H26, `inject_event_days`, `freemium._is_event_creator`, scénario `ui:check` si besoin)
17. `test(infra): gardes statiques B029` (T-S*)
18. `chore: close lot B029` (`CHANGELOG.md`, `TASKS.md` ✅, `DEV_LOG.md` avec la procédure de retour arrière et la rétention des sauvegardes §4.2, §4.6)

### 9.3 Risques et parades

| Risque | Parade |
|---|---|
| Régression de droits pendant la factorisation | La table §3.6 est encodée en matrices R1/R2 ; chaque changement voulu est listé (D1–D20) et testé ; les tests 403 existants restent inchangés. |
| Fuite du contexte entre requêtes (tests avec contexte d'application ouvert) | Vidage par `before_request` (§3.3) ; test H26. |
| Migration en production (données réelles) | Sauvegarde automatique seulement si des écritures sont prévues ; un seul commit ; rollback en cas d'exception ; idempotence (M14) ; vérification en lecture seule après déploiement ; l'ancien code tolère les données migrées (§4.6). |
| Disque rempli ou données conservées au-delà de la purge par les sauvegardes | Une sauvegarde par migration effective, rotation à 3, purge à 30 jours (§4.2) ; sauvegardes hors médias et hors export. |
| Démarrage bloqué par une migration en échec | Même `try/except` journalisé que la purge : l'application démarre, et le secours I3c couvre le créateur. |
| Doublon de participant créateur sous concurrence | Relecture du canonique (I2, C28) ; signalement par `check_identity`. |
| Sessions existantes | Les sessions créateur (`_user_id`) et invité (`guest_<code>`) restent valides sans réécriture. Un créateur sans participant en obtient un à la première requête. |
| Événements non vérifiés encore utilisés | Ils sont purgés à J+3 ; le créateur dispose du lien `verify` ; risque faible et accepté (D11). |
| Brute-force distribué / DoS par épuisement de quota | Plus de verrou d'événement ni de compteur global bloquant ; quotas par IP et par (IP, cible) ; alerte par cible (§7.6). |
| Redis indisponible ou compteurs évincés (LRU) | Repli mémoire journalisé ; éviction acceptée comme plafond (§7.6). |
| Limite d'invités décalée d'une unité (participant créateur ajouté aux événements anciens) | Effet accepté et documenté ; correction du comptage transmise à B030 (§1.3). |
| Compteurs de limitation partagés entre tests | `limiter.reset()` dans la fixture `app` ; IP simulées dans les tests de limitation. |
| Tests dépendants des fixtures | La fixture `event` reste sans participant créateur, donc les compteurs d'invités et les soldes sont inchangés ; seules les 13 adaptations du §8.9 sont touchées. |
| Collision entre un ancien code créateur de 6 caractères et un code d'événement | Priorité à l'événement sur l'accueil ; reconnexion par `/mycode` (D16). |
| Divergence avec B017 (`base.html`, `inject_globals`) | Contrat explicite (§3.8) ; tests B017 T31–T33 verts ; localisation par variable ou libellé ; garde T-S2 ; L6 parcourt toutes les pages avec chaque module désactivé. |

---

## 10. Impact sur B018 (à intégrer lors de la réécriture de `specs/B018-i18n.md`)

Ordre d'exécution : B017 → B029 → B030 → B018 → B019 → … → B028. B018 s'appuie donc sur le code issu de B029 **et** de B030.

### 10.1 API de résolution d'acteur que B018 utilise

- `ctx.actor` / `actor_for(participant) -> Actor(name, type, guest_id)` : c'est **la** source du nom et du type d'acteur, dans le journal, le chat, les médias et les attributions.
- `SYSTEM_ACTOR` / `SYSTEM_ACTOR_NAME` : l'acteur système. B018 remplace la **valeur** de `SYSTEM_ACTOR_NAME` par `SYSTEM_PLACEHOLDER` (`"@system"`), importée de `app.i18n`.
- `CREATOR_FALLBACK_NAME` : le nom par défaut du participant créateur quand `Creator.display_name` est vide. B018 remplace sa valeur par `CREATOR_PLACEHOLDER` (`"@creator"`).
- `actor_type` reste dans `{"creator", "guest", "system"}`. Un créateur a désormais un **nom propre** (le `display_name` de son participant) : l'identifiant `@creator` ne sert plus qu'aux données héritées et au nom par défaut.
- Gabarits : `current_participant` (créateur compris) et `current_guest` (invité seulement) (§3.8).

### 10.2 Ce qui devient caduc ou change dans la spec B018

1. §2.7 `actor_identity(guest, is_creator)` dans `app/utils.py` : **supprimé du plan**. Il est remplacé par `ctx.actor` (B029). Les lignes de l'inventaire B018 qui suppriment `_actor_name`/`_actor` ou introduisent `actor_identity` (C2, P2, P4, M2, M3, L1, L5, G2, V1, V4, H1, U1, et la mention de `voting/__init__.py:269`) sont **déjà réalisées** par B029 et retirées de B018.
2. §2.7 « Changement assumé : costs journalise le nom du créateur » : **déjà fait** par B029 (D8).
3. §2.7 `app/media/__init__.py:201` : déjà remplacé par `ctx.actor.name`. B018 n'a plus rien à y faire.
4. §2.7 `ensure_creator_guest` : le nom par défaut est `CREATOR_FALLBACK_NAME`. B018 change seulement la valeur de la constante.
5. §2.7 « Comparaisons d'attribution » (`lists/detail.html`, `events/dashboard.html`, passage de `actor_name` par les vues) : **caduc**. B029 compare par identifiant et a supprimé `actor_name` et `my_name` des gabarits.
6. §2.9 SQL de migration des identifiants neutres, deux conditions à réécrire parce que les colonnes contiennent désormais des `Guest.id` :
   - `list_items` : `AND assigned_to_id IN (SELECT id FROM guests WHERE creator_id IS NOT NULL)` au lieu de `IN (SELECT id FROM creators)` ;
   - `media_items` : `AND uploaded_by IN (SELECT id FROM guests WHERE creator_id IS NOT NULL)` au lieu de `uploaded_by IS NULL`.
   Les conditions sur `activity_logs`, `chat_messages` (`author_type='creator'`) et `guests` restent valides. Comme B018 s'exécute après B029, sa migration suppose que `migrate_identity` est déjà passée.
7. **Messages et réponses supprimés par B029** (lignes à retirer de l'inventaire B018) :
   - **E21** « Événement introuvable. » : les 6 occurrences (`dashboard`, `members`, `export_event`, `delete_event`, `guest_access`, `my_code`) disparaissent (D12, remplacées par `abort(404)`) ;
   - **E1** « Code invalide (8 caractères). » : supprimé (§7.4) ;
   - **E37** (`events.log` « Not found »), **C3**, **C4** (costs « Not found » / « Pas autorisé. »), **P5**, **L4**, **G5**, **V3**, **H2** (`_("Pas autorisé."), 403`) : convertis en `abort(404)`/`abort(403)` ;
   - **D10** (media, flash « Pas autorisé. ») et les **3 flashes `_("Pas autorisé.")` de meals** (`edit`, `delete`, `move`) : remplacés par `abort(403)` (D6).
8. **Messages conservés, dont le statut change** :
   - **E36** « Code invalide. » (`my_code`) : **conservé tel quel**, même texte, même emplacement, non enveloppé. B018 le traduit comme prévu ; il est désormais affiché pour tout échec de `/mycode`, y compris un mauvais format (§5.1) ;
   - « Code non reconnu. » (`access_by_code`) : conservé, désormais seul message d'échec de l'accueil (B018 le traduit) ;
   - « Code déjà utilisé. » (`join`) : conservé ; il sert aussi au refus d'un code égal au code du créateur ;
   - « Code perso requis (4 à 8 caractères). » : n'est plus utilisé que par `join` (ligne 480 de B018 : la variante `verify` disparaît).
   - §1.3 de B018 « Longueur du code d'accès… message traduit tel quel » : **caduc**.
9. Catalogue : B018 traduit les nouveaux msgid de B029, déjà enveloppés dans `_()` :
   - « Le code créateur doit faire 8 caractères (lettres minuscules et chiffres). » → `The creator code must be 8 characters (lowercase letters and digits).`
   - « Ce code est déjà utilisé. Choisissez-en un autre. » → `This code is already in use. Please choose another one.`
   - « Votre code créateur actuel est conservé. Laissez ce champ vide pour le garder, ou saisissez un nouveau code de 8 caractères pour le remplacer. » → `Your current creator code is kept. Leave this field empty to keep it, or enter a new 8-character code to replace it.`
10. Garde « pseudo commençant par @ » (§2.7) : inchangée. Elle s'applique aussi au nom du participant créateur saisi à `verify`.
11. Lectures `|actor` (§2.7) : la pastille est celle de B017 (`identity-chip`). Le nom du créateur en contexte événement vient de `current_participant.display_name` (§3.8) et passe par `|actor` comme les autres noms.
12. Commit B018 « identifiants d'acteur neutres et actor_identity partagé » (ligne 1488) : renommé en « identifiants d'acteur neutres (constantes de app/context.py) ». La partie « suppression des 8 copies » est retirée.

---

## 11. Traitement de l'audit `specs/audits/B029-spec.md`

### 11.1 Constats traités

| # | Sévérité | Traitement (section) |
|---|---|---|
| 1 | bloquant | Cache par requête : hook `before_request` `reset_event_context` ; tests unitaires avec un `test_request_context` par requête simulée (§3.3) ; C27, H26 |
| 2 | bloquant | Contrat B017 explicite : clés d'`inject_globals` conservées (`event_role`, `current_guest` avec la sémantique B017), ajout de `current_participant`, une seule pastille `identity-chip` dont seule l'expression du nom du créateur change ; plus de `participant-chip` ni de suppression de `title` (§2.3, §3.5, §3.8) ; H2, H3 réécrits |
| 3 | bloquant | Sauvegarde déclenchée par le calcul à blanc (`plan_identity_migration`), jamais par `check_identity` (lecture seule, périmètre aligné) ; rotation à 3 ; purge à 30 jours ; emplacement hors médias et hors export ; documentation des données personnelles (§4.2, §4.5) ; M23–M28 |
| 4 | majeur | Plus de limite globale bloquante : quotas d'échecs par IP et par (IP, cible) avec délai progressif, alerte par cible sans 429 (§7.6) ; A25, A36, A37, A39 |
| 5 | majeur | Plus de verrou d'événement ; texte « au plus une heure » remplacé (§7.6) ; A22–A25 réécrits |
| 6 | majeur | `verify` : aucune suggestion ni affichage pour un créateur qui a déjà un code ; champ vide = code conservé ; nouveau msgid (§7.2, §7.5) ; A43, A44 |
| 7 | majeur | Ordre complet avec B030 (en-tête, §10) ; E21, E1, E36 et les messages de meals ajoutés au §10.2 (7, 8) |
| 8 | majeur | Échec `/mycode` : flash existant « Code invalide. », rendu 200, décompte ; POST avec participant → redirection sans résolution ; `join` ne compte que les refus de code (§5.1, §7.6) ; A38, A41, A42 |
| 9 | majeur | D17 (`export_pdf` d'un autre créateur), D18 (`invite*`/`export_pdf` sur événement inactif ou non vérifié), D19 (ordre contexte → objet → droit partout), D20 (`get_media_quota` : décision « inchangé, B030 ») (§3.7) ; H27, H29–H31 |
| 10 | mineur | Relecture du canonique après commit ; plafond documenté (I2, §3.3) ; C28 |
| 11 | mineur | Appel placé après les `add_col` ; commandes Docker de vérification et de restauration (§4.1, §4.6) |
| 12 | mineur | `flush()` après les étapes 1–2 ; `display_name[:50]` (§4.3, §5.10) ; M29 |
| 13 | mineur | H1 utilise `creator_guest` |
| 14 | mineur | Table et totaux mis à jour ; `test_freemium::test_cannot_create_event_at_limit` noté « vérifié » (§8.9) |
| 15 | mineur | `HX-Redirect` en HTMX (§3.3, §6.1) ; C29, H28 |
| 16 | mineur | `IntegrityError` attrapée au commit de `verify`, `rollback`, erreur « déjà utilisé » (§5.1, §7.5) ; A45 |
| 17 | mineur | Littéraux de chaîne retirés avant la regex (T-S2) |
| 18 | mineur | Commit 0 `docs` qui ajoute `meals`, `costs`, `media`, `context`, `ui` aux scopes de `AGENTS.md` ; `app/context.py` en scope `context` (§9.2) |
| 19 | mineur | Effet sur `can_add_guest` documenté et transmis à B030 (§1.3, §9.3) |
| 20 | mineur | `make_app` supprimée ; `app_factory` (B017) utilisée seule, sans les fixtures `app`/`client` (§8.1) |
| 21 | mineur | `in_memory_fallback_enabled=True` + `swallow_errors=True` ; éviction LRU documentée comme plafond (§7.6) ; A40 |

### 11.2 Constats écartés

Aucun. Les 21 constats sont traités.

### 11.3 Re-audit (N1–N7 et #14 partiel)

| # | Sévérité | Traitement |
|---|---|---|
| N1 | majeur | Décision du coordinateur : B017 se rend robuste de son côté (T16/T17 et graine avec `verified_at`, scène `event-unverified` limitée à `verify`/`verify_sent`). B029 a l'obligation de vérifier T16, T17, T94, T96 et `ui:check` au commit 6, avec un arrêt et une remontée si l'un est rouge ; tests H32, H33 ; critères 34 et 35 rendus inconditionnels (§3.8, §8.9, §9.1, §9.2) |
| N2 | mineur | `IP_FAILURES` devient un `shared_limit` (portée `ip-failures`) commun aux trois routes : compteur par IP **en tout** (§7.6) ; A47 |
| N3 | mineur | Premier palier relevé à 5/minute (puis 10/15 min, 15/h, 30/jour) ; compromis de l'IP partagée documenté (§7.6) ; A22, A24, A36 ajustés |
| N4 | mineur | `limits>=5.0` déclaré dans `pyproject.toml` et `requirements.txt` ; alerte sous `try/except` journalisé (§7.6) ; A46 |
| N5 | mineur | Purge à chaque sauvegarde, à chaque démarrage et à chaque `manage.py migrate` ; garantie reformulée et plafond assumé (§4.1, §4.2) ; M30 |
| N6 | mineur | Implémentation unique `_run_identity_steps(apply=…)` avec participant prévu, y compris dans la comparaison de nom (§4.2) ; M31 |
| N7 | mineur | Phrase alignée : le commit 0, isolé, modifie seulement la liste des scopes de `AGENTS.md` (§9.2) |
| #14 | mineur (partiel) | Tests B017 traités par N1 (vérifiés, non modifiés par B029) |

---

## Résumé

- **Fichier** : `specs/B029-contexte-identite.md`
- **Critères d'acceptation** : 36
- **Tests prévus** : 172 fonctions nouvelles (dont 3 paramétrées) et 13 adaptations de tests existants ; tests B017 T16, T17, T94, T96 et scène `event-unverified` vérifiés verts sans modification par B029
- **Ce que B018 doit adapter** (§10) :
  - utiliser `ctx.actor` à la place d'`actor_identity` ;
  - changer seulement la valeur des constantes `SYSTEM_ACTOR_NAME` et `CREATOR_FALLBACK_NAME` ;
  - réécrire deux conditions SQL de sa migration (`list_items`, `media_items`) ;
  - retirer de son inventaire E21, E1, E37, C3, C4, P5, L4, G5, V3, H2, D10, les flashes de meals et les 8 copies, déjà traités ;
  - noter E36 « Code invalide. » conservé ;
  - traduire les 3 nouveaux msgid.
- **Trois décisions clés** :
  1. Le créateur est toujours un `Guest`, créé à `verify`, par migration au démarrage ou en secours par le contexte, **sans jamais créer de foyer implicite**. Toute lecture renvoie le participant canonique.
  2. Un seul `load_event_context(code, require=…)`, mis en cache **par requête** (vidé dans `before_request`). Il lève 404, 403 ou une redirection vers `/mycode` (`HX-Redirect` en HTMX), et `inject_globals` le réutilise en respectant le contrat B017.
  3. Codes :
     - suggestion générée côté serveur au rendu (jamais pour un créateur qui a déjà un code) ;
     - 8 caractères pour tout nouveau code créateur ;
     - priorité au code d'événement sur l'accueil ;
     - quotas d'**échecs** par IP et par (IP, cible), avec délai progressif et sans aucun compteur global bloquant ;
     - repli mémoire si Redis tombe.
