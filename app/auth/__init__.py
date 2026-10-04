"""Auth blueprint - superadmin + creator validation."""


from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db, login_manager
from app.models import Creator

auth_bp = Blueprint("auth", __name__)

# Disposable email domains (extended)
DISPOSABLE_DOMAINS = {
    "mailinator.com", "temp-mail.com", "10minutemail.com", "guerrillamail.com",
    "yopmail.com", "throwaway.email", "getnada.com", "mailnesia.com",
    "tempmail.com", "fakeinbox.com", "sharklasers.com", "trashmail.com",
}


def is_disposable_email(email):
    """Check if email is from a disposable domain."""
    domain = email.split("@")[-1].lower()
    blocked = set(current_app.config.get("BLOCKED_EMAIL_DOMAINS", []))
    return domain in DISPOSABLE_DOMAINS or domain in blocked


@login_manager.user_loader
def load_user(user_id):
    return Creator.query.get(user_id)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("events.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if (email == current_app.config["SUPERADMIN_EMAIL"].lower()
                and password == current_app.config["SUPERADMIN_PASSWORD"]):
            # Create superadmin creator if not exists
            admin = Creator.query.filter_by(email=email).first()
            if not admin:
                admin = Creator(email=email, email_verified=True, display_name="Admin")
                db.session.add(admin)
                db.session.commit()
            login_user(admin, remember=True)
            return redirect(url_for("events.index"))
        flash("Identifiants incorrects.", "danger")
    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("events.create"))
