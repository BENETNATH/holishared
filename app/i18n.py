"""Libellés traduits et formats localisés (B018).

Une seule source pour les catégories, statuts et types affichés : les gabarits
passent par ``|label("<kind>")`` et ``choices("<kind>")``, jamais par une clé brute.
Les formats (montants, nombres, heures, dates) passent par Babel selon la langue active.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, time
from typing import TYPE_CHECKING, Any, Final

from babel import dates as bdates
from babel import numbers as bnum
from flask import has_request_context
from flask_babel import get_locale, gettext
from flask_babel import lazy_gettext as _l

if TYPE_CHECKING:
    from flask import Flask

log = logging.getLogger(__name__)

LABELS: Final[dict[str, dict[str, Any]]] = {
    "expense_category": {
        "general": _l("Général"),
        "food": _l("Alimentation"),
        "transport": _l("Transport"),
        "lodging": _l("Hébergement"),
        "activities": _l("Activités"),
        "other": _l("Autre"),
    },
    "info_category": {
        "address": _l("Adresse"),
        "access": _l("Accès / Parking"),
        "timing": _l("Horaires"),
        "docs": _l("Documents"),
        "notes": _l("Notes diverses"),
        "general": _l("Divers"),
    },
    "list_type": {
        "general": _l("Général"),
        "shopping": _l("Courses"),
        "materials": _l("Matériel"),
        "packing": _l("Valise"),
        "todo": _l("À faire"),
        "buffet": _l("Buffet"),
    },
    "rsvp_status": {"yes": _l("Oui"), "maybe": _l("Peut-être"), "no": _l("Non")},
    "meal_slot": {"lunch": _l("Midi"), "dinner": _l("Soir")},
}
# Libellé de repli quand la clé est vide ou inconnue (jamais la clé brute).
DEFAULTS: Final[dict[str, str | None]] = {
    "expense_category": "other",
    "info_category": "general",
    "list_type": "general",
    "rsvp_status": None,
    "meal_slot": None,
}

EXPENSE_CATEGORIES: Final = frozenset(LABELS["expense_category"])
INFO_CATEGORIES: Final = frozenset(LABELS["info_category"])
RSVP_STATUSES: Final = frozenset(LABELS["rsvp_status"])
MEAL_SLOTS: Final = frozenset(LABELS["meal_slot"])
CURRENCIES: Final[tuple[str, ...]] = ("EUR", "USD", "GBP", "CHF", "CAD", "AUD", "JPY")
BASE_CURRENCY: Final = "EUR"

# Journal d'activité : code d'action -> libellé court (phrases complètes : B020).
ACTION_LABELS: Final[dict[str, Any]] = {
    "activity.created": _l("Activité créée"),
    "activity.updated": _l("Activité modifiée"),
    "activity.deleted": _l("Activité supprimée"),
    "rsvp.updated": _l("Réponse à une activité"),
    "meal.created": _l("Repas ajouté"),
    "meal.updated": _l("Repas modifié"),
    "meal.deleted": _l("Repas supprimé"),
    "meal.moved": _l("Repas déplacé"),
    "meal.swapped": _l("Repas échangés"),
    "list.created": _l("Liste créée"),
    "list.deleted": _l("Liste supprimée"),
    "list_item.created": _l("Article ajouté"),
    "list_item.toggled": _l("Article coché ou décoché"),
    "list_item.deleted": _l("Article supprimé"),
    "list_item.claimed": _l("Article pris en charge"),
    "list_item.unclaimed": _l("Article libéré"),
    "list_item.restored": _l("Article rétabli"),
    "list.meal_covered": _l("Repas pris en compte dans une liste"),
    "list.meal_uncovered": _l("Repas retiré d'une liste"),
    "list.activity_covered": _l("Activité prise en compte dans une liste"),
    "list.activity_uncovered": _l("Activité retirée d'une liste"),
    "logistics.created": _l("Info pratique ajoutée"),
    "logistics.updated": _l("Info pratique modifiée"),
    "logistics.deleted": _l("Info pratique supprimée"),
    "poll.created": _l("Sondage créé"),
    "poll.voted": _l("Vote enregistré"),
    "poll.closed": _l("Sondage clos"),
    "poll.reopened": _l("Sondage rouvert"),
    "poll.deleted": _l("Sondage supprimé"),
    "activity.retained": _l("Activité retenue"),
    "activity.restored": _l("Activité restaurée"),
    "activity.dropped": _l("Activité non retenue"),
    "chat.message": _l("Message envoyé"),
    "chat.message_deleted": _l("Message supprimé"),
    "media.uploaded": _l("Média ajouté"),
    "media.deleted": _l("Média supprimé"),
    "household.created": _l("Foyer ajouté"),
    "household.updated": _l("Foyer modifié"),
    "household.deleted": _l("Foyer supprimé"),
    "expense.created": _l("Dépense ajoutée"),
    "expense.updated": _l("Dépense modifiée"),
    "expense.deleted": _l("Dépense supprimée"),
    "transfer.created": _l("Transfert enregistré"),
    "transfer.deleted": _l("Transfert supprimé"),
    "payment_request.created": _l("Demande de paiement créée"),
    "payment_request.resolved": _l("Demande de paiement réglée"),
    "payment_request.deleted": _l("Demande de paiement supprimée"),
    "ratio.updated": _l("Ratio de répartition modifié"),
    "participant.added": _l("Participant ajouté"),
    "participant.removed": _l("Participant retiré"),
    "participant.renamed": _l("Nom d'affichage modifié"),
    "api_key.created": _l("Clé API créée"),
    "api_key.revoked": _l("Clé API révoquée"),
}

# Journal lisible (B020) : phrase par code d'action, ``%(actor)s`` = auteur de l'action.
# La cible (titre, nom…) est ajoutée après « : » ; les détails vont sur une seconde ligne.
ACTION_SENTENCES: Final[dict[str, Any]] = {
    "activity.created": _l("%(actor)s a ajouté une activité"),
    "activity.updated": _l("%(actor)s a modifié une activité"),
    "activity.deleted": _l("%(actor)s a supprimé une activité"),
    "rsvp.updated": _l("%(actor)s a répondu « %(detail)s » à une activité"),
    "meal.created": _l("%(actor)s a ajouté un repas"),
    "meal.updated": _l("%(actor)s a modifié un repas"),
    "meal.deleted": _l("%(actor)s a supprimé un repas"),
    "meal.moved": _l("%(actor)s a déplacé un repas"),
    "meal.swapped": _l("%(actor)s a échangé deux repas"),
    "list.created": _l("%(actor)s a créé une liste"),
    "list.deleted": _l("%(actor)s a supprimé une liste"),
    "list_item.created": _l("%(actor)s a ajouté un article"),
    "list_item.toggled": _l("%(actor)s a modifié un article"),
    "list_item.deleted": _l("%(actor)s a supprimé un article"),
    "list_item.claimed": _l("%(actor)s s'occupe d'un article"),
    "list_item.unclaimed": _l("%(actor)s ne s'occupe plus d'un article"),
    "list_item.restored": _l("%(actor)s a rétabli un article"),
    "list.meal_covered": _l("%(actor)s a pris en compte un repas dans une liste"),
    "list.meal_uncovered": _l("%(actor)s a retiré un repas d'une liste"),
    "list.activity_covered": _l("%(actor)s a pris en compte une activité dans une liste"),
    "list.activity_uncovered": _l("%(actor)s a retiré une activité d'une liste"),
    "logistics.created": _l("%(actor)s a ajouté une info pratique"),
    "logistics.updated": _l("%(actor)s a modifié une info pratique"),
    "logistics.deleted": _l("%(actor)s a supprimé une info pratique"),
    "poll.created": _l("%(actor)s a créé un sondage"),
    "poll.voted": _l("%(actor)s a voté à un sondage"),
    "poll.closed": _l("%(actor)s a clos un sondage"),
    "poll.reopened": _l("%(actor)s a rouvert un sondage"),
    "poll.deleted": _l("%(actor)s a supprimé un sondage"),
    "activity.retained": _l("%(actor)s a retenu une activité"),
    "activity.restored": _l("%(actor)s a restauré une activité"),
    "activity.dropped": _l("%(actor)s a écarté une activité"),
    "chat.message": _l("%(actor)s a écrit un message"),
    "chat.message_deleted": _l("%(actor)s a supprimé un message"),
    "media.uploaded": _l("%(actor)s a ajouté un média"),
    "media.deleted": _l("%(actor)s a supprimé un média"),
    "household.created": _l("%(actor)s a ajouté un foyer"),
    "household.updated": _l("%(actor)s a modifié un foyer"),
    "household.deleted": _l("%(actor)s a supprimé un foyer"),
    "expense.created": _l("%(actor)s a ajouté une dépense"),
    "expense.updated": _l("%(actor)s a modifié une dépense"),
    "expense.deleted": _l("%(actor)s a supprimé une dépense"),
    "transfer.created": _l("%(actor)s a enregistré un transfert"),
    "transfer.deleted": _l("%(actor)s a supprimé un transfert"),
    "payment_request.created": _l("%(actor)s a demandé un paiement"),
    "payment_request.resolved": _l("%(actor)s a marqué une demande de paiement comme réglée"),
    "payment_request.deleted": _l("%(actor)s a supprimé une demande de paiement"),
    "ratio.updated": _l("%(actor)s a modifié les parts de répartition"),
    "participant.added": _l("%(actor)s a ajouté un participant"),
    "participant.removed": _l("%(actor)s a retiré un participant"),
    "participant.renamed": _l("%(actor)s a changé de nom d'affichage"),
    "api_key.created": _l("%(actor)s a créé une clé API"),
    "api_key.revoked": _l("%(actor)s a révoqué une clé API"),
}
# Variantes selon les détails enregistrés (cocher / décocher un article).
ACTION_VARIANTS: Final[dict[tuple[str, str], Any]] = {
    ("list_item.toggled", "done"): _l("%(actor)s a coché un article"),
    ("list_item.toggled", "undone"): _l("%(actor)s a décoché un article"),
}
# Détails techniques ou déjà intégrés à la phrase : jamais affichés sur la seconde ligne.
ACTION_HIDDEN_DETAILS: Final = frozenset(
    {"list_item.toggled", "ratio.updated", "media.uploaded", "rsvp.updated"}
)
# Préfixe du code d'action -> module (filtre du journal).
ACTION_MODULES: Final[dict[str, str]] = {
    "activity": "planning",
    "rsvp": "planning",
    "meal": "meals",
    "list": "lists",
    "list_item": "lists",
    "logistics": "logistics",
    "poll": "voting",
    "chat": "chat",
    "media": "media",
    "household": "costs",
    "expense": "costs",
    "transfer": "costs",
    "payment_request": "costs",
    "ratio": "costs",
    "participant": "participants",
    "api_key": "apikeys",
}
LOG_MODULE_LABELS: Final[dict[str, Any]] = {
    "planning": _l("Planning"),
    "meals": _l("Repas"),
    "lists": _l("Listes"),
    "costs": _l("Frais"),
    "voting": _l("Sondages"),
    "logistics": _l("Infos"),
    "chat": _l("Chat"),
    "media": _l("Media"),
    "participants": _l("Participants"),
    "apikeys": _l("Clés API"),
}


def label(key: str | None, kind: str) -> str:
    """Libellé traduit de ``key`` (filtre ``|label("kind")``) ; jamais la clé brute."""
    table = LABELS[kind]
    if key in table:
        return str(table[key])
    if key:
        log.warning("unknown %s key: %r", kind, key)
    default = DEFAULTS[kind]
    return str(table[default]) if default else ""


def choices(kind: str) -> list[tuple[str, str]]:
    return [(k, str(v)) for k, v in LABELS[kind].items()]


def is_valid(kind: str, key: str | None) -> bool:
    return key in LABELS[kind]


def action_label(code: str | None) -> str:
    if code in ACTION_LABELS:
        return str(ACTION_LABELS[code])
    if code:
        log.warning("unknown action code: %r", code)
    return code or ""


def action_module(code: str | None) -> str | None:
    """Module (clé de ``LOG_MODULE_LABELS``) d'un code d'action, ``None`` si inconnu."""
    return ACTION_MODULES.get((code or "").partition(".")[0])


def action_codes(module: str) -> list[str]:
    return [c for c in ACTION_LABELS if action_module(c) == module]


def describe_action(
    code: str | None, actor: str, target: str | None = None, details: str | None = None
) -> dict[str, str]:
    """Phrase lisible et traduite d'une entrée du journal (jamais le code technique).

    ``sentence`` : « Antoine a ajouté une activité : Randonnée » ; ``detail`` : ligne secondaire.
    Les valeurs (acteur, cible, détails) sont des données utilisateur : le gabarit les échappe.
    """
    template = ACTION_VARIANTS.get((code or "", details or "")) or ACTION_SENTENCES.get(code or "")
    if template is None:
        if code:
            log.warning("unknown action code: %r", code)
        sentence = gettext("%(actor)s a effectué une action", actor=actor)
    else:
        inline = label(details, "rsvp_status") if code == "rsvp.updated" else ""
        sentence = str(template) % {"actor": actor, "detail": inline}
    if target:
        sentence = gettext("%(sentence)s : %(target)s", sentence=sentence, target=target)
    shown = details if details and code not in ACTION_HIDDEN_DETAILS else ""
    return {"sentence": sentence, "detail": shown or ""}


def household_default_name(display_name: str) -> str:
    """Nom de foyer par défaut, dans la langue de la requête (donnée utilisateur ensuite)."""
    if has_request_context():
        return str(gettext("Foyer %(name)s", name=display_name))
    return f"Foyer {display_name}"  # hors requête (seed, scripts) : langue source


def current_locale() -> str:
    """Langue active (``fr`` hors requête, p. ex. tâches RQ)."""
    loc = get_locale()
    return str(loc) if loc else "fr"


def format_money(
    value: float | None, currency: str | None = BASE_CURRENCY, sign: bool = False
) -> str:
    if value is None:
        return ""
    cur = currency if currency in CURRENCIES else BASE_CURRENCY
    out = bnum.format_currency(value, cur, locale=current_locale())
    return f"+{out}" if sign and value > 0 else out


def format_number(value: float | None, decimals: int | None = None) -> str:
    if value is None:
        return ""
    if decimals is None:
        return bnum.format_decimal(value, locale=current_locale())
    pattern = "#,##0." + "0" * decimals if decimals else "#,##0"
    return bnum.format_decimal(value, format=pattern, locale=current_locale())


def format_percent(fraction: float | None) -> str:
    """``0.4`` -> ``40 %`` (fr) / ``40%`` (en)."""
    if fraction is None:
        return ""
    return bnum.format_percent(fraction, locale=current_locale())


def format_time_short(value: time | datetime | None) -> str:
    if value is None:
        return ""
    return bdates.format_time(value, "short", locale=current_locale())


def format_date_safe(value: date | datetime | None, fmt: str = "medium") -> str:
    """``format_date`` sans le piège ``None`` -> date du jour (F07)."""
    if value is None:
        return ""
    return bdates.format_date(value, format=fmt, locale=current_locale())


def format_datetime_safe(value: datetime | None, fmt: str = "medium") -> str:
    if value is None:
        return ""
    from flask_babel import format_datetime

    return str(format_datetime(value, format=fmt))


_FILE_UNITS: Final = (_l("o"), _l("Ko"), _l("Mo"), _l("Go"), _l("To"))


def format_filesize(nbytes: float | None) -> str:
    """Taille lisible (unités de 1024) ; unités traduites (o/Ko/Mo -> B/KB/MB)."""
    if nbytes is None:
        return ""
    value = float(nbytes)
    unit = 0
    while value >= 1024 and unit < len(_FILE_UNITS) - 1:
        value /= 1024
        unit += 1
    return f"{format_number(value, 0 if value >= 10 or unit == 0 else 1)} {_FILE_UNITS[unit]}"


def format_date_short(value: date | None) -> str:
    return "" if value is None else bdates.format_skeleton("dMM", value, locale=current_locale())


def format_datetime_short(value: datetime | None) -> str:
    return "" if value is None else bdates.format_datetime(value, "short", locale=current_locale())


def currency_label(code: str) -> str:
    """``EUR — euro`` / ``EUR — Euro`` selon la langue."""
    return f"{code} — {bnum.get_currency_name(code, locale=current_locale())}"


def register(app: Flask) -> None:
    filters: dict[str, Callable[..., str]] = {
        "label": label,
        "action_label": action_label,
        "money": format_money,
        "number": format_number,
        "time": format_time_short,
        "percent": format_percent,
        "filesize": format_filesize,
        "date_short": format_date_short,
        "datetime_short": format_datetime_short,
        "format_date": format_date_safe,
        "format_datetime": format_datetime_safe,
    }
    for name, fn in filters.items():
        app.add_template_filter(fn, name)
    app.add_template_global(choices, "choices")
    app.add_template_global(currency_label, "currency_label")
    app.jinja_env.globals["CURRENCIES"] = CURRENCIES
