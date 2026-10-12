# Spec B003 — Blueprint Planning (activités + RSVP)

**Statut** : SPEC v2 (post-audit)
**Date** : 2026-10-04
**Lot** : B003
**Dépendances** : B001 ✅ (models, extensions), B002 ✅ (ActivityLog model + log_action helper)

> **Note** : Le modèle `ActivityLog` existe dans `app/models.py` (commit 326e99b).
> Le helper `log_action()` est dans `app/utils.py` (créé dans ce lot, section 4).

---

## 1. Périmètre

Le blueprint `planning` gère :
- La création / modification / suppression d'activités
- La liste des activités (par date, par événement)
- Le RSVP (yes / no / maybe) par invité
- L'affichage du nombre de confirmés

**Hors périmètre** :
- Le chat (B008)
- Les notifications (B014)
- Le drag-and-drop de planning (v2)
- Le HTMX partial pour le RSVP (v2 — v1 fait un redirect classique)

---

## 2. Modèle (déjà existant dans models.py)

```python
class Activity:
    id: str (32, PK, hex)
    title: str (200, NOT NULL)
    description: str (Text, default "")
    date: date (NOT NULL)
    start_time: time (nullable)
    end_time: time (nullable)
    location: str (300, default "")
    min_headcount: int (default 1)
    bring_items: str (Text, default "")
    created_by: str (32, FK guests.id, nullable)  # NULL si créé par le créateur
    created_at: datetime (default utcnow)
    event_id: str (32, FK events.id, NOT NULL)

class ActivityRSVP:
    id: str (32, PK, hex)
    status: str (10, NOT NULL)  # "yes" | "no" | "maybe"
    updated_at: datetime (default utcnow, onupdate utcnow)
    activity_id: str (32, FK activities.id, NOT NULL)
    guest_id: str (32, FK guests.id, NOT NULL)
    # UNIQUE (activity_id, guest_id)

class ActivityLog:
    id: str (32, PK, hex)
    event_id: str (32, FK events.id, NOT NULL, index)
    actor_name: str (100, NOT NULL)
    actor_type: str (20, NOT NULL)  # "creator" | "guest" | "system"
    action: str (50, NOT NULL)
    target: str (200, nullable)
    details: str (Text, nullable)
    created_at: datetime (default utcnow, index)
```

**Propriété existante** : `Activity.confirmed_count` → int (nombre de RSVP "yes", **sans filtre** sur `is_active` du guest — un RSVP est un historique).

---

## 3. Pattern de routes

Le blueprint `planning_bp` est enregistré **SANS** `url_prefix` dans `app/__init__.py`.
Les routes doivent donc inclure le chemin complet dans les décorateurs :

```python
@planning_bp.route("/e/<code>/planning")
@planning_bp.route("/e/<code>/planning/new", methods=["GET", "POST"])
@planning_bp.route("/e/<code>/planning/<activity_id>/edit", methods=["GET", "POST"])
@planning_bp.route("/e/<code>/planning/<activity_id>/delete", methods=["POST"])
@planning_bp.route("/e/<code>/planning/<activity_id>/rsvp", methods=["POST"])
```

---

## 4. Helper ActivityLog (prérequis, créé dans ce lot)

Fichier : `app/utils.py`

```python
from app.models import ActivityLog


def log_action(db_session, event_id, actor_name, actor_type, action, target=None, details=None):
    """Créer un ActivityLog (sans commit).

    Le caller fait db.session.commit() une seule fois après avoir
    ajouté l'entité principale + le log.
    """
    log = ActivityLog(
        event_id=event_id,
        actor_name=actor_name,
        actor_type=actor_type,
        action=action,
        target=target,
        details=details,
    )
    db_session.add(log)
    return log
```

### Convention actor_name / actor_type

| Acteur | actor_name | actor_type |
|--------|-----------|------------|
| Créateur (logged in) | `current_user.display_name` ou `"Créateur"` si vide | `"creator"` |
| Guest (session) | `guest.display_name` | `"guest"` |
| Système (auto) | `"Système"` | `"system"` |

---

## 5. Routes

### 5.1 — Liste des activités

```
GET /e/<code>/planning
```

**Accès** : Créateur (logged in, `current_user.id == event.creator_id`) OU invité en session (`session["guest_<code>"]`).

