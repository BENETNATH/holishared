"""Logistics blueprint — infos pratiques (B005)."""

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

from app.extensions import db
from app.models import Event, Guest, LogisticsItem
from app.utils import log_action

logistics_bp = Blueprint("logistics", __name__)

CATEGORIES = frozenset({"address", "access", "timing", "docs", "notes", "general"})

CATEGORY_LABELS = {
    "address": "Adresse",
    "access": "Accès / Parking",
    "timing": "Horaires",
    "docs": "Documents",
    "notes": "Notes diverses",
    "general": "Divers",
}

MAX_TITLE = 200
MAX_CONTENT = 5000


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


def _category_labels() -> dict[str, str]:
    """Translated category labels, in display order."""
    return {key: _(label) for key, label in CATEGORY_LABELS.items()}


def _validate_form() -> tuple[list[str], dict[str, str], tuple[str, str, str, int]]:
    """Validate the logistics form.

    Returns (errors, form_data, fields) where form_data holds the raw
    strings for re-rendering and fields the typed values (only meaningful
    when errors is empty).
    """
    errors: list[str] = []
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    category = request.form.get("category", "").strip() or "general"
    order_raw = request.form.get("order", "").strip()

    if len(title) < 2:
        errors.append(_("Titre requis (min 2 caractères)."))
    elif len(title) > MAX_TITLE:
        errors.append(_("Titre trop long (max 200)."))

    if not content:
        errors.append(_("Contenu requis."))
    elif len(content) > MAX_CONTENT:
        errors.append(_("Contenu trop long (max 5000)."))

    if category not in CATEGORIES:
        errors.append(_("Catégorie invalide."))

    order = 0
    if order_raw:
        try:
            order = int(order_raw)
        except ValueError:
            errors.append(_("Ordre invalide."))

    form_data = {
        "title": title,
        "content": content,
        "category": category,
        "order": order_raw or "0",
    }
    return errors, form_data, (title, content, category, order)


@logistics_bp.route("/e/<code>/logistics")
def index(code: str) -> Response | str:
    """List the event's practical info, grouped by category."""
    event = _get_event_or_404(code)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    items = (
        LogisticsItem.query.filter_by(event_id=event.id)
        .order_by(LogisticsItem.category.asc(), LogisticsItem.order.asc())
        .all()
    )

    return render_template(
        "logistics/index.html",
        event=event,
        items=items,
        guest=guest,
        is_creator=is_creator,
        category_labels=_category_labels(),
    )


@logistics_bp.route("/e/<code>/logistics/new", methods=["GET", "POST"])
def create(code: str) -> Response | str:
    """Create a new practical info item."""
    event = _get_event_or_404(code)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    if request.method == "GET":
        return render_template(
            "logistics/form.html",
            event=event,
            item=None,
            form_data={},
            errors=[],
            category_labels=_category_labels(),
            action_url=url_for("logistics.create", code=code),
        )

    errors, form_data, (title, content, category, order) = _validate_form()
    if errors:
        return render_template(
            "logistics/form.html",
            event=event,
            item=None,
            form_data=form_data,
            errors=errors,
            category_labels=_category_labels(),
            action_url=url_for("logistics.create", code=code),
        )

    item = LogisticsItem(
        title=title,
        content=content,
        category=category,
        order=order,
        event_id=event.id,
    )
    db.session.add(item)
    actor_name, actor_type = _actor_name(guest, is_creator)
    log_action(db.session, event.id, actor_name, actor_type, "logistics.created", target=title)
    db.session.commit()

    flash(_("Info pratique créée."))
    return redirect(url_for("logistics.index", code=code))


@logistics_bp.route("/e/<code>/logistics/<item_id>/edit", methods=["GET", "POST"])
def edit(code: str, item_id: str) -> Response | tuple[str, int] | str:
    """Edit an existing practical info item (creator only)."""
    event = _get_event_or_404(code)
    item = LogisticsItem.query.filter_by(id=item_id, event_id=event.id).first()
    if item is None:
        abort(404)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied
    if not is_creator:
        return _("Pas autorisé."), 403

    action_url = url_for("logistics.edit", code=code, item_id=item.id)

    if request.method == "GET":
        form_data = {
            "title": item.title,
            "content": item.content,
            "category": item.category,
            "order": str(item.order),
        }
        return render_template(
            "logistics/form.html",
            event=event,
            item=item,
            form_data=form_data,
            errors=[],
            category_labels=_category_labels(),
            action_url=action_url,
        )

    errors, form_data, (title, content, category, order) = _validate_form()
    if errors:
        return render_template(
            "logistics/form.html",
            event=event,
            item=item,
            form_data=form_data,
            errors=errors,
            category_labels=_category_labels(),
            action_url=action_url,
        )

    item.title = title
    item.content = content
    item.category = category
    item.order = order
    actor_name, actor_type = _actor_name(guest, is_creator)
    log_action(db.session, event.id, actor_name, actor_type, "logistics.updated", target=title)
    db.session.commit()

    flash(_("Info pratique modifiée."))
    return redirect(url_for("logistics.index", code=code))


@logistics_bp.route("/e/<code>/logistics/<item_id>/delete", methods=["POST"])
def delete(code: str, item_id: str) -> Response | tuple[str, int] | str:
    """Delete a practical info item (creator only)."""
    event = _get_event_or_404(code)
    item = LogisticsItem.query.filter_by(id=item_id, event_id=event.id).first()
    if item is None:
        abort(404)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied
    if not is_creator:
        return _("Pas autorisé."), 403

    title = item.title
    db.session.delete(item)
    actor_name, actor_type = _actor_name(guest, is_creator)
    log_action(db.session, event.id, actor_name, actor_type, "logistics.deleted", target=title)
    db.session.commit()

    flash(_("Info pratique supprimée."))
    return redirect(url_for("logistics.index", code=code))
