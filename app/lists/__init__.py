"""Lists blueprint — listes partagées (B004)."""

import json
from datetime import date, time
from typing import Any, cast

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_babel import _
from flask_wtf.csrf import generate_csrf
from sqlalchemy import case, func, or_
from sqlalchemy.exc import IntegrityError
from werkzeug.wrappers import Response

from app.context import EventContext, load_event_context, log_event
from app.extensions import db, limiter
from app.forms import FormErrors
from app.i18n import is_valid
from app.models import (
    Activity,
    Event,
    Guest,
    ListActivityCoverage,
    ListItem,
    ListMealCoverage,
    Meal,
    SharedList,
)

lists_bp = Blueprint("lists", __name__)


def _get_list_or_404(event: Event, list_id: str) -> SharedList:
    """Load a shared list belonging to the event or abort with 404."""
    shared_list = cast(
        "SharedList | None", SharedList.query.filter_by(id=list_id, event_id=event.id).first()
    )
    if shared_list is None:
        abort(404)
    return shared_list


def _get_item_or_404(shared_list: SharedList, item_id: str) -> ListItem:
    """Load a list item belonging to the list or abort with 404."""
    item = cast(
        "ListItem | None", ListItem.query.filter_by(id=item_id, list_id=shared_list.id).first()
    )
    if item is None:
        abort(404)
    return item


def _list_items(shared_list: SharedList) -> list[ListItem]:
    return cast(
        "list[ListItem]", cast("Any", shared_list.items).order_by(ListItem.created_at.asc()).all()
    )


ITEMS_ID = "list-items"
PANEL_ID = "list-panel-content"
MODES = ("all", "meals", "activities")
UNDO_SECONDS = 8


HOME_UNASSIGNED_LIMIT = 5


def home_items(ctx: EventContext) -> dict[str, Any]:
    """Données du bloc « Pour moi » / « À répartir » de l'accueil (B020a, 20.7)."""
    lists = SharedList.query.filter_by(event_id=ctx.event.id).order_by(SharedList.created_at).all()
    by_id = {lst.id: lst for lst in lists}
    groups: dict[str, dict[str, Any]] = {}
    total = taken = 0
    if ctx.participant is not None:
        mine = (
            ListItem.query.filter(
                ListItem.list_id.in_(by_id), ListItem.assigned_to_id == ctx.participant.id
            )
            .order_by(ListItem.created_at)
            .all()
        )
        for item in mine:
            group = groups.setdefault(
                item.list_id, {"list": by_id[item.list_id], "open": [], "done": []}
            )
            group["done" if item.is_done else "open"].append(item)
            taken += int(item.is_done)
        total = len(mine)
    free = ListItem.query.filter(
        ListItem.list_id.in_(by_id),
        ListItem.is_done.is_(False),
        or_(ListItem.assigned_to_id.is_(None), ListItem.assigned_to == ""),
    )
    return {
        "groups": sorted(groups.values(), key=lambda g: g["list"].created_at),
        "total": total,
        "taken": taken,
        "unassigned": [
            (item, by_id[item.list_id])
            for item in free.order_by(ListItem.created_at).limit(HOME_UNASSIGNED_LIMIT)
        ],
        "unassigned_total": free.count(),
    }


def _is_htmx() -> bool:
    return request.headers.get("HX-Request") == "true"


def _module_on(name: str) -> bool:
    return name in current_app.config["ENABLED_MODULES"] and name in current_app.blueprints


def _home_fragment(ctx: EventContext) -> str:
    return render_template("events/_my_items.html", event=ctx.event, **home_items(ctx))


def _htmx_headers(response: Response, *, reswap: str | None = None, **events: Any) -> Response:
    """En-têtes HTMX : `HX-Trigger` en JSON ASCII (les en-têtes HTTP sont en latin-1)."""
    if events:
        response.headers["HX-Trigger"] = json.dumps(events, ensure_ascii=True)
    if reswap:
        response.headers["HX-Reswap"] = reswap
    return response


