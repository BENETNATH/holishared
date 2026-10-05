"""Lists blueprint — listes partagées (B004)."""

from typing import Any, cast

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
from app.models import Activity, Event, Guest, ListItem, Meal, SharedList
from app.utils import log_action

lists_bp = Blueprint("lists", __name__)

LIST_TYPE_CHOICES = ["general", "shopping", "packing", "materials", "buffet", "todo"]
LIST_TYPES = frozenset(LIST_TYPE_CHOICES)


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


def _actor_name(guest: Guest | None, is_creator: bool) -> tuple[str, str]:
    """(actor_name, actor_type) for ActivityLog entries."""
    if is_creator:
        return (current_user.display_name or "Créateur"), "creator"
    if guest is not None:
        return guest.display_name, "guest"
    return "Système", "system"


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


@lists_bp.route("/e/<code>/lists")
def index(code: str) -> Response | tuple[str, int] | str:
    """List the event's shared lists."""
    event = _get_event_or_404(code)
    guest, _, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    lists = (
        SharedList.query.filter_by(event_id=event.id)
        .order_by(SharedList.created_at.asc())
        .all()
    )
    return render_template("lists/index.html", event=event, lists=lists, guest=guest)


@lists_bp.route("/e/<code>/lists/new", methods=["GET", "POST"])
def create(code: str) -> Response | tuple[str, int] | str:
    """Create a new shared list."""
    event = _get_event_or_404(code)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    if request.method == "GET":
        return render_template(
            "lists/form.html",
            event=event,
            form_data={},
            errors=[],
            list_types=LIST_TYPE_CHOICES,
        )

    title = request.form.get("title", "").strip()
    list_type = request.form.get("list_type", "").strip()
    if list_type not in LIST_TYPES:
        list_type = "general"

    errors: list[str] = []
    if len(title) < 2:
        errors.append(_("Titre requis (min 2 caractères)."))
    elif len(title) > 200:
        errors.append(_("Titre trop long (max 200)."))

    if errors:
        return render_template(
            "lists/form.html",
            event=event,
            form_data={"title": title, "list_type": list_type},
            errors=errors,
            list_types=LIST_TYPE_CHOICES,
        )

    shared_list = SharedList(title=title, list_type=list_type, event_id=event.id)
    db.session.add(shared_list)
    actor_name, actor_type = _actor_name(guest, is_creator)
    log_action(db.session, event.id, actor_name, actor_type, "list.created", target=title)
    db.session.commit()

    flash(_("Liste créée."))
    return redirect(url_for("lists.index", code=code))


@lists_bp.route("/e/<code>/lists/<list_id>")
def detail(code: str, list_id: str) -> Response | tuple[str, int] | str:
    """Show a shared list with its items + meal plan side panel."""
    event = _get_event_or_404(code)
    shared_list = _get_list_or_404(event, list_id)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    # Side panels: meals + activities, with cross-list coverage.
    # An item is hidden from this list's panel once ANOTHER list has checked
    # it off (so you can track what's already been noted/bought).
    all_lists = SharedList.query.filter_by(event_id=event.id).all()
    meal_covered_by: dict[str, set[str]] = {}
    act_covered_by: dict[str, set[str]] = {}
    for lst in all_lists:
        for mid in (lst.covered_meals or []):
            meal_covered_by.setdefault(mid, set()).add(lst.id)
        for aid in (lst.covered_activities or []):
            act_covered_by.setdefault(aid, set()).add(lst.id)

    meals = (
        Meal.query.filter_by(event_id=event.id)
        .order_by(Meal.date.asc(), Meal.slot.asc())
        .all()
    )
    meal_acts = [
        m for m in meals
        if shared_list.id in meal_covered_by.get(m.id, set()) or not meal_covered_by.get(m.id)
    ]

    activities = (
        Activity.query.filter_by(event_id=event.id)
        .order_by(Activity.date.asc(), Activity.start_time.asc().nulls_last())
        .all()
    )
    act_acts = [
        a for a in activities
        if shared_list.id in act_covered_by.get(a.id, set()) or not act_covered_by.get(a.id)
    ]

    covered_meal_ids = set(shared_list.covered_meals or [])
    covered_act_ids = set(shared_list.covered_activities or [])

    return render_template(
        "lists/detail.html",
        event=event,
        shared_list=shared_list,
        items=_list_items(shared_list),
        guest=guest,
        is_creator=is_creator,
        errors=[],
        form_data={},
        meal_acts=meal_acts,
        act_acts=act_acts,
        covered_meal_ids=covered_meal_ids,
        covered_act_ids=covered_act_ids,
    )


@lists_bp.route("/e/<code>/lists/<list_id>/items", methods=["POST"])
@limiter.limit("20 per hour")
def add_item(code: str, list_id: str) -> Response | tuple[str, int] | str:
    """Add an item to a shared list."""
    event = _get_event_or_404(code)
    shared_list = _get_list_or_404(event, list_id)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

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
        return render_template(
            "lists/detail.html",
            event=event,
            shared_list=shared_list,
            items=_list_items(shared_list),
            guest=guest,
            is_creator=is_creator,
            errors=errors,
            form_data={
                "name": name,
                "quantity": quantity,
                "section": section,
                "assigned_to": assigned_to,
            },
        )

    item = ListItem(
        name=name,
        quantity=quantity,
        section=section,
        assigned_to=assigned_to,
        list_id=shared_list.id,
    )
    db.session.add(item)
    actor_name, actor_type = _actor_name(guest, is_creator)
    log_action(
        db.session,
        event.id,
        actor_name,
        actor_type,
        "list_item.created",
        target=name,
        details=shared_list.title,
    )
    db.session.commit()

    flash(_("Article ajouté."))
    return redirect(url_for("lists.detail", code=code, list_id=shared_list.id))