**Comportement** :
1. `event = Event.query.filter_by(code=code, is_active=True).first()` → si None : 404.
2. Vérifier l'accès :
   - Si `current_user.is_authenticated` et `current_user.id == event.creator_id` → OK.
   - Sinon, `guest_id = session.get(f"guest_{code}")` → si None : redirect `/e/<code>/mycode`.
   - Sinon, `guest = Guest.query.filter_by(id=guest_id, event_id=event.id, is_active=True).first()` → si None : redirect `/e/<code>/mycode`.
3. Charger les activités : `event.activities.filter_by(...)` triées par `date ASC`, `start_time ASC` (NULL en dernier).
4. Pour chaque activité, charger le RSVP du guest courant (si guest).
5. Rend `planning/index.html`.

**Variables template** :
- `event` : Event
- `activities` : list[Activity] (triées)
- `guest` : Guest | None
- `today` : `date.today()`

**Cas limites** :
- Événement sans activités → message "Aucune activité planifiée. Ajoutez-en une !"
- Activité sans `start_time` → affichée sans heure.
- `start_time` présent, `end_time` absent → afficher "14:00" (pas de tiret).
- `end_time` présent, `start_time` absent → afficher "jusqu'à 16:00".
- `min_headcount` non atteint → badge "insuffisant" avec texte explicite.

---

### 5.2 — Formulaire de création (GET) + Création (POST)

```
GET  /e/<code>/planning/new       → rend planning/form.html (vide)
POST /e/<code>/planning/new       → crée l'activité
```

**Accès** : Créateur OU invité en session (mêmes checks que 5.1).

**Champs du formulaire** :

| Champ | Type HTML | Requis | Validation serveur |
|-------|-----------|--------|-------------------|
| `title` | text | Oui | 2-200 chars, strip. Erreur : "Titre requis (min 2 caractères)." |
| `description` | textarea | Non | max 2000 chars. Erreur : "Description trop longue (max 2000)." |
| `date` | date | Oui | Doit être dans [event.start_date, event.end_date]. Erreur : "Date hors de la période de l'événement." |
| `start_time` | time | Non | HH:MM. Si présent et end_time présent : end > start. |
| `end_time` | time | Non | HH:MM. Erreur : "Heure de fin avant heure de début." |
| `location` | text | Non | max 300 chars. Erreur : "Lieu trop long (max 300)." |
| `min_headcount` | number | Non | 1-50, default 1. Erreur : "Nombre entre 1 et 50." |
| `bring_items` | text | Non | max 500 chars. Erreur : "Champ trop long (max 500)." |

**Comportement POST** :
1. Valider tous les champs. Si erreur → re-rendre `form.html` avec les erreurs dans `<ul class="errors" aria-live="polite">`.
2. Créer l'`Activity` :
   - `created_by` = `guest.id` si guest, `None` si créateur.
3. Log : `log_action(db, event.id, actor_name, actor_type, "activity.created", target=title)`.
4. `db.session.commit()`.
5. Redirect → `GET /e/<code>/planning` avec flash "Activité créée."

**Pas de limite sur le nombre d'activités** par événement (le rate limit de B015 couvrira l'abus).

---

### 5.3 — Formulaire d'édition (GET) + Modification (POST)

```
GET  /e/<code>/planning/<activity_id>/edit       → rend planning/form.html (pré-rempli)
POST /e/<code>/planning/<activity_id>/edit       → modifie l'activité
```

**Accès** : Créateur de l'événement OU créateur de l'activité.

**Logique de permission (edit/delete)** :
```python
def _can_modify(event, activity, current_user, guest):
    # Créateur de l'événement : toujours autorisé
    if current_user.is_authenticated and current_user.id == event.creator_id:
        return True
    # Créateur de l'activité (guest)
    if guest and activity.created_by == guest.id:
        return True
    return False
```

Si pas autorisé → **return "Pas autorisé.", 403** (pas de redirect).

**Comportement POST** :
1. Vérifier la permission → 403 si non.
2. Valider les champs (mêmes règles que 5.2).
3. Mettre à jour l'activité.
4. Log : `log_action(db, event.id, actor_name, actor_type, "activity.updated", target=title)`.
5. `db.session.commit()`.
6. Redirect → planning index avec flash "Activité modifiée."

**Cas limites** :
- `activity_id` invalide (non hex 32) → 404.
- Activité appartenant à un autre événement → 404.

---

### 5.4 — Suppression

```
POST /e/<code>/planning/<activity_id>/delete
```

**Accès** : mêmes permissions que 5.3.