def _htmx_toast(message: str, tone: str = "danger") -> Response:
    """Erreur de validation HTMX : rien n'est remplacé, un toast s'affiche (module ui/htmx)."""
    response = make_response("", 200)
    return _htmx_headers(
        response, reswap="none", **{"ui:toast": {"message": message, "tone": tone}}
    )


def _items_context(ctx: EventContext, shared_list: SharedList) -> dict[str, Any]:
    """Articles non cochés groupés par section (ordre d'apparition, sans section en dernier), puis cochés."""
    items = _list_items(shared_list)
    sections: dict[str, list[ListItem]] = {}
    for item in items:
        if not item.is_done:
            sections.setdefault(item.section or "", []).append(item)
    named = [{"name": name, "rows": rows} for name, rows in sections.items() if name]
    if "" in sections:
        named.append({"name": "", "rows": sections[""]})
    return {
        "event": ctx.event,
        "shared_list": shared_list,
        "groups": named,
        "has_sections": any(group["name"] for group in named),
        "done_items": [i for i in items if i.is_done],
        "section_names": sorted({i.section for i in items if i.section}, key=str.casefold),
        "item_total": len(items),
    }


def _items_fragment(ctx: EventContext, shared_list: SharedList) -> str:
    return render_template("lists/_items.html", ctx=ctx, **_items_context(ctx, shared_list))


def _item_response(
    ctx: EventContext, shared_list: SharedList, message: str | None = None, **events: Any
) -> Response:
    """HTMX : fragment de la liste (cible `#list-items`) ou de l'accueil ; sinon redirection."""
    if _is_htmx():
        html = (
            _items_fragment(ctx, shared_list)
            if request.headers.get("HX-Target") == ITEMS_ID
            else _home_fragment(ctx)
        )
        return _htmx_headers(make_response(html), **events)
    if message:
        flash(message)
    return redirect(url_for("lists.detail", code=ctx.event.code, list_id=shared_list.id))


def _list_stats(list_ids: list[str]) -> dict[str, tuple[int, int]]:
    """list_id -> (cochés, total) en une requête."""
    if not list_ids:
        return {}
    rows = (
        db.session.query(
            ListItem.list_id,
            func.count(ListItem.id),
            func.coalesce(func.sum(case((ListItem.is_done.is_(True), 1), else_=0)), 0),
        )
        .filter(ListItem.list_id.in_(list_ids))
        .group_by(ListItem.list_id)
        .all()
    )
    return {list_id: (int(done), int(total)) for list_id, total, done in rows}


@lists_bp.route("/e/<code>/lists", methods=["GET", "POST"])
def index(code: str) -> Response | tuple[str, int] | str:
    """Cartes des listes de l'événement + création rapide."""
    ctx = load_event_context(code)
    event = ctx.event

    errors = FormErrors()
    form_title = ""
    form_type = "general"
    if request.method == "POST":
        form_title = request.form.get("title", "").strip()
        form_type = request.form.get("list_type", "general")
        if not is_valid("list_type", form_type):
            form_type = "general"
        if len(form_title) < 2:
            errors.add("title", _("Titre requis (min 2 caractères)."))
        elif len(form_title) > 200:
            errors.add("title", _("Titre trop long (max 200)."))
        if not errors:
            shared_list = SharedList(title=form_title, list_type=form_type, event_id=event.id)
            db.session.add(shared_list)
            log_event(ctx, "list.created", target=form_title)
            db.session.commit()
            flash(_("Liste créée."))
            return redirect(url_for("lists.index", code=code))

    lists = (
        SharedList.query.filter_by(event_id=event.id).order_by(SharedList.created_at.asc()).all()
    )
    stats = _list_stats([lst.id for lst in lists])
    return render_template(
        "lists/index.html",
        event=event,
        cards=[(lst, *stats.get(lst.id, (0, 0))) for lst in lists],
        errors=errors,
        form_title=form_title,
        form_type=form_type,
    )


