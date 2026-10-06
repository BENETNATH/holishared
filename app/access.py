"""Codes d'accès : suggestion, résolution, limitation des échecs (B029)."""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from flask import Response, g, request
from flask_limiter.util import get_remote_address
from limits import parse

from app.extensions import limiter
from app.models import Creator, Event, Guest, generate_guest_code

security_log = logging.getLogger("app.security")

CodeKind = Literal["event", "creator", "guest"]

IP_FAILURE_LIMIT = "20 per 15 minutes;50 per day"  # par IP, en tout (3 routes, un compteur)
TARGET_FAILURE_LIMIT = "5 per minute;10 per 15 minutes;15 per hour;30 per day"  # par (IP, cible)
TARGET_ALERT_THRESHOLD = "50 per hour"  # alerte par cible, jamais de 429
JOIN_CREATION_LIMIT = "20 per hour"  # créations d'invités réussies par IP (/join)


@dataclass(frozen=True)
class CodeMatch:
    kind: CodeKind
    event: Event | None
    creator: Creator | None
    guest: Guest | None


def normalize_code(raw: str) -> str:
    return raw.strip().lower()


def is_code_format(code: str) -> bool:
    return 4 <= len(code) <= 8 and re.fullmatch(r"[a-z0-9]+", code) is not None


def resolve_home_code(raw: str) -> CodeMatch | None:
    """Code saisi à l'accueil : événement d'abord (les codes d'événement circulent), puis créateur."""
    code = normalize_code(raw)
    if not is_code_format(code):
        return None
    if len(code) == 6:
        event = Event.query.filter(
            Event.code == code, Event.is_active.is_(True), Event.verified_at.isnot(None)
        ).first()
        if event is not None:
            return CodeMatch("event", event, None, None)
    creator = Creator.query.filter_by(personal_code=code).first()
    if creator is not None:
        return CodeMatch("creator", None, creator, None)
    return None


def resolve_event_code(event: Event, raw: str) -> CodeMatch | None:
    """Code saisi sur la page /mycode d'un événement : créateur de l'événement, puis invité."""
    code = normalize_code(raw)
    if not is_code_format(code):
        return None
    creator = event.creator
    if creator.personal_code == code:
        return CodeMatch("creator", event, creator, None)
    guest = Guest.query.filter_by(
        event_id=event.id, code=code, is_active=True, creator_id=None
    ).first()
    if guest is not None:
        return CodeMatch("guest", event, None, guest)
    return None


def _suggest(used: Callable[[str], bool]) -> str:
    for _ in range(5):
        code = generate_guest_code(8)
        if not used(code):
            return code
    raise RuntimeError("could not generate an unused access code")


def suggest_creator_code() -> str:
    return _suggest(lambda c: Creator.query.filter_by(personal_code=c).first() is not None)


def suggest_guest_code(event: Event) -> str:
    return _suggest(lambda c: Guest.query.filter_by(event_id=event.id, code=c).first() is not None)


def ip_event_key() -> str:
    return f"{get_remote_address()}:event:{(request.view_args or {}).get('code', '')}"


def attempt_failed(response: Response) -> bool:
    return bool(g.get("code_attempt_failed", False))


IP_FAILURES = limiter.shared_limit(
    IP_FAILURE_LIMIT,
    scope="ip-failures",
    key_func=get_remote_address,
    methods=["POST"],
    deduct_when=attempt_failed,
)
EVENT_TARGET_FAILURES = limiter.shared_limit(
    TARGET_FAILURE_LIMIT,
    scope="event-target",
    key_func=ip_event_key,
    methods=["POST"],
    deduct_when=attempt_failed,
)


def mark_attempt_failed(scope: Literal["home", "event", "join"], event_code: str | None) -> None:
    """Compte un échec de code (le code saisi n'est jamais journalisé)."""
    g.code_attempt_failed = True
    security_log.warning(
        "code_attempt_failed scope=%s event=%s ip=%s",
        scope,
        event_code or "-",
        get_remote_address(),
    )
    try:
        within = limiter.limiter.hit(
            parse(TARGET_ALERT_THRESHOLD), "target-alert", event_code or "home"
        )
        if not within:
            security_log.warning("code_target_alert event=%s", event_code or "home")
    except Exception:
        security_log.warning("code_target_alert_failed", exc_info=True)


def join_creation_allowed() -> bool:
    """Compte une création d'invité réussie pour l'IP ; faux au-delà de la limite.

    Compteur distinct des échecs de code : ne gêne jamais une connexion ``/mycode``.
    """
    if not limiter.enabled:
        return True
    return bool(
        limiter.limiter.hit(parse(JOIN_CREATION_LIMIT), "join-created", get_remote_address())
    )


def log_code_login(kind: Literal["creator", "guest"], event_code: str | None) -> None:
    security_log.info("code_login kind=%s event=%s", kind, event_code or "-")
