"""Chat blueprint — chat par événement (B008, B025b).

Page : les 50 derniers messages. Fragments ``<li>`` (HTMX/fetch) :
``?after=<id>&ts=<iso>`` = messages plus récents que le curseur (polling incrémental),
``?before=<id>`` = les 50 messages précédents. L'ordre est (created_at, id).
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

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
from sqlalchemy import and_, or_
from werkzeug.wrappers import Response

from app.context import EventContext, load_event_context, log_event
from app.extensions import db, limiter
from app.models import ChatMessage
from app.push import notify

chat_bp = Blueprint("chat", __name__)

PAGE_SIZE = 50
AFTER_CAP = 100
MAX_CONTENT_LENGTH = 2000
GROUP_SECONDS = 300


@dataclass
class Row:
    msg: ChatMessage
    mine: bool
    continued: bool  # même auteur, même jour, moins de 5 minutes après le message précédent
    new_day: bool  # séparateur de date à afficher avant le message
    author: str


def _is_htmx() -> bool:
    return request.headers.get("HX-Request") == "true"


def _author_key(msg: ChatMessage) -> str:
    return msg.guest_id or f"{msg.author_type}:{msg.author_name}"


def _rows(
    ctx: EventContext, messages: list[ChatMessage], prev: ChatMessage | None = None
) -> list[Row]:
    rows: list[Row] = []
    me = ctx.participant.id if ctx.participant else None
    for msg in messages:
        new_day = prev is None or prev.created_at.date() != msg.created_at.date()
        continued = (
            prev is not None
            and not new_day
            and _author_key(prev) == _author_key(msg)
            and (msg.created_at - prev.created_at).total_seconds() <= GROUP_SECONDS
        )
        rows.append(Row(msg, bool(me and msg.guest_id == me), continued, new_day, _author_key(msg)))
        prev = msg
    return rows


def _before(msg: ChatMessage) -> object:
    return or_(
        ChatMessage.created_at < msg.created_at,
        and_(ChatMessage.created_at == msg.created_at, ChatMessage.id < msg.id),
    )


def _query(ctx: EventContext) -> Any:
    return ChatMessage.query.filter_by(event_id=ctx.event.id)


def _latest(ctx: EventContext, cut: object = None) -> list[ChatMessage]:
    """Les 50 messages les plus récents (avant ``cut`` si fourni), du plus ancien au plus récent."""
    q = _query(ctx)
    if cut is not None:
        q = q.filter(cut)
    found = q.order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(PAGE_SIZE).all()
    return list(reversed(found))


def _has_older(ctx: EventContext, first: ChatMessage | None) -> bool:
    return first is not None and _query(ctx).filter(_before(first)).first() is not None


def _newer(ctx: EventContext, after: str, ts: str) -> tuple[list[ChatMessage], ChatMessage | None]:
    """Messages postérieurs au curseur ; repli sur l'horodatage si le message a disparu."""
    cursor = _query(ctx).filter_by(id=after).first() if after else None
    if cursor is not None:
        cond = or_(
            ChatMessage.created_at > cursor.created_at,
            and_(ChatMessage.created_at == cursor.created_at, ChatMessage.id > cursor.id),
        )
    else:
        try:
            moment = datetime.fromisoformat(ts).replace(tzinfo=None)
        except ValueError:
            return [], None
        cond = ChatMessage.created_at > moment
    found = (
        _query(ctx)
        .filter(cond)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .limit(AFTER_CAP)
        .all()
    )
    return found, cursor


def _fragment(ctx: EventContext, rows: list[Row], **headers: str) -> Response:
    response = make_response(
        render_template("chat/_messages.html", ctx=ctx, event=ctx.event, rows=rows)
    )
    response.headers.update(headers)
    return response


def _toast(message: str, status: int, tone: str = "danger") -> Response:
    response = make_response("", status)
    response.headers["HX-Trigger"] = json.dumps(
        {"ui:toast": {"message": message, "tone": tone}}, ensure_ascii=True
    )
    return response


@chat_bp.route("/e/<code>/chat")
def index(code: str) -> Response | str:
    """Page du chat, ou fragment ``<li>`` (``after``, ``before``, requête HTMX)."""
    ctx = load_event_context(code)

    if "after" in request.args:
        found, cursor = _newer(ctx, request.args["after"], request.args.get("ts", ""))
        return _fragment(ctx, _rows(ctx, found, cursor))

    cut = None
    if request.args.get("before"):
        anchor = _query(ctx).filter_by(id=request.args["before"]).first()
        cut = _before(anchor) if anchor is not None else ChatMessage.id.is_(None)
    messages = _latest(ctx, cut)
    rows = _rows(ctx, messages)

    if _is_htmx():
        more = _has_older(ctx, messages[0] if messages else None)
        return _fragment(ctx, rows, **{"X-Chat-Has-More": "true" if more else "false"})

    return render_template(
        "chat/index.html",
        ctx=ctx,
        event=ctx.event,
        rows=rows,
        older_id=messages[0].id if _has_older(ctx, messages[0] if messages else None) else None,
    )


@chat_bp.route("/e/<code>/chat/send", methods=["POST"])
@limiter.limit("30 per minute")
def send(code: str) -> Response | str:
    """Send a chat message (content 1-2000 chars, stripped)."""
    ctx = load_event_context(code)
    participant = ctx.participant
    if participant is None:  # garanti par require="participant"
        abort(403)

    content = request.form.get("content", "").strip()
    error = None
    if not content:
        error = _("Message vide.")
    elif len(content) > MAX_CONTENT_LENGTH:
        error = _("Message trop long (max 2000).")
    if error:
        if _is_htmx():
            return _toast(error, 422)
        flash(error)
        return redirect(url_for("chat.index", code=code))

    message = ChatMessage(
        content=content,
        guest_id=participant.id,
        author_name=ctx.actor.name,
        author_type=ctx.actor.type,
        event_id=ctx.event.id,
    )
    db.session.add(message)
    log_event(ctx, "chat.message", target=content[:50])
    db.session.commit()
    notify(
        ctx.event, "chat", participant, content,
        url_for("chat.index", code=code), f"chat-{ctx.event.code}",
    )

    if _is_htmx():
        # Tout ce qui est arrivé depuis le curseur du client, son message compris : aucun trou possible.
        found, cursor = _newer(ctx, request.form.get("after", ""), request.form.get("ts", ""))
        if message not in found:
            found.append(message)
        return _fragment(ctx, _rows(ctx, found, cursor))
    return redirect(url_for("chat.index", code=code))


@chat_bp.route("/e/<code>/chat/<msg_id>/delete", methods=["POST"])
def delete(code: str, msg_id: str) -> Response | tuple[str, int]:
    """Delete a message (moderation: author or event creator)."""
    ctx = load_event_context(code)
    message = ChatMessage.query.filter_by(id=msg_id, event_id=ctx.event.id).first()
    if message is None:
        abort(404)
    if not ctx.can_delete(message):
        abort(403)

    db.session.delete(message)
    log_event(ctx, "chat.message_deleted", target=message.content[:50])
    db.session.commit()

    if _is_htmx():
        return _toast(_("Message supprimé."), 200, "success")
    flash(_("Message supprimé."))
    return redirect(url_for("chat.index", code=code))
