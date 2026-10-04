"""Events blueprint - creation, invites, guest access."""

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, current_app, session, g)
from flask_login import login_required, current_user
from datetime import date, datetime
from app.extensions import db, limiter
from app.models import Event, Guest, Creator, Activity, generate_event_code, generate_guest_code
from app.freemium import can_create_event, can_add_guest, max_duration_days
from app.auth import is_disposable_email
import secrets

events_bp = Blueprint("events", __name__)


# === Creator: Event Management ===

@events_bp.route("/")
@login_required
def index():
    """List creator's events."""
    events = current_user.events.filter_by(is_active=True).order_by(Event.created_at.desc()).all()
    return render_template("events/index.html", events=events)


@events_bp.route("/new", methods=["GET", "POST"])
@limiter.limit("10 per hour")
@login_required
def create():
    """Create a new event."""
    if not can_create_event(current_user):
        flash("Limite d'événements atteinte.", "warning")
        return redirect(url_for("events.index"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date")
        location = request.form.get("location", "").strip()
        email = request.form.get("email", "").strip().lower()

        # Validation
        errors = []
        if not title:
            errors.append("Titre requis.")
        if not start_date or not end_date:
            errors.append("Dates requises.")
        else:
            sd = datetime.strptime(start_date, "%Y-%m-%d").date()
            ed = datetime.strptime(end_date, "%Y-%m-%d").date()
            if ed < sd:
                errors.append("Date de fin avant date de début.")
            elif (ed - sd).days + 1 > max_duration_days():
                errors.append(f"Durée max : {max_duration_days()} jours.")
        if not email:
            errors.append("Email requis pour validation.")
        elif is_disposable_email(email):
            errors.append("Domaine email non accepté (jetable).")

        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            # Create or get creator
            creator = current_user
            if creator.email != email:
                # New creator account for this email
                creator = Creator.query.filter_by(email=email).first()
                if not creator:
                    creator = Creator(email=email, email_verified=False)
                    db.session.add(creator)

            # Create event
            event = Event(
                title=title,
                description=description,
                start_date=datetime.strptime(start_date, "%Y-%m-%d").date(),
                end_date=datetime.strptime(end_date, "%Y-%m-%d").date(),
                location=location,
                creator_id=creator.id,
            )
            db.session.add(event)
            db.session.commit()

            # Send verification email (if SMTP configured)
            if current_app.config["SMTP_HOST"]:
                _send_verification_email(creator, event)
            else:
                # Dev mode: auto-verify
                creator.email_verified = True
                db.session.commit()
                flash("Mode dev : compte auto-validé.", "info")

            flash(f"Événement créé : {event.code}", "success")
            return redirect(url_for("events.dashboard", code=event.code))

    return render_template("events/create.html")


@events_bp.route("/<code>")
def dashboard(code):
    """Event dashboard (accessible by creator or guest with valid code)."""
    event = Event.query.filter_by(code=code, is_active=True).first()
    if not event:
        flash("Événement introuvable.", "danger")
        return redirect(url_for("events.index"))

    # Check access: creator or guest
    guest = _get_current_guest(event)
    if not guest and not (current_user.is_authenticated and current_user.id == event.creator_id):
        return redirect(url_for("events.guest_access", code=code))

    # Load data
    activities = event.activities.filter_by(date=date.today()).all()
    lists = event.lists.all()
    polls = event.polls.filter_by(is_closed=False).all()

    from flask_babel import _ as _tr
    from app.logistics import CATEGORY_LABELS
    from app.models import LogisticsItem

    logistics_items = (
        LogisticsItem.query.filter_by(event_id=event.id)
        .order_by(LogisticsItem.category.asc(), LogisticsItem.order.asc())
        .all()
    )
    category_labels = {k: _tr(v) for k, v in CATEGORY_LABELS.items()}

    return render_template("events/dashboard.html",
                           event=event, guest=guest,
                           activities=activities, lists=lists, polls=polls,
                           logistics_items=logistics_items,
                           category_labels=category_labels)


@events_bp.route("/<code>/invite")
@login_required
def invite(code):
    """Generate invite links for guests."""
    event = Event.query.filter_by(code=code, creator_id=current_user.id).first_or_404()
    if not can_add_guest(event):
        flash("Limite d'invités atteinte.", "warning")
        return redirect(url_for("events.dashboard", code=code))

    invite_url = f"{current_app.config['APP_URL']}/e/{code}/join"
    return render_template("events/invite.html", event=event, invite_url=invite_url)


# === Guest Access ===

@events_bp.route("/<code>/join", methods=["GET", "POST"])
def guest_access(code):
    """Guest joins an event with display name + creates personal code."""
    event = Event.query.filter_by(code=code, is_active=True).first()
    if not event:
        flash("Événement introuvable.", "danger")
        return redirect(url_for("events.index"))

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        if not display_name or len(display_name) < 2:
            flash("Nom d'affichage requis (min 2 caractères).", "danger")
            return render_template("events/join.html", event=event)

        if not can_add_guest(event):
            flash("Événement complet.", "danger")
            return render_template("events/join.html", event=event)

        # Create guest
        guest_code = generate_guest_code()
        guest = Guest(
            code=guest_code,
            display_name=display_name,
            event_id=event.id,
        )
        db.session.add(guest)
        db.session.commit()

        # Store in session
        session[f"guest_{code}"] = guest.id

        flash(f"Ton code perso : {guest_code}", "success")
        return redirect(url_for("events.dashboard", code=code))

    return render_template("events/join.html", event=event)


@events_bp.route("/<code>/mycode", methods=["GET", "POST"])
def my_code(code):
    """Guest enters their personal code to access the event."""
    event = Event.query.filter_by(code=code, is_active=True).first()
    if not event:
        flash("Événement introuvable.", "danger")
        return redirect(url_for("events.index"))

    if request.method == "POST":
        guest_code = request.form.get("guest_code", "").strip().lower()
        guest = Guest.query.filter_by(event_id=event.id, code=guest_code, is_active=True).first()
        if guest:
            session[f"guest_{code}"] = guest.id
            return redirect(url_for("events.dashboard", code=code))
        flash("Code invalide.", "danger")

    return render_template("events/mycode.html", event=event)


# === Helpers ===

def _get_current_guest(event):
    """Get the current guest from session for this event."""
    guest_id = session.get(f"guest_{event.code}")
    if guest_id:
        return Guest.query.filter_by(id=guest_id, event_id=event.id, is_active=True).first()
    return None


def _send_verification_email(creator, event):
    """Send verification email to creator."""
    import smtplib
    from email.mime.text import MIMEText

    url = f"{current_app.config['APP_URL']}/e/{event.code}/verify/{creator.verification_token}"
    msg = MIMEText(f"""Bonjour,

Tu as créé l'événement "{event.title}" sur holishared.
Valide ton compte pour activer l'événement :

{url}

— holishared
""")
    msg["Subject"] = "Valide ton événement - holishared"
    msg["From"] = current_app.config["SMTP_FROM"]
    msg["To"] = creator.email

    with smtplib.SMTP(current_app.config["SMTP_HOST"], current_app.config["SMTP_PORT"]) as s:
        s.starttls()
        s.login(current_app.config["SMTP_USER"], current_app.config["SMTP_PASSWORD"])
        s.send_message(msg)


@events_bp.route("/<code>/verify/<token>")
def verify(code, token):
    """Verify creator email via token."""
    event = Event.query.filter_by(code=code).first_or_404()
    creator = Creator.query.get(event.creator_id)
    if creator and creator.verification_token == token:
        creator.email_verified = True
        db.session.commit()
        flash("Compte validé !", "success")
    else:
        flash("Lien de validation invalide ou expiré.", "danger")
    return redirect(url_for("events.dashboard", code=code))


@events_bp.route("/<code>/log")
def log(code):
    """Activity log for an event (traceability)."""
    from app.models import ActivityLog
    event = Event.query.filter_by(code=code, is_active=True).first()
    if not event:
        return "Not found", 404

    guest = _get_current_guest(event)
    if not guest and not (current_user.is_authenticated and current_user.id == event.creator_id):
        return redirect(url_for("events.guest_access", code=code))

    logs = ActivityLog.query.filter_by(event_id=event.id).order_by(ActivityLog.created_at.desc()).limit(100).all()
    return render_template("events/log.html", event=event, logs=logs)
