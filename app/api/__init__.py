"""API REST v1 (B034) : accès par clé API, droits de rôle, découvrabilité.

Chaque requête (sauf ``/api/health``) exige un en-tête ``Authorization: Bearer hs_…``.
La clé est liée à un événement ET à son owner (créateur ou invité) : elle ne sert
que pour CET événement (tout autre code → 404, aucune fuite). Les droits sont ceux
du rôle de l'owner (``EventContext`` + table ``_RIGHTS``). Toute réponse est JSON
(``{"error": "…"}`` en cas d'erreur). Limite : 60 req/min par clé (``api_key_func``).
"""

import hashlib
import threading
from datetime import date, datetime, time
from time import monotonic
from typing import Any, cast

from flask import Blueprint, abort, current_app, g, jsonify, request
from flask_babel import gettext as _
from sqlalchemy.exc import IntegrityError
from werkzeug.wrappers import Response

from app.context import EventContext, get_or_create_creator_participant, log_event
from app.costs import (
    _base_cents,
    _household_in_event,
    _household_involved,
    _log_expense,
    _my_household,
    _parse_amount,
    _parse_date,
    _parse_rate,
    _per_expense_shares,
    _settlement,
    _visible,
)
from app.extensions import db, limiter
from app.forms import FormErrors
from app.i18n import BASE_CURRENCY, CURRENCIES, MEAL_SLOTS, RSVP_STATUSES, is_valid
from app.infos import ordered_infos
from app.models import (
    MAX_MEALS_PER_CELL,
    Activity,
    ActivityRSVP,
    ApiKey,
    ChatMessage,
    Creator,
    Event,
    Expense,
    Guest,
    Household,
    ListItem,
    LogisticsItem,
    Meal,
    PaymentRequest,
    Poll,
    PollOption,
    PollVote,
    SharedList,
    Transfer,
)
from app.planning import RSVP_CLEAR
from app.polls import KIND_ACTIVITIES, KIND_FREE, KINDS, PollView, poll_views
from app.voting import _activity_label

api_bp = Blueprint("api", __name__)

APP_VERSION = "0.1.0"


# === Authentification (clé Bearer) =====================================================


def api_key_func() -> str:
    """Clé de rate-limit : id de la clé API valide, sinon ``anon:<ip>`` (A10)."""
    api_key = _resolve_api_key()
    if api_key is not None:
        return api_key.id
    return f"anon:{request.remote_addr}"


def _resolve_api_key() -> ApiKey | None:
    """Résout la clé Bearer (cache ``g``) ; None si absente, inconnue, révoquée ou orpheline.

    Orpheline = événement ou owner supprimé : on renvoie None (→ 401) plutôt que de
    laisser une exception (→ 500).
    """
    cached = g.get("api_key")
    if cached is not None:
        return cached
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    key = header[7:].strip()
    if not key:
        return None
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    api_key = ApiKey.query.filter_by(key_hash=key_hash).first()
    if api_key is None or api_key.revoked_at is not None:
        return None
    if db.session.get(Event, api_key.event_id) is None:
        return None
    if api_key.owner_creator_id is not None:
        if db.session.get(Creator, api_key.owner_creator_id) is None:
            return None
    else:
        guest = db.session.get(Guest, api_key.owner_guest_id)
        if guest is None or not guest.is_active:
            return None
    g.api_key = api_key
    return api_key


def _build_ctx(api_key: ApiKey, event: Event) -> EventContext:
    """Contexte d'événement pour la clé : participant et rôle de l'owner."""
    if api_key.owner_creator_id is not None:
        creator = db.session.get(Creator, api_key.owner_creator_id)
        if creator is None:
            abort(401)
        participant = get_or_create_creator_participant(event, creator)
        return EventContext(event, participant, is_creator=True)
    guest = db.session.get(Guest, api_key.owner_guest_id)
    if guest is None or not guest.is_active or guest.creator_id is not None:
        abort(401)
    return EventContext(event, guest, is_creator=False)


def _touch_last_used(api_key: ApiKey) -> None:
    """Met à jour ``last_used_at`` (throttlé à 60 s) ; commit léger."""
    now = datetime.utcnow()
    last = api_key.last_used_at
    if last is not None and (now - last).total_seconds() < 60:
        return
    api_key.last_used_at = now
    db.session.commit()


# F2 : fenêtre glissante par IP pour les clés invalides (60 req/60 s). Les clés
# valides sont limitées par les décorateurs ``@limiter.limit`` (qui ne s'exécutent
# qu'à l'appel du view, donc jamais pour une clé rejetée en ``before_request``).
_ANON_API_LIMIT = 60
_ANON_API_WINDOW = 60.0
_anon_api_hits: dict[str, list[float]] = {}
_anon_api_lock = threading.Lock()


def _anon_api_limited(ip: str) -> bool:
    """True si l'IP a dépassé 60 requêtes à clé invalide sur la dernière minute (F2)."""
    now = monotonic()
    with _anon_api_lock:
        hits = [t for t in _anon_api_hits.get(ip, []) if now - t < _ANON_API_WINDOW]
        if len(hits) >= _ANON_API_LIMIT:
            _anon_api_hits[ip] = hits
            return True
        hits.append(now)
        _anon_api_hits[ip] = hits
        if len(_anon_api_hits) > 1024:  # garde mémoire : purge des IP expirées
            stale = [k for k, v in _anon_api_hits.items() if now - v[-1] >= _ANON_API_WINDOW]
            for k in stale:
                del _anon_api_hits[k]
    return False


def _reset_anon_api_hits() -> None:
    """Efface la fenêtre glissante des clés invalides (isolation des tests)."""
    with _anon_api_lock:
        _anon_api_hits.clear()


