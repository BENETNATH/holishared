"""Étapes de démarrage : migrations, purge RGPD, migration d'identité.

Chaque étape est indépendante : un échec est journalisé (``rollback``) et n'empêche jamais
les suivantes de s'exécuter.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta

from flask import Flask

from app.extensions import db
from app.models import Event

logger = logging.getLogger(__name__)

Step = tuple[str, Callable[[Flask], object]]


def purge_expired_events(app: Flask) -> int:
    """Supprime les événements terminés depuis plus de 30 jours ou non vérifiés depuis 3 jours.

    Un commit par événement : l'échec de l'un (journalisé avec son id) ne bloque pas les autres.
    """
    from app.migrations import prune_backups

    prune_backups(app.instance_path)
    now = datetime.utcnow()
    expired = {
        ev.id: ev
        for ev in Event.query.filter(
            Event.end_date.isnot(None),
            Event.end_date < date.today() - timedelta(days=30),
            Event.is_active.is_(True),
        ).all()
        + Event.query.filter(
            Event.verified_at.is_(None),
            Event.created_at < now - timedelta(days=3),
            Event.is_active.is_(True),
        ).all()
    }
    purged = 0
    for event_id, event in expired.items():
        try:
            db.session.delete(event)
            db.session.commit()
            purged += 1
        except Exception:
            db.session.rollback()
            logger.exception("purge failed event=%s", event_id)
    return purged


def default_steps() -> list[Step]:
    """Migrations (avant la purge : elle charge les lignes), purge, puis identité."""
    from app.migrations import (
        log_foreign_key_orphans,
        run_api_keys_migration,
        run_costs_migration,
        run_identity_migration,
        run_lists_migration,
        run_meals_migration,
        run_polls_migration,
        run_push_migration,
    )

    return [
        ("meals", run_meals_migration),
        ("lists", run_lists_migration),
        ("costs", run_costs_migration),
        ("polls", run_polls_migration),
        ("push", run_push_migration),
        ("api_keys", run_api_keys_migration),
        ("purge", purge_expired_events),
        ("identity", run_identity_migration),
        ("fk-check", log_foreign_key_orphans),  # lecture seule
    ]


def run_startup_steps(app: Flask, steps: Sequence[Step] | None = None) -> dict[str, bool]:
    """Exécute chaque étape dans son propre try/except ; renvoie ``{nom: réussie}``.

    ``SKIP_STARTUP_MIGRATION=1`` (p. ex. ``python -m app.migrations check``) ne lance rien.
    """
    if os.environ.get("SKIP_STARTUP_MIGRATION") == "1":
        return {}
    results: dict[str, bool] = {}
    for name, step in default_steps() if steps is None else steps:
        try:
            step(app)
            results[name] = True
        except Exception:
            db.session.rollback()
            logger.exception("startup step %s failed (continuing)", name)
            results[name] = False
    return results
