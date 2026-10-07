"""Logistics blueprint — infos pratiques (B005, B025b)."""

import json

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
from werkzeug.wrappers import Response

from app.context import EventContext, load_event_context, log_event
from app.extensions import db, limiter
from app.forms import FormErrors
from app.i18n import is_valid
from app.infos import linkify, ordered_infos
from app.models import LogisticsItem

logistics_bp = Blueprint("logistics", __name__)
logistics_bp.add_app_template_filter(linkify, "linkify")

MAX_TITLE = 200
MAX_CONTENT = 5000
SHEET_FORM_ID = "info-sheet-form"
LIST_ID = "infos-list"


def _htmx() -> bool:
    return request.headers.get("HX-Request") == "true"


def _validate_form() -> tuple[FormErrors, dict[str, str], tuple[str, str, str]]:
    """Validate the logistics form.

    Returns (errors, form_data, fields) where form_data holds the raw
    strings for re-rendering and fields the typed values (only meaningful
    when errors is empty). L'ordre d'affichage n'est plus saisissable (B025b).
    """
    errors = FormErrors()
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    category = request.form.get("category", "").strip() or "general"

    if len(title) < 2:
        errors.add("title", _("Titre requis (min 2 caractères)."))
    elif len(title) > MAX_TITLE:
        errors.add("title", _("Titre trop long (max 200)."))

    if not content:
        errors.add("content", _("Contenu requis."))
    elif len(content) > MAX_CONTENT:
        errors.add("content", _("Contenu trop long (max 5000)."))

    if not is_valid("info_category", category):
        errors.add("category", _("Catégorie invalide."))

    form_data = {"title": title, "content": content, "category": category}
    return errors, form_data, (title, content, category)


def _groups(event_id: str) -> list[tuple[str, list[LogisticsItem]]]:
    groups: dict[str, list[LogisticsItem]] = {}
    for item in ordered_infos(event_id):
        groups.setdefault(item.category or "general", []).append(item)
    return list(groups.items())


def _list_html(ctx: EventContext) -> str:
    return render_template(
        "logistics/_list.html", ctx=ctx, event=ctx.event, groups=_groups(ctx.event.id)
    )


def _list_response(ctx: EventContext, message: str) -> Response:
    """Fragment de liste à jour + toast (réponse HTMX)."""
    response = make_response(_list_html(ctx))
    response.headers["HX-Trigger"] = json.dumps(
        {"ui:toast": {"message": message, "tone": "success"}}, ensure_ascii=True
    )
    return response


def _form_error_response(
    ctx: EventContext, item: LogisticsItem | None, form_data: dict[str, str], errors: FormErrors
) -> Response:
    """Formulaire de la feuille re-rendu avec les erreurs par champ (remplace le formulaire)."""
    html = render_template(
        "logistics/_sheet_form.html", event=ctx.event, item=item, form_data=form_data, errors=errors
    )
    response = make_response(html)
    response.headers["HX-Retarget"] = f"#{SHEET_FORM_ID}"
    response.headers["HX-Reswap"] = "outerHTML"
    return response


def _page(
    ctx: EventContext, item: LogisticsItem | None, form_data: dict[str, str], errors: FormErrors
) -> str:
    action = (
        url_for("logistics.edit", code=ctx.event.code, item_id=item.id)
        if item
        else url_for("logistics.create", code=ctx.event.code)
    )
    return render_template(
        "logistics/form.html",
        event=ctx.event,
        item=item,
        form_data=form_data,
        errors=errors,
        action_url=action,
    )


@logistics_bp.route("/e/<code>/logistics")
def index(code: str) -> Response | str:
    """Infos pratiques en cartes, groupées par catégorie (ordre logique)."""
    ctx = load_event_context(code)
    return render_template(
        "logistics/index.html",
        ctx=ctx,
        event=ctx.event,
        groups=_groups(ctx.event.id),
        item=None,
        form_data={},
        errors=FormErrors(),
    )


@logistics_bp.route("/e/<code>/logistics/new", methods=["GET", "POST"])
@limiter.limit("20 per hour", methods=["POST"])
def create(code: str) -> Response | str:
    """Create a new practical info item."""
    ctx = load_event_context(code)
    event = ctx.event

    if request.method == "GET":
        return _page(ctx, None, {}, FormErrors())

    errors, form_data, (title, content, category) = _validate_form()
    if errors:
        if _htmx():
            return _form_error_response(ctx, None, form_data, errors)
        return _page(ctx, None, form_data, errors)

    item = LogisticsItem(title=title, content=content, category=category, event_id=event.id)
    db.session.add(item)
    log_event(ctx, "logistics.created", target=title)
    db.session.commit()

    if _htmx():
        return _list_response(ctx, _("Info pratique créée."))
    flash(_("Info pratique créée."))
    return redirect(url_for("logistics.index", code=code))


@logistics_bp.route("/e/<code>/logistics/<item_id>/edit", methods=["GET", "POST"])
def edit(code: str, item_id: str) -> Response | tuple[str, int] | str:
    """Edit an existing practical info item.

    Collaborative: any participant (creator or guest) may complete or fix the
    practical info (address, access, timing…). Deletion stays creator-only.
    """
    ctx = load_event_context(code)
    item = LogisticsItem.query.filter_by(id=item_id, event_id=ctx.event.id).first()
    if item is None:
        abort(404)

    if request.method == "GET":
        form_data = {"title": item.title, "content": item.content, "category": item.category}
        return _page(ctx, item, form_data, FormErrors())

    errors, form_data, (title, content, category) = _validate_form()
    if errors:
        if _htmx():
            return _form_error_response(ctx, item, form_data, errors)
        return _page(ctx, item, form_data, errors)

    item.title = title
    item.content = content
    item.category = category
    log_event(ctx, "logistics.updated", target=title)
    db.session.commit()

    if _htmx():
        return _list_response(ctx, _("Info pratique modifiée."))
    flash(_("Info pratique modifiée."))
    return redirect(url_for("logistics.index", code=code))


@logistics_bp.route("/e/<code>/logistics/<item_id>/delete", methods=["POST"])
def delete(code: str, item_id: str) -> Response | tuple[str, int] | str:
    """Delete a practical info item (creator only)."""
    ctx = load_event_context(code)
    item = LogisticsItem.query.filter_by(id=item_id, event_id=ctx.event.id).first()
    if item is None:
        abort(404)
    if not ctx.can_delete(item):
        abort(403)

    title = item.title
    db.session.delete(item)
    log_event(ctx, "logistics.deleted", target=title)
    db.session.commit()

    if _htmx():
        return _list_response(ctx, _("Info pratique supprimée."))
    flash(_("Info pratique supprimée."))
    return redirect(url_for("logistics.index", code=code))
