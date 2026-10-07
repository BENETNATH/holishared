"""Main blueprint - landing page, service worker, offline page, UI catalog."""

from flask import Blueprint, Response, abort, current_app, render_template

from app.context import device_events
from app.forms import FormErrors
from app.icons import ICON_NAMES
from app.ui import asset_version, precache_urls

main_bp = Blueprint("main", __name__)
LANDING_EVENTS = 3  # « Vos événements » sur l'accueil ; la liste complète est sur /e/


def render_landing(errors: FormErrors | None = None, code: str = "") -> str:
    """Accueil : « Vos événements » (appareil connu), créer, ou saisir un code."""
    from app.events import event_cards

    return render_template(
        "main/landing.html",
        cards=event_cards(device_events())[:LANDING_EVENTS],
        errors=errors or FormErrors(),
        code=code,
    )


@main_bp.route("/")
def index() -> str:
    """Landing page: create event or access by code."""
    return render_landing()


@main_bp.route("/sw.js")
def service_worker() -> Response:
    """Service worker served from the root so its scope covers the whole site."""
    from flask import url_for

    body = render_template(
        "sw.js",
        cache_name="holishared-" + asset_version(),
        precache=precache_urls(),
        offline_url=url_for("main.offline"),
        push_icon=url_for("static", filename="icons/icon-192.png"),
    )
    response = Response(body, mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@main_bp.route("/offline")
def offline() -> str:
    """Standalone offline page (no session data: it is precached)."""
    return render_template("main/offline.html")


@main_bp.route("/_ui")
def ui_catalog() -> str:
    """Component catalogue, development only (UI_CATALOG_ENABLED)."""
    if not current_app.config["UI_CATALOG_ENABLED"]:
        abort(404)
    return render_template("main/ui_catalog.html", icon_names=ICON_NAMES)
