"""Helpers Jinja du kit UI : icônes, empreintes d'assets, navigation, chaînes JS (B017)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from flask import Flask, current_app, url_for
from flask_babel import gettext as _
from markupsafe import Markup, escape

from app.icons import ICONS

PRIMARY_ORDER: Final[tuple[str, ...]] = (
    "planning",
    "meals",
    "lists",
    "costs",
    "voting",
    "logistics",
    "chat",
    "media",
)

_MODULE_ENDPOINTS: Final[dict[str, str]] = {
    "planning": "planning.index",
    "meals": "meals.index",
    "lists": "lists.index",
    "costs": "costs.index",
    "voting": "voting.index",
    "logistics": "logistics.index",
    "chat": "chat.index",
    "media": "media.gallery",
}
_MODULE_ICONS: Final[dict[str, str]] = {
    "planning": "calendar-days",
    "meals": "utensils",
    "lists": "list-checks",
    "costs": "wallet",
    "voting": "vote",
    "logistics": "info",
    "chat": "message-circle",
    "media": "image",
}
_EVENT_SECTIONS: Final[dict[str, str]] = {
    "events.dashboard": "home",
    "events.members": "participants",
    "events.invite": "invite",
    "events.invite_qr": "invite",
    "events.invite_email": "invite",
    "events.invite_resend": "invite",
    "events.log": "log",
}
BOTTOM_NAV_MODULES: Final[int] = 4


def N_(s: str) -> str:  # noqa: N802 - marqueur d'extraction pybabel, sans traduction
    return s


JS_STRINGS: Final[dict[str, str]] = {
    "copied": N_("Copié"),
    "copy_failed": N_("Copie impossible"),
    "close": N_("Fermer"),
    "cancel": N_("Annuler"),
    "confirm": N_("Confirmer"),
    "confirm_title": N_("Confirmer l'action"),
    "new_version": N_("Nouvelle version disponible"),
    "reload": N_("Recharger"),
    "show": N_("Voir"),
    "hide": N_("Masquer"),
    "loading": N_("Chargement…"),
}


def ui_strings() -> dict[str, str]:
    """Registre des chaînes JS, traduit à la requête (rendu dans #ui-strings)."""
    return {key: _(msgid) for key, msgid in JS_STRINGS.items()}


def ui_importmap() -> dict[str, dict[str, str]]:
    """Import map : un spécificateur nu `ui/<module>` par fichier, URL à empreinte."""
    folder = Path(current_app.static_folder or "", "js", "ui")
    return {
        "imports": {
            f"ui/{f.stem}": asset_url(f"js/ui/{f.name}") for f in sorted(folder.glob("*.js"))
        }
    }


@lru_cache(maxsize=256)
def _hash_file(path: str, mtime_ns: int) -> str:
    """Empreinte du contenu ; la clé inclut mtime_ns pour suivre les modifications."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:10]


def asset_hash(filename: str) -> str:
    """10 premiers caractères hex du sha256 du fichier statique."""
    path = Path(current_app.static_folder or "", filename)
    return _hash_file(str(path), path.stat().st_mtime_ns)


def asset_url(filename: str) -> str:
    """URL d'un asset statique avec empreinte (cache busting)."""
    return url_for("static", filename=filename, v=asset_hash(filename))


def icon(name: str, label: str | None = None, size: int = 20, class_: str = "") -> Markup:
    """SVG Lucide en ligne ; KeyError si le nom est inconnu."""
    body = ICONS[name]
    classes = f"ui-icon {class_}" if class_ else "ui-icon"
    if label is None:
        a11y = 'aria-hidden="true"'
    else:
        a11y = f'role="img" aria-label="{escape(label)}"'
    return Markup(  # noqa: S704 - label et classes échappés, corps issu de app.icons
        f'<svg class="{escape(classes)}" width="{size}" height="{size}" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round" {a11y} focusable="false">{body}</svg>'
    )


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    icon: str
    href: str | None  # None pour les boutons (confidentialité)
    active: bool


@dataclass(frozen=True)
class Nav:
    context: str  # "event" | "global"
    primary: list[NavItem]  # destinations de la barre du bas (sans « Plus »)
    more_modules: list[NavItem]  # modules relégués dans « Plus »
    event_items: list[NavItem]  # créateur : participants, invite, log ; invité : log
    account_items: list[NavItem]  # events, logout (créateur, contexte event) ; [] sinon
    more_active: bool  # une entrée de la feuille « Plus » est active


def nav_section(endpoint: str | None) -> str | None:
    """Clé de navigation d'un endpoint Flask (None si aucune)."""
    if endpoint is None:
        return None
    if endpoint == "main.index":
        return "landing"
    if endpoint in ("events.create", "events.verify_sent"):
        return "create"
    if endpoint == "events.index":
        return "events"
    if endpoint in _EVENT_SECTIONS:
        return _EVENT_SECTIONS[endpoint]
    blueprint = endpoint.partition(".")[0]
    return blueprint if blueprint in PRIMARY_ORDER else None


def build_nav(
    endpoint: str | None,
    enabled_modules: Sequence[str],
    event_code: str | None,
    role: str | None,
    authenticated: bool,
) -> Nav:
    """Navigation du shell pour la page courante (contexte event ou global)."""
    current = nav_section(endpoint)

    def item(key: str, label: str, icon_name: str, ep: str | None, **values: Any) -> NavItem:
        href = url_for(ep, **values) if ep else None
        return NavItem(key, label, icon_name, href, key == current)

    if not (event_code and role in ("creator", "guest")):
        primary = [
            item("landing", _("Accueil"), "house", "main.index"),
            item("create", _("Créer"), "calendar-plus", "events.create"),
        ]
        if authenticated:
            primary.append(item("events", _("Mes événements"), "calendar-range", "events.index"))
        return Nav("global", primary, [], [], [], False)

    labels = {
        "planning": _("Planning"),
        "meals": _("Repas"),
        "lists": _("Listes"),
        "costs": _("Frais"),
        "voting": _("Sondages"),
        "logistics": _("Infos"),
        "chat": _("Chat"),
        "media": _("Media"),
    }
    modules = [
        item(m, labels[m], _MODULE_ICONS[m], _MODULE_ENDPOINTS[m], code=event_code)
        for m in PRIMARY_ORDER
        if m in enabled_modules
    ]
    primary = [item("home", _("Accueil"), "house", "events.dashboard", code=event_code)]
    primary += modules[:BOTTOM_NAV_MODULES]
    more_modules = modules[BOTTOM_NAV_MODULES:]
    event_items = []
    if role == "creator":
        event_items.append(
            item("participants", _("Participants"), "users", "events.members", code=event_code)
        )
        event_items.append(
            item("invite", _("Inviter"), "user-plus", "events.invite", code=event_code)
        )
    event_items.append(item("log", _("Journal"), "scroll-text", "events.log", code=event_code))
    account_items = []
    if role == "creator":
        account_items = [
            item("events", _("Mes événements"), "calendar-range", "events.index"),
            item("logout", _("Déconnexion"), "log-out", "auth.logout"),
        ]
    more_active = any(i.active for i in more_modules + event_items + account_items)
    return Nav("event", primary, more_modules, event_items, account_items, more_active)


def init_ui(app: Flask) -> None:
    """Enregistre les globaux Jinja du kit UI."""
    app.jinja_env.globals.update(
        asset_url=asset_url,
        icon=icon,
        ui_importmap=ui_importmap,
        ui_strings=ui_strings,
        build_nav=build_nav,
    )
