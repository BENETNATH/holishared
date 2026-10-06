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
    *,
    with_household: bool = True,
) -> Guest:
    """Participant créateur de l'événement (idempotent, flush sans commit).

    Réutilise le participant canonique actif (le plus ancien), sinon réactive
    le plus récent inactif, sinon en crée un. Le foyer n'est créé que si
    ``with_household`` est vrai et qu'aucun foyer n'existe pour ce Guest.
    L'appelant valide la transaction.
    """
    from app.context import CREATOR_FALLBACK_NAME

    mine = Guest.query.filter_by(creator_id=creator.id, event_id=event.id)
    guest: Guest | None = mine.filter_by(is_active=True).order_by(Guest.joined_at, Guest.id).first()
    if guest is None:
        guest = mine.filter_by(is_active=False).order_by(Guest.joined_at.desc()).first()
        if guest is not None:
            guest.is_active = True
    if guest is None:
        guest = Guest(
            code=secrets.token_hex(8),
            display_name=(creator.display_name or CREATOR_FALLBACK_NAME)[:50],
            event_id=event.id,
            creator_id=creator.id,
        )
        db.session.add(guest)
    db.session.flush()

    if (
        with_household
        and Household.query.filter_by(guest_id=guest.id, event_id=event.id).first() is None
    ):
        db.session.add(
            Household(
                name=f"Foyer {guest.display_name}",
                num_adults=max(1, num_adults),
                num_children=max(0, num_children),
                event_id=event.id,
                guest_id=guest.id,
            )
        )
        db.session.flush()
    return guest