**Comportement** :
1. Vérifier la permission → 403 si non.
2. Récupérer le `title` avant suppression (pour le log).
3. Supprimer l'activité (cascade : les RSVP sont supprimés via `cascade="all, delete-orphan"`).
4. Log : `log_action(db, event.id, actor_name, actor_type, "activity.deleted", target=title)`.
5. `db.session.commit()`.
6. Redirect → planning index avec flash "Activité supprimée."

---

### 5.5 — RSVP

```
POST /e/<code>/planning/<activity_id>/rsvp
```

**Accès** : Invité en session uniquement.

**Champ** : `status` = "yes" | "no" | "maybe"

**Comportement** :
1. Vérifier que le guest est en session. Si non → redirect `/e/<code>/mycode`.
2. Si `current_user.is_authenticated` et `current_user.id == event.creator_id` → flash "Le créateur ne fait pas de RSVP." + redirect.
3. Vérifier que `status` est dans `{"yes", "no", "maybe"}`. Si non → flash "Statut invalide." + redirect.
4. **Upsert avec gestion de concurrency** :
   ```python
   try:
       rsvp = ActivityRSVP(activity_id=activity.id, guest_id=guest.id, status=status)
       db.session.add(rsvp)
       db.session.commit()
   except IntegrityError:
       db.session.rollback()
       rsvp = ActivityRSVP.query.filter_by(activity_id=activity.id, guest_id=guest.id).first()
       rsvp.status = status
       db.session.commit()
   ```
5. Log : `log_action(db, event.id, guest.display_name, "guest", "rsvp.updated", target=activity.title, details=status)`.
6. `db.session.commit()` (si le log n'a pas été commité avec l'upsert).
7. Redirect → planning index.

**Cas limites** :
- Activité inexistante → 404.
- Créateur qui tente de RSVP → flash + redirect (pas de 403).

---

## 6. Activités passées

**Décision** : Les activités dont la date est passée restent :
- Modifiables (edit)
- Supprimables (delete)
- RSVP-ables

Pas de lock temporel. L'utilisateur gère son propre historique.

---

## 7. Templates

### 7.1 — `planning/index.html`

```html
{% extends "base.html" %}
{% block content %}
<h1>{{ _("Planning") }} — {{ event.title }}</h1>

<a href="{{ url_for('planning.new', code=event.code) }}" class="btn btn-primary">
  {{ _("Nouvelle activité") }}
</a>

{% if not activities %}
  <p class="empty">{{ _("Aucune activité planifiée. Ajoutez-en une !") }}</p>
{% else %}
  {% set grouped = activities | groupby("date") %}
  {% for date, acts in grouped %}
    <h2 class="day-header {% if date == today %}today{% endif %}">
      {{ date | format_date('full') }}
    </h2>
    {% for act in acts %}
      <div class="activity-card">
        {% if act.start_time %}
          <span class="time">
            {{ act.start_time.strftime("%H:%M") }}
            {% if act.end_time %} – {{ act.end_time.strftime("%H:%M") }}{% endif %}
          </span>
        {% endif %}
        <h3>{{ act.title }}</h3>
        {% if act.description %}<p>{{ act.description }}</p>{% endif %}
        {% if act.location %}<p class="location">📍 {{ act.location }}</p>{% endif %}
        {% if act.bring_items %}<p class="bring">{{ _("Apporter") }} : {{ act.bring_items }}</p>{% endif %}
        
        <span class="badge-headcount {% if act.confirmed_count >= act.min_headcount %}ok{% else %}insufficient{% endif %}"
              aria-label="{{ act.confirmed_count }} {{ _('confirmés sur') }} {{ act.min_headcount }} {{ _('requis') }}">
          {{ act.confirmed_count }}/{{ act.min_headcount }}
          {% if act.confirmed_count < act.min_headcount %}
            <span class="sr-only">{{ _("— insuffisant") }}</span>
          {% endif %}
        </span>
        
        {% if guest %}
          <form method="post" action="{{ url_for('planning.rsvp', code=event.code, activity_id=act.id) }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <button type="submit" name="status" value="yes" aria-pressed="{{ 'true' if guest_rsvps.get(act.id) == 'yes' else 'false' }}">{{ _("Oui") }}</button>
            <button type="submit" name="status" value="no" aria-pressed="{{ 'true' if guest_rsvps.get(act.id) == 'no' else 'false' }}">{{ _("Non") }}</button>
            <button type="submit" name="status" value="maybe" aria-pressed="{{ 'true' if guest_rsvps.get(act.id) == 'maybe' else 'false' }}">{{ _("Peut-être") }}</button>
          </form>
        {% endif %}
        
        {% if can_modify %}
          <a href="{{ url_for('planning.edit', code=event.code, activity_id=act.id) }}">{{ _("Modifier") }}</a>
          <form method="post" action="{{ url_for('planning.delete', code=event.code, activity_id=act.id) }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <button type="submit" class="btn-danger">{{ _("Supprimer") }}</button>
          </form>
        {% endif %}
      </div>
    {% endfor %}
  {% endfor %}
{% endif %}
{% endblock %}
```