@lists_bp.route("/e/<code>/lists/new")
def create(code: str) -> Response:
    """Legacy: creation is now inline on the index page."""
    return redirect(url_for("lists.index", code=code))


# --- Panneau « Repas & activités » (B023, contrat §11.5.3) --------------------------------

_SLOT_TIME = {"lunch": time(12, 0), "dinner": time(20, 0)}


def _panel_context(
    ctx: EventContext, shared_list: SharedList, mode: str = "all", hide: bool = False
) -> dict[str, Any]:
    """Repas et activités par jour, avec leur état « pris en compte » pour cette liste."""
    event = ctx.event
    meals_on, acts_on = _module_on("meals"), _module_on("planning")
    covered_meals = {
        row[0]
        for row in db.session.query(ListMealCoverage.meal_id).filter_by(list_id=shared_list.id)
    }
    covered_acts = {
        row[0]
        for row in db.session.query(ListActivityCoverage.activity_id).filter_by(
            list_id=shared_list.id
        )
    }
    meals = (
        Meal.query.filter_by(event_id=event.id).order_by(*Meal.ordering()).all() if meals_on else []
    )
    acts = (
        Activity.query.filter(Activity.event_id == event.id, Activity.status != "dropped")
        .order_by(Activity.date.asc(), Activity.start_time.asc().nulls_last(), Activity.created_at)
        .all()
        if acts_on
        else []
    )
    total = len(meals) + len(acts)
    covered = sum(m.id in covered_meals for m in meals) + sum(a.id in covered_acts for a in acts)
    available = {"meals": meals_on, "activities": acts_on}
    if mode not in MODES or (mode != "all" and not available[mode]):
        mode = "all"
    days: dict[date, list[tuple[tuple[Any, ...], dict[str, Any]]]] = {}
    if mode in ("all", "meals"):
        for position, meal in enumerate(meals):
            row = {"kind": "meal", "obj": meal, "covered": meal.id in covered_meals}
            key = (_SLOT_TIME.get(meal.slot, time(12, 0)), 0, position)
            days.setdefault(meal.date, []).append((key, row))
    if mode in ("all", "activities"):
        for position, act in enumerate(acts):
            row = {"kind": "activity", "obj": act, "covered": act.id in covered_acts}
            key = (act.start_time or time(23, 59), 1, position)
            days.setdefault(act.date, []).append((key, row))
    today = date.today()
    grouped = []
    for day in sorted(days):
        rows = [
            r
            for _key, r in sorted(days[day], key=lambda pair: pair[0])
            if not (hide and r["covered"])
        ]
        if rows:
            grouped.append({"date": day, "rows": rows, "past": day < today, "today": day == today})
    return {
        "event": event,
        "shared_list": shared_list,
        "days": grouped,
        "mode": mode,
        "hide": hide,
        "available": available,
        "covered_count": covered,
        "total_count": total,
        "has_content": bool(meals or acts),
        "empty_all": total == 0,
    }


def _panel_fragment(ctx: EventContext, shared_list: SharedList, mode: str, hide: bool) -> str:
    return render_template(
        "lists/_panel.html", ctx=ctx, oob=True, **_panel_context(ctx, shared_list, mode, hide)
    )


def _panel_args() -> tuple[str, bool]:
    source = request.form if request.method == "POST" else request.args
    return source.get("mode", "all"), source.get("hide") == "1"


@lists_bp.route("/e/<code>/lists/<list_id>/panel")
def panel(code: str, list_id: str) -> str:
    """Fragment HTMX du panneau (changement de filtre ou de bascule)."""
    ctx = load_event_context(code)
    shared_list = _get_list_or_404(ctx.event, list_id)
    mode, hide = _panel_args()
    return _panel_fragment(ctx, shared_list, mode, hide)


