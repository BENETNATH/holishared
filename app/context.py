"""Contexte d'événement par requête : événement, participant, rôle, droits (B029)."""

import logging
from dataclasses import dataclass
from typing import Literal

from flask import Response, abort, g, redirect, request, session, url_for
from flask_login import current_user

from app.extensions import db
from app.models import (
    Activity,
    ActivityLog,
    ChatMessage,
    Creator,
    Event,
    Expense,
    Guest,
    Household,
    ListItem,
    LogisticsItem,
    Meal,
    MediaItem,
    PaymentRequest,
    Poll,
    SharedList,
    Transfer,
)

logger = logging.getLogger(__name__)

Role = Literal["creator", "guest", "visitor"]
ActorType = Literal["creator", "guest", "system"]
Requirement = Literal["participant", "creator", "none"]

SYSTEM_ACTOR_NAME = "Système"  # B018 remplace la valeur par SYSTEM_PLACEHOLDER ("@system")
CREATOR_FALLBACK_NAME = "Créateur"  # B018 remplace la valeur par CREATOR_PLACEHOLDER ("@creator")


@dataclass(frozen=True)
class Actor:
    name: str
    type: ActorType
    guest_id: str | None


SYSTEM_ACTOR = Actor(name=SYSTEM_ACTOR_NAME, type="system", guest_id=None)


def actor_for(participant: Guest | None) -> Actor:
    """None -> SYSTEM_ACTOR ; participant créateur -> "creator" ; sinon "guest"."""
    if participant is None:
        return SYSTEM_ACTOR
    kind: ActorType = "creator" if participant.creator_id is not None else "guest"
    return Actor(name=participant.display_name, type=kind, guest_id=participant.id)


# Droits (table §3.6) : (créateur seul | créateur ou auteur | participant | jamais).
_CREATOR = "creator"
_AUTHOR = "author"
_ANY = "participant"
_NEVER = "never"

# type -> (règle d'édition, règle de suppression, colonne d'auteur)
_RIGHTS: dict[type, tuple[str, str, str | None]] = {
    Activity: (_AUTHOR, _AUTHOR, "created_by"),
    Meal: (_AUTHOR, _AUTHOR, "created_by"),
    SharedList: (_NEVER, _CREATOR, None),
    ListItem: (_AUTHOR, _ANY, "assigned_to_id"),
    LogisticsItem: (_ANY, _CREATOR, None),
    Poll: (_CREATOR, _CREATOR, None),
    ChatMessage: (_NEVER, _AUTHOR, "guest_id"),
    MediaItem: (_NEVER, _AUTHOR, "uploaded_by"),
    Household: (_ANY, _CREATOR, None),
    Expense: (_NEVER, _CREATOR, None),
    Transfer: (_NEVER, _CREATOR, None),
    PaymentRequest: (_ANY, _CREATOR, None),
    Guest: (_CREATOR, _CREATOR, None),
    Event: (_CREATOR, _CREATOR, None),
}


@dataclass
class EventContext:
    event: Event
    participant: Guest | None
    is_creator: bool  # True <=> créateur de CET événement, connecté (flask-login)

    @property
    def role(self) -> Role:
        if self.is_creator:
            return "creator"
        return "guest" if self.participant is not None else "visitor"

    @property
    def actor(self) -> Actor:
        return actor_for(self.participant)

    def is_author(self, author_id: str | None) -> bool:
        return (
            self.participant is not None
            and author_id is not None
            and author_id == self.participant.id
        )

    def _allowed(self, obj: object, index: int) -> bool:
        rights = _RIGHTS.get(type(obj))
        if rights is None:
            raise TypeError(f"no rights defined for {type(obj).__name__}")
        if self.participant is None:
            return False
        rule = rights[index]
        if rule == _ANY:
            ok = True
        elif rule == _CREATOR:
            ok = self.is_creator
        elif rule == _AUTHOR:
            column = rights[2] or ""
            ok = self.is_creator or self.is_author(getattr(obj, column))
        else:
            ok = False
        if ok and index == 1 and isinstance(obj, Guest):
            return obj.creator_id is None
        return ok

    def can_edit(self, obj: object) -> bool:
        return self._allowed(obj, 0)

    def can_delete(self, obj: object) -> bool:
        return self._allowed(obj, 1)


def get_event_context() -> EventContext | None:
    """g.event_ctx s'il existe, sinon None. Aucune requête."""
    ctx: EventContext | None = g.get("event_ctx")
    return ctx


def reset_event_context() -> None:
    """Vide le cache de contexte et le drapeau d'échec de code (début de requête)."""
    g.pop("event_ctx", None)
    g.pop("code_attempt_failed", None)


def get_or_create_creator_participant(event: Event, creator: Creator) -> Guest:
    """Participant créateur canonique (I2) ; créé en secours, sans foyer, si absent."""
    guest = _canonical_creator_guest(event, creator)
    if guest is not None:
        return guest
    from app.utils import ensure_creator_guest

    ensure_creator_guest(event, creator, with_household=False)
    db.session.commit()
    logger.warning("creator participant backfilled event=%s", event.code)
    return _canonical_creator_guest(event, creator) or ensure_creator_guest(
        event, creator, with_household=False
    )


def _canonical_creator_guest(event: Event, creator: Creator) -> Guest | None:
    guest: Guest | None = (
        Guest.query.filter_by(creator_id=creator.id, event_id=event.id, is_active=True)
        .order_by(Guest.joined_at, Guest.id)
        .first()
    )
    return guest


def load_event_context(code: str, *, require: Requirement = "participant") -> EventContext:
    """Résout événement, participant et rôle ; refuse selon ``require`` (§3.3)."""
    cached = get_event_context()
    if cached is not None and cached.event.code == code:
        ctx = cached
    else:
        event = Event.query.filter_by(code=code, is_active=True).first()
        if event is None or event.verified_at is None:
            abort(404)
        is_creator = bool(current_user.is_authenticated and current_user.id == event.creator_id)
        participant: Guest | None = None
        if is_creator:
            participant = get_or_create_creator_participant(event, current_user)
        elif session.get(f"guest_{code}"):
            participant = Guest.query.filter_by(
                id=session.get(f"guest_{code}"),
                event_id=event.id,
                is_active=True,
                creator_id=None,
            ).first()
        ctx = EventContext(event, participant, is_creator)
        g.event_ctx = ctx
    if require != "none" and ctx.participant is None:
        url = url_for("events.my_code", code=ctx.event.code)
        if request.headers.get("HX-Request") == "true":
            abort(Response(status=204, headers={"HX-Redirect": url}))
        abort(redirect(url))
    if require == "creator" and not ctx.is_creator:
        abort(403)
    return ctx


def log_event(
    ctx: EventContext, action: str, target: str | None = None, details: str | None = None
) -> ActivityLog:
    """Journalise l'action de l'acteur du contexte. Sans commit."""
    from app.utils import log_action

    return log_action(
        db.session, ctx.event.id, ctx.actor.name, ctx.actor.type, action, target, details
    )
