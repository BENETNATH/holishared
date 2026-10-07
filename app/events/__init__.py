"""Events blueprint - creation, invites, guest access."""

import logging
import re
from collections.abc import Iterable
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
from flask_babel import format_date, ngettext
from flask_babel import gettext as _
from flask_login import current_user, login_required, logout_user
from sqlalchemy.exc import IntegrityError
from werkzeug.wrappers import Response

from app.access import (
    EVENT_TARGET_FAILURES,
    IP_FAILURES,
    join_creation_allowed,
    log_code_login,
    mark_attempt_failed,
    normalize_code,
    resolve_event_code,
    resolve_home_code,
    start_creator_session,
    start_guest_session,
    suggest_creator_code,
    suggest_guest_code,
)
from app.auth import is_disposable_email
from app.context import EventContext, device_events, load_event_context, log_event
from app.costs import my_household, parse_household, save_my_household
from app.extensions import db, limiter
from app.forms import FormErrors
from app.freemium import can_add_guest, guest_gauge, has_feature, max_duration_days, require_tier
from app.i18n import action_module, current_locale, household_default_name
from app.main import render_landing
from app.models import (
    Activity,
    Creator,
    Event,
    Expense,
    Guest,
    Household,
    Meal,
    PaymentRequest,
    Transfer,
    generate_guest_code,
)
from app.utils import ensure_creator_guest


def _parse_date_field(errors: FormErrors, field: str, raw: str | None, missing: str) -> date | None:
    """Date ISO d'un champ de formulaire ; ajoute l'erreur du champ si absente/invalide."""
    if not raw:
        errors.add(field, missing)
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        errors.add(field, _("Format de date invalide (AAAA-MM-JJ)."))
        return None


def _valid_email(email: str) -> bool:
    """Validate email format using email-validator."""
    from email_validator import EmailNotValidError, validate_email

    try:
        validate_email(email, check_deliverability=False)
        return True
    except EmailNotValidError:
        return False


def event_status(event: Event, today: date) -> dict[str, Any]:
    """Phase de l'événement (``upcoming``/``ongoing``/``past``) avec libellés traduits."""
    total = (event.end_date - event.start_date).days + 1
    if today < event.start_date:
        n = (event.start_date - today).days
        return {
            "key": "upcoming",
            "badge": _("À venir"),
            "label": ngettext("Dans %(n)d jour", "Dans %(n)d jours", n, n=n),
            "percent": 0,
        }
    if today > event.end_date:
        return {"key": "past", "badge": _("Terminé"), "label": _("Terminé"), "percent": 100}
    day = (today - event.start_date).days + 1
    return {
        "key": "ongoing",
        "badge": _("En cours"),
        "label": _("Jour %(day)d sur %(total)d", day=day, total=total),
        "percent": day * 100 // total,
    }


events_bp = Blueprint("events", __name__)
logger = logging.getLogger(__name__)

RECENT_MESSAGES = 3
INFOS_ON_HOME = 3


# === Creator: Event Management ===


def event_cards(events: Iterable[Event]) -> list[dict[str, Any]]:
    """Cartes d'événements triées : en cours, à venir, puis terminés (B020a)."""
    today = date.today()
    cards = [
        {
            "event": e,
            "status": event_status(e, today),
            "participants": e.guests.filter_by(is_active=True).count(),
        }
        for e in events
    ]
    rank = {"ongoing": 0, "upcoming": 1, "past": 2}

    def order(card: dict[str, Any]) -> tuple[int, int]:
        key = card["status"]["key"]
        day = card["event"].start_date.toordinal()
        return rank[key], -card["event"].end_date.toordinal() if key == "past" else day

    cards.sort(key=order)
    return cards


@events_bp.route("/")
def index() -> str | Response:
    """Mes événements : ceux de l'appareil, créateur connecté ou invité (F01)."""
    events = device_events()
    if not events and not current_user.is_authenticated:
        flash(
            _(
                "Aucun événement n'est enregistré sur cet appareil. "
                "Créez un événement ou saisissez votre code."
            ),
            "info",
        )
        return redirect(url_for("main.index"))
    return render_template("events/index.html", cards=event_cards(events))