@api_bp.before_request
def _authenticate() -> None:
    """Authentifie la clé (sauf ``/api/health``) et pose le contexte sur ``g``."""
    if request.endpoint == "api.health":
        return
    api_key = _resolve_api_key()
    if api_key is None:
        # F2 : les clés invalides sont rate-limitées par IP (60 req/60 s).
        if _anon_api_limited(request.remote_addr or "unknown"):
            abort(429)
        abort(401)
    event = db.session.get(Event, api_key.event_id)
    if event is None:
        abort(401)
    # F1 : un événement inactif ou non-vérifié révoque l'accès API (spec §6.2.5 → 404).
    if not event.is_active or event.verified_at is None:
        abort(404)
    # Isolation inter-événements : la clé ne sert que pour SON événement.
    if request.view_args.get("code", "") != event.code:
        abort(404)
    ctx = _build_ctx(api_key, event)
    g.api_key = api_key
    g.api_event = event
    g.api_ctx = ctx
    _touch_last_used(api_key)


def _ctx() -> EventContext:
    """Contexte API (posé par ``before_request``) ; inatteignable sans clé valide."""
    return cast("EventContext", g.api_ctx)


# === Découvrabilité (index + métadonnées) =============================================


def api_endpoint(
    *, description: str, request: dict[str, str] | None, response: dict[str, str] | None
) -> Any:
    """Décorateur : métadonnées d'endpoint pour l'index (découvrabilité, §5)."""

    def decorator(func: Any) -> Any:
        func.api_meta = {
            "description": description,
            "request": request,
            "response": response,
        }
        return func

    return decorator


def _api_rules() -> list[tuple[str, str, dict[str, Any]]]:
    """(méthode, chemin, métadonnées) de chaque endpoint v1 documenté (hors health/index)."""
    out: list[tuple[str, str, dict[str, Any]]] = []
    for rule in current_app.url_map.iter_rules():
        if not rule.endpoint.startswith("api."):
            continue
        if rule.endpoint in ("api.health", "api.index"):
            continue
        view = current_app.view_functions[rule.endpoint]
        meta = getattr(view, "api_meta", None)
        if not isinstance(meta, dict):
            continue
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            out.append((method, rule.rule, meta))
    out.sort(key=lambda item: (item[1], item[0]))
    return out


# === Erreurs JSON (le blueprint prime sur les handlers HTML de l'app) =================


def _json_error(status: int, message: str) -> Response:
    return jsonify({"error": message}), status


@api_bp.errorhandler(400)
def _bad_request(e: Exception) -> Response:
    return _json_error(400, getattr(e, "description", None) or _("Requête invalide."))


@api_bp.errorhandler(401)
def _unauthorized(e: Exception) -> Response:
    return _json_error(401, _("Authentification requise."))


@api_bp.errorhandler(403)
def _forbidden(e: Exception) -> Response:
    return _json_error(403, _("Accès refusé."))


@api_bp.errorhandler(404)
def _not_found(e: Exception) -> Response:
    return _json_error(404, _("Introuvable."))


@api_bp.errorhandler(429)
def _too_many(e: Exception) -> Response:
    return _json_error(429, _("Trop de requêtes. Patientez un instant."))


# === Aides de lecture du corps JSON ===================================================


def _json_body() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400)
    return data


def _str(data: dict[str, Any], field: str) -> str:
    """Champ texte ; ``""`` si absent, None ou non texte (type inattendu → validation)."""
    value = data.get(field)
    return value.strip() if isinstance(value, str) else ""


def _num(data: dict[str, Any], field: str) -> str:
    """Champ numérique (int/float/str) ; ``""`` si absent ou non numérique."""
    value = data.get(field)
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    return ""


def _list_str(data: dict[str, Any], field: str) -> list[str]:
    """Liste de chaînes (dé-dupliquée, ordre conservé) ; ``[]`` si absent ou non liste."""
    value = data.get(field)
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(v) for v in value if isinstance(v, (str, int, float))))


def _first_error(errors: FormErrors) -> str | None:
    return next(iter(errors), None)


def _error(status: int, message: str | None) -> Response:
    return _json_error(status, message or _("Requête invalide."))


# === Validation (miroir des modules UI, corps JSON) ===================================


def _parse_time(value: str) -> time | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


def _parse_iso_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _validate_activity(data: dict[str, Any], event: Event) -> tuple[FormErrors, dict[str, Any]]:
    errors = FormErrors()
    title = _str(data, "title")
    description = _str(data, "description")
    date_raw = _str(data, "date")
    start_raw = _str(data, "start_time")
    end_raw = _str(data, "end_time")
    location = _str(data, "location")
    headcount_raw = _num(data, "min_headcount")
    bring_items = _str(data, "bring_items")

    if len(title) < 2:
        errors.add("title", _("Titre requis (min 2 caractères)."))
    if len(description) > 2000:
        errors.add("description", _("Description trop longue (max 2000)."))

    activity_date: date | None = None
    if not date_raw:
        errors.add("date", _("Date requise."))
    else:
        try:
            activity_date = datetime.strptime(date_raw, "%Y-%m-%d").date()
        except ValueError:
            errors.add("date", _("Format de date invalide (AAAA-MM-JJ)."))
        else:
            if not (event.start_date <= activity_date <= event.end_date):
                errors.add("date", _("Date hors de la période de l'événement."))

    start_time = _parse_time(start_raw)
    end_time = _parse_time(end_raw)
    if start_raw and start_time is None:
        errors.add("start_time", _("Heure invalide."))
    if end_raw and end_time is None:
        errors.add("end_time", _("Heure invalide."))
    if start_time is not None and end_time is not None and end_time <= start_time:
        errors.add("end_time", _("Heure de fin avant heure de début."))

    if len(location) > 300:
        errors.add("location", _("Lieu trop long (max 300)."))

    min_headcount = 1
    if headcount_raw:
        try:
            min_headcount = int(headcount_raw)
        except ValueError:
            errors.add("min_headcount", _("Nombre entre 1 et 50."))
        else:
            if not 1 <= min_headcount <= 50:
                errors.add("min_headcount", _("Nombre entre 1 et 50."))

    if len(bring_items) > 500:
        errors.add("bring_items", _("Champ trop long (max 500)."))

    values = {
        "title": title,
        "description": description,
        "date": activity_date or event.start_date,
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "min_headcount": min_headcount,
        "bring_items": bring_items,
    }
    return errors, values


