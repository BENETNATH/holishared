"""Lists blueprint — listes partagées (B004)."""

from typing import Any, cast

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
from app.models import Activity, Event, Guest, ListItem, Meal, SharedList

lists_bp = Blueprint("lists", __name__)


def _get_list_or_404(event: Event, list_id: str) -> SharedList:
    """Load a shared list belonging to the event or abort with 404."""
    shared_list = cast("SharedList | None", SharedList.query.filter_by(id=list_id, event_id=event.id).first())
    if shared_list is None:
        abort(404)
    return shared_list


def _get_item_or_404(shared_list: SharedList, item_id: str) -> ListItem:
    """Load a list item belonging to the list or abort with 404."""
    item = cast("ListItem | None", ListItem.query.filter_by(id=item_id, list_id=shared_list.id).first())
    if item is None:
        abort(404)
    return item


def _list_items(shared_list: SharedList) -> list[ListItem]:
    return cast("list[ListItem]", cast("Any", shared_list.items).order_by(ListItem.created_at.asc()).all())


@lists_bp.route("/e/<code>/lists", methods=["GET", "POST"])
def index(code: str) -> Response | tuple[str, int] | str:
    """List the event's shared lists + inline creation."""
    ctx = load_event_context(code)
    event = ctx.event

    lists = (
        SharedList.query.filter_by(event_id=event.id)
        .order_by(SharedList.created_at.asc())
        .all()
    )

    errors: list[str] = []
    form_title = ""
    if request.method == "POST":
        form_title = request.form.get("title", "").strip()
        if len(form_title) < 2:
            errors.append(_("Titre requis (min 2 caractères)."))
        elif len(form_title) > 200:
            errors.append(_("Titre trop long (max 200)."))
        if not errors:
            shared_list = SharedList(title=form_title, event_id=event.id)
            db.session.add(shared_list)
            log_event(ctx, "list.created", target=form_title)
            db.session.commit()
            flash(_("Liste créée."))
            return redirect(url_for("lists.index", code=code))

    return render_template(
        "lists/index.html",
        event=event,
        lists=lists,
        errors=errors,
        form_title=form_title,
    )


@lists_bp.route("/e/<code>/lists/new")
def create(code: str) -> Response:
    """Legacy: creation is now inline on the index page."""
    return redirect(url_for("lists.index", code=code))


def _list_side_panels(event: Event, shared_list: SharedList) -> dict[str, Any]:
    """Compute the meal/activity side panels for a list detail view.

    All meals/activities of the event are returned. The template marks the
    ones covered by this list and lets the user filter them out (instead of
    auto-hiding them the moment they are checked).
    """
    meals = (
        Meal.query.filter_by(event_id=event.id)
        .order_by(Meal.date.asc(), Meal.slot.asc())
        .all()
    )
    activities = (
        Activity.query.filter_by(event_id=event.id)
        .order_by(Activity.date.asc(), Activity.start_time.asc().nulls_last())
        .all()
    )
    return {
        "meal_acts": meals,
        "act_acts": activities,
        "covered_meal_ids": set(shared_list.covered_meals or []),
        "covered_act_ids": set(shared_list.covered_activities or []),
    }


@lists_bp.route("/e/<code>/lists/<list_id>")
def detail(code: str, list_id: str) -> Response | tuple[str, int] | str:
    """Show a shared list with its items + meal plan side panel."""
    ctx = load_event_context(code)
    event = ctx.event
    shared_list = _get_list_or_404(event, list_id)

    panels = _list_side_panels(event, shared_list)
    return render_template(
        "lists/detail.html",
        event=event,
        shared_list=shared_list,
        items=_list_items(shared_list),
        errors=[],
        form_data={},
        **panels,
    )


@lists_bp.route("/e/<code>/lists/<list_id>/items", methods=["POST"])
@limiter.limit("20 per hour")
def add_item(code: str, list_id: str) -> Response | tuple[str, int] | str:
    """Add an item to a shared list."""
    ctx = load_event_context(code)
    event = ctx.event
    shared_list = _get_list_or_404(event, list_id)

    name = request.form.get("name", "").strip()
    quantity = request.form.get("quantity", "").strip() or "1"
    section = request.form.get("section", "").strip()
    assigned_to = request.form.get("assigned_to", "").strip()

    errors: list[str] = []
    if len(name) < 1:
        errors.append(_("Nom requis."))
    elif len(name) > 300:
        errors.append(_("Nom trop long (max 300)."))
    if len(quantity) > 50:
        errors.append(_("Quantité trop longue (max 50)."))
    if len(section) > 100:
        errors.append(_("Section trop longue (max 100)."))
    if len(assigned_to) > 50:
        errors.append(_("Nom trop long (max 50)."))

    if errors:
        panels = _list_side_panels(event, shared_list)
        return render_template(
            "lists/detail.html",
            event=event,
            shared_list=shared_list,
            items=_list_items(shared_list),
            errors=errors,
            form_data={
                "name": name,
                "quantity": quantity,
                "section": section,
                "assigned_to": assigned_to,
            },
            **panels,
        )

    assigned_to_id = None
    if assigned_to:
        matches = Guest.query.filter_by(
            event_id=event.id, is_active=True, display_name=assigned_to
        ).all()
        if len(matches) == 1:
            assigned_to_id = matches[0].id
    item = ListItem(
        name=name,
        quantity=quantity,
        section=section,
        assigned_to=assigned_to,
        assigned_to_id=assigned_to_id,
        list_id=shared_list.id,
    )
    db.session.add(item)
    log_event(ctx, "list_item.created", target=name, details=shared_list.title)
    db.session.commit()

    flash(_("Article ajouté."))
    return redirect(url_for("lists.detail", code=code, list_id=shared_list.id))


