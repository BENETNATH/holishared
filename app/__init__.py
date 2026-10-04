"""Holishared - App factory."""

import os
import shutil
import time
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, g, jsonify, request, session

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
        "ENABLED_MODULES", "planning,lists,logistics,voting,media,chat,costs"
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
    # Compiled catalogs live in <project>/translations/<locale>/LC_MESSAGES.
    app.config["BABEL_TRANSLATION_DIRECTORIES"] = os.path.join(
        BASE_DIR, "translations"
    )

    # Extensions
    from flask_wtf import CSRFProtect

    from app.extensions import babel, db, limiter, login_manager

    db.init_app(app)
    login_manager.init_app(app)
    CSRFProtect(app)
    limiter.init_app(app)

    # Language selector. A ?lang= switch is persisted in the session so the
    # preference survives navigation; otherwise fall back to the browser
    # Accept-Language, then the default.
    def get_locale():
        supported = app.config["BABEL_SUPPORTED_LOCALES"]
        chosen = request.args.get("lang")
        if chosen in supported:
            session["lang"] = chosen
            return chosen
        if session.get("lang") in supported:
            return session["lang"]
        return (
            request.accept_languages.best_match(supported)
            or app.config["BABEL_DEFAULT_LOCALE"]
        )

    babel.init_app(app, locale_selector=get_locale)

    # Date formatting for templates
    from flask_babel import format_date as babel_format_date

    @app.template_filter("format_date")
    def format_date_filter(value, fmt="medium"):
        return babel_format_date(value, format=fmt)

    # Core blueprints (always registered)
    from app.auth import auth_bp
    from app.events import events_bp

    app.register_blueprint(auth_bp, url_prefix="/admin")
    app.register_blueprint(events_bp, url_prefix="/e")

    # Module blueprints — registered only when the module is enabled, so a
    # disabled (e.g. premium) module returns 404 instead of exposing a
    # half-wired route, and the nav links stay consistent with ENABLED_MODULES.
    from app.chat import chat_bp
    from app.costs import costs_bp
    from app.lists import lists_bp
    from app.logistics import logistics_bp
    from app.media import media_bp
    from app.planning import planning_bp
    from app.voting import voting_bp

    module_blueprints = {
        "planning": planning_bp,
        "lists": lists_bp,
        "logistics": logistics_bp,
        "voting": voting_bp,
        "media": media_bp,
        "chat": chat_bp,
        "costs": costs_bp,
    }
    for name, bp in module_blueprints.items():
        if name in app.config["ENABLED_MODULES"]:
            app.register_blueprint(bp)

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

    # Security headers (B015) — applied to every response
    @app.after_request
    def security_headers(response):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "  # Alpine.js inline
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "font-src 'self';"
        )
        return response

    # Health check (B015) — no auth, 503 on failure
    started_at = time.monotonic()

    @app.route("/health")
    def health():
        db_ok = True
        try:
            db.session.execute(db.text("SELECT 1"))
        except Exception:
            db_ok = False
        disk = shutil.disk_usage(app.instance_path)
        disk_ok = disk.used / disk.total < 0.9
        healthy = db_ok and disk_ok
        return (
            jsonify(
                {
                    "status": "ok" if healthy else "error",
                    "db": db_ok,
                    "disk": disk_ok,
                    "uptime_s": int(time.monotonic() - started_at),
                }
            ),
            200 if healthy else 503,
        )

    return app