@events_bp.route("/access", methods=["GET", "POST"])
@IP_FAILURES
def access_by_code() -> str | Response:
    """Code saisi à l'accueil : code d'événement -> page d'accès, code créateur -> connexion.

    Tout échec (mal formé, inconnu, code d'invité) donne le même message : rien ne dit si le code existe.
    """
    if request.method == "POST":
        raw = request.form.get("code", "").strip()
        match = resolve_home_code(raw)
        if match is None or match.kind == "guest":
            mark_attempt_failed("home", None)
            errors = FormErrors()
            errors.add(
                "code",
                _("Ce code n'est pas valable. Vérifiez-le, ou utilisez « J'ai oublié mon code »."),
            )
            return render_landing(errors, raw[:64])
        if match.creator is not None:
            start_creator_session(match.creator)
            log_code_login("creator", None)
            return redirect(url_for("events.index"))
        return redirect(url_for("events.my_code", code=cast("Event", match.event).code))
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

        errors = FormErrors()
        if not title:
            errors.add("title", _("Titre requis."))
        sd = _parse_date_field(errors, "start_date", start_date, _("Date de début requise."))
        ed = _parse_date_field(errors, "end_date", end_date, _("Date de fin requise."))
        if sd and ed:
            if ed < sd:
                errors.add("end_date", _("Date de fin avant date de début."))
            elif (ed - sd).days + 1 > max_duration_days():
                days = max_duration_days()
                errors.add(
                    "end_date",
                    ngettext("Durée max : %(n)d jour.", "Durée max : %(n)d jours.", days, n=days),
                )
        if not email:
            errors.add("email", _("Email requis."))
        elif not _valid_email(email):
            errors.add("email", _("Format d'email invalide."))
        elif is_disposable_email(email):
            errors.add("email", _("Domaine email non accepté (jetable)."))

        if errors:
            return render_template(
                "events/create.html",
                errors=errors,
                max_days=max_duration_days(),
                form={
                    "title": title,
                    "description": description,
                    "start_date": start_date,
                    "end_date": end_date,
                    "location": location,
                    "email": email,
                },
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
            db.session.rollback()
            errors.add_global(_("Limite d'événements atteinte (%(count)d).", count=existing_count))
            return render_template(
                "events/create.html",
                errors=errors,
                max_days=max_duration_days(),
                form={
                    "title": title,
                    "description": description,
                    "start_date": start_date,
                    "end_date": end_date,
                    "location": location,
                    "email": email,
                },
            )

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

        # E-mail de vérification. Sans SMTP, le lien n'est montré que si DEV_SHOW_SECRETS
        # (dev/staging) l'autorise : jamais de secret affiché par défaut (F16).
        if current_app.config["SMTP_HOST"]:
            _send_verification_email(creator, event, token)
        elif current_app.config["DEV_SHOW_SECRETS"]:
            flash(
                _(
                    "Mode développement (SMTP non configuré) : cliquez sur le lien de vérification : %(url)s",
                    url=url_for("events.verify", token=token, _external=True),
                ),
                "warning",
            )
        else:
            logger.warning("verification_mail_not_sent smtp=unconfigured event=%s", event.code)
        session[f"pending_{event.code}"] = True  # ce navigateur peut demander un renvoi
        return redirect(url_for("events.verify_sent", code=event.code))

    return render_template("events/create.html", errors=FormErrors(), max_days=max_duration_days())


def _masked_email(email: str | None) -> str:
    """``a***@domaine`` : assez pour reconnaître l'adresse, pas pour la deviner."""
    if not email or "@" not in email:
        return ""
    return f"{email[0]}***@{email.rsplit('@', 1)[-1]}"


@events_bp.route("/new/sent/<code>")
def verify_sent(code: str) -> str | Response:
    """Page shown after event creation: 'check your email'."""
    event = Event.query.filter_by(code=code, is_active=True).first()
    if not event:
        abort(404)
    return render_template(
        "events/verify_sent.html",
        event=event,
        masked_email=_masked_email(event.creator_email),
        mail_enabled=bool(current_app.config["SMTP_HOST"]),
        can_resend=event.verified_at is None and bool(session.get(f"pending_{code}")),
    )


@events_bp.route("/new/sent/<code>/resend", methods=["POST"])
@limiter.limit("3 per hour")
def resend_verification(code: str) -> Response:
    """Renvoi du lien : réservé au navigateur qui a créé l'événement, 3 par heure."""
    event = Event.query.filter_by(code=code, is_active=True).first()
    if event is None or event.verified_at is not None or not session.get(f"pending_{code}"):
        abort(404)
    token = event.verification_token
    creator = Creator.query.get(event.creator_id)
    if token and creator is not None:
        if current_app.config["SMTP_HOST"]:
            _send_verification_email(creator, event, token)
            flash(_("L'e-mail de confirmation vient d'être renvoyé."), "success")
        elif current_app.config["DEV_SHOW_SECRETS"]:
            flash(
                _(
                    "Mode développement (SMTP non configuré) : cliquez sur le lien de vérification : %(url)s",
                    url=url_for("events.verify", token=token, _external=True),
                ),
                "warning",
            )
    return redirect(url_for("events.verify_sent", code=code))


@events_bp.route("/verify/<token>", methods=["GET", "POST"])
def verify(token: str) -> str | Response:
    """Creator clicks the verification link: set code + nickname + invite."""
    event = Event.query.filter_by(verification_token=token, is_active=True).first()
    if not event:
        flash(_("Lien invalide ou expiré."), "danger")
        return redirect(url_for("main.index"))
    if event.verified_at is not None:
        # Already verified — log the creator in and go to dashboard.
        creator = Creator.query.get(event.creator_id)
        if creator:
            start_creator_session(creator)
        return redirect(url_for("events.dashboard", code=event.code))

    creator = Creator.query.get(event.creator_id)
    has_existing_code = bool(creator and creator.personal_code)

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        personal_code = normalize_code(request.form.get("personal_code", ""))
        invite_emails_raw = request.form.get("invite_emails", "").strip()
        store_creator_email = request.form.get("store_creator_email", "") == "1"
        num_adults_raw = request.form.get("num_adults", "1")
        num_children_raw = request.form.get("num_children", "0")

        errors = FormErrors()
        if not display_name or len(display_name) < 2:
            errors.add("display_name", _("Pseudo requis (min 2 caractères)."))
        keep_code = (
            creator is not None
            and has_existing_code
            and personal_code
            in (
                "",
                creator.personal_code,
            )
        )
        if not keep_code:
            if not re.fullmatch(r"[a-z0-9]{8}", personal_code):
                errors.add(
                    "personal_code",
                    _("Le code créateur doit faire 8 caractères (lettres minuscules et chiffres)."),
                )
            elif Creator.query.filter(
                Creator.personal_code == personal_code, Creator.id != event.creator_id
            ).first():
                errors.add("personal_code", _("Ce code est déjà utilisé. Choisissez-en un autre."))

        # Household fields (the creator is a participant in their own event).
        try:
            num_adults = max(1, min(20, int(num_adults_raw)))
        except (ValueError, TypeError):
            num_adults = 1
        try:
            num_children = max(0, min(20, int(num_children_raw)))
        except (ValueError, TypeError):
            num_children = 0

        def _form_error(messages: FormErrors) -> str:
            suggestion = personal_code or ("" if has_existing_code else suggest_creator_code())
            return render_template(
                "events/verify.html",
                event=event,
                token=token,
                errors=messages,
                mail_enabled=bool(current_app.config["SMTP_HOST"]),
                has_existing_code=has_existing_code,
                form_data={
                    "display_name": display_name,
                    "personal_code": suggestion,
                    "invite_emails": invite_emails_raw,
                    "num_adults": num_adults,
                    "num_children": num_children,
                },
            )

        if errors:
            return _form_error(errors)

        # Update creator
        if creator:
            creator.display_name = display_name
            if not keep_code:
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

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            dup = FormErrors()
            dup.add("personal_code", _("Ce code est déjà utilisé. Choisissez-en un autre."))
            return _form_error(dup)

        # Send invite emails (NOT stored unless requested)
        if invite_emails_raw and current_app.config["SMTP_HOST"]:
            invite_emails = [e.strip().lower() for e in invite_emails_raw.split(",") if e.strip()]
            for ie in invite_emails:
                if _valid_email(ie) and not is_disposable_email(ie):
                    _send_invite_email(ie, event)

        if creator:
            start_creator_session(creator)
        flash(_("Événement confirmé !"), "success")
        return redirect(url_for("events.dashboard", code=event.code))

    return render_template(
        "events/verify.html",
        event=event,
        token=token,
        mail_enabled=bool(current_app.config["SMTP_HOST"]),
        errors=FormErrors(),
        has_existing_code=has_existing_code,
        form_data={} if has_existing_code else {"personal_code": suggest_creator_code()},
    )


@events_bp.route("/<code>")
def dashboard(code: str) -> str | Response:
    """Accueil de l'événement (créateur ou invité avec code valide)."""
    from app.infos import ordered_infos
    from app.lists import home_items
    from app.models import ChatMessage, ListMealCoverage, LogisticsItem, Poll, SharedList
    from app.polls import poll_views

    ctx = load_event_context(code)
    event = ctx.event
    today = date.today()
    modules = [m for m in current_app.config["ENABLED_MODULES"] if m in current_app.blueprints]

    # Courses : un repas est « couvert » quand ses ingrédients sont dans une liste.
    covered_meal_ids = {
        row[0]
        for row in db.session.query(ListMealCoverage.meal_id)
        .join(SharedList, SharedList.id == ListMealCoverage.list_id)
        .filter(SharedList.event_id == event.id)
    }

    # Chronologie du jour : activités + repas (déjeuner 12:00, dîner 20:00 ; sans heure -> fin).
    slot_hour = {"lunch": (12, 0), "dinner": (20, 0)}
    timeline: list[dict[str, object]] = []
    for act in event.activities.filter_by(date=today).filter(Activity.status != "dropped"):
        timeline.append(
            {
                "kind": "activity",
                "time": act.start_time or time(23, 59),
                "title": act.title,
                "location": act.location,
            }
        )
    for meal in event.meals.filter_by(date=today).order_by(*Meal.ordering()):
        h, m = slot_hour.get(meal.slot, (12, 0))
        timeline.append(
            {
                "kind": "meal",
                "time": time(h, m),
                "title": meal.title,
                "slot": meal.slot,
                "covered": meal.id in covered_meal_ids,
            }
        )
    timeline.sort(key=lambda e: cast("time", e["time"]))

    recent_messages = []
    if "chat" in modules:
        recent_messages = list(
            reversed(
                ChatMessage.query.filter_by(event_id=event.id)
                .order_by(ChatMessage.created_at.desc())
                .limit(RECENT_MESSAGES)
                .all()
            )
        )
    infos_total = LogisticsItem.query.filter_by(event_id=event.id).count()
    return render_template(
        "events/dashboard.html",
        event=event,
        status=event_status(event, today),
        timeline=timeline,
        polls=sorted(  # à voter en premier (tri stable : les plus récents d'abord)
            poll_views(
                event.polls.filter_by(is_closed=False)
                .order_by(Poll.created_at.desc(), Poll.id)
                .all(),
                ctx.participant,
            ),
            key=lambda view: view.has_voted,
        ),
        recent_messages=recent_messages,
        infos=ordered_infos(event.id, INFOS_ON_HOME),
        infos_total=infos_total,
        share_url=_join_url(event),
        **(home_items(ctx) if "lists" in modules else {}),
    )


def _join_url(event: Event) -> str:
    """Lien public de REJOINDRE (jamais l'URL du tableau de bord)."""
    base = str(current_app.config["APP_URL"]).rstrip("/")
    return base + url_for("events.guest_access", code=event.code)


@events_bp.route("/<code>/me", methods=["GET", "POST"])
def me(code: str) -> str | Response | tuple[str, int]:
    """Mon profil : nom d'affichage modifiable et code personnel masqué par défaut (B020)."""
    ctx = load_event_context(code)
    participant = ctx.participant
    if participant is None:  # inatteignable : load_event_context exige un participant
        abort(403)
    errors = FormErrors()
    display_name = participant.display_name
    if request.method == "POST":
        display_name = " ".join(request.form.get("display_name", "").split())
        if not 2 <= len(display_name) <= 50:
            errors.add("display_name", _("Le nom doit faire entre 2 et 50 caractères."))
        else:
            if display_name != participant.display_name:
                log_event(ctx, "participant.renamed", target=display_name)  # acteur : ancien nom
                participant.display_name = display_name
                if ctx.is_creator:
                    current_user.display_name = display_name
                db.session.commit()
            flash(_("Nom d'affichage enregistré."), "success")
            return redirect(url_for("events.me", code=code))
    return _me_page(ctx, display_name, errors)


def _me_page(
    ctx: EventContext,
    display_name: str,
    errors: FormErrors,
    hh_errors: FormErrors | None = None,
    hh_form: dict[str, Any] | None = None,
    status: int = 200,
) -> tuple[str, int]:
    participant = ctx.participant
    if participant is None:  # inatteignable : load_event_context exige un participant
        abort(403)
    personal = ctx.event.creator.personal_code if ctx.is_creator else participant.code
    return (
        render_template(
            "events/me.html",
            event=ctx.event,
            personal_code=personal,
            errors=errors,
            display_name=display_name,
            household=my_household(ctx),
            hh_errors=hh_errors or FormErrors(),
            hh_form=hh_form or {},
            default_household_name=household_default_name(participant.display_name),
        ),
        status,
    )


@events_bp.route("/<code>/me/household", methods=["POST"])
def me_household(code: str) -> str | Response | tuple[str, int]:
    """Mon foyer : nom, adultes, enfants (création si le participant n'a pas de foyer)."""
    ctx = load_event_context(code)
    if ctx.participant is None:  # inatteignable : load_event_context exige un participant
        abort(403)
    values, errors = parse_household(request.form)
    if errors:
        return _me_page(
            ctx,
            ctx.participant.display_name,
            FormErrors(),
            errors,
            {k: request.form.get(k, "") for k in ("name", "num_adults", "num_children")},
        )
    save_my_household(ctx, values)
    flash(_("Foyer enregistré."), "success")
    return redirect(url_for("events.me", code=code) + "#h-household")


@events_bp.route("/<code>/manage")
def manage(code: str) -> str:
    """Gérer l'événement (créateur) : exports et suppression définitive."""
    ctx = load_event_context(code, require="creator")
    return render_template(
        "events/manage.html",
        event=ctx.event,
        pdf_included=has_feature(ctx.event.creator, "pdf_export"),
    )


def _participants_page(
    ctx: EventContext,
    errors: FormErrors | None = None,
    form: dict[str, str] | None = None,
    status: int = 200,
) -> tuple[str, int]:
    """Page Participants (liste, jauge, invitation) ; ``errors``/``form`` rejouent un envoi refusé."""
    event = ctx.event
    guests = (
        Guest.query.filter_by(event_id=event.id, is_active=True).order_by(Guest.display_name).all()
    )
    guests.sort(key=lambda g: g.creator_id is None)  # le créateur en tête (tri stable)
    page = render_template(
        "events/members.html",
        event=event,
        guests=guests,
        households={
            h.guest_id: h for h in Household.query.filter_by(event_id=event.id) if h.guest_id
        },
        gauge=guest_gauge(event),
        join_url=_join_url(event),
        smtp_ready=bool(current_app.config["SMTP_HOST"]),
        errors=errors or FormErrors(),
        form=form or {},
    )
    return page, status


def _check_email(errors: FormErrors, field: str, email: str | None) -> None:
    if email and not _valid_email(email):
        errors.add(field, _("Format d'email invalide."))
    elif email and is_disposable_email(email):
        errors.add(field, _("Domaine email non accepté (jetable)."))


@events_bp.route("/<code>/members", methods=["GET", "POST"])
def members(code: str) -> str | Response | tuple[str, int]:
    """Participants : liste pour tous ; le créateur invite, ajoute et retire (B020)."""
    ctx = load_event_context(code)
    if request.method == "GET":
        return _participants_page(ctx)
    if not ctx.is_creator:
        abort(403)
    action = request.form.get("action", "")
    if action == "add":
        return _add_participant(ctx)
    if action == "remove":
        return _remove_participant(ctx)
    abort(400)


def _add_participant(ctx: EventContext) -> Response | tuple[str, int]:
    """Le créateur ajoute un participant : Guest, code personnel et foyer (F21)."""
    event = ctx.event
    display_name = " ".join(request.form.get("display_name", "").split())
    email = request.form.get("email", "").strip().lower() or None
    errors = FormErrors()
    if not 2 <= len(display_name) <= 50:
        errors.add("display_name", _("Le nom doit faire entre 2 et 50 caractères."))
    _check_email(errors, "email", email)
    if not can_add_guest(event):
        errors.add_global(_("Limite d'invités atteinte."))
    if errors:
        form = {"display_name": display_name, "email": email or ""}
        return _participants_page(ctx, errors, form)
    member = Guest(
        code=generate_guest_code(), display_name=display_name, email=email, event_id=event.id
    )
    db.session.add(member)
    db.session.flush()
    db.session.add(
        Household(
            name=household_default_name(display_name),
            num_adults=1,
            num_children=0,
            event_id=event.id,
            guest_id=member.id,
        )
    )
    log_event(ctx, "participant.added", target=display_name)
    db.session.commit()
    flash(_("%(name)s ajouté·e (code : %(code)s)", name=display_name, code=member.code), "success")
    return redirect(url_for("events.members", code=event.code))


def _remove_participant(ctx: EventContext) -> Response:
    """Retire un participant (désactivation). Son foyer n'est supprimé que s'il est sans effet."""
    event = ctx.event
    target = Guest.query.filter_by(id=request.form.get("guest_id", ""), event_id=event.id).first()
    if target is None or not target.is_active:
        abort(404)
    if not ctx.can_delete(target):
        abort(403)
    name = target.display_name
    household = Household.query.filter_by(guest_id=target.id, event_id=event.id).first()
    kept = None
    if household is not None:
        # Un foyer peut être cité par des dépenses (payeur, parts, répartition libre), des transferts
        # ou des demandes : on ne le supprime que si l'événement n'a aucune dépense et que le foyer
        # n'a ni transfert ni demande ; sinon il reste dans les Frais.
        linked = (
            Expense.query.filter_by(event_id=event.id).first()
            or Transfer.query.filter(
                (Transfer.from_household_id == household.id)
                | (Transfer.to_household_id == household.id)
            ).first()
            or PaymentRequest.query.filter(
                (PaymentRequest.from_household_id == household.id)
                | (PaymentRequest.to_household_id == household.id)
            ).first()
        )
        if linked is None:
            db.session.delete(household)
        else:
            kept = household.name
    target.is_active = False
    log_event(ctx, "participant.removed", target=name)
    db.session.commit()
    if kept:
        flash(
            _(
                "%(name)s retiré·e. Son foyer « %(household)s » reste dans les Frais.",
                name=name,
                household=kept,
            ),
            "success",
        )
    else:
        flash(_("%(name)s retiré·e.", name=name), "success")
    return redirect(url_for("events.members", code=event.code))


@events_bp.route("/<code>/export")
def export_event(code: str) -> Response:
    """Creator-only: download a ZIP archive of the whole event (JSON + media)."""
    import io
    import json
    import zipfile

    from app.costs import _per_expense_shares, _settlement
    from app.models import (
        Activity,
        Expense,
        ListActivityCoverage,
        ListMealCoverage,
        MediaItem,
        Poll,
        SharedList,
    )

    ctx = load_event_context(code, require="creator")
    event = ctx.event

    guests = event.guests.all()
    households = Household.query.filter_by(event_id=event.id).all()
    # Une dépense personnelle n'est visible que des membres du foyer payeur (B024), créateur compris.
    expenses = [
        e
        for e in Expense.query.filter_by(event_id=event.id).all()
        if e.is_shared
        or (
            ctx.participant is not None
            and e.paid_by is not None
            and e.paid_by.guest_id == ctx.participant.id
        )
    ]
    lists = SharedList.query.filter_by(event_id=event.id).all()
    polls = Poll.query.filter_by(event_id=event.id).all()
    activities = Activity.query.filter_by(event_id=event.id).all()

    shares, paid = _per_expense_shares(households, expenses)
    balances = {h.name: (paid[h.id] - shares[h.id]) / 100.0 for h in households}
    settlements = [
        {"from": f[0], "to": f[1], "amount": f[2] / 100.0}
        for f in _settlement(households, expenses, [])
    ]

    def _iso(value: Any) -> str | None:
        return value.isoformat() if value is not None else None

    data = {
        "titre": event.title,
        "lieu": event.location,
        "description": event.description,
        "date_debut": _iso(event.start_date),
        "date_fin": _iso(event.end_date),
        "invites": [{"nom": g.display_name, "code": g.code, "email": g.email} for g in guests],
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
                    {"nom": i.name, "fait": i.is_done, "assigne": i.assigned_to} for i in lst.items
                ],
                "repas_pris_en_compte": [
                    m.title
                    for m in Meal.query.join(
                        ListMealCoverage, ListMealCoverage.meal_id == Meal.id
                    ).filter(ListMealCoverage.list_id == lst.id)
                ],
                "activites_pris_en_compte": [
                    a.title
                    for a in Activity.query.join(
                        ListActivityCoverage, ListActivityCoverage.activity_id == Activity.id
                    ).filter(ListActivityCoverage.list_id == lst.id)
                ],
            }
            for lst in lists
        ],
        "sondages": [{"question": p.question, "ferme": p.is_closed} for p in polls],
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("evenement.json", json.dumps(data, ensure_ascii=False, indent=2))
        media_dir = Path(current_app.instance_path) / "media" / event.code
        if media_dir.exists():
            for file in sorted(media_dir.iterdir()):
                if file.is_file():
                    item = MediaItem.query.filter_by(event_id=event.id, filename=file.name).first()
                    arcname = (
                        f"medias/{item.original_name}"
                        if (item and item.original_name)
                        else f"medias/{file.name}"
                    )
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

    event = load_event_context(code, require="creator").event

    event_code = event.code
    event_title = event.title
    try:
        db.session.delete(event)
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash(_("La suppression a échoué. Réessayez."), "danger")
        return redirect(url_for("events.dashboard", code=event_code))

    # Purge the media folder on disk.
    media_dir = Path(current_app.instance_path) / "media" / event_code
    if media_dir.exists():
        shutil.rmtree(media_dir, ignore_errors=True)

    # Clear the creator's session link to this event + log out the creator.
    session.pop(f"guest_{event_code}", None)
    if current_user.is_authenticated:
        logout_user()

    flash(
        _(
            "Événement « %(title)s » et toutes ses données ont été définitivement supprimés.",
            title=event_title,
        ),
        "success",
    )
    return redirect(url_for("events.index"))


