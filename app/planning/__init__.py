"""Planning blueprint — activités et RSVP (B003)."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from flask import (
    Blueprint,
    abort,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_babel import _
from sqlalchemy.exc import IntegrityError
from werkzeug.wrappers import Response

from app.context import EventContext, load_event_context, log_event
from app.extensions import db, limiter
from app.forms import FormErrors
from app.i18n import RSVP_STATUSES
from app.models import Activity, ActivityRSVP, Event, Guest, Meal

planning_bp = Blueprint("planning", __name__)


@dataclass
class ActivityFields:
    """Parsed and validated activity form fields."""

    title: str
    description: str
    date: date
    start_time: time | None
    end_time: time | None
    location: str
    min_headcount: int
    bring_items: str


def _parse_time(value: str) -> time | None:
    """Parse an HH:MM string, or None when empty/invalid."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


def _validate_form(event: Event) -> tuple[FormErrors, dict[str, str], ActivityFields]:
    """Validate the activity form.

    Returns (errors, form_data, fields) where form_data holds the raw
    strings for re-rendering and fields the typed values (only meaningful
    when errors is empty).
    """
    errors = FormErrors()
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    date_raw = request.form.get("date", "").strip()
    start_raw = request.form.get("start_time", "").strip()
    end_raw = request.form.get("end_time", "").strip()
    location = request.form.get("location", "").strip()
    headcount_raw = request.form.get("min_headcount", "").strip()
    bring_items = request.form.get("bring_items", "").strip()

    if len(title) < 2:
        errors.add("title", _("Titre requis (min 2 caractères)."))
    if len(description) > 2000:
        errors.add("description", _("Description trop longue (max 2000)."))

    activity_date: date | None = None
    if not date_raw:
        errors.add("date", _("Date requise."))
    else:
        try:
            activity_date = datetime.strptime(date_raw, "%Y-%m-%d").date()
        except ValueError:
            errors.add("date", _("Format de date invalide (AAAA-MM-JJ)."))
        else:
            if not (event.start_date <= activity_date <= event.end_date):
                errors.add("date", _("Date hors de la période de l'événement."))

    start_time = _parse_time(start_raw)
    end_time = _parse_time(end_raw)
    if start_raw and start_time is None:
        errors.add("start_time", _("Heure invalide."))
    if end_raw and end_time is None:
        errors.add("end_time", _("Heure invalide."))
    if start_time is not None and end_time is not None and end_time <= start_time:
        errors.add("end_time", _("Heure de fin avant heure de début."))

    if len(location) > 300:
        errors.add("location", _("Lieu trop long (max 300)."))

    min_headcount = 1
    if headcount_raw:
        try:
            min_headcount = int(headcount_raw)
        except ValueError:
            errors.add("min_headcount", _("Nombre entre 1 et 50."))
        else:
            if not 1 <= min_headcount <= 50:
                errors.add("min_headcount", _("Nombre entre 1 et 50."))

    if len(bring_items) > 500:
        errors.add("bring_items", _("Champ trop long (max 500)."))

    form_data = {
        "title": title,
        "description": description,
        "date": date_raw,
        "start_time": start_raw,
        "end_time": end_raw,
        "location": location,
        "min_headcount": headcount_raw or "1",
        "bring_items": bring_items,
    }
    fields = ActivityFields(
        title=title,
        description=description,
        date=activity_date or event.start_date,
        start_time=start_time,
        end_time=end_time,
        location=location,
        min_headcount=min_headcount,
        bring_items=bring_items,
    )
    return errors, form_data, fields


RSVP_CLEAR = "none"  # statut spécial : retire la réponse de la personne


@dataclass
class RsvpSummary:
    """Réponses à une activité : prénoms d'affichage par statut et réponse de la personne."""

    names: dict[str, list[str]] = field(default_factory=lambda: {"yes": [], "maybe": [], "no": []})
    mine: str | None = None

    def count(self, status: str) -> int:
        return len(self.names[status])