def _detail_page(
    ctx: EventContext, shared_list: SharedList, errors: FormErrors, form_data: dict[str, Any]
) -> str:
    return render_template(
        "lists/detail.html",
        ctx=ctx,
        errors=errors,
        form_data=form_data,
        oob=False,
        **{**_items_context(ctx, shared_list), **_panel_context(ctx, shared_list)},
    )


@lists_bp.route("/e/<code>/lists/<list_id>")
def detail(code: str, list_id: str) -> Response | tuple[str, int] | str:
    """Une liste : articles, ajout rapide et panneau « Repas & activités » à la demande."""
    ctx = load_event_context(code)
    shared_list = _get_list_or_404(ctx.event, list_id)
    return _detail_page(ctx, shared_list, FormErrors(), {})


def _parse_item_form(form: Any, event: Event) -> tuple[dict[str, Any], FormErrors]:
    name = form.get("name", "").strip()
    quantity = form.get("quantity", "").strip() or "1"
    section = form.get("section", "").strip()
    assigned_to = form.get("assigned_to", "").strip()
    errors = FormErrors()
    if len(name) < 1:
        errors.add("name", _("Nom requis."))
    elif len(name) > 300:
        errors.add("name", _("Nom trop long (max 300)."))
    if len(quantity) > 50:
        errors.add("quantity", _("Quantité trop longue (max 50)."))
    if len(section) > 100:
        errors.add("section", _("Section trop longue (max 100)."))
    if len(assigned_to) > 50:
        errors.add("assigned_to", _("Nom trop long (max 50)."))
    assigned_to_id = None
    if assigned_to and not errors:
        matches = Guest.query.filter_by(
            event_id=event.id, is_active=True, display_name=assigned_to
        ).all()
        if len(matches) == 1:
            assigned_to_id = matches[0].id
    values = {
        "name": name,
        "quantity": quantity,
        "section": section,
        "assigned_to": assigned_to,
        "assigned_to_id": assigned_to_id,
    }
    return values, errors


@lists_bp.route("/e/<code>/lists/<list_id>/items", methods=["POST"])
@limiter.limit("200 per hour")
def add_item(code: str, list_id: str) -> Response | tuple[str, int] | str:
    """Ajoute un article (nom ; quantité et section facultatives)."""
    ctx = load_event_context(code)
    shared_list = _get_list_or_404(ctx.event, list_id)
    values, errors = _parse_item_form(request.form, ctx.event)

    if errors:
        if _is_htmx():
            return _htmx_toast(errors.remaining()[0])
        return _detail_page(ctx, shared_list, errors, values)

    item = ListItem(
        **values,
        list_id=shared_list.id,
        created_by=ctx.participant.id if ctx.participant else None,
    )
    db.session.add(item)
    log_event(ctx, "list_item.created", target=values["name"], details=shared_list.title)
    db.session.commit()
    return _item_response(ctx, shared_list, _("Article ajouté."))


@lists_bp.route("/e/<code>/lists/<list_id>/items/restore", methods=["POST"])
@limiter.limit("200 per hour")
def restore_item(code: str, list_id: str) -> Response | tuple[str, int] | str:
    """Annulation d'une suppression : recrée l'article (même nom, quantité, section, coche)."""
    ctx = load_event_context(code)
    shared_list = _get_list_or_404(ctx.event, list_id)
    values, errors = _parse_item_form(request.form, ctx.event)
    if errors:
        abort(400)
    # L'attribution n'est rétablie que pour soi-même ; le créateur peut rétablir celle d'un autre.
    wanted = request.form.get("assigned_to_id", "")
    assignee = None
    if ctx.participant is not None and wanted:
        if wanted == ctx.participant.id or ctx.is_creator:
            assignee = Guest.query.filter_by(
                id=wanted, event_id=ctx.event.id, is_active=True
            ).first()
    values["assigned_to"] = assignee.display_name if assignee else ""
    values["assigned_to_id"] = assignee.id if assignee else None
    author = ctx.participant.id if ctx.participant else None
    if ctx.is_creator:
        original = Guest.query.filter_by(
            id=request.form.get("created_by", ""), event_id=ctx.event.id
        ).first()
        author = original.id if original else author
    item = ListItem(
        **values,
        is_done=request.form.get("is_done") == "1",
        list_id=shared_list.id,
        created_by=author,
    )
    db.session.add(item)
    log_event(ctx, "list_item.restored", target=values["name"], details=shared_list.title)
    db.session.commit()
    return _item_response(ctx, shared_list, _("Article rétabli."))