@events_bp.route("/<code>/export/pdf")
@login_required  # type: ignore[untyped-decorator]
@require_tier("pro")
def export_pdf(code: str) -> Response | str:
    """Gated accountancy PDF export (pro feature).

    Free tier → soft paywall (no raw 400/403). Pro+ → a placeholder response;
    the real PDF generation is a Stripe/LemonSqueezy-locked hook.
    """
    event = load_event_context(code, require="creator").event
    return render_template("freemium/pdf_export.html", event=event, code=code)


@events_bp.route("/<code>/invite")
def invite(code: str) -> Response:
    """Ancienne page « Invitations » : fusionnée dans Participants (B020)."""
    load_event_context(code, require="creator")
    return redirect(url_for("events.members", code=code, _anchor="invite"))


@events_bp.route("/<code>/invite/qr")
def invite_qr(code: str) -> tuple[bytes, int, dict[str, str]]:
    """Serve a QR code (PNG) of the event invite URL, generated server-side.

    Server-side generation keeps the CSP intact (no external QR image or
    script is needed).
    """
    import io

    import qrcode

    load_event_context(code, require="none")
    invite_url = current_app.config["APP_URL"].rstrip("/") + url_for(
        "events.guest_access", code=code
    )
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
def invite_email(code: str) -> Response | tuple[str, int]:
    """Le créateur invite une personne par e-mail ; erreurs par champ, état honnête sans SMTP."""
    ctx = load_event_context(code, require="creator")
    event = ctx.event
    if not current_app.config["SMTP_HOST"]:  # le formulaire n'est pas proposé : état honnête
        flash(_("L'envoi d'emails n'est pas configuré sur ce serveur."), "warning")
        return redirect(url_for("events.members", code=code, _anchor="invite"))
    email = request.form.get("email", "").strip().lower()
    errors = FormErrors()
    if not email:
        errors.add("invite_email", _("Email requis."))
    else:
        _check_email(errors, "invite_email", email)
    if errors:
        return _participants_page(ctx, errors, {"invite_email": email})
    if not can_add_guest(event):
        flash(_("Limite d'invités atteinte."), "warning")
    else:
        _send_guest_invite_email(event, email)
        flash(_("Invitation envoyée à %(email)s.", email=email), "success")
    return redirect(url_for("events.members", code=code, _anchor="invite"))


