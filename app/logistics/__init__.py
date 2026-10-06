"""Logistics blueprint — infos pratiques (B005)."""

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
from app.i18n import is_valid
from app.models import LogisticsItem

logistics_bp = Blueprint("logistics", __name__)

MAX_TITLE = 200
MAX_CONTENT = 5000


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

    if not is_valid("info_category", category):
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
    ctx = load_event_context(code)
    event = ctx.event

    items = (
        LogisticsItem.query.filter_by(event_id=event.id)
        .order_by(LogisticsItem.category.asc(), LogisticsItem.order.asc())
        .all()
    )

    return render_template(
        "logistics/index.html",
        event=event,
        items=items,
    )


@logistics_bp.route("/e/<code>/logistics/new", methods=["GET", "POST"])
@limiter.limit("20 per hour")
def create(code: str) -> Response | str:
    """Create a new practical info item."""
    ctx = load_event_context(code)
    event = ctx.event

    if request.method == "GET":
        return render_template(
            "logistics/form.html",
            event=event,
            item=None,
            form_data={},
            errors=[],
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
    log_event(ctx, "logistics.created", target=title)
    db.session.commit()

    flash(_("Info pratique créée."))
    return redirect(url_for("logistics.index", code=code))


@logistics_bp.route("/e/<code>/logistics/<item_id>/edit", methods=["GET", "POST"])
def edit(code: str, item_id: str) -> Response | tuple[str, int] | str:
    """Edit an existing practical info item.

    Collaborative: any participant (creator or guest) may complete or fix the
    practical info (address, access, timing…). Deletion stays creator-only.
    """
    ctx = load_event_context(code)
    event = ctx.event
    item = LogisticsItem.query.filter_by(id=item_id, event_id=event.id).first()
    if item is None:
        abort(404)

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
            action_url=action_url,
        )

    item.title = title
    item.content = content
    item.category = category
    item.order = order
    log_event(ctx, "logistics.updated", target=title)
    db.session.commit()

    flash(_("Info pratique modifiée."))
    return redirect(url_for("logistics.index", code=code))


@logistics_bp.route("/e/<code>/logistics/<item_id>/delete", methods=["POST"])
def delete(code: str, item_id: str) -> Response | tuple[str, int] | str:
    """Delete a practical info item (creator only)."""
    ctx = load_event_context(code)
    event = ctx.event
    item = LogisticsItem.query.filter_by(id=item_id, event_id=event.id).first()
    if item is None:
        abort(404)
    if not ctx.can_delete(item):
        abort(403)

    title = item.title
    db.session.delete(item)
    log_event(ctx, "logistics.deleted", target=title)
    db.session.commit()

    flash(_("Info pratique supprimée."))
    return redirect(url_for("logistics.index", code=code))