@lists_bp.route("/e/<code>/lists/<list_id>/items/<item_id>/toggle", methods=["POST"])
def toggle_item(code: str, list_id: str, item_id: str) -> Response | tuple[str, int] | str:
    """Coche/décoche un article, sans attribution préalable (refusé s'il est pris par un autre)."""
    ctx = load_event_context(code)
    shared_list = _get_list_or_404(ctx.event, list_id)
    item = _get_item_or_404(shared_list, item_id)

    if item.assigned_to_id is not None and not ctx.can_edit(item):
        abort(403)

    wanted = request.form.get("is_done")
    item.is_done = (wanted == "1") if wanted in ("0", "1") else not item.is_done
    log_event(
        ctx, "list_item.toggled", target=item.name, details="done" if item.is_done else "undone"
    )
    db.session.commit()
    return _item_response(ctx, shared_list)


@lists_bp.route("/e/<code>/lists/<list_id>/items/<item_id>/delete", methods=["POST"])
def delete_item(code: str, list_id: str, item_id: str) -> Response | tuple[str, int] | str:
    """Supprime un article (son auteur ou le créateur) ; HTMX : toast d'annulation."""
    ctx = load_event_context(code)
    shared_list = _get_list_or_404(ctx.event, list_id)
    item = _get_item_or_404(shared_list, item_id)
    if not ctx.can_delete(item):
        abort(403)

    undo = {
        "name": item.name,
        "quantity": item.quantity,
        "section": item.section,
        "is_done": "1" if item.is_done else "0",
        "assigned_to_id": item.assigned_to_id or "",
        "created_by": item.created_by or "",
        "csrf_token": generate_csrf(),
    }
    db.session.delete(item)
    log_event(ctx, "list_item.deleted", target=undo["name"], details=shared_list.title)
    db.session.commit()
    toast = {
        "message": _("Article supprimé."),
        "tone": "info",
        "timeout": UNDO_SECONDS * 1000,
        "action": {
            "label": _("Annuler"),
            "post": url_for("lists.restore_item", code=ctx.event.code, list_id=shared_list.id),
            "values": undo,
            "target": f"#{ITEMS_ID}",
            "swap": "outerHTML",
        },
    }
    return _item_response(ctx, shared_list, _("Article supprimé."), **{"ui:toast": toast})


@lists_bp.route("/e/<code>/lists/<list_id>/items/<item_id>/claim", methods=["POST"])
def claim_item(code: str, list_id: str, item_id: str) -> Response | tuple[str, int] | str:
    """« Je m'occupe » : attribution facultative à soi-même."""
    ctx = load_event_context(code)
    shared_list = _get_list_or_404(ctx.event, list_id)
    item = _get_item_or_404(shared_list, item_id)

    if item.assigned_to_id is not None and not ctx.can_edit(item):
        abort(403)

    item.assigned_to = ctx.actor.name
    item.assigned_to_id = ctx.participant.id if ctx.participant else None
    log_event(ctx, "list_item.claimed", target=item.name, details=shared_list.title)
    db.session.commit()
    return _item_response(ctx, shared_list, _("Vous vous êtes attribué cet article."))


