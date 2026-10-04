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
    session,
    url_for,
)
from flask_babel import _
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from werkzeug.wrappers import Response

from app.extensions import db
from app.models import Activity, ActivityRSVP, Event, Guest
from app.utils import log_action

planning_bp = Blueprint("planning", __name__)

RSVP_STATUSES = frozenset({"yes", "no", "maybe"})


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


def _get_event_or_404(code: str) -> Event:
    """Load an active event by code or abort with 404."""
    event: Event | None = Event.query.filter_by(code=code, is_active=True).first()
    if event is None:
        abort(404)
    return event


def _resolve_actor(event: Event, code: str) -> tuple[Guest | None, bool, Response | None]:
    """Resolve the current actor for an event.

    Returns (guest, is_creator, denied). ``denied`` is a redirect to the
    mycode page when neither the creator nor a guest session matches.
    """
    if current_user.is_authenticated and current_user.id == event.creator_id:
        return None, True, None
    guest_id = session.get(f"guest_{code}")
    if guest_id:
        guest = Guest.query.filter_by(id=guest_id, event_id=event.id, is_active=True).first()
        if guest is not None:
            return guest, False, None
    return None, False, redirect(url_for("events.my_code", code=code))


def _can_modify(event: Event, activity: Activity, guest: Guest | None) -> bool:
    """Event creator or activity creator may modify/delete."""
    if current_user.is_authenticated and current_user.id == event.creator_id:
        return True
    return guest is not None and activity.created_by == guest.id


def _actor_name(guest: Guest | None, is_creator: bool) -> tuple[str, str]:
    """(actor_name, actor_type) for ActivityLog entries."""
    if is_creator:
        return (current_user.display_name or "Créateur"), "creator"
    if guest is not None:
        return guest.display_name, "guest"
    return "Système", "system"


