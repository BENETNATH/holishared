"""Planning blueprint — activités et RSVP (B003)."""

from dataclasses import dataclass
from datetime import date, datetime, time

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_babel import _
from sqlalchemy.exc import IntegrityError
from werkzeug.wrappers import Response

from app.context import load_event_context, log_event
from app.extensions import db, limiter
from app.forms import FormErrors
from app.i18n import RSVP_STATUSES
from app.models import Activity, ActivityRSVP, Event

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


@planning_bp.route("/e/<code>/planning")
def index(code: str) -> Response | tuple[str, int] | str:
    """List the event's activities, grouped by date."""
    ctx = load_event_context(code)
    event = ctx.event

    activities = (
        Activity.query.filter_by(event_id=event.id)
        .order_by(Activity.date.asc(), Activity.start_time.asc().nulls_last())
        .all()
    )

    guest_rsvps: dict[str, str] = {}
    if ctx.participant is not None:
        for rsvp in ActivityRSVP.query.filter_by(guest_id=ctx.participant.id).all():
            guest_rsvps[rsvp.activity_id] = rsvp.status

    return render_template(
        "planning/index.html",
        event=event,
        activities=activities,
        today=date.today(),
        guest_rsvps=guest_rsvps,
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
            form_data={},
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
    """Upsert the guest's RSVP for an activity."""
    ctx = load_event_context(code)
    participant = ctx.participant
    if participant is None:  # garanti par require="participant"
        abort(403)
    activity = Activity.query.filter_by(id=activity_id, event_id=ctx.event.id).first()
    if activity is None:
        abort(404)

    status = request.form.get("status", "")
    if status not in RSVP_STATUSES:
        flash(_("Statut invalide."))
        return redirect(url_for("planning.index", code=code))

    try:
        db.session.add(ActivityRSVP(activity_id=activity.id, guest_id=participant.id, status=status))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = ActivityRSVP.query.filter_by(activity_id=activity.id, guest_id=participant.id).first()
        if existing is not None:
            existing.status = status
            db.session.commit()

    log_event(ctx, "rsvp.updated", target=activity.title, details=status)
    db.session.commit()

    return redirect(url_for("planning.index", code=code))
