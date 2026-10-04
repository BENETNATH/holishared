"""Main blueprint - landing page."""

from flask import Blueprint, render_template

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index() -> str:
    """Landing page: create event or access by code."""
    return render_template("main/landing.html")