def _validate_meal(data: dict[str, Any], event: Event) -> tuple[FormErrors, dict[str, Any]]:
    errors = FormErrors()
    title = _str(data, "title")
    if len(title) < 2:
        errors.add("title", _("Nom requis (min 2 caractères)."))
    elif len(title) > 200:
        errors.add("title", _("Nom trop long (max 200)."))
    day = _parse_iso_date(_str(data, "date"))
    slot = _str(data, "slot")
    if day is None or not (event.start_date <= day <= event.end_date):
        errors.add("date", _("Date hors de la période de l'événement."))
    if slot not in MEAL_SLOTS:
        errors.add("slot", _("Créneau invalide."))
    values: dict[str, Any] = {"title": title, "date": day, "slot": slot}
    return errors, values


def _validate_list(data: dict[str, Any]) -> tuple[FormErrors, dict[str, Any]]:
    errors = FormErrors()
    title = _str(data, "title")
    list_type = _str(data, "list_type") or "general"
    if not is_valid("list_type", list_type):
        list_type = "general"
    if len(title) < 2:
        errors.add("title", _("Titre requis (min 2 caractères)."))
    elif len(title) > 200:
        errors.add("title", _("Titre trop long (max 200)."))
    values = {"title": title, "list_type": list_type}
    return errors, values


def _validate_item(data: dict[str, Any], event: Event) -> tuple[FormErrors, dict[str, Any]]:
    name = _str(data, "name")
    quantity = _str(data, "quantity") or "1"
    section = _str(data, "section")
    assigned_to = _str(data, "assigned_to")
    errors = FormErrors()
    if len(name) < 1:
        errors.add("name", _("Nom requis."))
    elif len(name) > 300:
        errors.add("name", _("Nom trop long (max 300)."))
    if len(quantity) > 50:
        errors.add("quantity", _("Quantité trop longue (max 50)."))
    if len(section) > 100:
        errors.add("section", _("Section trop longue (max 100)."))
    if len(assigned_to) > 50:
        errors.add("assigned_to", _("Nom trop long (max 50)."))
    assigned_to_id: str | None = None
    if assigned_to and not errors:
        matches = Guest.query.filter_by(
            event_id=event.id, is_active=True, display_name=assigned_to
        ).all()
        if len(matches) == 1:
            assigned_to_id = matches[0].id
    values = {
        "name": name,
        "quantity": quantity,
        "section": section,
        "assigned_to": assigned_to,
        "assigned_to_id": assigned_to_id,
    }
    return errors, values


def _validate_logistics(data: dict[str, Any]) -> tuple[FormErrors, dict[str, Any]]:
    errors = FormErrors()
    title = _str(data, "title")
    content = _str(data, "content")
    category = _str(data, "category") or "general"
    if len(title) < 2:
        errors.add("title", _("Titre requis (min 2 caractères)."))
    elif len(title) > 200:
        errors.add("title", _("Titre trop long (max 200)."))
    if not content:
        errors.add("content", _("Contenu requis."))
    elif len(content) > 5000:
        errors.add("content", _("Contenu trop long (max 5000)."))
    if not is_valid("info_category", category):
        errors.add("category", _("Catégorie invalide."))
    values = {"title": title, "content": content, "category": category}
    return errors, values


def _validate_poll(data: dict[str, Any], ctx: EventContext) -> tuple[FormErrors, dict[str, Any]]:
    errors = FormErrors()
    question = _str(data, "question")
    kind = _str(data, "kind") or KIND_FREE
    options_raw = _str(data, "options")
    chosen_ids = _list_str(data, "activity_ids")

    if len(question) < 2:
        errors.add("question", _("Question requise (min 2 caractères)."))
    elif len(question) > 300:
        errors.add("question", _("Question trop longue (max 300 caractères)."))

    labels = [line.strip() for line in options_raw.splitlines() if line.strip()]
    fields: dict[str, Any] = {
        "question": question,
        "kind": KIND_FREE,
        "free_labels": labels,
        "activities": [],
    }
    if kind not in KINDS:
        errors.add("kind", _("Type de sondage invalide."))
    elif kind == KIND_FREE:
        if len(labels) < 2:
            errors.add("options", _("Au moins 2 options requises (une par ligne)."))
        elif len(labels) > 10:
            errors.add("options", _("Maximum 10 options (une par ligne)."))
    else:
        fields["kind"] = KIND_ACTIVITIES
        if "planning" not in current_app.blueprints:
            errors.add("kind", _("Le Planning n'est pas activé : choisissez une question libre."))
        else:
            found = {
                a.id: a
                for a in Activity.query.filter(
                    Activity.event_id == ctx.event.id,
                    Activity.status != "dropped",
                    Activity.id.in_(chosen_ids),
                )
            }
            if len(found) != len(chosen_ids):
                errors.add("activity_ids", _("Activité introuvable dans cet événement."))
            elif len(found) < 2:
                errors.add("activity_ids", _("Sélectionnez au moins 2 activités."))
            elif len(found) + len(labels) > 10:
                errors.add("options", _("Maximum 10 options (activités comprises)."))
            fields["activities"] = [found[i] for i in chosen_ids if i in found]
    if any(len(label) > 200 for label in labels):
        errors.add("options", _("Option trop longue (max 200 caractères)."))
    return errors, fields


def _validate_chat(data: dict[str, Any]) -> tuple[FormErrors, str]:
    content = _str(data, "content")
    errors = FormErrors()
    if not content:
        errors.add("content", _("Message vide."))
    elif len(content) > 2000:
        errors.add("content", _("Message trop long (max 2000)."))
    return errors, content


