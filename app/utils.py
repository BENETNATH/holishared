"""Shared helpers for holishared."""

from flask_sqlalchemy.session import Session as FlaskSession
from sqlalchemy.orm import Session, scoped_session

from app.models import ActivityLog


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