### 7.2 — `planning/form.html`

```html
{% extends "base.html" %}
{% block content %}
<h1>{% if activity %}{{ _("Modifier") }}{% else %}{{ _("Nouvelle activité") }}{% endif %}</h1>

{% if errors %}
<ul class="errors" aria-live="assertive">
  {% for e in errors %}<li>{{ e }}</li>{% endfor %}
</ul>
{% endif %}

<form method="post" action="{{ action_url }}">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  
  <label for="title">{{ _("Titre") }} *</label>
  <input type="text" id="title" name="title" required minlength="2" maxlength="200"
         value="{{ form_data.get('title', '') }}">
  
  <label for="description">{{ _("Description") }}</label>
  <textarea id="description" name="description" rows="3" maxlength="2000">{{ form_data.get('description', '') }}</textarea>
  
  <label for="date">{{ _("Date") }} *</label>
  <input type="date" id="date" name="date" required
         min="{{ event.start_date.isoformat() }}" max="{{ event.end_date.isoformat() }}"
         value="{{ form_data.get('date', '') }}">
  
  <label for="start_time">{{ _("Heure de début") }}</label>
  <input type="time" id="start_time" name="start_time" value="{{ form_data.get('start_time', '') }}">
  
  <label for="end_time">{{ _("Heure de fin") }}</label>
  <input type="time" id="end_time" name="end_time" value="{{ form_data.get('end_time', '') }}">
  
  <label for="location">{{ _("Lieu") }}</label>
  <input type="text" id="location" name="location" maxlength="300" value="{{ form_data.get('location', '') }}">
  
  <label for="min_headcount">{{ _("Nombre minimum de participants") }}</label>
  <input type="number" id="min_headcount" name="min_headcount" min="1" max="50" value="{{ form_data.get('min_headcount', 1) }}">
  
  <label for="bring_items">{{ _("Apporter") }}</label>
  <input type="text" id="bring_items" name="bring_items" maxlength="500"
         placeholder="{{ _('Ex : 2 chaises, 1 nappe') }}" value="{{ form_data.get('bring_items', '') }}">
  
  <button type="submit">{% if activity %}{{ _("Modifier") }}{% else %}{{ _("Créer") }}{% endif %}</button>
</form>
{% endblock %}
```

---

## 8. Accessibilité (WCAG 2.1 AA)

- Chaque input a un `<label for="...">`.
- Les boutons RSVP sont des `<button type="submit">` dans des `<form>` individuels (navigation clavier native).
- `aria-pressed="true"` sur le bouton RSVP actif.
- Le badge headcount a `aria-label` explicite + texte `.sr-only` "— insuffisant" (pas de couleur seule).
- Les erreurs de formulaire sont dans `<ul aria-live="assertive">`.
- Les flash messages sont dans `<div aria-live="polite" role="status">` (dans base.html).
- Contraste : texte #1a1a1a sur #ffffff (ratio 17:1).
- Touch targets ≥ 44×44px sur mobile.
- Focus visible : `:focus-visible { outline: 3px solid #005fcc; }`.
- Ordre de focus : naturel (DOM order), pas de `tabindex` positif.

---

## 9. i18n — Liste exhaustive des strings

Tous les textes passent par `_()` (Flask-Babel gettext) :

