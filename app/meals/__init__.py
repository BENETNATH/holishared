"""Meals blueprint — grille de repas (module distinct de planning)."""

from datetime import date, datetime

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
from werkzeug.wrappers import Response

from app.context import load_event_context, log_event
from app.extensions import db, limiter
from app.models import Meal

meals_bp = Blueprint("meals", __name__)

SLOTS = frozenset({"lunch", "dinner"})


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
    ctx = load_event_context(code)
    event = ctx.event

    meals = (
        Meal.query.filter_by(event_id=event.id)
        .order_by(Meal.date.asc(), Meal.slot.asc())
        .all()
    )
    # One meal per (date, slot) cell.
    by_cell: dict[tuple[date, str], Meal] = {(m.date, m.slot): m for m in meals}

    return render_template(
        "meals/index.html",
        event=event,
        meals=meals,
        by_cell=by_cell,
        today=date.today(),
    )


@meals_bp.route("/e/<code>/meals/create", methods=["POST"])
@limiter.limit("60 per hour")
def create(code: str) -> Response:
    """Create a meal in an empty cell."""
    ctx = load_event_context(code)
    event = ctx.event

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
        created_by=ctx.participant.id if ctx.participant else None,
        event_id=event.id,
    )
    db.session.add(meal)
    log_event(ctx, "meal.created", target=title)
    db.session.commit()

    flash(_("Repas ajouté."))
    return redirect(url_for("meals.index", code=code))


@meals_bp.route("/e/<code>/meals/<meal_id>/edit", methods=["POST"])
def edit(code: str, meal_id: str) -> Response:
    """Edit a meal's title."""
    ctx = load_event_context(code)
    meal = Meal.query.filter_by(id=meal_id, event_id=ctx.event.id).first()
    if meal is None:
        abort(404)
    if not ctx.can_edit(meal):
        abort(403)

    title = request.form.get("title", "").strip()
    if len(title) < 2:
        flash(_("Nom requis (min 2 caractères)."))
        return redirect(url_for("meals.index", code=code))
    if len(title) > 200:
        flash(_("Nom trop long (max 200)."))
        return redirect(url_for("meals.index", code=code))

    meal.title = title
    log_event(ctx, "meal.updated", target=title)
    db.session.commit()

    flash(_("Repas modifié."))
    return redirect(url_for("meals.index", code=code))


@meals_bp.route("/e/<code>/meals/<meal_id>/delete", methods=["POST"])
def delete(code: str, meal_id: str) -> Response:
    """Delete a meal."""
    ctx = load_event_context(code)
    meal = Meal.query.filter_by(id=meal_id, event_id=ctx.event.id).first()
    if meal is None:
        abort(404)
    if not ctx.can_delete(meal):
        abort(403)

    title = meal.title
    db.session.delete(meal)
    log_event(ctx, "meal.deleted", target=title)
    db.session.commit()

    flash(_("Repas supprimé."))
    return redirect(url_for("meals.index", code=code))


@meals_bp.route("/e/<code>/meals/move", methods=["POST"])
def move(code: str) -> Response:
    """Move a meal to a target cell; swap if the target cell is occupied."""
    ctx = load_event_context(code)
    event = ctx.event

    meal_id = request.form.get("meal_id", "")
    meal = Meal.query.filter_by(id=meal_id, event_id=event.id).first()
    if meal is None:
        abort(404)
    if not ctx.can_edit(meal):
        abort(403)

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

    log_event(ctx, "meal.moved", target=meal.title)
    db.session.commit()

    return redirect(url_for("meals.index", code=code))
