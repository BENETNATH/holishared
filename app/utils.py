"""Shared helpers for holishared."""

import secrets

from flask_sqlalchemy.session import Session as FlaskSession
from sqlalchemy.orm import Session, scoped_session

from app.extensions import db
from app.models import ActivityLog, Creator, Event, Guest, Household


def log_action(
    db_session: scoped_session[FlaskSession] | Session,
    event_id: str,
    actor_name: str,
    actor_type: str,
    action: str,
    target: str | None = None,
    details: str | None = None,
) -> ActivityLog:
    """Créer un ActivityLog (sans commit).

    Le caller fait db.session.commit() une seule fois après avoir
    ajouté l'entité principale + le log.
    """
    log = ActivityLog(
        event_id=event_id,
        actor_name=actor_name,
        actor_type=actor_type,
        action=action,
        target=target,
        details=details,
    )
    db_session.add(log)
    return log


def ensure_creator_guest(
    event: Event,
    creator: Creator,
    num_adults: int = 1,
    num_children: int = 0,
) -> Guest:
    """Ensure the creator has a participant identity for this event.

    The creator is a participant in their own event: they can vote, RSVP to
    activities, and appear in the groups (households). This lazily creates
    their ``Guest`` record (linked via ``creator_id``) and a ``Household`` if
    they don't exist yet, then returns the Guest.

    The Guest code is a random 16-char token (not guessable, not used by the
    creator who accesses the event via their personal code).

    If new records are created, they are committed immediately so the creator's
    identity persists even when this is called from a read-only (GET) route.
    """
    created = False
    guest = Guest.query.filter_by(
        creator_id=creator.id, event_id=event.id, is_active=True
    ).first()
    if guest is None:
        guest = Guest(
            code=secrets.token_hex(8),
            display_name=creator.display_name or "Créateur",
            event_id=event.id,
            creator_id=creator.id,
        )
        db.session.add(guest)
        db.session.flush()
        created = True

    # Ensure a Household exists for the creator (so they appear in the groups).
    household = Household.query.filter_by(guest_id=guest.id, event_id=event.id).first()
    if household is None:
        household = Household(
            name=f"Foyer {guest.display_name}",
            num_adults=max(1, num_adults),
            num_children=max(0, num_children),
            event_id=event.id,
            guest_id=guest.id,
        )
        db.session.add(household)
        db.session.flush()
        created = True

    if created:
        db.session.commit()

    return guest