| String | Usage |
|--------|-------|
| "Planning" | H1 |
| "Nouvelle activité" | Bouton + H1 formulaire |
| "Aucune activité planifiée. Ajoutez-en une !" | Empty state |
| "Titre" | Label |
| "Description" | Label |
| "Date" | Label |
| "Heure de début" | Label |
| "Heure de fin" | Label |
| "Lieu" | Label |
| "Nombre minimum de participants" | Label |
| "Apporter" | Label + prefix dans la carte |
| "Ex : 2 chaises, 1 nappe" | Placeholder |
| "Créer" | Bouton submit create |
| "Modifier" | Bouton submit edit + lien |
| "Supprimer" | Bouton delete |
| "Oui" | RSVP button |
| "Non" | RSVP button |
| "Peut-être" | RSVP button |
| "confirmés sur" | Badge headcount |
| "requis" | Badge headcount |
| "— insuffisant" | Badge (sr-only) |
| "Activité créée." | Flash |
| "Activité modifiée." | Flash |
| "Activité supprimée." | Flash |
| "Pas autorisé." | 403 body |
| "Le créateur ne fait pas de RSVP." | Flash |
| "Statut invalide." | Flash |
| "Titre requis (min 2 caractères)." | Erreur validation |
| "Description trop longue (max 2000)." | Erreur validation |
| "Date hors de la période de l'événement." | Erreur validation |
| "Heure de fin avant heure de début." | Erreur validation |
| "Lieu trop long (max 300)." | Erreur validation |
| "Nombre entre 1 et 50." | Erreur validation |
| "Champ trop long (max 500)." | Erreur validation |

**Format de date** : `babel.format_date(date, 'full')` → "mercredi 3 décembre 2026" (FR) / "Wednesday, December 3, 2026" (EN).

---

## 10. Sécurité

- **CSRF** : `flask_wtf.CSRFProtect(app)` + `csrf_token()` dans chaque formulaire POST. Ajouter `flask-wtf` dans `pyproject.toml`.
- **XSS** : Jinja2 auto-escaping activé par défaut. Ne JAMAIS utiliser `|safe` sur du contenu utilisateur.
- **Validation serveur** : Tous les champs sont validés côté serveur (pas de confiance client).
- **Permissions** : Check dans le code (pas juste dans le template).
- **Rate limit** : Différé en B015 (Flask-Limiter). Risque acceptable : l'endpoint nécessite une session guest valide + CSRF token.
- **SQL injection** : SQLAlchemy ORM uniquement, pas de raw SQL.
- **ID validation** : `activity_id` est un str(32) hex. Si le format est invalide, la query retourne None → 404. Pas de besoin de validation regex explicite.

---

## 11. Tests (à écrire AVANT le code)

Fichier : `tests/test_planning.py`

### Fixtures (à ajouter dans conftest.py)

```python
@pytest.fixture
def activity(db, event):
    from datetime import date, time
    from app.models import Activity

    a = Activity(
        title="Swimming",
        description="Pool party",
        date=date(2026, 12, 3),  # dans [2026-12-01, 2026-12-07]
        start_time=time(14, 0),
        end_time=time(16, 0),
        location="Pool",
        min_headcount=3,
        bring_items="Maillots",
        event_id=event.id,
    )
    db.session.add(a)
    db.session.commit()
    return a


@pytest.fixture
def activity_rsvp(db, activity, guest):
    from app.models import ActivityRSVP

    r = ActivityRSVP(
        status="yes",
        activity_id=activity.id,
        guest_id=guest.id,
    )
    db.session.add(r)
    db.session.commit()
    return r
```

### Tests (44 au total)