@lists_bp.route("/e/<code>/lists/<list_id>/items/<item_id>/unclaim", methods=["POST"])
def unclaim_item(code: str, list_id: str, item_id: str) -> Response | tuple[str, int] | str:
    """Libère un article (la personne concernée ou le créateur)."""
    ctx = load_event_context(code)
    shared_list = _get_list_or_404(ctx.event, list_id)
    item = _get_item_or_404(shared_list, item_id)

    if not ctx.can_edit(item):
        abort(403)

    item.assigned_to = ""
    item.assigned_to_id = None
    log_event(ctx, "list_item.unclaimed", target=item.name, details=shared_list.title)
    db.session.commit()
    return _item_response(ctx, shared_list, _("Article libéré."))


@lists_bp.route("/e/<code>/lists/<list_id>/delete", methods=["POST"])
def delete_list(code: str, list_id: str) -> Response | tuple[str, int] | str:
    """Supprime une liste (créateur ; articles et couvertures en cascade)."""
    ctx = load_event_context(code)
    shared_list = _get_list_or_404(ctx.event, list_id)
    if not ctx.can_delete(shared_list):
        abort(403)

    title = shared_list.title
    db.session.delete(shared_list)
    log_event(ctx, "list.deleted", target=title)
    db.session.commit()

    flash(_("Liste supprimée."))
    return redirect(url_for("lists.index", code=code))


def _toggle_coverage(
    code: str, list_id: str, target_id: str, kind: str
) -> Response | tuple[str, int] | str:
    """Ajoute/retire la ligne de couverture (idempotent avec `covered=0|1`) ; HTMX : fragment du panneau."""
    ctx = load_event_context(code)
    shared_list = _get_list_or_404(ctx.event, list_id)
    meal = kind == "meal"
    if not _module_on("meals" if meal else "planning"):
        abort(404)
    target = (
        (Meal if meal else Activity).query.filter_by(id=target_id, event_id=ctx.event.id).first()
    )
    if target is None:
        abort(404)
    model: Any = ListMealCoverage if meal else ListActivityCoverage
    column = "meal_id" if meal else "activity_id"
    row = model.query.filter_by(**{"list_id": shared_list.id, column: target.id}).first()
    wanted = request.form.get("covered")
    covered = (wanted == "1") if wanted in ("0", "1") else row is None
    if covered and row is None:
        db.session.add(
            model(
                **{
                    "list_id": shared_list.id,
                    column: target.id,
                    "covered_by": ctx.participant.id if ctx.participant else None,
                }
            )
        )
    elif not covered and row is not None:
        db.session.delete(row)
    if covered != (row is not None):
        log_event(
            ctx,
            f"list.{kind}_{'covered' if covered else 'uncovered'}",
            target=target.title,
            details=shared_list.title,
        )
    try:
        db.session.commit()
    except (
        IntegrityError
    ):  # double clic concurrent : la couverture existe déjà, l'opération est idempotente
        db.session.rollback()
    if _is_htmx():
        mode, hide = _panel_args()
        return _panel_fragment(ctx, shared_list, mode, hide)
    return redirect(url_for("lists.detail", code=code, list_id=list_id))


@lists_bp.route("/e/<code>/lists/<list_id>/meals/<meal_id>/toggle", methods=["POST"])
def toggle_meal(code: str, list_id: str, meal_id: str) -> Response | tuple[str, int] | str:
    """Cette liste prend en compte (ou non) ce repas."""
    return _toggle_coverage(code, list_id, meal_id, "meal")


@lists_bp.route("/e/<code>/lists/<list_id>/activities/<activity_id>/toggle", methods=["POST"])
def toggle_activity(code: str, list_id: str, activity_id: str) -> Response | tuple[str, int] | str:
    """Cette liste prend en compte (ou non) cette activité."""
    return _toggle_coverage(code, list_id, activity_id, "activity")