def _rsvp_summaries(
    ctx: EventContext, activity_id: str | None = None
) -> defaultdict[str, RsvpSummary]:
    """Réponses de tout l'événement (ou d'une activité) en une seule requête."""
    query = (
        db.session.query(
            ActivityRSVP.activity_id,
            ActivityRSVP.status,
            ActivityRSVP.guest_id,
            Guest.display_name,
        )
        .join(Guest, Guest.id == ActivityRSVP.guest_id)
        .join(Activity, Activity.id == ActivityRSVP.activity_id)
        .filter(Activity.event_id == ctx.event.id, Guest.is_active.is_(True))
        .order_by(Guest.display_name, Guest.id)
    )
    if activity_id is not None:
        query = query.filter(ActivityRSVP.activity_id == activity_id)
    summaries: defaultdict[str, RsvpSummary] = defaultdict(RsvpSummary)
    for act_id, status, guest_id, name in query:
        summaries[act_id].names[status].append(name)
        if ctx.is_author(guest_id):
            summaries[act_id].mine = status
    return summaries


def _author_names(event: Event) -> dict[str, str]:
    return dict(db.session.query(Guest.id, Guest.display_name).filter_by(event_id=event.id))


def _parse_day(value: str | None) -> date | None:
    try:
        return datetime.strptime(value or "", "%Y-%m-%d").date()
    except ValueError:
        return None


def _default_day(event: Event, requested: str | None = None) -> date:
    """Jour demandé s'il est dans la période, sinon aujourd'hui, sinon le premier jour."""
    for day in (_parse_day(requested), date.today()):
        if day is not None and event.start_date <= day <= event.end_date:
            return day
    return event.start_date


def _card_context(ctx: EventContext, activity: Activity) -> dict[str, object]:
    return {
        "ctx": ctx,
        "event": ctx.event,
        "act": activity,
        "summary": _rsvp_summaries(ctx, activity.id)[activity.id],
        "authors": _author_names(ctx.event),
    }


@planning_bp.route("/e/<code>/planning")
def index(code: str) -> Response | tuple[str, int] | str:
    """Programme : jours de l'événement (jours vides inclus), repas en lecture seule et activités."""
    ctx = load_event_context(code)
    event = ctx.event

    activities: dict[date, list[Activity]] = defaultdict(list)
    for activity in Activity.query.filter_by(event_id=event.id).order_by(
        Activity.date, Activity.start_time.asc().nulls_first(), Activity.created_at, Activity.id
    ):
        activities[activity.date].append(activity)
    meals: dict[date, list[Meal]] = defaultdict(list)
    for meal in Meal.query.filter_by(event_id=event.id).order_by(*Meal.ordering()):
        meals[meal.date].append(meal)

    return render_template(
        "planning/index.html",
        event=event,
        days=[event.start_date + timedelta(days=i) for i in range(event.duration_days)],
        activities=activities,
        meals=meals,
        summaries=_rsvp_summaries(ctx),
        authors=_author_names(event),
        today=date.today(),
        selected_day=_default_day(event, request.args.get("day")),
        form_data={},
        errors=FormErrors(),
    )


@planning_bp.route("/e/<code>/planning/new", methods=["GET", "POST"])
@limiter.limit("20 per hour")
def create(code: str) -> Response | tuple[str, int] | str:
    """Create a new activity."""
    ctx = load_event_context(code)
    event = ctx.event

    if request.method == "GET":
        return render_template(
            "planning/form.html",
            event=event,
            activity=None,
            form_data={"date": _default_day(event, request.args.get("date")).isoformat()},
            errors=FormErrors(),
            action_url=url_for("planning.create", code=code),
        )

    errors, form_data, fields = _validate_form(event)
    if errors:
        return render_template(
            "planning/form.html",
            event=event,
            activity=None,
            form_data=form_data,
            errors=errors,
            action_url=url_for("planning.create", code=code),
        )

    activity = Activity(
        title=fields.title,
        description=fields.description,
        date=fields.date,
        start_time=fields.start_time,
        end_time=fields.end_time,
        location=fields.location,
        min_headcount=fields.min_headcount,
        bring_items=fields.bring_items,
        created_by=ctx.participant.id if ctx.participant else None,
        event_id=event.id,
    )
    db.session.add(activity)
    log_event(ctx, "activity.created", target=fields.title)
    db.session.commit()

    flash(_("Activité créée."))
    return redirect(url_for("planning.index", code=code))


