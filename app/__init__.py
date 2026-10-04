"""Holishared - App factory."""

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, g, request

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env", override=True)


def create_app():
    app = Flask(__name__)

    # Core config
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev")
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "false") == "true"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["PERMANENT_SESSION_LIFETIME"] = int(
        os.environ.get("PERMANENT_SESSION_LIFETIME", "86400")
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///holishared.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # App identity
    app.config["APP_DOMAIN"] = os.environ.get("APP_DOMAIN", "localhost")
    app.config["APP_URL"] = os.environ.get("APP_URL", "http://localhost:8400")

    # Superadmin
    app.config["SUPERADMIN_EMAIL"] = os.environ.get("SUPERADMIN_EMAIL", "admin@example.com")
    app.config["SUPERADMIN_PASSWORD"] = os.environ.get("SUPERADMIN_PASSWORD", "change")

    # Freemium limits
    app.config["MAX_GUESTS_PER_EVENT"] = int(os.environ.get("MAX_GUESTS_PER_EVENT", "10"))
    app.config["MAX_DURATION_DAYS"] = int(os.environ.get("MAX_DURATION_DAYS", "30"))
    app.config["MAX_EVENTS_PER_CREATOR"] = int(os.environ.get("MAX_EVENTS_PER_CREATOR", "3"))
    app.config["ENABLED_MODULES"] = os.environ.get(
        "ENABLED_MODULES", "planning,lists,logistics,voting,media,chat"
    ).split(",")

    # Anti-abus
    app.config["RATE_LIMIT_CREATE"] = os.environ.get("RATE_LIMIT_CREATE", "5/hour")
    app.config["BLOCKED_EMAIL_DOMAINS"] = os.environ.get("BLOCKED_EMAIL_DOMAINS", "").split(",")

    # Email
    app.config["SMTP_HOST"] = os.environ.get("SMTP_HOST", "")
    app.config["SMTP_PORT"] = int(os.environ.get("SMTP_PORT", "587"))
    app.config["SMTP_USER"] = os.environ.get("SMTP_USER", "")
    app.config["SMTP_PASSWORD"] = os.environ.get("SMTP_PASSWORD", "")
    app.config["SMTP_FROM"] = os.environ.get("SMTP_FROM", "holishared@localhost")

    # i18n
    app.config["BABEL_DEFAULT_LOCALE"] = os.environ.get("DEFAULT_LANGUAGE", "fr")
    app.config["BABEL_SUPPORTED_LOCALES"] = os.environ.get("SUPPORTED_LANGUAGES", "fr,en").split(
        ","
    )

    # Extensions
    from flask_wtf import CSRFProtect

    from app.extensions import babel, db, login_manager

    db.init_app(app)
    login_manager.init_app(app)
    CSRFProtect(app)

    # Language selector
    def get_locale():
        return (
            request.args.get("lang")
            or request.accept_languages.best_match(app.config["BABEL_SUPPORTED_LOCALES"])
            or app.config["BABEL_DEFAULT_LOCALE"]
        )

    babel.init_app(app, locale_selector=get_locale)

    # Date formatting for templates
    from flask_babel import format_date as babel_format_date

    @app.template_filter("format_date")
    def format_date_filter(value, fmt="medium"):
        return babel_format_date(value, format=fmt)

    # Blueprints
    from app.auth import auth_bp
    from app.events import events_bp
    from app.lists import lists_bp
    from app.logistics import logistics_bp
    from app.media import media_bp
    from app.planning import planning_bp
    from app.voting import voting_bp

    app.register_blueprint(auth_bp, url_prefix="/admin")
    app.register_blueprint(events_bp, url_prefix="/e")
    app.register_blueprint(planning_bp)
    app.register_blueprint(lists_bp)
    app.register_blueprint(logistics_bp)
    app.register_blueprint(media_bp)
    app.register_blueprint(voting_bp)

    # Context processor
    @app.context_processor
    def inject_globals():
        return {
            "app_name": "holishared",
            "enabled_modules": app.config["ENABLED_MODULES"],
            "current_lang": g.lang if hasattr(g, "lang") else None,
        }

    # Error handlers
    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template

        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(e):
        from flask import render_template

        return render_template("errors/403.html"), 403

    return app
