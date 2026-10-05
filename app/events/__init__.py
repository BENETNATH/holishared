"""Events blueprint - creation, invites, guest access."""

import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, cast

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.wrappers import Response

from app.auth import is_disposable_email
from app.extensions import db, limiter
from app.freemium import can_add_guest, max_duration_days, require_tier
from app.models import Creator, Event, Guest, Household, generate_guest_code
from app.utils import ensure_creator_guest


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

        # Auto-create or reuse Creator from email. personal_code is set later,
        # at verification (not generated here — it would be a phantom identity).
        creator = Creator.query.filter_by(email=email).first()
        if not creator:
            creator = Creator(
                email=email,
                display_name=email.split("@")[0].title(),
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

        # Send verification email (if SMTP configured); otherwise show the
        # link directly (dev mode, no SMTP).
        if current_app.config["SMTP_HOST"]:
            _send_verification_email(creator, event, token)
            flash("Un email de vérification a été envoyé.", "success")
        else:
            flash(
                "Mode dev (pas de SMTP) — clique sur le lien de vérification : "
                + url_for("events.verify", token=token, _external=True),
                "warning",
            )
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
        return redirect(url_for("main.index"))
    if event.verified_at is not None:
        # Already verified — log the creator in and go to dashboard.
        creator = Creator.query.get(event.creator_id)
        if creator:
            login_user(creator)
        return redirect(url_for("events.dashboard", code=event.code))

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        personal_code = request.form.get("personal_code", "").strip().lower()
        invite_emails_raw = request.form.get("invite_emails", "").strip()
        store_creator_email = request.form.get("store_creator_email", "") == "1"
        num_adults_raw = request.form.get("num_adults", "1")
        num_children_raw = request.form.get("num_children", "0")

        errors = []
        if not display_name or len(display_name) < 2:
            errors.append("Pseudo requis (min 2 caractères).")
        if not personal_code or len(personal_code) < 4 or len(personal_code) > 8:
            errors.append("Code perso requis (4 à 8 caractères).")
        elif not re.fullmatch(r"[a-z0-9]+", personal_code):
            errors.append("Code : lettres minuscules et chiffres uniquement.")

        # Household fields (the creator is a participant in their own event).
        try:
            num_adults = max(1, min(20, int(num_adults_raw)))
        except (ValueError, TypeError):
            num_adults = 1
        try:
            num_children = max(0, min(20, int(num_children_raw)))
        except (ValueError, TypeError):
            num_children = 0

        if errors:
            return render_template("events/verify.html", event=event, token=token, errors=errors,
                                   form_data={"display_name": display_name,
                                              "personal_code": personal_code,
                                              "invite_emails": invite_emails_raw,
                                              "num_adults": num_adults,
                                              "num_children": num_children})

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

        # The creator is a participant in their own event: give them a
        # participant identity (Guest + Household) so they can vote, RSVP,
        # and appear in the groups.
        if creator:
            ensure_creator_guest(event, creator, num_adults, num_children)

        db.session.commit()

        # Send invite emails (NOT stored unless requested)
        if invite_emails_raw and current_app.config["SMTP_HOST"]:
            invite_emails = [e.strip().lower() for e in invite_emails_raw.split(",") if e.strip()]
            for ie in invite_emails:
                if _valid_email(ie) and not is_disposable_email(ie):
                    _send_invite_email(ie, event)

        if creator:
            login_user(creator)
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

    # The creator is a participant in their own event: ensure their participant
    # identity (Guest + Household) exists so they can vote and appear in the
    # groups. Idempotent — a no-op once created (at verification).
    if current_user.is_authenticated and current_user.id == event.creator_id:
        ensure_creator_guest(event, current_user)

    # Load data
    today = date.today()
    activities = event.activities.filter_by(date=today).all()
    today_meals = event.meals.filter_by(date=today).all()
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

    # Courses status: a meal is "covered" when its ingredients are already
    # checked off in any of the event's shared lists.
    covered_meal_ids: set[str] = set()
    for lst in event.lists:
        covered_meal_ids.update(lst.covered_meals or [])

    # Build a single chronological timeline of today's meals + activities.
    # Meals have no clock time, so each slot maps to a canonical hour
    # (lunch → 12:00, dinner → 20:00); activities with no start_time sort last.
    slot_hour = {"lunch": (12, 0), "dinner": (20, 0)}
    timeline: list[dict[str, object]] = []
    for act in activities:
        timeline.append({
            "kind": "activity",
            "time": act.start_time or time(23, 59),
            "title": act.title,
            "location": act.location,
            "obj": act,
        })
    for meal in today_meals:
        h, m = slot_hour.get(meal.slot, (12, 0))
        timeline.append({
            "kind": "meal",
            "time": time(h, m),
            "title": meal.title,
            "slot": meal.slot,
            "covered": meal.id in covered_meal_ids,
            "obj": meal,
        })
    timeline.sort(key=lambda e: cast("time", e["time"]))

    return render_template("events/dashboard.html",
                           event=event, guest=guest,
                           activities=activities, today_meals=today_meals,
                           timeline=timeline,
                           covered_meal_ids=covered_meal_ids,
                           lists=lists, polls=polls,
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


def _is_event_creator(event: Event) -> bool:
    """True if the current session belongs to the event's creator."""
    return bool(current_user.is_authenticated and current_user.id == event.creator_id)


@events_bp.route("/<code>/export")
def export_event(code: str) -> Response:
    """Creator-only: download a ZIP archive of the whole event (JSON + media)."""
    import io
    import json
    import zipfile

    from app.costs import _per_expense_shares, _settlement
    from app.models import Activity, Expense, MediaItem, Poll, SharedList

    event = Event.query.filter_by(code=code, is_active=True).first()
    if not event:
        flash("Événement introuvable.", "danger")
        return redirect(url_for("events.index"))
    if not _is_event_creator(event):
        abort(403)

    guests = event.guests.all()
    households = Household.query.filter_by(event_id=event.id).all()
    expenses = Expense.query.filter_by(event_id=event.id).all()
    lists = SharedList.query.filter_by(event_id=event.id).all()
    polls = Poll.query.filter_by(event_id=event.id).all()
    activities = Activity.query.filter_by(event_id=event.id).all()

    shares, paid = _per_expense_shares(households, expenses)
    balances = {h.name: (paid[h.id] - shares[h.id]) / 100.0 for h in households}
    settlements = [
        {"from": f[0], "to": f[1], "amount": f[2] / 100.0} for f in _settlement(households, expenses, [])
    ]

    def _iso(value: Any) -> str | None:
        return value.isoformat() if value is not None else None

    data = {
        "titre": event.title,
        "lieu": event.location,
        "description": event.description,
        "date_debut": _iso(event.start_date),
        "date_fin": _iso(event.end_date),
        "invites": [
            {"nom": g.display_name, "code": g.code, "email": g.email} for g in guests
        ],
        "foyers": [
            {"nom": h.name, "adultes": h.num_adults, "enfants": h.num_children} for h in households
        ],
        "activites": [
            {
                "titre": a.title,
                "date": _iso(a.date),
                "heure": _iso(a.start_time),
                "lieu": a.location,
                "description": a.description,
            }
            for a in activities
        ],
        "depenses": [
            {
                "description": e.description,
                "montant": e.amount,
                "devise": e.currency,
                "categorie": e.category,
                "paye_par": e.paid_by.name if e.paid_by else None,
                "date": _iso(e.date),
            }
            for e in expenses
        ],
        "soldes": balances,
        "reglements": settlements,
        "listes": [
            {
                "titre": lst.title,
                "type": lst.list_type,
                "articles": [
                    {"nom": i.name, "fait": i.is_done, "assigne": i.assigned_to}
                    for i in lst.items
                ],
            }
            for lst in lists
        ],
        "sondages": [
            {"question": p.question, "ferme": p.is_closed} for p in polls
        ],
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("evenement.json", json.dumps(data, ensure_ascii=False, indent=2))
        media_dir = Path(current_app.instance_path) / "media" / event.code
        if media_dir.exists():
            for file in sorted(media_dir.iterdir()):
                if file.is_file():
                    item = MediaItem.query.filter_by(event_id=event.id, filename=file.name).first()
                    arcname = f"medias/{item.original_name}" if (item and item.original_name) else f"medias/{file.name}"
                    zf.write(file, arcname)
    buf.seek(0)

    from werkzeug.utils import secure_filename

    safe_title = secure_filename(event.title) or "evenement"
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"holishared-{safe_title}-archive.zip",
    )


@events_bp.route("/<code>/delete", methods=["POST"])
def delete_event(code: str) -> Response:
    """Creator-only: permanently delete the event (DB cascade + media on disk)."""
    import shutil

    event = Event.query.filter_by(code=code, is_active=True).first()
    if not event:
        flash("Événement introuvable.", "danger")
        return redirect(url_for("events.index"))
    if not _is_event_creator(event):
        abort(403)

    event_code = event.code
    event_title = event.title
    try:
        db.session.delete(event)
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("La suppression a échoué. Réessayez.", "danger")
        return redirect(url_for("events.dashboard", code=event_code))

    # Purge the media folder on disk.
    media_dir = Path(current_app.instance_path) / "media" / event_code
    if media_dir.exists():
        shutil.rmtree(media_dir, ignore_errors=True)

    # Clear the creator's session link to this event + log out the creator.
    session.pop(f"guest_{event_code}", None)
    if current_user.is_authenticated:
        logout_user()

    flash(f"Événement « {event_title} » et toutes ses données ont été définitivement supprimés.", "success")
    return redirect(url_for("events.index"))


@events_bp.route("/<code>/export/pdf")
@login_required  # type: ignore[untyped-decorator]
@require_tier("pro")
def export_pdf(code: str) -> Response | str:
    """Gated accountancy PDF export (pro feature).

    Free tier → soft paywall (no raw 400/403). Pro+ → a placeholder response;
    the real PDF generation is a Stripe/LemonSqueezy-locked hook.
    """
    from flask_login import current_user as _cu

    event = Event.query.filter_by(code=code, creator_id=_cu.id, is_active=True).first_or_404()
    return render_template("freemium/pdf_export.html", event=event, code=code)


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

    # Guest-cap gauge + premium state (Lot 5 freemium).
    max_guests = int(current_app.config.get("MAX_GUESTS_PER_EVENT", 10))
    from app.freemium import has_feature

    unlimited = has_feature(current_user, "unlimited_guests")
    count = len(guests)
    pct = min(100, round(count / max_guests * 100)) if max_guests else 0
    guest_gauge = {
        "count": count,
        "max": max_guests,
        "pct": pct,
        "unlimited": unlimited,
        "at_limit": (not unlimited) and count >= max_guests,
    }
    return render_template("events/invite.html", event=event, invite_url=invite_url,
                           guests=guests, guest_gauge=guest_gauge)


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


def _rq_queue():
    """Get the RQ queue (lazy import)."""
    from rq import Queue
    from redis import Redis
    return Queue("default", connection=Redis.from_url(
        current_app.config.get("REDIS_URL", "redis://localhost:6379/0")
    ))


def _smtp_cfg() -> tuple[str, int, str, str, str]:
    """(host, port, user, password, from) from app config."""
    c = current_app.config
    return c["SMTP_HOST"], c["SMTP_PORT"], c["SMTP_USER"], c["SMTP_PASSWORD"], c["SMTP_FROM"]


def _send_guest_invite_email(event: Event, email: str, display_name: str | None = None) -> None:
    """Enqueue guest invite email (RQ)."""
    from app import tasks
    join_url = f"{current_app.config['APP_URL']}/e/{event.code}/join"
    host, port, user, pw, frm = _smtp_cfg()
    _rq_queue().enqueue(
        tasks.send_guest_invite_email,
        host, port, user, pw, frm, email,
        event.title,
        f"{event.start_date:%d/%m/%Y}",
        f"{event.end_date:%d/%m/%Y}",
        join_url,
        display_name,
    )


def _send_verification_email(creator: Creator, event: Event, token: str) -> None:
    """Enqueue verification email (RQ)."""
    from app import tasks
    url = url_for("events.verify", token=token, _external=True)
    to_addr = event.creator_email or creator.email
    host, port, user, pw, frm = _smtp_cfg()
    _rq_queue().enqueue(
        tasks.send_verification_email,
        host, port, user, pw, frm, to_addr, event.title, url,
    )


def _send_invite_email(to_addr: str, event: Event) -> None:
    """Enqueue invite email (RQ)."""
    from app import tasks
    join_url = f"{current_app.config['APP_URL']}/e/{event.code}/join"
    host, port, user, pw, frm = _smtp_cfg()
    _rq_queue().enqueue(
        tasks.send_invite_email,
        host, port, user, pw, frm, to_addr,
        event.title,
        event.start_date.strftime('%d/%m/%Y'),
        event.end_date.strftime('%d/%m/%Y'),
        event.location or "",
        join_url,
    )


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

        # Send recovery email with the code (RQ)
        if current_app.config["SMTP_HOST"]:
            from app import tasks
            host, port, user, pw, frm = _smtp_cfg()
            _rq_queue().enqueue(
                tasks.send_recovery_email,
                host, port, user, pw, frm, email,
                creator.personal_code, creator.display_name,
            )
            flash("Ton code a été envoyé par email.", "success")
        else:
            # Dev mode: show code directly
            flash(f"Ton code : {creator.personal_code}", "success")

        return redirect(url_for("events.recover_code"))

    return render_template("events/recover.html")
