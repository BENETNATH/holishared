"""Main blueprint - dashboard."""

from flask import Blueprint, render_template
from flask_login import login_required

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def dashboard():
    return render_template("main/dashboard.html")


@main_bp.route("/health")
def health():
    from flask import current_app
    return {
        "status": "ok",
        "config_loaded": bool(current_app.config.get("SECRET_KEY", "") != "dev-key-change-me"),
        "superadmin_email": current_app.config.get("SUPERADMIN_EMAIL", "NOT SET"),
    }, 200
