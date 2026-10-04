"""Main blueprint - landing page."""

from flask import Blueprint, redirect, url_for
from flask_login import current_user

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index() -> str:
    """Landing: redirect logged-in users to their events, others to login."""
    if current_user.is_authenticated:
        return redirect(url_for("events.index"))
    return redirect(url_for("auth.login"))
