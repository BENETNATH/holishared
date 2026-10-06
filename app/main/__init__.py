"""Main blueprint - landing page, service worker, offline page, UI catalog."""

from flask import Blueprint, Response, render_template

from app.ui import asset_version, precache_urls

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index() -> str:
    """Landing page: create event or access by code."""
    return render_template("main/landing.html")


@main_bp.route("/sw.js")
def service_worker() -> Response:
    """Service worker served from the root so its scope covers the whole site."""
    from flask import url_for

    body = render_template(
        "sw.js",
        cache_name="holishared-" + asset_version(),
        precache=precache_urls(),
        offline_url=url_for("main.offline"),
    )
    response = Response(body, mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@main_bp.route("/offline")
def offline() -> str:
    """Standalone offline page (no session data: it is precached)."""
    return render_template("main/offline.html")
