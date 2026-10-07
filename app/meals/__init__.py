"""Meals blueprint — grille de repas (module distinct de planning).

Plusieurs repas peuvent partager une case (jour + créneau), dans la limite de
``MAX_MEALS_PER_CELL`` ; ``Meal.position`` les ordonne. Les identifiants ne
changent jamais lors d'un déplacement, d'un réordonnancement ou d'un échange.
Une requête HTMX reçoit le fragment ``meals/_grid.html`` à jour (erreurs et
confirmations dans l'en-tête ``HX-Trigger``) ; sinon, flash + redirection.
"""

import json
from collections import defaultdict
from datetime import date, datetime, timedelta

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
from sqlalchemy import text
from werkzeug.wrappers import Response

from app.context import EventContext, load_event_context, log_event
from app.extensions import db, limiter
from app.i18n import LABELS, MEAL_SLOTS, format_date_safe
from app.models import MAX_MEALS_PER_CELL, Meal

meals_bp = Blueprint("meals", __name__)


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _is_htmx() -> bool:
    return request.headers.get("HX-Request") == "true"


def _grid_context(ctx: EventContext) -> dict[str, object]:
    event = ctx.event
    cells: dict[tuple[date, str], list[Meal]] = defaultdict(list)
    for meal in Meal.query.filter_by(event_id=event.id).order_by(*Meal.ordering()):
        cells[(meal.date, meal.slot)].append(meal)
    today = date.today()
    return {
        "event": event,
        "cells": cells,
        "days": [event.start_date + timedelta(days=i) for i in range(event.duration_days)],
        "today": today,
        "selected_day": today if event.start_date <= today <= event.end_date else event.start_date,
        "max_per_cell": MAX_MEALS_PER_CELL,
    }


def _respond(ctx: EventContext, message: str, *, ok: bool = True) -> Response:
    """Fragment de grille (HTMX) ou flash + redirection ; `ok=False` : erreur (422 en HTMX)."""
    if not _is_htmx():
        flash(message, "success" if ok else "danger")
        return redirect(url_for("meals.index", code=ctx.event.code))
    response = make_response(render_template("meals/_grid.html", **_grid_context(ctx)))
    response.status_code = 200 if ok else 422
    payload = {"message": message, "tone": "success" if ok else "danger"}
    response.headers["HX-Trigger"] = json.dumps({"meals:message": payload})
    return response


def _cell(event_id: str, day: date, slot: str) -> list[Meal]:
    return list(
        Meal.query.filter_by(event_id=event_id, date=day, slot=slot).order_by(
            Meal.position, Meal.created_at, Meal.id
        )
    )


def _renumber(meals: list[Meal]) -> None:
    for index, meal in enumerate(meals):
        meal.position = index


def _clean_title() -> tuple[str, str | None]:
    title = request.form.get("title", "").strip()
    if len(title) < 2:
        return title, _("Nom requis (min 2 caractères).")
    if len(title) > 200:
        return title, _("Nom trop long (max 200).")
    return title, None


def _target(ctx: EventContext) -> tuple[date, str, str | None]:
    """Date et créneau demandés (formulaire), avec le message d'erreur éventuel."""
    event = ctx.event
    day = _parse_date(request.form.get("date", ""))
    slot = request.form.get("slot", "")
    if day is None or not (event.start_date <= day <= event.end_date):
        return date.min, slot, _("Date hors de la période de l'événement.")
    if slot not in MEAL_SLOTS:
        return day, slot, _("Créneau invalide.")
    return day, slot, None


def _lock_for_write() -> None:
    """SQLite : prend le verrou d'écriture AVANT de relire la case (la limite ne se contourne pas par course)."""
    if db.engine.dialect.name != "sqlite":
        return
    raw = db.session.connection().connection
    if not raw.in_transaction:
        db.session.execute(text("BEGIN IMMEDIATE"))


def _full_message() -> str:
    return str(_("Cette case est pleine (%(max)d repas maximum).", max=MAX_MEALS_PER_CELL))


def _meal_or_404(ctx: EventContext, meal_id: str, *, edit: bool = True) -> Meal:
    meal: Meal | None = Meal.query.filter_by(id=meal_id, event_id=ctx.event.id).first()
    if meal is None:
        abort(404)
    if edit and not ctx.can_edit(meal):
        abort(403)
    return meal


@meals_bp.route("/e/<code>/meals")
def index(code: str) -> Response | str:
    """Show the meal grid for the event."""
    ctx = load_event_context(code)
    return render_template("meals/index.html", **_grid_context(ctx))