@events_bp.route("/<code>/invite/resend/<guest_id>", methods=["POST"])
def invite_resend(code: str, guest_id: str) -> Response:
    """Le créateur renvoie l'invitation à un participant qui a une adresse e-mail."""
    event = load_event_context(code, require="creator").event
    guest = Guest.query.filter_by(id=guest_id, event_id=event.id, is_active=True).first_or_404()
    if not guest.email:
        flash(_("Aucun email enregistré pour cet invité."), "warning")
    elif not current_app.config["SMTP_HOST"]:
        flash(_("L'envoi d'emails n'est pas configuré sur ce serveur."), "warning")
    else:
        _send_guest_invite_email(event, guest.email, guest.display_name)
        flash(_("Invitation renvoyée à %(name)s.", name=guest.display_name), "success")
    return redirect(url_for("events.members", code=code))


# === Guest Access ===


@events_bp.route("/<code>/join", methods=["GET", "POST"])
@IP_FAILURES
@EVENT_TARGET_FAILURES
def guest_access(code: str) -> str | Response | tuple[str, int]:
    """Guest joins an event with display name + creates personal code."""
    ctx = load_event_context(code, require="none")
    event = ctx.event
    if ctx.participant is not None:
        return redirect(url_for("events.dashboard", code=code))

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        guest_code = request.form.get("code", "").strip().lower()
        email = request.form.get("email", "").strip().lower() or None
        num_adults_raw = request.form.get("num_adults", "1")
        num_children_raw = request.form.get("num_children", "0")

        # Field-level validation (the guest chooses their own personal code).
        errors = FormErrors()
        code_refused = False
        too_many = False
        if not display_name or len(display_name) < 2:
            errors.add("display_name", _("Pseudo requis (min 2 caractères)."))
        if not guest_code or len(guest_code) < 4 or len(guest_code) > 8:
            errors.add("code", _("Code perso requis (4 à 8 caractères)."))
        elif not re.fullmatch(r"[a-z0-9]+", guest_code):
            errors.add("code", _("Code : lettres minuscules et chiffres uniquement."))
        if email and not _valid_email(email):
            errors.add("email", _("Format d'email invalide."))
        elif email and is_disposable_email(email):
            errors.add("email", _("Domaine email non accepté (jetable)."))
        if not can_add_guest(event):
            errors.add_global(_("Événement complet."))

        # L'unicité du code n'est testée qu'une fois tout le reste valide : sinon un code
        # libre/pris se devine sans consommer de quota (oracle de codes, audit #1).
        if not errors and (
            Guest.query.filter_by(event_id=event.id, code=guest_code).first()
            or event.creator.personal_code == guest_code
        ):
            errors.add("code", _("Code déjà utilisé."))
            code_refused = True
        if not errors and not join_creation_allowed():
            errors.add_global(_("Trop d'inscriptions depuis votre connexion. Réessayez plus tard."))
            too_many = True

        # Household fields
        num_adults = 1
        num_children = 0
        try:
            num_adults = max(1, min(20, int(num_adults_raw)))
            num_children = max(0, min(20, int(num_children_raw)))
        except (ValueError, TypeError):
            pass

        if errors:
            if code_refused:
                mark_attempt_failed("join", code)
            page = render_template(
                "events/join.html",
                event=event,
                errors=errors,
                display_name=display_name,
                code=guest_code or suggest_guest_code(event),
                email=email,
                num_adults=num_adults,
                num_children=num_children,
            )
            return page, 429 if too_many else 200

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
            name=household_default_name(display_name),
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
        # choice and stays visible on the dashboard ("Votre code personnel").
        start_guest_session(code, guest)
        return redirect(url_for("events.dashboard", code=code))

    return render_template(
        "events/join.html", event=event, errors=FormErrors(), code=suggest_guest_code(event)
    )