```
class TestPlanningIndex:
    test_index_renders_for_creator          # GET → 200, contient le titre
    test_index_renders_for_guest            # GET avec session guest → 200
    test_index_404_for_invalid_code         # GET /e/xxxxxx/planning → 404
    test_index_redirects_if_no_access       # GET sans session → 302 /e/<code>/mycode
    test_index_shows_activities_sorted      # 2 activités, vérifie l'ordre dans le HTML
    test_index_shows_empty_message          # Pas d'activité → message empty
    test_index_shows_confirmed_count        # Badge "1/3" visible
    test_index_shows_insufficient_badge     # confirmed < min → classe "insufficient"
    test_index_shows_rsvp_status            # Le RSVP "yes" du guest est aria-pressed="true"
    test_index_inactive_event_404           # Event is_active=False → 404

class TestCreateActivity:
    test_create_get_renders_form            # GET /new → 200, formulaire vide
    test_create_success_as_creator          # POST → 302, activité en DB
    test_create_success_as_guest            # POST avec session guest → 302, created_by=guest.id
    test_create_missing_title               # POST title="" → 200, erreur dans HTML
    test_create_title_too_short             # POST title="A" → 200, erreur
    test_create_description_too_long        # POST description 2001 chars → 200, erreur
    test_create_date_outside_event          # POST date=2026-11-01 → 200, erreur
    test_create_end_before_start            # POST start=16:00 end=14:00 → 200, erreur
    test_create_location_too_long           # POST location 301 chars → 200, erreur
    test_create_min_headcount_out_of_range  # POST min_headcount=0 → 200, erreur
    test_create_bring_items_too_long        # POST bring_items 501 chars → 200, erreur
    test_create_logs_activity               # POST → ActivityLog "activity.created" en DB
    test_create_redirects_to_index          # POST → 302 Location=/e/<code>/planning

class TestEditActivity:
    test_edit_get_renders_prefilled         # GET /edit → 200, champs pré-remplis
    test_edit_success_as_creator            # POST → 302, champs modifiés en DB
    test_edit_success_as_activity_creator   # POST (guest qui a créé) → 302
    test_edit_forbidden_for_other_guest     # POST (autre guest) → 403
    test_edit_404_for_invalid_id            # POST /edit/invalid → 404
    test_edit_404_for_invalid_code          # POST /e/badcode/... → 404
    test_edit_logs_activity                 # POST → ActivityLog "activity.updated"

class TestDeleteActivity:
    test_delete_success_as_creator          # POST → 302, activité supprimée
    test_delete_success_as_activity_creator # POST (guest créateur) → 302
    test_delete_forbidden_for_other_guest   # POST (autre guest) → 403
    test_delete_cascades_rsvps              # POST → RSVP supprimés en DB
    test_delete_404_for_invalid_id          # POST /delete/invalid → 404
    test_delete_logs_activity               # POST → ActivityLog "activity.deleted"

class TestRSVP:
    test_rsvp_yes                           # POST status=yes → 302, RSVP en DB
    test_rsvp_no                            # POST status=no → 302
    test_rsvp_maybe                         # POST status=maybe → 302
    test_rsvp_update_existing               # POST status=no (après yes) → status modifié
    test_rsvp_invalid_status                # POST status=xyz → 302, flash "Statut invalide."
    test_rsvp_forbidden_for_creator         # POST (créateur logged in) → 302, flash
    test_rsvp_redirects_if_not_logged_in    # POST sans session → 302 /e/<code>/mycode
    test_rsvp_404_for_invalid_activity      # POST /rsvp/invalid → 404
    test_rsvp_logs_activity                 # POST → ActivityLog "rsvp.updated"
```

**Total : 44 tests**

Règles :
- Chaque test : setup précis → une action → un assert précis.
- Pas de test qui dépend d'un autre.
- Les tests de permission utilisent des fixtures distincts (creator, guest, other_guest).
- Fixture `other_guest` à ajouter dans conftest.py (2e guest sur le même événement).

---

## 12. Fichiers à créer/modifier

| Fichier | Action | Détail |
|---------|--------|--------|
| `app/utils.py` | **Créer** | Helper `log_action()` |
| `app/planning/__init__.py` | **Créer** | Blueprint (5 routes) |
| `app/templates/planning/index.html` | **Créer** | Liste + cartes + RSVP |
| `app/templates/planning/form.html` | **Créer** | Formulaire create/edit |
| `tests/conftest.py` | **Modifier** | Fixtures `activity`, `activity_rsvp`, `other_guest` |
| `tests/test_planning.py` | **Créer** | 44 tests |
| `pyproject.toml` | **Modifier** | Ajouter `flask-wtf` |
| `app/__init__.py` | **Modifier** | `CSRFProtect(app)` |

---

## 13. Critères d'acceptation du lot

- [ ] `GET /e/<code>/planning` rend la liste des activités (triées, groupées par date)
- [ ] `GET /e/<code>/planning/new` rend le formulaire vide
- [ ] `POST /e/<code>/planning/new` crée une activité (validation complète, 7 champs)
- [ ] `GET /e/<code>/planning/<id>/edit` rend le formulaire pré-rempli
- [ ] `POST /e/<code>/planning/<id>/edit` modifie (permission check → 403)
- [ ] `POST /e/<code>/planning/<id>/delete` supprime (cascade RSVP, permission → 403)
- [ ] `POST /e/<code>/planning/<id>/rsvp` upsert le RSVP (concurrency-safe)
- [ ] Chaque action est loggée dans ActivityLog (6 types d'actions)
- [ ] 44 tests passent
- [ ] Ruff + mypy + pytest verts
- [ ] Templates accessibles (WCAG 2.1 AA)
- [ ] i18n : 33 strings, pas de texte en dur
- [ ] CSRF tokens sur tous les POST
