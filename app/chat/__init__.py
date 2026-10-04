"""Chat blueprint — chat par événement (B008)."""

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
from app.models import ChatMessage, Event, Guest
from app.utils import log_action

chat_bp = Blueprint("chat", __name__)

MAX_MESSAGES = 50
MAX_CONTENT_LENGTH = 2000


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
    """(actor_name, actor_type) for ChatMessage / ActivityLog entries."""
    if is_creator:
        return (current_user.display_name or "Créateur"), "creator"
    if guest is not None:
        return guest.display_name, "guest"
    return "Système", "system"


def _recent_messages(event: Event) -> list[ChatMessage]:
    """The 50 most recent messages, oldest first (display order)."""
    messages = (
        ChatMessage.query.filter_by(event_id=event.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(MAX_MESSAGES)
        .all()
    )
    return list(reversed(messages))


def _can_delete(event: Event, message: ChatMessage, guest: Guest | None) -> bool:
    """Event creator or the message's author may delete it."""
    if current_user.is_authenticated and current_user.id == event.creator_id:
        return True
    return guest is not None and message.guest_id == guest.id


def _is_htmx() -> bool:
    return request.headers.get("HX-Request") == "true"


@chat_bp.route("/e/<code>/chat")
def index(code: str) -> Response | str:
    """Event chat history (50 latest messages, ascending)."""
    event = _get_event_or_404(code)
    guest, _, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    messages = _recent_messages(event)

    def can_delete(message: ChatMessage) -> bool:
        return _can_delete(event, message, guest)

    if _is_htmx():
        return render_template(
            "chat/_messages.html", event=event, messages=messages, can_delete=can_delete
        )

    return render_template(
        "chat/index.html", event=event, messages=messages, guest=guest, can_delete=can_delete
    )


@chat_bp.route("/e/<code>/chat/send", methods=["POST"])
def send(code: str) -> Response | str:
    """Send a chat message (content 1-2000 chars, stripped)."""
    event = _get_event_or_404(code)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    content = request.form.get("content", "").strip()
    if not content:
        flash(_("Message vide."))
        return redirect(url_for("chat.index", code=code))
    if len(content) > MAX_CONTENT_LENGTH:
        flash(_("Message trop long (max 2000)."))
        return redirect(url_for("chat.index", code=code))

    author_name, author_type = _actor_name(guest, is_creator)
    db.session.add(
        ChatMessage(
            content=content,
            guest_id=guest.id if guest is not None else None,
            author_name=author_name,
            author_type=author_type,
            event_id=event.id,
        )
    )
    log_action(db.session, event.id, author_name, author_type, "chat.message", target=content[:50])
    db.session.commit()

    if _is_htmx():

        def can_delete(message: ChatMessage) -> bool:
            return _can_delete(event, message, guest)

        return render_template(
            "chat/_messages.html",
            event=event,
            messages=_recent_messages(event),
            can_delete=can_delete,
        )

    return redirect(url_for("chat.index", code=code))


@chat_bp.route("/e/<code>/chat/<msg_id>/delete", methods=["POST"])
def delete(code: str, msg_id: str) -> Response | tuple[str, int]:
    """Delete a message (moderation: author or event creator)."""
    event = _get_event_or_404(code)
    message = ChatMessage.query.filter_by(id=msg_id, event_id=event.id).first()
    if message is None:
        abort(404)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied
    if not _can_delete(event, message, guest):
        return _("Pas autorisé."), 403

    db.session.delete(message)
    actor_name, actor_type = _actor_name(guest, is_creator)
    log_action(
        db.session,
        event.id,
        actor_name,
        actor_type,
        "chat.message_deleted",
        target=message.content[:50],
    )
    db.session.commit()

    flash(_("Message supprimé."))
    return redirect(url_for("chat.index", code=code))