@events_bp.route("/<code>/mycode", methods=["GET", "POST"])
@IP_FAILURES
@EVENT_TARGET_FAILURES
def my_code(code: str) -> str | Response:
    """Guest (or the event's creator) enters their personal code to access the event."""
    ctx = load_event_context(code, require="none")
    if ctx.participant is not None:
        return redirect(url_for("events.dashboard", code=code))

    errors = FormErrors()
    typed = ""
    if request.method == "POST":
        typed = request.form.get("guest_code", "").strip()
        match = resolve_event_code(ctx.event, typed)
        if match is None:
            mark_attempt_failed("event", code)
            errors.add(
                "guest_code",
                _(
                    "Ce code n'est pas valable pour cet événement. Vérifiez-le, "
                    "ou rejoignez l'événement."
                ),
            )
            typed = typed[:64]
        elif match.guest is not None:
            start_guest_session(code, match.guest)
            log_code_login("guest", code)
            return redirect(url_for("events.dashboard", code=code))
        else:
            start_creator_session(cast("Creator", match.creator))
            log_code_login("creator", code)
            return redirect(url_for("events.dashboard", code=code))

    return render_template("events/mycode.html", event=ctx.event, errors=errors, typed=typed)


# === Helpers ===


def _rq_queue():
    """Get the RQ queue (lazy import)."""
    from redis import Redis
    from rq import Queue

    return Queue(
        "default",
        connection=Redis.from_url(current_app.config.get("REDIS_URL", "redis://localhost:6379/0")),
    )


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
        host,
        port,
        user,
        pw,
        frm,
        email,
        event.title,
        format_date(event.start_date, "long"),
        format_date(event.end_date, "long"),
        join_url,
        display_name,
        lang=current_locale(),
    )


