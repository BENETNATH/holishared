"""Meals blueprint — grille de repas (module distinct de planning)."""

from datetime import date, datetime

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
from werkzeug.wrappers import Response

from app.extensions import db, limiter
from app.models import Event, Guest, Meal
from app.utils import log_action

meals_bp = Blueprint("meals", __name__)

SLOTS = frozenset({"lunch", "dinner"})


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


def _can_modify(event: Event, meal: Meal, guest: Guest | None) -> bool:
    """Event creator or meal creator may modify/delete/move."""
    if current_user.is_authenticated and current_user.id == event.creator_id:
        return True
    return guest is not None and meal.created_by == guest.id


def _actor_name(guest: Guest | None, is_creator: bool) -> tuple[str, str]:
    """(actor_name, actor_type) for ActivityLog entries."""
    if is_creator:
        return (current_user.display_name or "Créateur"), "creator"
    if guest is not None:
        return guest.display_name, "guest"
    return "Système", "system"


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


@meals_bp.route("/e/<code>/meals")
def index(code: str) -> Response | str:
    """Show the meal grid for the event."""
    event = _get_event_or_404(code)
    guest, _, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    meals = (
        Meal.query.filter_by(event_id=event.id)
        .order_by(Meal.date.asc(), Meal.slot.asc())
        .all()
    )
    # One meal per (date, slot) cell.
    by_cell: dict[tuple[date, str], Meal] = {(m.date, m.slot): m for m in meals}

    def can_modify(meal: Meal) -> bool:
        return _can_modify(event, meal, guest)

    return render_template(
        "meals/index.html",
        event=event,
        meals=meals,
        by_cell=by_cell,
        guest=guest,
        can_modify=can_modify,
        today=date.today(),
    )


@meals_bp.route("/e/<code>/meals/create", methods=["POST"])
@limiter.limit("60 per hour")
def create(code: str) -> Response:
    """Create a meal in an empty cell."""
    event = _get_event_or_404(code)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    title = request.form.get("title", "").strip()
    meal_date = _parse_date(request.form.get("date", ""))
    slot = request.form.get("slot", "")

    if len(title) < 2:
        flash(_("Nom requis (min 2 caractères)."))
        return redirect(url_for("meals.index", code=code))
    if len(title) > 200:
        flash(_("Nom trop long (max 200)."))
        return redirect(url_for("meals.index", code=code))
    if meal_date is None or not (event.start_date <= meal_date <= event.end_date):
        flash(_("Date hors de la période de l'événement."))
        return redirect(url_for("meals.index", code=code))
    if slot not in SLOTS:
        flash(_("Créneau invalide."))
        return redirect(url_for("meals.index", code=code))

    existing = Meal.query.filter_by(event_id=event.id, date=meal_date, slot=slot).first()
    if existing is not None:
        flash(_("Cette case est déjà occupée."))
        return redirect(url_for("meals.index", code=code))

    meal = Meal(
        title=title,
        date=meal_date,
        slot=slot,
        created_by=guest.id if guest is not None else None,
        event_id=event.id,
    )
    db.session.add(meal)
    actor_name, actor_type = _actor_name(guest, is_creator)
    log_action(db.session, event.id, actor_name, actor_type, "meal.created", target=title)
    db.session.commit()

    flash(_("Repas ajouté."))
    return redirect(url_for("meals.index", code=code))


@meals_bp.route("/e/<code>/meals/<meal_id>/edit", methods=["POST"])
def edit(code: str, meal_id: str) -> Response:
    """Edit a meal's title."""
    event = _get_event_or_404(code)
    meal = Meal.query.filter_by(id=meal_id, event_id=event.id).first()
    if meal is None:
        abort(404)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied
    if not _can_modify(event, meal, guest):
        flash(_("Pas autorisé."))
        return redirect(url_for("meals.index", code=code))

    title = request.form.get("title", "").strip()
    if len(title) < 2:
        flash(_("Nom requis (min 2 caractères)."))
        return redirect(url_for("meals.index", code=code))
    if len(title) > 200:
        flash(_("Nom trop long (max 200)."))
        return redirect(url_for("meals.index", code=code))

    meal.title = title
    actor_name, actor_type = _actor_name(guest, is_creator)
    log_action(db.session, event.id, actor_name, actor_type, "meal.updated", target=title)
    db.session.commit()

    flash(_("Repas modifié."))
    return redirect(url_for("meals.index", code=code))


@meals_bp.route("/e/<code>/meals/<meal_id>/delete", methods=["POST"])
def delete(code: str, meal_id: str) -> Response:
    """Delete a meal."""
    event = _get_event_or_404(code)
    meal = Meal.query.filter_by(id=meal_id, event_id=event.id).first()
    if meal is None:
        abort(404)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied
    if not _can_modify(event, meal, guest):
        flash(_("Pas autorisé."))
        return redirect(url_for("meals.index", code=code))

    title = meal.title
    db.session.delete(meal)
    actor_name, actor_type = _actor_name(guest, is_creator)
    log_action(db.session, event.id, actor_name, actor_type, "meal.deleted", target=title)
    db.session.commit()

    flash(_("Repas supprimé."))
    return redirect(url_for("meals.index", code=code))


@meals_bp.route("/e/<code>/meals/move", methods=["POST"])
def move(code: str) -> Response:
    """Move a meal to a target cell; swap if the target cell is occupied."""
    event = _get_event_or_404(code)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    meal_id = request.form.get("meal_id", "")
    meal = Meal.query.filter_by(id=meal_id, event_id=event.id).first()
    if meal is None:
        abort(404)
    if not _can_modify(event, meal, guest):
        flash(_("Pas autorisé."))
        return redirect(url_for("meals.index", code=code))

    target_date = _parse_date(request.form.get("date", ""))
    target_slot = request.form.get("slot", "")
    if target_date is None or not (event.start_date <= target_date <= event.end_date):
        flash(_("Date hors de la période de l'événement."))
        return redirect(url_for("meals.index", code=code))
    if target_slot not in SLOTS:
        flash(_("Créneau invalide."))
        return redirect(url_for("meals.index", code=code))

    # Same cell: nothing to do.
    if meal.date == target_date and meal.slot == target_slot:
        return redirect(url_for("meals.index", code=code))

    occupant = Meal.query.filter_by(event_id=event.id, date=target_date, slot=target_slot).first()
    if occupant is not None:
        # Swap the two meals' (date, slot) in three flushed steps so the
        # unique (event, date, slot) constraint is never transiently
        # violated: park the mover, free the target cell, then place it.
        orig_date, orig_slot = meal.date, meal.slot
        meal.slot = "tmp"
        db.session.flush()
        occupant.date, occupant.slot = orig_date, orig_slot
        db.session.flush()
        meal.date, meal.slot = target_date, target_slot
        db.session.flush()
    else:
        meal.date = target_date
        meal.slot = target_slot

    actor_name, actor_type = _actor_name(guest, is_creator)
    log_action(db.session, event.id, actor_name, actor_type, "meal.moved", target=meal.title)
    db.session.commit()

    return redirect(url_for("meals.index", code=code))
