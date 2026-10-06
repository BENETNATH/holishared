"""Holishared - App factory."""

import os
import shutil
import time
from datetime import date, datetime
from pathlib import Path
from typing import cast

from dotenv import load_dotenv
from flask import Flask, jsonify, request, session
from werkzeug.wrappers import Response

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env", override=False)


def create_app() -> Flask:
    app = Flask(__name__, instance_path=os.environ.get("INSTANCE_PATH") or None)

    # Core config
    secret_key = os.environ.get("SECRET_KEY", "")
    if not secret_key or secret_key == "dev":
        raise RuntimeError(
            "SECRET_KEY must be set to a strong random value (>= 32 chars). "
            "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
        )
    app.config["SECRET_KEY"] = secret_key
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "true") == "true"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = int(
        os.environ.get("PERMANENT_SESSION_LIFETIME", "86400")
    )
    # Resolve relative SQLite paths against the project root so the DB
    # file always lands in <project>/instance/ regardless of cwd.
    db_uri = os.environ.get("DATABASE_URL", "sqlite:///instance/holishared.db")
    if db_uri == "sqlite:///:memory:":
        pass  # in-memory DB, no path resolution needed
    elif db_uri.startswith("sqlite:///") and not db_uri.startswith("sqlite:////"):
        rel_path = db_uri[len("sqlite:///"):]
        abs_path = BASE_DIR / rel_path
        db_uri = f"sqlite:///{abs_path}"
    app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # App identity
    app.config["APP_DOMAIN"] = os.environ.get("APP_DOMAIN", "localhost")
    app.config["APP_URL"] = os.environ.get("APP_URL", "http://localhost:8400")

    # Superadmin
    app.config["SUPERADMIN_EMAIL"] = os.environ.get("SUPERADMIN_EMAIL", "admin@example.com")
    superadmin_pw = os.environ.get("SUPERADMIN_PASSWORD", "")
    if not superadmin_pw or superadmin_pw == "change":
        raise RuntimeError(
            "SUPERADMIN_PASSWORD must be set to a strong value. "
            "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(16))'"
        )
    app.config["SUPERADMIN_PASSWORD"] = superadmin_pw

    # Freemium limits
    app.config["SW_ENABLED"] = os.environ.get("SW_ENABLED", "true") == "true"
    app.config["UI_CATALOG_ENABLED"] = os.environ.get("UI_CATALOG_ENABLED", "false") == "true"
    app.config["MAX_GUESTS_PER_EVENT"] = int(os.environ.get("MAX_GUESTS_PER_EVENT", "10"))
    app.config["MAX_DURATION_DAYS"] = int(os.environ.get("MAX_DURATION_DAYS", "30"))
    app.config["MAX_EVENTS_PER_CREATOR"] = int(os.environ.get("MAX_EVENTS_PER_CREATOR", "3"))
    app.config["ENABLED_MODULES"] = os.environ.get(
        "ENABLED_MODULES", "planning,meals,lists,logistics,voting,media,chat,costs"
    ).split(",")

    # Anti-abus
    app.config["RATE_LIMIT_CREATE"] = os.environ.get("RATE_LIMIT_CREATE", "5/hour")
    app.config["BLOCKED_EMAIL_DOMAINS"] = os.environ.get("BLOCKED_EMAIL_DOMAINS", "").split(",")

    # Redis (rate limiter + RQ)
    app.config["REDIS_URL"] = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

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
    from werkzeug.middleware.proxy_fix import ProxyFix

    from app.extensions import babel, db, limiter, login_manager

    # Behind a reverse proxy (nginx, Caddy, etc.): trust the first hop so
    # request.remote_addr reflects the real client IP (X-Forwarded-For).
    # NOTE: ProxyFix trusts XFF unconditionally. This is safe because:
    #   - Docker: app port is only `expose`d (not published), unreachable externally
    #   - Dev: manage.py run binds 127.0.0.1 only
    # If the app is ever directly reachable, add a trusted-proxy filter.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    login_manager.init_app(app)
    CSRFProtect(app)
    limiter.init_app(app)

    # Ensure database tables exist (idempotent; no-op if already created).
    # Import models first so SQLAlchemy knows about all tables.
    from app import models as _models  # noqa: F401
    # SQLite: enable WAL mode + busy timeout for concurrent access.
    with app.app_context():
        if db_uri.startswith("sqlite"):
            from sqlalchemy import event as sa_event

            @sa_event.listens_for(db.engine, "connect")
            def _set_sqlite_pragma(dbapi_conn, _record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.close()
        db.create_all()

    # Auto-purge: delete events ended >30d ago OR unverified >3d ago.
    from datetime import timedelta

    from app.models import Event as _Event

    def _purge_expired_events() -> None:
        from app.migrations import prune_backups

        prune_backups(app.instance_path)
        now = datetime.utcnow()
        # 1. Ended events: 30 days after end_date
        cutoff_ended = date.today() - timedelta(days=30)
        expired_ended = _Event.query.filter(
            _Event.end_date.isnot(None),
            _Event.end_date < cutoff_ended,
            _Event.is_active == True,  # noqa: E712
        ).all()
        # 2. Unverified events: 3 days after creation
        cutoff_unverified = now - timedelta(days=3)
        expired_unverified = _Event.query.filter(
            _Event.verified_at.is_(None),
            _Event.created_at < cutoff_unverified,
            _Event.is_active == True,  # noqa: E712
        ).all()
        to_delete = {ev.id for ev in expired_ended} | {ev.id for ev in expired_unverified}
        for ev in expired_ended + expired_unverified:
            if ev.id in to_delete:
                db.session.delete(ev)
                to_delete.discard(ev.id)
        if expired_ended or expired_unverified:
            db.session.commit()

    with app.app_context():
        try:
            if os.environ.get("SKIP_STARTUP_MIGRATION") != "1":
                from app.migrations import run_meals_migration

                run_meals_migration(app)  # avant la purge : elle charge les repas en cascade
            _purge_expired_events()
            if os.environ.get("SKIP_STARTUP_MIGRATION") != "1":
                from app.migrations import run_identity_migration

                run_identity_migration(app)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Auto-purge/migration failed (continuing)")

    # Language selector. A ?lang= switch is persisted in the session so the
    # preference survives navigation; otherwise fall back to the browser
    # Accept-Language, then the default.
    def get_locale() -> str:
        supported = app.config["BABEL_SUPPORTED_LOCALES"]
        chosen = request.args.get("lang")
        if chosen is not None and chosen in supported:
            session["lang"] = chosen
            return chosen
        lang = session.get("lang")
        if lang in supported:
            return cast("str", lang)
        return (
            request.accept_languages.best_match(supported)
            or cast("str", app.config["BABEL_DEFAULT_LOCALE"])
        )

    babel.init_app(app, locale_selector=get_locale)

    # Flask-Babel caches the resolved locale in g._flask_babel.babel_locale
    # for the duration of the request.  When the user clicks the FR/EN
    # toggle (?lang=fr / ?lang=en) we must invalidate that cache so the
    # selector is re-invoked with the new argument.
    @app.before_request
    def _reset_locale_on_switch() -> None:
        if request.args.get("lang"):
            from flask import g as _g
            fb = getattr(_g, "_flask_babel", None)
            if fb is not None and hasattr(fb, "babel_locale"):
                fb.babel_locale = None

    # Libellés et formats localisés (filtres label, money, number, time, format_date…).
    from app import i18n

    i18n.register(app)

    @app.template_filter("add_days")
    def add_days_filter(value: object, days: int) -> object:
        from datetime import date as _date
        from datetime import timedelta
        if isinstance(value, _date):
            return value + timedelta(days=days)
        return value

    # Le contexte d'événement est mis en cache sur g pour UNE requête (B029).
    from app.context import reset_event_context

    app.before_request(reset_event_context)

    # Core blueprints (always registered)
    from app.auth import auth_bp
    from app.events import events_bp
    from app.main import main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/admin")
    app.register_blueprint(events_bp, url_prefix="/e")

    # Module blueprints — registered only when the module is enabled, so a
    # disabled (e.g. premium) module returns 404 instead of exposing a
    # half-wired route, and the nav links stay consistent with ENABLED_MODULES.
    from app.chat import chat_bp
    from app.costs import costs_bp
    from app.lists import lists_bp
    from app.logistics import logistics_bp
    from app.meals import meals_bp
    from app.media import media_bp
    from app.planning import planning_bp
    from app.voting import voting_bp

    module_blueprints = {
        "planning": planning_bp,
        "meals": meals_bp,
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

    from app.ui import init_ui

    init_ui(app)

    # Context processor — aucune requête : réutilise le contexte chargé par la vue (B029).
    @app.context_processor
    def inject_globals() -> dict[str, object]:
        from flask_babel import get_locale as _get_locale

        from app.context import get_event_context

        loc = _get_locale()
        ctx = get_event_context()
        participant = ctx.participant if ctx else None
        return {
            "app_name": "holishared",
            "enabled_modules": [m for m in app.config["ENABLED_MODULES"] if m in app.blueprints],
            "current_lang": loc.language if loc else None,
            "current_event": ctx.event if ctx else None,
            "current_guest": participant if (ctx and ctx.role == "guest") else None,
            "event_role": ctx.role if (ctx and ctx.role != "visitor") else None,
            "ctx": ctx,
            "current_participant": participant,
        }

    # Error handlers
    @app.errorhandler(404)
    def not_found(e: Exception) -> tuple[str, int]:
        from flask import render_template

        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(e: Exception) -> tuple[str, int]:
        from flask import render_template

        return render_template("errors/403.html"), 403

    # Security headers (B015) — applied to every response
    @app.after_request
    def security_headers(response: Response) -> Response:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # HTML pages: never serve stale content (session/lang-dependent).
        # Static assets are cached by the service worker, so exclude them.
        ctype = response.headers.get("Content-Type", "")
        if "text/html" in ctype and "/static/" not in request.path:
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "  # scripts inline : thème, import map, pages historiques (durcissement en B028)
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "font-src 'self';"
        )
        return response

    # Health check (B015) — no auth, 503 on failure
    started_at = time.monotonic()

    @app.route("/health")
    def health() -> tuple[Response, int]:
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