def _validate_expense(data: dict[str, Any], ctx: EventContext) -> tuple[FormErrors, dict[str, Any]]:
    description = _str(data, "description")
    category = _str(data, "category") or "general"
    currency = _str(data, "currency").upper() or BASE_CURRENCY
    household_id = _str(data, "household_id")
    is_shared = data.get("is_shared", True)
    if not isinstance(is_shared, bool):
        is_shared = True
    errors = FormErrors()
    if not description:
        errors.add("description", _("Description requise."))
    elif len(description) > 300:
        errors.add("description", _("Description trop longue (max 300)."))
    amount_cents = _parse_amount(_num(data, "amount"), errors)
    if currency not in CURRENCIES:
        errors.add("currency", _("Devise invalide."))
        currency = BASE_CURRENCY
    exchange_rate = _parse_rate(_num(data, "exchange_rate"), currency, errors)
    if not (errors.has("amount") or errors.has("exchange_rate")) and (
        _base_cents(amount_cents, exchange_rate) < 1
    ):
        errors.add("amount", _("Montant trop faible une fois converti."))
    if not is_valid("expense_category", category):
        errors.add("category", _("Catégorie invalide."))
    payer: Household | None = None
    if not household_id:
        errors.add("household_id", _("Foyer payeur requis."))
    elif not _household_in_event(household_id, ctx.event):
        errors.add("household_id", _("Foyer payeur invalide."))
    else:
        payer = db.session.get(Household, household_id)
    if payer is not None and not is_shared and not _household_involved(payer, ctx):
        errors.add("is_shared", _("Une dépense personnelle doit être payée par votre foyer."))
    exp_date = _parse_date(_str(data, "date"), errors)
    values = {
        "description": description,
        "amount_cents": amount_cents,
        "currency": currency,
        "exchange_rate": exchange_rate,
        "category": category,
        "paid_by_household_id": household_id,
        "date": exp_date,
        "is_shared": is_shared,
    }
    return errors, values


def _validate_household(data: dict[str, Any]) -> tuple[FormErrors, dict[str, Any]]:
    name = _str(data, "name")
    errors = FormErrors()
    if len(name) < 2:
        errors.add("name", _("Nom du foyer requis (min 2 caractères)."))
    elif len(name) > 100:
        errors.add("name", _("Nom trop long (max 100)."))
    values: dict[str, Any] = {"name": name, "num_adults": 1, "num_children": 0}
    try:
        num_adults = int(_num(data, "num_adults") or "1")
        num_children = int(_num(data, "num_children") or "0")
    except (ValueError, TypeError):
        errors.add_global(_("Valeurs numériques invalides."))
        return values, errors
    if num_adults < 1 or num_adults > 50:
        errors.add("num_adults", _("Adultes : entre 1 et 50."))
    if num_children < 0 or num_children > 50:
        errors.add("num_children", _("Enfants : entre 0 et 50."))
    values.update(num_adults=num_adults, num_children=num_children)
    return errors, values


def _validate_transfer(data: dict[str, Any], ctx: EventContext) -> tuple[FormErrors, dict[str, Any]]:
    errors = FormErrors()
    from_id = _str(data, "from_household_id")
    to_id = _str(data, "to_household_id")
    # Droits : un non-créateur n'enregistre qu'un transfert impliquant son foyer.
    if not ctx.is_creator:
        mine = _my_household(ctx)
        if mine is None or mine.id not in (from_id, to_id):
            abort(403)
    if not from_id or not to_id:
        errors.add("from_household_id", _("Foyers d'origine et de destination requis."))
    elif from_id == to_id:
        errors.add("from_household_id", _("Le foyer d'origine et de destination doivent différer."))
    elif not _household_in_event(from_id, ctx.event) or not _household_in_event(to_id, ctx.event):
        errors.add("from_household_id", _("Foyer invalide pour cet événement."))
    amount_cents = _parse_amount(_num(data, "amount"), errors)
    note = _str(data, "note")
    if len(note) > 300:
        errors.add("note", _("Note trop longue (max 300)."))
    t_date = _parse_date(_str(data, "date"), errors)
    values = {
        "from_household_id": from_id,
        "to_household_id": to_id,
        "amount_cents": amount_cents,
        "note": note,
        "date": t_date,
    }
    return errors, values


def _validate_payment_request(
    data: dict[str, Any], ctx: EventContext
) -> tuple[FormErrors, dict[str, Any]]:
    errors = FormErrors()
    mine = _my_household(ctx)
    if not ctx.is_creator and mine is None:
        abort(403)
    from_id = _str(data, "from_household_id") or (mine.id if mine else "")
    if not ctx.is_creator and mine is not None and from_id != mine.id:
        abort(403)
    to_id = _str(data, "to_household_id")
    message = _str(data, "message")
    if not from_id or not to_id:
        errors.add("to_household_id", _("Foyers requis."))
    elif from_id == to_id:
        errors.add("to_household_id", _("Les foyers doivent différer."))
    elif not _household_in_event(from_id, ctx.event) or not _household_in_event(to_id, ctx.event):
        errors.add("to_household_id", _("Foyer invalide pour cet événement."))
    amount_cents = _parse_amount(_num(data, "amount"), errors)
    if len(message) > 500:
        errors.add("message", _("Message trop long (max 500)."))
    values = {
        "from_household_id": from_id,
        "to_household_id": to_id,
        "amount_cents": amount_cents,
        "message": message,
    }
    return errors, values


# === Sérialisation ====================================================================


def _rsvp_names(event_id: str) -> dict[str, dict[str, list[str]]]:
    """activity_id -> {yes/maybe/no: [prénoms]} en une requête (participants actifs)."""
    out: dict[str, dict[str, list[str]]] = {}
    rows = (
        db.session.query(ActivityRSVP.activity_id, ActivityRSVP.status, Guest.display_name)
        .join(Guest, Guest.id == ActivityRSVP.guest_id)
        .join(Activity, Activity.id == ActivityRSVP.activity_id)
        .filter(Activity.event_id == event_id, Guest.is_active.is_(True))
        .order_by(Guest.display_name, Guest.id)
        .all()
    )
    for activity_id, status, name in rows:
        if status in ("yes", "maybe", "no"):
            out.setdefault(activity_id, {"yes": [], "maybe": [], "no": []})[status].append(name)
    return out