def _send_verification_email(creator: Creator, event: Event, token: str) -> None:
    """Enqueue verification email (RQ)."""
    from app import tasks

    url = url_for("events.verify", token=token, _external=True)
    to_addr = event.creator_email or creator.email
    host, port, user, pw, frm = _smtp_cfg()
    _rq_queue().enqueue(
        tasks.send_verification_email,
        host,
        port,
        user,
        pw,
        frm,
        to_addr,
        event.title,
        url,
        lang=current_locale(),
    )


def _send_invite_email(to_addr: str, event: Event) -> None:
    """Enqueue invite email (RQ)."""
    from app import tasks

    join_url = f"{current_app.config['APP_URL']}/e/{event.code}/join"
    host, port, user, pw, frm = _smtp_cfg()
    _rq_queue().enqueue(
        tasks.send_invite_email,
        host,
        port,
        user,
        pw,
        frm,
        to_addr,
        event.title,
        format_date(event.start_date, "long"),
        format_date(event.end_date, "long"),
        event.location or "",
        join_url,
        lang=current_locale(),
    )


LOG_PAGE_SIZE = 50


@events_bp.route("/<code>/log")
def log(code: str) -> str | Response | tuple[str, int]:
    """Journal de l'événement (B020) : phrases lisibles, filtres module/personne, 50 par page."""
    from app.i18n import LOG_MODULE_LABELS, action_codes, describe_action
    from app.models import ActivityLog
    from app.ui import LOG_ICONS

    event = load_event_context(code).event
    module = request.args.get("type", "")
    who = request.args.get("who", "")
    page = max(1, request.args.get("page", 1, type=int) or 1)

    query = ActivityLog.query.filter_by(event_id=event.id)
    if module in LOG_MODULE_LABELS:
        query = query.filter(ActivityLog.action.in_(action_codes(module)))
    else:
        module = ""
    if who:
        query = query.filter(ActivityLog.actor_name == who)
    rows = (
        query.order_by(ActivityLog.created_at.desc(), ActivityLog.id)
        .offset((page - 1) * LOG_PAGE_SIZE)
        .limit(LOG_PAGE_SIZE + 1)
        .all()
    )
    has_older = len(rows) > LOG_PAGE_SIZE
    days: list[dict[str, Any]] = []
    for row in rows[:LOG_PAGE_SIZE]:
        entry = {
            "time": row.created_at,
            "icon": LOG_ICONS.get(action_module(row.action) or "", "scroll-text"),
            **describe_action(row.action, row.actor_name, row.target, row.details),
        }
        day = row.created_at.date()
        if not days or days[-1]["day"] != day:
            days.append({"day": day, "entries": []})
        days[-1]["entries"].append(entry)
    people = [
        (name, name)
        for (name,) in db.session.query(ActivityLog.actor_name)
        .filter_by(event_id=event.id)
        .distinct()
        .order_by(ActivityLog.actor_name)
    ]
    filters: dict[str, Any] = {k: v for k, v in (("type", module), ("who", who)) if v}
    return render_template(
        "events/log.html",
        event=event,
        days=days,
        modules=[(key, str(text)) for key, text in LOG_MODULE_LABELS.items()],
        people=people,
        module=module,
        who=who,
        page=page,
        older_url=url_for("events.log", code=code, **{**filters, "page": page + 1})
        if has_older
        else None,
        newer_url=url_for(
            "events.log", code=code, **({**filters, "page": page - 1} if page > 2 else filters)
        )
        if page > 1
        else None,
    )