@lists_bp.route("/e/<code>/lists/<list_id>/items/<item_id>/toggle", methods=["POST"])
def toggle_item(code: str, list_id: str, item_id: str) -> Response | tuple[str, int] | str:
    """Toggle an item's is_done flag."""
    ctx = load_event_context(code)
    event = ctx.event
    shared_list = _get_list_or_404(event, list_id)
    item = _get_item_or_404(shared_list, item_id)

    item.is_done = not item.is_done
    log_event(ctx, "list_item.toggled", target=item.name, details="done" if item.is_done else "undone")
    db.session.commit()

    return redirect(url_for("lists.detail", code=code, list_id=shared_list.id))


@lists_bp.route("/e/<code>/lists/<list_id>/items/<item_id>/delete", methods=["POST"])
def delete_item(code: str, list_id: str, item_id: str) -> Response | tuple[str, int] | str:
    """Delete an item from a shared list."""
    ctx = load_event_context(code)
    event = ctx.event
    shared_list = _get_list_or_404(event, list_id)
    item = _get_item_or_404(shared_list, item_id)

    name = item.name
    db.session.delete(item)
    log_event(ctx, "list_item.deleted", target=name, details=shared_list.title)
    db.session.commit()

    flash(_("Article supprimé."))
    return redirect(url_for("lists.detail", code=code, list_id=shared_list.id))


@lists_bp.route("/e/<code>/lists/<list_id>/items/<item_id>/claim", methods=["POST"])
def claim_item(code: str, list_id: str, item_id: str) -> Response | tuple[str, int] | str:
    """Self-assign an item to the current actor (to-do list)."""
    ctx = load_event_context(code)
    event = ctx.event
    shared_list = _get_list_or_404(event, list_id)
    item = _get_item_or_404(shared_list, item_id)

    item.assigned_to = ctx.actor.name
    item.assigned_to_id = ctx.participant.id if ctx.participant else None
    log_event(ctx, "list_item.claimed", target=item.name, details=shared_list.title)
    db.session.commit()

    flash(_("Vous vous êtes attribué cet article."))
    return redirect(url_for("lists.detail", code=code, list_id=shared_list.id))


@lists_bp.route("/e/<code>/lists/<list_id>/items/<item_id>/unclaim", methods=["POST"])
def unclaim_item(code: str, list_id: str, item_id: str) -> Response | tuple[str, int] | str:
    """Release a self-assigned item (assignee or creator only)."""
    ctx = load_event_context(code)
    event = ctx.event
    shared_list = _get_list_or_404(event, list_id)
    item = _get_item_or_404(shared_list, item_id)

    if not ctx.can_edit(item):
        abort(403)

    item.assigned_to = ""
    item.assigned_to_id = None
    log_event(ctx, "list_item.unclaimed", target=item.name, details=shared_list.title)
    db.session.commit()

    flash(_("Article libéré."))
    return redirect(url_for("lists.detail", code=code, list_id=shared_list.id))


@lists_bp.route("/e/<code>/lists/<list_id>/delete", methods=["POST"])
def delete_list(code: str, list_id: str) -> Response | tuple[str, int] | str:
    """Delete a shared list (creator only, items cascade)."""
    ctx = load_event_context(code)
    event = ctx.event
    shared_list = _get_list_or_404(event, list_id)
    if not ctx.can_delete(shared_list):
        abort(403)

    title = shared_list.title
    db.session.delete(shared_list)
    log_event(ctx, "list.deleted", target=title)
    db.session.commit()

    flash(_("Liste supprimée."))
    return redirect(url_for("lists.index", code=code))


@lists_bp.route("/e/<code>/lists/<list_id>/meals/<meal_id>/toggle", methods=["POST"])
def toggle_meal(code: str, list_id: str, meal_id: str) -> Response:
    """Toggle a meal as covered by this list."""
    ctx = load_event_context(code)
    event = ctx.event
    shared_list = _get_list_or_404(event, list_id)

    covered = shared_list.covered_meals or []
    if meal_id in covered:
        covered.remove(meal_id)
    else:
        covered.append(meal_id)
    shared_list.covered_meals = covered
    db.session.commit()
    return redirect(request.referrer or url_for("lists.detail", code=code, list_id=list_id))


@lists_bp.route("/e/<code>/lists/<list_id>/activities/<activity_id>/toggle", methods=["POST"])
def toggle_activity(code: str, list_id: str, activity_id: str) -> Response:
    """Toggle an activity as covered by this list."""
    ctx = load_event_context(code)
    event = ctx.event
    shared_list = _get_list_or_404(event, list_id)

    covered = shared_list.covered_activities or []
    if activity_id in covered:
        covered.remove(activity_id)
    else:
        covered.append(activity_id)
    shared_list.covered_activities = covered
    db.session.commit()
    return redirect(request.referrer or url_for("lists.detail", code=code, list_id=list_id))