@meals_bp.route("/e/<code>/meals/create", methods=["POST"])
@limiter.limit("60 per hour")
def create(code: str) -> Response:
    """Ajoute un repas en fin de case."""
    ctx = load_event_context(code)
    title, error = _clean_title()
    day, slot, target_error = _target(ctx)
    error = error or target_error
    if error:
        return _respond(ctx, error, ok=False)
    _lock_for_write()
    cell = _cell(ctx.event.id, day, slot)
    if len(cell) >= MAX_MEALS_PER_CELL:
        return _respond(ctx, _full_message(), ok=False)

    db.session.add(
        Meal(
            title=title,
            date=day,
            slot=slot,
            position=len(cell),
            created_by=ctx.participant.id if ctx.participant else None,
            event_id=ctx.event.id,
        )
    )
    log_event(ctx, "meal.created", target=title)
    db.session.commit()
    return _respond(ctx, _("Repas ajouté."))


@meals_bp.route("/e/<code>/meals/<meal_id>/edit", methods=["POST"])
def edit(code: str, meal_id: str) -> Response:
    """Edit a meal's title."""
    ctx = load_event_context(code)
    meal = _meal_or_404(ctx, meal_id)
    title, error = _clean_title()
    if error:
        return _respond(ctx, error, ok=False)

    meal.title = title
    log_event(ctx, "meal.updated", target=title)
    db.session.commit()
    return _respond(ctx, _("Repas modifié."))


@meals_bp.route("/e/<code>/meals/<meal_id>/delete", methods=["POST"])
def delete(code: str, meal_id: str) -> Response:
    """Delete a meal."""
    ctx = load_event_context(code)
    meal = Meal.query.filter_by(id=meal_id, event_id=ctx.event.id).first()
    if meal is None:
        abort(404)
    if not ctx.can_delete(meal):
        abort(403)

    title, day, slot = meal.title, meal.date, meal.slot
    db.session.delete(meal)
    db.session.flush()
    _renumber(_cell(ctx.event.id, day, slot))
    log_event(ctx, "meal.deleted", target=title)
    db.session.commit()
    return _respond(ctx, _("Repas supprimé."))


@meals_bp.route("/e/<code>/meals/move", methods=["POST"])
def move(code: str) -> Response:
    """Déplace un repas vers une case : avant `before_id` si fourni, sinon en fin de case."""
    ctx = load_event_context(code)
    meal = _meal_or_404(ctx, request.form.get("meal_id", ""))
    day, slot, error = _target(ctx)
    if error:
        return _respond(ctx, error, ok=False)

    source = (meal.date, meal.slot)
    _lock_for_write()
    others = [m for m in _cell(ctx.event.id, day, slot) if m.id != meal.id]
    before_id = request.form.get("before_id", "")
    if source != (day, slot) and len(others) >= MAX_MEALS_PER_CELL:
        return _respond(ctx, _full_message(), ok=False)

    index = next((i for i, m in enumerate(others) if m.id == before_id), len(others))
    others.insert(index, meal)
    meal.date, meal.slot = day, slot
    _renumber(others)
    if source != (day, slot):
        db.session.flush()
        _renumber(_cell(ctx.event.id, *source))
    log_event(ctx, "meal.moved", target=meal.title)
    db.session.commit()
    if source == (day, slot):
        return _respond(ctx, _("Repas déplacé."))
    cell_label = f"{format_date_safe(day, 'EEEE d MMMM')}, {str(LABELS['meal_slot'][slot]).lower()}"
    return _respond(ctx, _("Repas ajouté à : %(cell)s.", cell=cell_label))


@meals_bp.route("/e/<code>/meals/swap", methods=["POST"])
def swap(code: str) -> Response:
    """Échange explicite : les deux repas permutent (jour, créneau, position)."""
    ctx = load_event_context(code)
    first = _meal_or_404(ctx, request.form.get("meal_id", ""))
    second = _meal_or_404(ctx, request.form.get("other_id", ""))
    if first.id == second.id:
        return _respond(ctx, _("Choisissez un autre repas."), ok=False)

    _lock_for_write()
    cells = {(m.date, m.slot) for m in (first, second)}
    first.date, second.date = second.date, first.date
    first.slot, second.slot = second.slot, first.slot
    first.position, second.position = second.position, first.position
    db.session.flush()
    for day, slot in cells:  # positions sans trous dans chaque case touchée
        _renumber(_cell(ctx.event.id, day, slot))
    log_event(ctx, "meal.swapped", target=first.title, details=second.title)
    db.session.commit()
    return _respond(ctx, _("Repas échangés."))