@events_bp.route("/recover", methods=["GET", "POST"])
@limiter.limit("5 per 15 minutes")
def recover_code() -> str | Response:
    """Récupération du code par e-mail ; la réponse ne dit jamais si l'adresse existe (F16)."""
    errors = FormErrors()
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email or not _valid_email(email):
            errors.add("email", _("Format d'e-mail invalide."))
        else:
            _send_recovery(email)
            flash(
                _(
                    "Si un code est associé à cette adresse, il vient de vous être envoyé "
                    "par e-mail. Pensez à vérifier vos courriers indésirables."
                ),
                "success",
            )
            return redirect(url_for("events.recover_code"))
    return render_template("events/recover.html", errors=errors, email=email)


def _send_recovery(email: str) -> None:
    creator = Creator.query.filter_by(email=email).first()
    if creator is None or not creator.personal_code:
        return
    if current_app.config["SMTP_HOST"]:
        from app import tasks

        host, port, user, pw, frm = _smtp_cfg()
        try:
            _rq_queue().enqueue(
                tasks.send_recovery_email,
                host,
                port,
                user,
                pw,
                frm,
                email,
                creator.personal_code,
                creator.display_name,
                lang=current_locale(),
            )
        except Exception:  # la réponse reste identique : pas d'écart observable entre adresses
            logger.exception("recovery_mail_enqueue_failed")
    elif current_app.config["DEV_SHOW_SECRETS"]:
        flash(_("Votre code : %(code)s", code=creator.personal_code), "warning")
    else:
        logger.warning("recovery_mail_not_sent smtp=unconfigured")