def _parse_time(value: str) -> time | None:
    """Parse an HH:MM string, or None when empty/invalid."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


def _validate_form(event: Event) -> tuple[list[str], dict[str, str], ActivityFields]:
    """Validate the activity form.

    Returns (errors, form_data, fields) where form_data holds the raw
    strings for re-rendering and fields the typed values (only meaningful
    when errors is empty).
    """
    errors: list[str] = []
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    date_raw = request.form.get("date", "").strip()
    start_raw = request.form.get("start_time", "").strip()
    end_raw = request.form.get("end_time", "").strip()
    location = request.form.get("location", "").strip()
    headcount_raw = request.form.get("min_headcount", "").strip()
    bring_items = request.form.get("bring_items", "").strip()

    if len(title) < 2:
        errors.append(_("Titre requis (min 2 caractères)."))
    if len(description) > 2000:
        errors.append(_("Description trop longue (max 2000)."))

    activity_date: date | None = None
    if not date_raw:
        errors.append(_("Date hors de la période de l'événement."))
    else:
        try:
            activity_date = datetime.strptime(date_raw, "%Y-%m-%d").date()
        except ValueError:
            errors.append(_("Date hors de la période de l'événement."))
        else:
            if not (event.start_date <= activity_date <= event.end_date):
                errors.append(_("Date hors de la période de l'événement."))

    start_time = _parse_time(start_raw)
    end_time = _parse_time(end_raw)
    if (start_raw and start_time is None) or (end_raw and end_time is None):
        errors.append(_("Heure de fin avant heure de début."))
    elif start_time is not None and end_time is not None and end_time <= start_time:
        errors.append(_("Heure de fin avant heure de début."))

    if len(location) > 300:
        errors.append(_("Lieu trop long (max 300)."))

    min_headcount = 1
    if headcount_raw:
        try:
            min_headcount = int(headcount_raw)
        except ValueError:
            errors.append(_("Nombre entre 1 et 50."))
        else:
            if not 1 <= min_headcount <= 50:
                errors.append(_("Nombre entre 1 et 50."))

    if len(bring_items) > 500:
        errors.append(_("Champ trop long (max 500)."))

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
    event = _get_event_or_404(code)
    guest, _, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    activities = (
        Activity.query.filter_by(event_id=event.id)
        .order_by(Activity.date.asc(), Activity.start_time.asc().nulls_last())
        .all()
    )

    guest_rsvps: dict[str, str] = {}
    if guest is not None:
        for rsvp in ActivityRSVP.query.filter_by(guest_id=guest.id).all():
            guest_rsvps[rsvp.activity_id] = rsvp.status

    def can_modify(activity: Activity) -> bool:
        return _can_modify(event, activity, guest)

    return render_template(
        "planning/index.html",
        event=event,
        activities=activities,
        guest=guest,
        today=date.today(),
        guest_rsvps=guest_rsvps,
        can_modify=can_modify,
    )


@planning_bp.route("/e/<code>/planning/new", methods=["GET", "POST"])
def create(code: str) -> Response | tuple[str, int] | str:
    """Create a new activity."""
    event = _get_event_or_404(code)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    if request.method == "GET":
        return render_template(
            "planning/form.html",
            event=event,
            activity=None,
            form_data={},
            errors=[],
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
        created_by=guest.id if guest is not None else None,
        event_id=event.id,
    )
    db.session.add(activity)
    actor_name, actor_type = _actor_name(guest, is_creator)
    log_action(
        db.session, event.id, actor_name, actor_type, "activity.created", target=fields.title
    )
    db.session.commit()

    flash(_("Activité créée."))
    return redirect(url_for("planning.index", code=code))


@planning_bp.route("/e/<code>/planning/<activity_id>/edit", methods=["GET", "POST"])
def edit(code: str, activity_id: str) -> Response | tuple[str, int] | str:
    """Edit an existing activity."""
    event = _get_event_or_404(code)
    activity = Activity.query.filter_by(id=activity_id, event_id=event.id).first()
    if activity is None:
        abort(404)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied
    if not _can_modify(event, activity, guest):
        return _("Pas autorisé."), 403

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
            errors=[],
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
    actor_name, actor_type = _actor_name(guest, is_creator)
    log_action(
        db.session, event.id, actor_name, actor_type, "activity.updated", target=fields.title
    )
    db.session.commit()

    flash(_("Activité modifiée."))
    return redirect(url_for("planning.index", code=code))


@planning_bp.route("/e/<code>/planning/<activity_id>/delete", methods=["POST"])
def delete(code: str, activity_id: str) -> Response | tuple[str, int] | str:
    """Delete an activity (RSVPs cascade)."""
    event = _get_event_or_404(code)
    activity = Activity.query.filter_by(id=activity_id, event_id=event.id).first()
    if activity is None:
        abort(404)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied
    if not _can_modify(event, activity, guest):
        return _("Pas autorisé."), 403

    title = activity.title
    db.session.delete(activity)
    actor_name, actor_type = _actor_name(guest, is_creator)
    log_action(db.session, event.id, actor_name, actor_type, "activity.deleted", target=title)
    db.session.commit()

    flash(_("Activité supprimée."))
    return redirect(url_for("planning.index", code=code))


@planning_bp.route("/e/<code>/planning/<activity_id>/rsvp", methods=["POST"])
def rsvp(code: str, activity_id: str) -> Response | tuple[str, int] | str:
    """Upsert the guest's RSVP for an activity."""
    event = _get_event_or_404(code)

    if current_user.is_authenticated and current_user.id == event.creator_id:
        flash(_("Le créateur ne fait pas de RSVP."))
        return redirect(url_for("planning.index", code=code))

    guest_id = session.get(f"guest_{code}")
    guest = None
    if guest_id:
        guest = Guest.query.filter_by(id=guest_id, event_id=event.id, is_active=True).first()
    if guest is None:
        return redirect(url_for("events.my_code", code=code))

    activity = Activity.query.filter_by(id=activity_id, event_id=event.id).first()
    if activity is None:
        abort(404)

    status = request.form.get("status", "")
    if status not in RSVP_STATUSES:
        flash(_("Statut invalide."))
        return redirect(url_for("planning.index", code=code))

    try:
        db.session.add(ActivityRSVP(activity_id=activity.id, guest_id=guest.id, status=status))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = ActivityRSVP.query.filter_by(activity_id=activity.id, guest_id=guest.id).first()
        if existing is not None:
            existing.status = status
            db.session.commit()

    log_action(
        db.session,
        event.id,
        guest.display_name,
        "guest",
        "rsvp.updated",
        target=activity.title,
        details=status,
    )
    db.session.commit()

    return redirect(url_for("planning.index", code=code))