@planning_bp.route("/e/<code>/planning/<activity_id>/edit", methods=["GET", "POST"])
def edit(code: str, activity_id: str) -> Response | tuple[str, int] | str:
    """Edit an existing activity."""
    ctx = load_event_context(code)
    event = ctx.event
    activity = Activity.query.filter_by(id=activity_id, event_id=event.id).first()
    if activity is None:
        abort(404)
    if not ctx.can_edit(activity):
        abort(403)

    action_url = url_for("planning.edit", code=code, activity_id=activity.id)

    if request.method == "GET":
        form_data = {
            "title": activity.title,
            "description": activity.description,
            "date": activity.date.isoformat(),
            "start_time": activity.start_time.strftime("%H:%M") if activity.start_time else "",
            "end_time": activity.end_time.strftime("%H:%M") if activity.end_time else "",
            "location": activity.location,
            "min_headcount": str(activity.min_headcount),
            "bring_items": activity.bring_items,
        }
        return render_template(
            "planning/form.html",
            event=event,
            activity=activity,
            form_data=form_data,
            errors=FormErrors(),
            action_url=action_url,
        )

    errors, form_data, fields = _validate_form(event)
    if errors:
        return render_template(
            "planning/form.html",
            event=event,
            activity=activity,
            form_data=form_data,
            errors=errors,
            action_url=action_url,
        )

    activity.title = fields.title
    activity.description = fields.description
    activity.date = fields.date
    activity.start_time = fields.start_time
    activity.end_time = fields.end_time
    activity.location = fields.location
    activity.min_headcount = fields.min_headcount
    activity.bring_items = fields.bring_items
    log_event(ctx, "activity.updated", target=fields.title)
    db.session.commit()

    flash(_("Activité modifiée."))
    return redirect(url_for("planning.index", code=code))


@planning_bp.route("/e/<code>/planning/<activity_id>/delete", methods=["POST"])
def delete(code: str, activity_id: str) -> Response | tuple[str, int] | str:
    """Delete an activity (RSVPs cascade)."""
    ctx = load_event_context(code)
    activity = Activity.query.filter_by(id=activity_id, event_id=ctx.event.id).first()
    if activity is None:
        abort(404)
    if not ctx.can_delete(activity):
        abort(403)

    title = activity.title
    db.session.delete(activity)
    log_event(ctx, "activity.deleted", target=title)
    db.session.commit()

    flash(_("Activité supprimée."))
    return redirect(url_for("planning.index", code=code))


@planning_bp.route("/e/<code>/planning/<activity_id>/rsvp", methods=["POST"])
def rsvp(code: str, activity_id: str) -> Response | tuple[str, int] | str:
    """Upsert (ou retire, ``status=none``) la réponse du participant, créateur compris.

    Une requête HTMX reçoit la carte à jour ; sinon redirection vers le programme.
    """
    ctx = load_event_context(code)
    participant = ctx.participant
    if participant is None:  # garanti par require="participant"
        abort(403)
    activity = Activity.query.filter_by(id=activity_id, event_id=ctx.event.id).first()
    if activity is None:
        abort(404)

    htmx = request.headers.get("HX-Request") == "true"
    status = request.form.get("status", "")
    if status not in RSVP_STATUSES and status != RSVP_CLEAR:
        if htmx:
            html = render_template("planning/_card.html", **_card_context(ctx, activity))
            return make_response(html, 422)
        flash(_("Statut invalide."))
        return redirect(url_for("planning.index", code=code))

    existing = ActivityRSVP.query.filter_by(
        activity_id=activity.id, guest_id=participant.id
    ).first()
    if status == RSVP_CLEAR:
        if existing is not None:
            db.session.delete(existing)
    elif existing is not None:
        existing.status = status
    else:
        db.session.add(
            ActivityRSVP(activity_id=activity.id, guest_id=participant.id, status=status)
        )
    try:
        db.session.flush()
    except IntegrityError:  # double envoi concurrent : la réponse existe déjà, on la met à jour
        db.session.rollback()
        existing = ActivityRSVP.query.filter_by(
            activity_id=activity.id, guest_id=participant.id
        ).first()
        if existing is not None and status != RSVP_CLEAR:
            existing.status = status
    log_event(ctx, "rsvp.updated", target=activity.title, details=status)
    db.session.commit()

    if htmx:
        return render_template("planning/_card.html", **_card_context(ctx, activity))
    return redirect(url_for("planning.index", code=code))
