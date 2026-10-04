"""Events blueprint - creation, invites, guest access."""

import re
from datetime import date, datetime
from typing import cast

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user
from werkzeug.wrappers import Response

from app.auth import is_disposable_email
from app.extensions import db, limiter
from app.freemium import can_add_guest, max_duration_days
from app.models import Creator, Event, Guest, Household, generate_guest_code


def _valid_email(email: str) -> bool:
    """Validate email format using email-validator."""
    from email_validator import EmailNotValidError, validate_email
    try:
        validate_email(email, check_deliverability=False)
        return True
    except EmailNotValidError:
        return False

events_bp = Blueprint("events", __name__)


# === Creator: Event Management ===

@events_bp.route("/")
@login_required  # type: ignore[untyped-decorator]
def index() -> str:
    """List creator's events."""
    events = current_user.events.filter_by(is_active=True).order_by(Event.created_at.desc()).all()
    return render_template("events/index.html", events=events)


@events_bp.route("/access", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def access_by_code() -> str | Response:
    """Access events by personal code (no login required)."""
    from app.models import Creator
    if request.method == "POST":
        code = request.form.get("code", "").strip().lower()
        if len(code) != 8:
            flash("Code invalide (8 caractères).", "danger")
            return redirect(url_for("main.index"))
        creator = Creator.query.filter_by(personal_code=code).first()
        if creator is None:
            flash("Code non reconnu.", "danger")
            return redirect(url_for("main.index"))
        login_user(creator)
        return redirect(url_for("events.index"))
    return redirect(url_for("main.index"))


@events_bp.route("/new", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def create() -> str | Response:
    """Create a new event (no login — email verification required)."""
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date")
        location = request.form.get("location", "").strip()
        email = request.form.get("email", "").strip().lower()

        errors = []
        if not title:
            errors.append("Titre requis.")
        if not start_date or not end_date:
            errors.append("Dates requises.")
        else:
            try:
                sd = datetime.strptime(start_date, "%Y-%m-%d").date()
                ed = datetime.strptime(end_date, "%Y-%m-%d").date()
            except ValueError:
                errors.append("Format de date invalide (AAAA-MM-JJ).")
            else:
                if ed < sd:
                    errors.append("Date de fin avant date de début.")
                elif (ed - sd).days + 1 > max_duration_days():
                    errors.append(f"Durée max : {max_duration_days()} jours.")
        if not email:
            errors.append("Email requis.")
        elif not _valid_email(email):
            errors.append("Format d'email invalide.")
        elif is_disposable_email(email):
            errors.append("Domaine email non accepté (jetable).")

        if errors:
            return render_template(
                "events/create.html",
                errors=errors,
                form={"title": title, "description": description,
                      "start_date": start_date, "end_date": end_date,
                      "location": location, "email": email},
            )

        # Auto-create or reuse Creator from email.
        creator = Creator.query.filter_by(email=email).first()
        if not creator:
            creator = Creator(
                email=email,
                display_name=email.split("@")[0].title(),
                personal_code=generate_guest_code(),
            )
            db.session.add(creator)
            db.session.flush()

        # Check event limit
        existing_count = Event.query.filter_by(creator_id=creator.id, is_active=True).count()
        if existing_count >= int(current_app.config["MAX_EVENTS_PER_CREATOR"]):
            flash(f"Limite d'événements atteinte ({existing_count}).", "warning")
            return redirect(url_for("events.create"))

        # Create event with verification token (unverified until link clicked).
        import secrets as _secrets
        token = _secrets.token_urlsafe(32)
        event = Event(
            title=title,
            description=description,
            start_date=datetime.strptime(cast("str", start_date), "%Y-%m-%d").date(),
            end_date=datetime.strptime(cast("str", end_date), "%Y-%m-%d").date(),
            location=location,
            creator_id=creator.id,
            creator_email=email,
            verification_token=token,
        )
        db.session.add(event)
        db.session.commit()

        # Send verification email (if SMTP configured).
        if current_app.config["SMTP_HOST"]:
            _send_verification_email(creator, event, token)

        session["creator_id"] = creator.id
        flash("Un email de vérification a été envoyé.", "success")
        return redirect(url_for("events.verify_sent", code=event.code))

    return render_template("events/create.html")


@events_bp.route("/new/sent/<code>")
def verify_sent(code: str) -> str | Response:
    """Page shown after event creation: 'check your email'."""
    event = Event.query.filter_by(code=code, is_active=True).first()
    if not event:
        abort(404)
    return render_template("events/verify_sent.html", event=event)


@events_bp.route("/verify/<token>", methods=["GET", "POST"])
def verify(token: str) -> str | Response:
    """Creator clicks the verification link: set code + nickname + invite."""
    event = Event.query.filter_by(verification_token=token, is_active=True).first()
    if not event:
        flash("Lien invalide ou expiré.", "danger")
        return redirect(url_for("main.landing"))
    if event.verified_at is not None:
        # Already verified — go to dashboard.
        session["creator_id"] = event.creator_id
        return redirect(url_for("events.dashboard", code=event.code))

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        personal_code = request.form.get("personal_code", "").strip().lower()
        invite_emails_raw = request.form.get("invite_emails", "").strip()
        store_creator_email = request.form.get("store_creator_email", "") == "1"

        errors = []
        if not display_name or len(display_name) < 2:
            errors.append("Pseudo requis (min 2 caractères).")
        if not personal_code or len(personal_code) < 4 or len(personal_code) > 8:
            errors.append("Code perso requis (4 à 8 caractères).")
        elif not re.fullmatch(r"[a-z0-9]+", personal_code):
            errors.append("Code : lettres minuscules et chiffres uniquement.")

        if errors:
            return render_template("events/verify.html", event=event, token=token, errors=errors,
                                   form_data={"display_name": display_name,
                                              "personal_code": personal_code,
                                              "invite_emails": invite_emails_raw})

        # Update creator
        creator = Creator.query.get(event.creator_id)
        if creator:
            creator.display_name = display_name
            creator.personal_code = personal_code
            # Creator email: only kept if user explicitly opts in (code recovery).
            if not store_creator_email:
                creator.email = None  # erase — code recovery not possible

        # Verify the event
        event.verified_at = datetime.utcnow()
        event.verification_token = None  # single-use
        db.session.commit()

        # Send invite emails (NOT stored unless requested)
        if invite_emails_raw and current_app.config["SMTP_HOST"]:
            invite_emails = [e.strip().lower() for e in invite_emails_raw.split(",") if e.strip()]
            for ie in invite_emails:
                if _valid_email(ie) and not is_disposable_email(ie):
                    _send_invite_email(ie, event)

        session["creator_id"] = event.creator_id
        flash("Événement confirmé !", "success")
        return redirect(url_for("events.dashboard", code=event.code))

    return render_template("events/verify.html", event=event, token=token, errors=[], form_data={})


@events_bp.route("/<code>")
def dashboard(code: str) -> str | Response:
    """Event dashboard (accessible by creator or guest with valid code)."""
    event = Event.query.filter_by(code=code, is_active=True).first()
    if not event:
        flash("Événement introuvable.", "danger")
        return redirect(url_for("events.index"))

    # Check access: creator or guest. Returning guests re-enter their own
    # personal code (my_code); new guests arrive via the invite link/QR (join).
    guest = _get_current_guest(event)
    if not guest and not (current_user.is_authenticated and current_user.id == event.creator_id):
        return redirect(url_for("events.my_code", code=code))

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


@events_bp.route("/<code>/members", methods=["GET", "POST"])
def members(code: str) -> str | Response:
    """Event members page: list all guests, creator can add/remove."""
    event = Event.query.filter_by(code=code, is_active=True).first()
    if not event:
        flash("Événement introuvable.", "danger")
        return redirect(url_for("events.index"))

    is_creator = current_user.is_authenticated and current_user.id == event.creator_id
    guest = _get_current_guest(event)
    if not guest and not is_creator:
        return redirect(url_for("events.my_code", code=code))

    if request.method == "POST" and is_creator:
        action = request.form.get("action", "")
        if action == "add":
            display_name = request.form.get("display_name", "").strip()
            email = request.form.get("email", "").strip().lower() or None
            errors = []
            if not display_name or len(display_name) < 2:
                errors.append("Nom requis (min 2 caractères).")
            if email and not _valid_email(email):
                errors.append("Format d'email invalide.")
            if email and is_disposable_email(email):
                errors.append("Domaine email non accepté.")
            if not can_add_guest(event):
                errors.append("Limite d'invités atteinte.")
            if errors:
                for e in errors:
                    flash(e, "danger")
            else:
                new_code = generate_guest_code()
                member = Guest(
                    code=new_code,
                    display_name=display_name,
                    email=email,
                    event_id=event.id,
                )
                db.session.add(member)
                db.session.commit()
                flash(f"{display_name} ajouté·e (code : {new_code})", "success")
                return redirect(url_for("events.members", code=code))
        elif action == "remove":
            guest_id = request.form.get("guest_id", "")
            target = Guest.query.filter_by(id=guest_id, event_id=event.id).first()
            if target:
                target.is_active = False
                db.session.commit()
                flash(f"{target.display_name} retiré·e.", "success")
            return redirect(url_for("events.members", code=code))

    all_guests = Guest.query.filter_by(event_id=event.id, is_active=True).order_by(Guest.display_name).all()
    return render_template("events/members.html", event=event, guests=all_guests, is_creator=is_creator)


@events_bp.route("/<code>/invite")
@login_required  # type: ignore[untyped-decorator]
def invite(code: str) -> str | Response:
    """Generate invite links for guests."""
    event = Event.query.filter_by(code=code, creator_id=current_user.id).first_or_404()
    if not can_add_guest(event):
        flash("Limite d'invités atteinte.", "warning")
        return redirect(url_for("events.dashboard", code=code))

    invite_url = f"{current_app.config['APP_URL']}/e/{code}/join"
    guests = Guest.query.filter_by(event_id=event.id, is_active=True)\
        .order_by(Guest.display_name.asc()).all()
    return render_template("events/invite.html", event=event, invite_url=invite_url, guests=guests)


@events_bp.route("/<code>/invite/qr")
def invite_qr(code: str) -> tuple[bytes, int, dict[str, str]]:
    """Serve a QR code (PNG) of the event invite URL, generated server-side.

    Server-side generation keeps the CSP intact (no external QR image or
    script is needed).
    """
    import io

    import qrcode

    Event.query.filter_by(code=code).first_or_404()
    invite_url = current_app.config["APP_URL"].rstrip("/") + url_for("events.guest_access", code=code)
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(invite_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue(), 200, {"Content-Type": "image/png"}


@events_bp.route("/<code>/invite/email", methods=["POST"])
@limiter.limit("20 per hour")
@login_required  # type: ignore[untyped-decorator]
def invite_email(code: str) -> Response:
    """Creator invites a person by email to create their personal code."""
    event = Event.query.filter_by(code=code, creator_id=current_user.id).first_or_404()
    email = request.form.get("email", "").strip().lower()

    if not email:
        flash("Email requis.", "danger")
    elif not _valid_email(email):
        flash("Format d'email invalide.", "danger")
    elif is_disposable_email(email):
        flash("Domaine email non accepté (jetable).", "danger")
    elif not can_add_guest(event):
        flash("Limite d'invités atteinte.", "warning")
    elif not current_app.config["SMTP_HOST"]:
        flash("Email non configuré (SMTP_HOST vide).", "warning")
    else:
        _send_guest_invite_email(event, email)
        flash(f"Invitation envoyée à {email}.", "success")

    return redirect(url_for("events.invite", code=code))


@events_bp.route("/<code>/invite/resend/<guest_id>", methods=["POST"])
@login_required  # type: ignore[untyped-decorator]
def invite_resend(code: str, guest_id: str) -> Response:
    """Creator re-sends the code-creation invitation to an existing member."""
    event = Event.query.filter_by(code=code, creator_id=current_user.id).first_or_404()
    guest = Guest.query.filter_by(id=guest_id, event_id=event.id, is_active=True).first_or_404()

    if guest.email:
        _send_guest_invite_email(event, guest.email, guest.display_name)
        flash(f"Invitation renvoyée à {guest.display_name}.", "success")
    else:
        flash("Aucun email enregistré pour cet invité.", "warning")

    return redirect(url_for("events.invite", code=code))


# === Guest Access ===

@events_bp.route("/<code>/join", methods=["GET", "POST"])
@limiter.limit("10 per 15 minutes")
def guest_access(code: str) -> str | Response:
    """Guest joins an event with display name + creates personal code."""
    event = Event.query.filter_by(code=code, is_active=True).first()
    if not event:
        flash("Événement introuvable.", "danger")
        return redirect(url_for("events.index"))

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        guest_code = request.form.get("code", "").strip().lower()
        email = request.form.get("email", "").strip().lower() or None
        num_adults_raw = request.form.get("num_adults", "1")
        num_children_raw = request.form.get("num_children", "0")

        # Field-level validation (the guest chooses their own personal code).
        errors = []
        if not display_name or len(display_name) < 2:
            errors.append("Pseudo requis (min 2 caractères).")
        if not guest_code or len(guest_code) < 4 or len(guest_code) > 8:
            errors.append("Code perso requis (4 à 8 caractères).")
        elif not re.fullmatch(r"[a-z0-9]+", guest_code):
            errors.append("Code : lettres minuscules et chiffres uniquement.")
        else:
            if Guest.query.filter_by(event_id=event.id, code=guest_code).first():
                errors.append("Code déjà utilisé.")
        if email and not _valid_email(email):
            errors.append("Format d'email invalide.")
        elif email and is_disposable_email(email):
            errors.append("Domaine email non accepté (jetable).")
        if not can_add_guest(event):
            errors.append("Événement complet.")

        # Household fields
        num_adults = 1
        num_children = 0
        try:
            num_adults = max(1, min(20, int(num_adults_raw)))
            num_children = max(0, min(20, int(num_children_raw)))
        except (ValueError, TypeError):
            pass

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "events/join.html", event=event,
                display_name=display_name, code=guest_code, email=email,
                num_adults=num_adults, num_children=num_children,
            )

        guest = Guest(
            code=guest_code,
            display_name=display_name,
            email=email,
            event_id=event.id,
        )
        db.session.add(guest)
        db.session.flush()  # get guest.id

        # Auto-create household for cost sharing
        household = Household(
            name=f"Foyer {display_name}",
            num_adults=num_adults,
            num_children=num_children,
            adult_weight=1.0,
            child_weight=0.5,
            event_id=event.id,
            guest_id=guest.id,
        )
        db.session.add(household)
        db.session.commit()

        # Store in session. The code is NOT flashed: it is the guest's own
        # choice and stays visible on the dashboard ("Ton code personnel").
        session[f"guest_{code}"] = guest.id
        return redirect(url_for("events.dashboard", code=code))

    return render_template("events/join.html", event=event)


@events_bp.route("/<code>/mycode", methods=["GET", "POST"])
@limiter.limit("10 per 15 minutes")
def my_code(code: str) -> str | Response:
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

def _get_current_guest(event: Event) -> Guest | None:
    """Get the current guest from session for this event."""
    guest_id = session.get(f"guest_{event.code}")
    if guest_id:
        return cast("Guest | None", Guest.query.filter_by(id=guest_id, event_id=event.id, is_active=True).first())
    return None


def _send_guest_invite_email(event: Event, email: str, display_name: str | None = None) -> None:
    """Send a guest the invitation to create their personal code.

    The guest chooses their own code (no code is generated or flashed); the
    email only carries a link to the join page.
    """
    import smtplib
    from email.mime.text import MIMEText

    url = f"{current_app.config['APP_URL']}/e/{event.code}/join"
    name = f" {display_name}" if display_name else ""
    msg = MIMEText(f"""Bonjour{name},

Tu es invité(e) à l'événement "{event.title}" sur holishared
({event.start_date:%d/%m/%Y} → {event.end_date:%d/%m/%Y}).

Pour rejoindre, crée ton code personnel (4 à 8 lettres/chiffres que tu
retiendras) en suivant ce lien :

{url}

Ton code te servira à te reconnecter sur un autre appareil.

— holishared
""")
    msg["Subject"] = f"Invitation : {event.title} - holishared"
    msg["From"] = current_app.config["SMTP_FROM"]
    msg["To"] = email

    with smtplib.SMTP(current_app.config["SMTP_HOST"], current_app.config["SMTP_PORT"]) as s:
        s.starttls()
        s.login(current_app.config["SMTP_USER"], current_app.config["SMTP_PASSWORD"])
        s.send_message(msg)


def _send_verification_email(creator: Creator, event: Event, token: str) -> None:
    """Send verification email with link to set code + nickname."""
    import smtplib
    from email.mime.text import MIMEText

    url = f"{current_app.config['APP_URL']}/verify/{token}"
    to_addr = event.creator_email or creator.email
    msg = MIMEText(f"""Bonjour,

Tu as créé l'événement "{event.title}" sur holishared.

Pour finaliser, clique sur ce lien (valide 3 jours) :

{url}

Tu y définiras ton code personnel et ton pseudo, et tu pourras inviter tes proches.

— holishared
""")
    msg["Subject"] = "Valide ton événement - holishared"
    msg["From"] = current_app.config["SMTP_FROM"]
    msg["To"] = to_addr

    with smtplib.SMTP(current_app.config["SMTP_HOST"], current_app.config["SMTP_PORT"]) as s:
        s.starttls()
        s.login(current_app.config["SMTP_USER"], current_app.config["SMTP_PASSWORD"])
        s.send_message(msg)


def _send_invite_email(to_addr: str, event: Event) -> None:
    """Send an invite email to a guest (email NOT stored)."""
    import smtplib
    from email.mime.text import MIMEText

    url = f"{current_app.config['APP_URL']}/e/{event.code}/join"
    location_line = f"Lieu : {event.location}\n" if event.location else ""
    body = f"""Bonjour,

Tu es invité(e) à l'événement "{event.title}" sur holishared.

Dates : {event.start_date.strftime('%d/%m/%Y')} → {event.end_date.strftime('%d/%m/%Y')}
{location_line}
Pour rejoindre, clique ici :

{url}

Tu choisiras ton pseudo et ton code personnel.

— holishared
"""
    msg = MIMEText(body)
    msg["Subject"] = f"Invitation : {event.title}"
    msg["From"] = current_app.config["SMTP_FROM"]
    msg["To"] = to_addr

    with smtplib.SMTP(current_app.config["SMTP_HOST"], current_app.config["SMTP_PORT"]) as s:
        s.starttls()
        s.login(current_app.config["SMTP_USER"], current_app.config["SMTP_PASSWORD"])
        s.send_message(msg)


@events_bp.route("/<code>/log")
def log(code: str) -> str | Response | tuple[str, int]:
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


@events_bp.route("/recover", methods=["GET", "POST"])
@limiter.limit("5 per 15 minutes")
def recover_code() -> str | Response:
    """Recover personal code via stored email."""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email or not _valid_email(email):
            flash("Email invalide.", "danger")
            return render_template("events/recover.html")

        creator = Creator.query.filter_by(email=email).first()
        if not creator or not creator.personal_code:
            flash("Aucun compte trouvé avec cet email. Si tu n'avais pas coché 'conserver mon email', le code est perdu.", "danger")
            return render_template("events/recover.html")

        # Send recovery email with the code
        if current_app.config["SMTP_HOST"]:
            import smtplib
            from email.mime.text import MIMEText
            msg = MIMEText(f"""Bonjour,

Ton code personnel holishared est : {creator.personal_code}

Pseudo : {creator.display_name}

— holishared
""")
            msg["Subject"] = "Ton code holishared"
            msg["From"] = current_app.config["SMTP_FROM"]
            msg["To"] = email
            with smtplib.SMTP(current_app.config["SMTP_HOST"], current_app.config["SMTP_PORT"]) as s:
                s.starttls()
                s.login(current_app.config["SMTP_USER"], current_app.config["SMTP_PASSWORD"])
                s.send_message(msg)
            flash("Ton code a été envoyé par email.", "success")
        else:
            # Dev mode: show code directly
            flash(f"Ton code : {creator.personal_code}", "success")

        return redirect(url_for("events.recover_code"))

    return render_template("events/recover.html")
