"""Main blueprint - dashboard."""

from flask import Blueprint, render_template
from flask_login import login_required

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required  # type: ignore[untyped-decorator]
def dashboard() -> str:
    return render_template("main/dashboard.html")