@lists_bp.route("/e/<code>/lists/<list_id>/items/<item_id>/toggle", methods=["POST"])
def toggle_item(code: str, list_id: str, item_id: str) -> Response | tuple[str, int] | str:
    """Toggle an item's is_done flag."""
    event = _get_event_or_404(code)
    shared_list = _get_list_or_404(event, list_id)
    item = _get_item_or_404(shared_list, item_id)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    item.is_done = not item.is_done
    actor_name, actor_type = _actor_name(guest, is_creator)
    log_action(
        db.session,
        event.id,
        actor_name,
        actor_type,
        "list_item.toggled",
        target=item.name,
        details="done" if item.is_done else "undone",
    )
    db.session.commit()

    return redirect(url_for("lists.detail", code=code, list_id=shared_list.id))


@lists_bp.route("/e/<code>/lists/<list_id>/items/<item_id>/delete", methods=["POST"])
def delete_item(code: str, list_id: str, item_id: str) -> Response | tuple[str, int] | str:
    """Delete an item from a shared list."""
    event = _get_event_or_404(code)
    shared_list = _get_list_or_404(event, list_id)
    item = _get_item_or_404(shared_list, item_id)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    name = item.name
    db.session.delete(item)
    actor_name, actor_type = _actor_name(guest, is_creator)
    log_action(
        db.session,
        event.id,
        actor_name,
        actor_type,
        "list_item.deleted",
        target=name,
        details=shared_list.title,
    )
    db.session.commit()

    flash(_("Article supprimé."))
    return redirect(url_for("lists.detail", code=code, list_id=shared_list.id))


@lists_bp.route("/e/<code>/lists/<list_id>/items/<item_id>/claim", methods=["POST"])
def claim_item(code: str, list_id: str, item_id: str) -> Response | tuple[str, int] | str:
    """Self-assign an item to the current actor (to-do list)."""
    event = _get_event_or_404(code)
    shared_list = _get_list_or_404(event, list_id)
    item = _get_item_or_404(shared_list, item_id)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    actor_name, actor_type = _actor_name(guest, is_creator)
    actor_id = guest.id if guest else (current_user.id if is_creator else "")
    item.assigned_to = actor_name
    item.assigned_to_id = actor_id
    log_action(
        db.session, event.id, actor_name, actor_type,
        "list_item.claimed", target=item.name, details=shared_list.title,
    )
    db.session.commit()

    flash(_("Vous vous êtes attribué cet article."))
    return redirect(url_for("lists.detail", code=code, list_id=shared_list.id))


@lists_bp.route("/e/<code>/lists/<list_id>/items/<item_id>/unclaim", methods=["POST"])
def unclaim_item(code: str, list_id: str, item_id: str) -> Response | tuple[str, int] | str:
    """Release a self-assigned item (assignee or creator only)."""
    event = _get_event_or_404(code)
    shared_list = _get_list_or_404(event, list_id)
    item = _get_item_or_404(shared_list, item_id)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    actor_name, actor_type = _actor_name(guest, is_creator)
    actor_id = guest.id if guest else (current_user.id if is_creator else "")
    if not is_creator and item.assigned_to_id != actor_id:
        return _("Pas autorisé."), 403

    item.assigned_to = ""
    item.assigned_to_id = None
    log_action(
        db.session, event.id, actor_name, actor_type,
        "list_item.unclaimed", target=item.name, details=shared_list.title,
    )
    db.session.commit()

    flash(_("Article libéré."))
    return redirect(url_for("lists.detail", code=code, list_id=shared_list.id))


@lists_bp.route("/e/<code>/lists/<list_id>/delete", methods=["POST"])
def delete_list(code: str, list_id: str) -> Response | tuple[str, int] | str:
    """Delete a shared list (creator only, items cascade)."""
    event = _get_event_or_404(code)
    shared_list = _get_list_or_404(event, list_id)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied
    if not is_creator:
        return _("Pas autorisé."), 403

    title = shared_list.title
    db.session.delete(shared_list)
    actor_name, actor_type = _actor_name(guest, is_creator)
    log_action(db.session, event.id, actor_name, actor_type, "list.deleted", target=title)
    db.session.commit()

    flash(_("Liste supprimée."))
    return redirect(url_for("lists.index", code=code))


@lists_bp.route("/e/<code>/lists/<list_id>/meals/<meal_id>/toggle", methods=["POST"])
def toggle_meal(code: str, list_id: str, meal_id: str) -> Response:
    """Toggle a meal as covered by this list."""
    event = _get_event_or_404(code)
    shared_list = _get_list_or_404(event, list_id)
    _guest, _is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

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
    event = _get_event_or_404(code)
    shared_list = _get_list_or_404(event, list_id)
    _guest, _is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    covered = shared_list.covered_activities or []
    if activity_id in covered:
        covered.remove(activity_id)
    else:
        covered.append(activity_id)
    shared_list.covered_activities = covered
    db.session.commit()
    return redirect(request.referrer or url_for("lists.detail", code=code, list_id=list_id))
