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
from flask_babel import get_locale
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
        "general": _l("Liste"),
        "shopping": _l("Courses"),
        "packing": _l("Bagages"),
        "materials": _l("Matériel"),
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
    "list.created": _l("Liste créée"),
    "list.deleted": _l("Liste supprimée"),
    "list_item.created": _l("Article ajouté"),
    "list_item.toggled": _l("Article coché ou décoché"),
    "list_item.deleted": _l("Article supprimé"),
    "list_item.claimed": _l("Article pris en charge"),
    "list_item.unclaimed": _l("Article libéré"),
    "logistics.created": _l("Info pratique ajoutée"),
    "logistics.updated": _l("Info pratique modifiée"),
    "logistics.deleted": _l("Info pratique supprimée"),
    "poll.created": _l("Sondage créé"),
    "poll.voted": _l("Vote enregistré"),
    "poll.closed": _l("Sondage clos"),
    "chat.message": _l("Message envoyé"),
    "chat.message_deleted": _l("Message supprimé"),
    "media.uploaded": _l("Média ajouté"),
    "media.deleted": _l("Média supprimé"),
    "household.created": _l("Foyer ajouté"),
    "household.deleted": _l("Foyer supprimé"),
    "expense.created": _l("Dépense ajoutée"),
    "expense.deleted": _l("Dépense supprimée"),
    "transfer.created": _l("Transfert enregistré"),
    "transfer.deleted": _l("Transfert supprimé"),
    "payment_request.created": _l("Demande de paiement créée"),
    "payment_request.resolved": _l("Demande de paiement réglée"),
    "payment_request.deleted": _l("Demande de paiement supprimée"),
    "ratio.updated": _l("Ratio de répartition modifié"),
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