def _activity_json(activity: Activity, rsvps: dict[str, dict[str, list[str]]]) -> dict[str, Any]:
    return {
        "id": activity.id,
        "title": activity.title,
        "description": activity.description,
        "date": activity.date.isoformat(),
        "start_time": activity.start_time.strftime("%H:%M") if activity.start_time else None,
        "end_time": activity.end_time.strftime("%H:%M") if activity.end_time else None,
        "location": activity.location,
        "min_headcount": activity.min_headcount,
        "bring_items": activity.bring_items,
        "status": activity.status,
        "created_by": activity.created_by,
        "created_at": activity.created_at.isoformat() if activity.created_at else None,
        "rsvps": rsvps.get(activity.id, {"yes": [], "maybe": [], "no": []}),
    }


def _meal_json(meal: Meal) -> dict[str, Any]:
    return {
        "id": meal.id,
        "title": meal.title,
        "date": meal.date.isoformat(),
        "slot": meal.slot,
        "position": meal.position,
        "created_by": meal.created_by,
        "created_at": meal.created_at.isoformat() if meal.created_at else None,
    }


def _list_items(shared_list: SharedList) -> list[ListItem]:
    return list(shared_list.items.order_by(ListItem.created_at.asc()))


def _item_json(item: ListItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "quantity": item.quantity,
        "section": item.section,
        "assigned_to": item.assigned_to,
        "assigned_to_id": item.assigned_to_id,
        "is_done": item.is_done,
        "created_by": item.created_by,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _logistics_json(item: LogisticsItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "content": item.content,
        "category": item.category,
        "order": item.order,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _poll_json(view: PollView) -> dict[str, Any]:
    poll = view.poll
    return {
        "id": poll.id,
        "question": poll.question,
        "kind": poll.kind,
        "is_closed": poll.is_closed,
        "created_by": poll.created_by,
        "created_at": poll.created_at.isoformat() if poll.created_at else None,
        "voters": view.voters,
        "show_results": view.show_results,
        "options": [
            {
                "id": r.option.id,
                "label": r.option.label,
                "order": r.option.order,
                "activity_id": r.option.activity_id,
                "count": r.count,
                "fraction": r.fraction,
                "winner": r.winner,
                "mine": r.mine,
            }
            for r in view.options
        ],
    }


def _chat_json(message: ChatMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "content": message.content,
        "author_name": message.author_name,
        "author_type": message.author_type,
        "guest_id": message.guest_id,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def _household_json(h: Household) -> dict[str, Any]:
    return {
        "id": h.id,
        "name": h.name,
        "num_adults": h.num_adults,
        "num_children": h.num_children,
        "adult_weight": h.adult_weight,
        "child_weight": h.child_weight,
        "total_weight": h.total_weight,
        "guest_id": h.guest_id,
    }


def _expense_json(e: Expense) -> dict[str, Any]:
    return {
        "id": e.id,
        "description": e.description,
        "amount_cents": e.amount_cents,
        "currency": e.currency,
        "exchange_rate": e.exchange_rate,
        "category": e.category,
        "paid_by_household_id": e.paid_by_household_id,
        "date": e.date.isoformat() if e.date else None,
        "is_shared": e.is_shared,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def _transfer_json(t: Transfer) -> dict[str, Any]:
    return {
        "id": t.id,
        "from_household_id": t.from_household_id,
        "to_household_id": t.to_household_id,
        "amount_cents": t.amount_cents,
        "note": t.note,
        "date": t.date.isoformat() if t.date else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _payment_request_json(p: PaymentRequest) -> dict[str, Any]:
    return {
        "id": p.id,
        "from_household_id": p.from_household_id,
        "to_household_id": p.to_household_id,
        "amount_cents": p.amount_cents,
        "message": p.message,
        "is_resolved": p.is_resolved,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


# === Routes ===========================================================================


@api_bp.route("/health")
def health() -> Response:
    """Sonde de vie (sans clé) : ``{"ok": true, "version": "0.1.0"}`` (§5.3)."""
    return jsonify({"ok": True, "version": APP_VERSION})


@api_bp.route("/events/<code>/index")
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(
    description="Index des endpoints de l'API (généré depuis les routeurs)",
    request=None,
    response={"event": "string", "auth": "string", "endpoints": "list"},
)
def index(code: str) -> Response:
    """Découvrabilité : chaque endpoint v1 (méthode + chemin + métadonnées) (§5.1)."""
    ctx = _ctx()
    endpoints = [
        {
            "method": method,
            "path": path,
            "description": meta.get("description", ""),
            "request": meta.get("request"),
            "response": meta.get("response"),
        }
        for method, path, meta in _api_rules()
    ]
    return jsonify(
        {
            "event": ctx.event.code,
            "auth": "Authorization: Bearer hs_...",
            "endpoints": endpoints,
        }
    )


@api_bp.route("/events/<code>")
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(
    description="Infos événement + résumé de l'API",
    request=None,
    response={"code": "string", "title": "string", "participants": "list", "api": "object"},
)
def event_info(code: str) -> Response:
    """Infos de l'événement + champ ``api`` (auth, index, endpoints) (§5.2)."""
    ctx = _ctx()
    event = ctx.event
    guests = (
        Guest.query.filter_by(event_id=event.id, is_active=True)
        .order_by(Guest.display_name)
        .all()
    )
    participants = [
        {"id": g.id, "display_name": g.display_name, "is_creator": g.creator_id is not None}
        for g in guests
    ]
    return jsonify(
        {
            "code": event.code,
            "title": event.title,
            "description": event.description,
            "start_date": event.start_date.isoformat(),
            "end_date": event.end_date.isoformat(),
            "location": event.location,
            "participants": participants,
            "api": {
                "auth": "Authorization: Bearer hs_...",
                "index": f"/api/events/{event.code}/index",
                "endpoints": [f"{method} {path}" for method, path, _meta in _api_rules()],
            },
        }
    )


# --- Activités & RSVP ----------------------------------------------------------------


@api_bp.route("/events/<code>/activities")
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(description="Liste des activités", request=None, response={"activities": "list"})
def activities_list(code: str) -> Response:
    ctx = _ctx()
    activities = (
        Activity.query.filter_by(event_id=ctx.event.id)
        .order_by(
            Activity.date,
            Activity.start_time.asc().nulls_first(),
            Activity.created_at,
            Activity.id,
        )
        .all()
    )
    rsvps = _rsvp_names(ctx.event.id)
    return jsonify({"activities": [_activity_json(a, rsvps) for a in activities]})


@api_bp.route("/events/<code>/activities", methods=["POST"])
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(
    description="Créer une activité",
    request={"title": "string, requis, 2-200", "date": "YYYY-MM-DD, requis"},
    response={"id": "string"},
)
def activities_create(code: str) -> Response:
    ctx = _ctx()
    data = _json_body()
    errors, values = _validate_activity(data, ctx.event)
    if errors:
        return _error(400, _first_error(errors))
    activity = Activity(
        title=values["title"],
        description=values["description"],
        date=values["date"],
        start_time=values["start_time"],
        end_time=values["end_time"],
        location=values["location"],
        min_headcount=values["min_headcount"],
        bring_items=values["bring_items"],
        created_by=ctx.participant.id if ctx.participant else None,
        event_id=ctx.event.id,
    )
    db.session.add(activity)
    log_event(ctx, "activity.created", target=values["title"])
    db.session.commit()
    return jsonify(_activity_json(activity, _rsvp_names(ctx.event.id))), 201


@api_bp.route("/events/<code>/activities/<activity_id>/rsvp", methods=["POST"])
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(
    description="RSVP à une activité (son propre RSVP)",
    request={"status": "yes|no|maybe|none, requis"},
    response={"id": "string"},
)
def rsvp(code: str, activity_id: str) -> Response:
    ctx = _ctx()
    participant = ctx.participant
    if participant is None:
        abort(403)
    activity = Activity.query.filter_by(id=activity_id, event_id=ctx.event.id).first()
    if activity is None:
        abort(404)
    data = _json_body()
    status = _str(data, "status")
    if status not in RSVP_STATUSES and status != RSVP_CLEAR:
        return _error(400, _("Statut invalide."))
    existing = ActivityRSVP.query.filter_by(activity_id=activity.id, guest_id=participant.id).first()
    if status == RSVP_CLEAR:
        if existing is not None:
            db.session.delete(existing)
    elif existing is not None:
        existing.status = status
    else:
        db.session.add(ActivityRSVP(activity_id=activity.id, guest_id=participant.id, status=status))
    try:
        db.session.flush()
    except IntegrityError:  # double envoi concurrent : la réponse existe déjà, on la met à jour
        db.session.rollback()
        existing = ActivityRSVP.query.filter_by(
            activity_id=activity.id, guest_id=participant.id
        ).first()
        if existing is not None and status != RSVP_CLEAR:
            existing.status = status
    log_event(ctx, "rsvp.updated", target=activity.title, details=status)
    db.session.commit()
    return jsonify(_activity_json(activity, _rsvp_names(ctx.event.id)))


# --- Repas ---------------------------------------------------------------------------


@api_bp.route("/events/<code>/meals")
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(description="Liste des repas", request=None, response={"meals": "list"})
def meals_list(code: str) -> Response:
    ctx = _ctx()
    meals = Meal.query.filter_by(event_id=ctx.event.id).order_by(*Meal.ordering()).all()
    return jsonify({"meals": [_meal_json(m) for m in meals]})


@api_bp.route("/events/<code>/meals", methods=["POST"])
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(
    description="Créer un repas",
    request={"title": "string, requis, 2-200", "date": "YYYY-MM-DD, requis", "slot": "lunch|dinner, requis"},
    response={"id": "string"},
)
def meals_create(code: str) -> Response:
    ctx = _ctx()
    data = _json_body()
    errors, values = _validate_meal(data, ctx.event)
    if errors:
        return _error(400, _first_error(errors))
    cell = list(
        Meal.query.filter_by(event_id=ctx.event.id, date=values["date"], slot=values["slot"]).order_by(
            Meal.position, Meal.created_at, Meal.id
        )
    )
    if len(cell) >= MAX_MEALS_PER_CELL:
        return _error(400, _("Cette case est pleine (%(max)d repas maximum).", max=MAX_MEALS_PER_CELL))
    meal = Meal(
        title=values["title"],
        date=values["date"],
        slot=values["slot"],
        position=len(cell),
        created_by=ctx.participant.id if ctx.participant else None,
        event_id=ctx.event.id,
    )
    db.session.add(meal)
    log_event(ctx, "meal.created", target=values["title"])
    db.session.commit()
    return jsonify(_meal_json(meal)), 201


# --- Listes & articles ---------------------------------------------------------------


@api_bp.route("/events/<code>/lists")
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(description="Liste des listes", request=None, response={"lists": "list"})
def lists_list(code: str) -> Response:
    ctx = _ctx()
    lists = (
        SharedList.query.filter_by(event_id=ctx.event.id)
        .order_by(SharedList.created_at.asc())
        .all()
    )
    data = [
        {
            "id": lst.id,
            "title": lst.title,
            "list_type": lst.list_type,
            "created_at": lst.created_at.isoformat() if lst.created_at else None,
            "items": [_item_json(i) for i in _list_items(lst)],
        }
        for lst in lists
    ]
    return jsonify({"lists": data})


@api_bp.route("/events/<code>/lists", methods=["POST"])
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(
    description="Créer une liste",
    request={"title": "string, requis, 2-200"},
    response={"id": "string"},
)
def lists_create(code: str) -> Response:
    ctx = _ctx()
    data = _json_body()
    errors, values = _validate_list(data)
    if errors:
        return _error(400, _first_error(errors))
    shared_list = SharedList(title=values["title"], list_type=values["list_type"], event_id=ctx.event.id)
    db.session.add(shared_list)
    log_event(ctx, "list.created", target=values["title"])
    db.session.commit()
    return jsonify({"id": shared_list.id, "title": shared_list.title, "list_type": shared_list.list_type}), 201


@api_bp.route("/events/<code>/lists/<list_id>", methods=["DELETE"])
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(
    description="Supprimer une liste (créateur)",
    request=None,
    response={"ok": "boolean"},
)
def lists_delete(code: str, list_id: str) -> Response:
    ctx = _ctx()
    shared_list = SharedList.query.filter_by(id=list_id, event_id=ctx.event.id).first()
    if shared_list is None:
        abort(404)
    if not ctx.can_delete(shared_list):
        abort(403)
    title = shared_list.title
    db.session.delete(shared_list)
    log_event(ctx, "list.deleted", target=title)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.route("/events/<code>/lists/<list_id>/items")
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(description="Liste des articles d'une liste", request=None, response={"items": "list"})
def items_list(code: str, list_id: str) -> Response:
    ctx = _ctx()
    shared_list = SharedList.query.filter_by(id=list_id, event_id=ctx.event.id).first()
    if shared_list is None:
        abort(404)
    return jsonify({"items": [_item_json(i) for i in _list_items(shared_list)]})


@api_bp.route("/events/<code>/lists/<list_id>/items", methods=["POST"])
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(
    description="Ajouter un article à une liste",
    request={"name": "string, requis, 1-300"},
    response={"id": "string"},
)
def items_create(code: str, list_id: str) -> Response:
    ctx = _ctx()
    shared_list = SharedList.query.filter_by(id=list_id, event_id=ctx.event.id).first()
    if shared_list is None:
        abort(404)
    data = _json_body()
    errors, values = _validate_item(data, ctx.event)
    if errors:
        return _error(400, _first_error(errors))
    item = ListItem(
        **values,
        list_id=shared_list.id,
        created_by=ctx.participant.id if ctx.participant else None,
    )
    db.session.add(item)
    log_event(ctx, "list_item.created", target=values["name"], details=shared_list.title)
    db.session.commit()
    return jsonify(_item_json(item)), 201


# --- Infos pratiques -----------------------------------------------------------------


@api_bp.route("/events/<code>/logistics")
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(description="Liste des infos pratiques", request=None, response={"infos": "list"})
def logistics_list(code: str) -> Response:
    ctx = _ctx()
    return jsonify({"infos": [_logistics_json(i) for i in ordered_infos(ctx.event.id)]})


@api_bp.route("/events/<code>/logistics", methods=["POST"])
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(
    description="Créer une info pratique",
    request={"title": "string, requis, 2-200", "content": "string, requis, max 5000"},
    response={"id": "string"},
)
def logistics_create(code: str) -> Response:
    ctx = _ctx()
    data = _json_body()
    errors, values = _validate_logistics(data)
    if errors:
        return _error(400, _first_error(errors))
    item = LogisticsItem(
        title=values["title"],
        content=values["content"],
        category=values["category"],
        event_id=ctx.event.id,
    )
    db.session.add(item)
    log_event(ctx, "logistics.created", target=values["title"])
    db.session.commit()
    return jsonify(_logistics_json(item)), 201


# --- Sondages & votes ----------------------------------------------------------------


@api_bp.route("/events/<code>/polls")
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(description="Liste des sondages", request=None, response={"polls": "list"})
def polls_list(code: str) -> Response:
    ctx = _ctx()
    polls = (
        Poll.query.filter_by(event_id=ctx.event.id)
        .order_by(Poll.created_at.desc(), Poll.id)
        .all()
    )
    return jsonify({"polls": [_poll_json(v) for v in poll_views(polls, ctx.participant)]})


@api_bp.route("/events/<code>/polls", methods=["POST"])
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(
    description="Créer un sondage",
    request={"question": "string, requis, 2-300", "kind": "free|activities", "options": "string (libellés séparés par saut de ligne)"},
    response={"id": "string"},
)
def polls_create(code: str) -> Response:
    ctx = _ctx()
    data = _json_body()
    errors, fields = _validate_poll(data, ctx)
    if errors:
        return _error(400, _first_error(errors))
    poll = Poll(
        question=fields["question"],
        kind=fields["kind"],
        event_id=ctx.event.id,
        created_by=ctx.participant.id if ctx.participant else None,
    )
    order = 0
    for activity in fields["activities"]:
        poll.options.append(
            PollOption(label=_activity_label(activity), order=order, activity_id=activity.id)
        )
        order += 1
    for label in fields["free_labels"]:
        poll.options.append(PollOption(label=label, order=order))
        order += 1
    db.session.add(poll)
    log_event(ctx, "poll.created", target=fields["question"])
    db.session.commit()
    return jsonify(_poll_json(poll_views([poll], ctx.participant)[0])), 201


@api_bp.route("/events/<code>/polls/<poll_id>/vote", methods=["POST"])
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(
    description="Voter à un sondage (son propre vote)",
    request={"option_id": "string, requis"},
    response={"id": "string"},
)
def vote(code: str, poll_id: str) -> Response:
    ctx = _ctx()
    participant = ctx.participant
    if participant is None:
        abort(403)
    poll = Poll.query.filter_by(id=poll_id, event_id=ctx.event.id).first()
    if poll is None:
        abort(404)
    data = _json_body()
    option = PollOption.query.filter_by(id=_str(data, "option_id"), poll_id=poll.id).first()
    if option is None:
        abort(404)
    if poll.is_closed:
        return _error(400, _("Ce sondage est clos."))
    option_ids = [opt.id for opt in poll.options.all()]
    previous = PollVote.query.filter(
        PollVote.guest_id == participant.id, PollVote.option_id.in_(option_ids)
    ).all()
    if not any(v.option_id == option.id for v in previous):
        for old_vote in previous:
            db.session.delete(old_vote)
        db.session.add(PollVote(option_id=option.id, guest_id=participant.id))
        log_event(ctx, "poll.voted", target=poll.question, details=option.label)
        db.session.commit()
    return jsonify(_poll_json(poll_views([poll], ctx.participant)[0]))


# --- Chat ----------------------------------------------------------------------------


@api_bp.route("/events/<code>/chat")
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(description="Les 50 derniers messages du chat", request=None, response={"messages": "list"})
def chat_list(code: str) -> Response:
    ctx = _ctx()
    messages = (
        ChatMessage.query.filter_by(event_id=ctx.event.id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(50)
        .all()
    )
    messages.reverse()
    return jsonify({"messages": [_chat_json(m) for m in messages]})


@api_bp.route("/events/<code>/chat", methods=["POST"])
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(
    description="Envoyer un message",
    request={"content": "string, requis, 1-2000"},
    response={"id": "string"},
)
def chat_send(code: str) -> Response:
    ctx = _ctx()
    participant = ctx.participant
    if participant is None:
        abort(403)
    data = _json_body()
    errors, content = _validate_chat(data)
    if errors:
        return _error(400, _first_error(errors))
    message = ChatMessage(
        content=content,
        guest_id=participant.id,
        author_name=ctx.actor.name,
        author_type=ctx.actor.type,
        event_id=ctx.event.id,
    )
    db.session.add(message)
    log_event(ctx, "chat.message", target=content[:50])
    db.session.commit()
    return jsonify(_chat_json(message)), 201


# --- Frais ---------------------------------------------------------------------------


@api_bp.route("/events/<code>/costs")
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(
    description="Tableau de bord des frais",
    request=None,
    response={"households": "list", "expenses": "list", "balances": "object"},
)
def costs_dashboard(code: str) -> Response:
    ctx = _ctx()
    event = ctx.event
    households = event.households.order_by(Household.created_at, Household.id).all()
    all_expenses = event.expenses.order_by(Expense.date.desc(), Expense.created_at.desc()).all()
    expenses = [e for e in all_expenses if _visible(ctx, e)]
    shared_expenses = [e for e in all_expenses if e.is_shared]
    transfers = event.transfers.order_by(Transfer.created_at.desc()).all()
    payment_requests = event.payment_requests.order_by(
        PaymentRequest.is_resolved.asc(), PaymentRequest.created_at.desc()
    ).all()
    settlements = [
        {"from": f, "to": t, "amount": a / 100.0}
        for f, t, a in _settlement(households, shared_expenses, transfers)
    ]
    shares, paid = _per_expense_shares(households, shared_expenses)
    balances = {h.id: (paid[h.id] - shares[h.id]) / 100.0 for h in households}
    return jsonify(
        {
            "households": [_household_json(h) for h in households],
            "expenses": [_expense_json(e) for e in expenses],
            "transfers": [_transfer_json(t) for t in transfers],
            "payment_requests": [_payment_request_json(p) for p in payment_requests],
            "settlements": settlements,
            "balances": balances,
        }
    )


@api_bp.route("/events/<code>/costs/expenses", methods=["POST"])
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(
    description="Ajouter une dépense",
    request={"description": "string, requis, max 300", "amount": "string, requis, > 0", "household_id": "string, requis"},
    response={"id": "string"},
)
def expenses_create(code: str) -> Response:
    ctx = _ctx()
    data = _json_body()
    errors, values = _validate_expense(data, ctx)
    if errors:
        return _error(400, _first_error(errors))
    exp = Expense(
        **values,
        event_id=ctx.event.id,
        created_by=ctx.participant.id if ctx.participant else None,
    )
    db.session.add(exp)
    _log_expense(ctx, "expense.created", exp)
    db.session.commit()
    return jsonify(_expense_json(exp)), 201


@api_bp.route("/events/<code>/costs/households", methods=["POST"])
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(
    description="Ajouter un foyer (créateur)",
    request={"name": "string, requis, 2-100"},
    response={"id": "string"},
)
def households_create(code: str) -> Response:
    ctx = _ctx()
    if not ctx.is_creator:
        abort(403)
    data = _json_body()
    errors, values = _validate_household(data)
    if errors:
        return _error(400, _first_error(errors))
    first = Household.query.filter_by(event_id=ctx.event.id).first()
    household = Household(
        **values,
        adult_weight=first.adult_weight if first else 1.0,
        child_weight=first.child_weight if first else 0.5,
        event_id=ctx.event.id,
    )
    db.session.add(household)
    log_event(ctx, "household.created", target=values["name"])
    db.session.commit()
    return jsonify(_household_json(household)), 201


@api_bp.route("/events/<code>/costs/transfers", methods=["POST"])
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(
    description="Enregistrer un transfert",
    request={"from_household_id": "string, requis", "to_household_id": "string, requis", "amount": "string, requis, > 0"},
    response={"id": "string"},
)
def transfers_create(code: str) -> Response:
    ctx = _ctx()
    data = _json_body()
    errors, values = _validate_transfer(data, ctx)
    if errors:
        return _error(400, _first_error(errors))
    transfer = Transfer(
        from_household_id=values["from_household_id"],
        to_household_id=values["to_household_id"],
        amount_cents=values["amount_cents"],
        note=values["note"],
        date=values["date"],
        event_id=ctx.event.id,
        created_by=ctx.participant.id if ctx.participant else None,
    )
    db.session.add(transfer)
    log_event(ctx, "transfer.created", details=f"{values['amount_cents'] / 100:.2f} {BASE_CURRENCY}")
    db.session.commit()
    return jsonify(_transfer_json(transfer)), 201


@api_bp.route("/events/<code>/costs/payment-requests", methods=["POST"])
@limiter.limit("60 per minute", key_func=api_key_func)
@api_endpoint(
    description="Créer une demande de paiement",
    request={"from_household_id": "string, requis", "to_household_id": "string, requis", "amount": "string, requis, > 0"},
    response={"id": "string"},
)
def payment_requests_create(code: str) -> Response:
    ctx = _ctx()
    data = _json_body()
    errors, values = _validate_payment_request(data, ctx)
    if errors:
        return _error(400, _first_error(errors))
    payment_request = PaymentRequest(
        from_household_id=values["from_household_id"],
        to_household_id=values["to_household_id"],
        amount_cents=values["amount_cents"],
        message=values["message"],
        event_id=ctx.event.id,
        created_by=ctx.participant.id if ctx.participant else None,
    )
    db.session.add(payment_request)
    log_event(ctx, "payment_request.created", details=f"{values['amount_cents'] / 100:.2f} {BASE_CURRENCY}")
    db.session.commit()
    return jsonify(_payment_request_json(payment_request)), 201
