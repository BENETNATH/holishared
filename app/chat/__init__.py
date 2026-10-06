"""Chat blueprint — chat par événement (B008)."""

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
from app.models import ChatMessage, Event

chat_bp = Blueprint("chat", __name__)

MAX_MESSAGES = 50
MAX_CONTENT_LENGTH = 2000


def _recent_messages(event: Event) -> list[ChatMessage]:
    """The 50 most recent messages, oldest first (display order)."""
    messages = (
        ChatMessage.query.filter_by(event_id=event.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(MAX_MESSAGES)
        .all()
    )
    return list(reversed(messages))


def _is_htmx() -> bool:
    return request.headers.get("HX-Request") == "true"


@chat_bp.route("/e/<code>/chat")
def index(code: str) -> Response | str:
    """Event chat history (50 latest messages, ascending)."""
    event = load_event_context(code).event

    messages = _recent_messages(event)

    if _is_htmx():
        return render_template("chat/_messages.html", event=event, messages=messages)

    return render_template("chat/index.html", event=event, messages=messages)


@chat_bp.route("/e/<code>/chat/send", methods=["POST"])
@limiter.limit("30 per minute")
def send(code: str) -> Response | str:
    """Send a chat message (content 1-2000 chars, stripped)."""
    ctx = load_event_context(code)
    event = ctx.event
    participant = ctx.participant
    if participant is None:  # garanti par require="participant"
        abort(403)

    content = request.form.get("content", "").strip()
    if not content:
        flash(_("Message vide."))
        return redirect(url_for("chat.index", code=code))
    if len(content) > MAX_CONTENT_LENGTH:
        flash(_("Message trop long (max 2000)."))
        return redirect(url_for("chat.index", code=code))

    db.session.add(
        ChatMessage(
            content=content,
            guest_id=participant.id,
            author_name=ctx.actor.name,
            author_type=ctx.actor.type,
            event_id=event.id,
        )
    )
    log_event(ctx, "chat.message", target=content[:50])
    db.session.commit()

    if _is_htmx():
        return render_template(
            "chat/_messages.html", event=event, messages=_recent_messages(event)
        )

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

    flash(_("Message supprimé."))
    return redirect(url_for("chat.index", code=code))
