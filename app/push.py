"""Notifications Web Push (B027) : abonnements, ciblage, payload minimal, mise en file RQ.

Le payload ne contient que le texte affiché (titre = nom de l'événement) et un lien : ni e-mail,
ni montant, ni identifiant de participant. L'envoi réel est fait par ``app.tasks.send_push``
(worker RQ, sans contexte Flask). Toute défaillance est journalisée, jamais remontée.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Any
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, jsonify, request
from werkzeug.wrappers import Response

from app.context import load_event_context
from app.extensions import db, limiter
from app.models import Event, Guest, PushSubscription
from app.tasks import _translations

logger = logging.getLogger(__name__)

push_bp = Blueprint("push", __name__)

MAX_SUBSCRIPTIONS = 5  # par participant
PREVIEW_LENGTH = 90
SUPPORTED_LANGS = ("fr", "en")
PREFERENCES = ("notify_chat", "notify_polls", "notify_requests", "show_preview")
KINDS = {"chat": "notify_chat", "polls": "notify_polls", "requests": "notify_requests"}


def push_enabled() -> bool:
    """Vrai si le serveur a des clés VAPID."""
    return bool(
        current_app.config.get("VAPID_PUBLIC_KEY") and current_app.config.get("VAPID_PRIVATE_KEY")
    )


# --- Validation -------------------------------------------------------------------------


def _b64url_len(value: object) -> tuple[int, bytes] | None:
    if not isinstance(value, str) or not value or len(value) > 200:
        return None
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError):
        return None
    return len(raw), raw


def _valid_endpoint(value: object) -> bool:
    if not isinstance(value, str) or not 10 <= len(value) <= 2048:
        return False
    parts = urlsplit(value)
    return parts.scheme == "https" and bool(parts.hostname)


def _valid_keys(p256dh: object, auth: object) -> bool:
    key, secret = _b64url_len(p256dh), _b64url_len(auth)
    return bool(key and secret and key[0] == 65 and key[1][:1] == b"\x04" and secret[0] == 16)


def _json() -> dict[str, Any]:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _bad(error: str, status: int = 400) -> tuple[Response, int]:
    return jsonify(ok=False, error=error), status


def _prefs(sub: PushSubscription) -> dict[str, bool]:
    return {name: bool(getattr(sub, name)) for name in PREFERENCES}


def _apply_prefs(sub: PushSubscription, data: dict[str, Any]) -> bool:
    """Applique les préférences booléennes présentes ; False si l'une n'est pas un booléen."""
    values = {name: data[name] for name in PREFERENCES if name in data}
    if not all(isinstance(v, bool) for v in values.values()):
        return False
    for name, value in values.items():
        setattr(sub, name, value)
    return True


def _mine(ctx: Any, endpoint: object) -> PushSubscription | None:
    """Abonnement de CE participant (jamais celui d'un autre : pas d'IDOR)."""
    if not isinstance(endpoint, str) or ctx.participant is None:
        return None
    sub: PushSubscription | None = PushSubscription.query.filter_by(
        event_id=ctx.event.id, guest_id=ctx.participant.id, endpoint=endpoint
    ).first()
    return sub


# --- Routes -----------------------------------------------------------------------------


@push_bp.route("/e/<code>/push/subscribe", methods=["POST"])
@limiter.limit("20 per hour")
def subscribe(code: str) -> Response | tuple[Response, int]:
    """Enregistre (ou met à jour) l'abonnement de cet appareil."""
    ctx = load_event_context(code)
    participant = ctx.participant
    if participant is None:
        abort(403)
    data = _json()
    raw_keys = data.get("keys")
    keys: dict[str, Any] = raw_keys if isinstance(raw_keys, dict) else {}
    endpoint = data.get("endpoint")
    if not isinstance(endpoint, str) or not _valid_endpoint(endpoint):
        return _bad("endpoint")
    if not _valid_keys(keys.get("p256dh"), keys.get("auth")):
        return _bad("keys")
    sub = PushSubscription.query.filter_by(event_id=ctx.event.id, endpoint=endpoint).first()
    if sub is None:
        taken = PushSubscription.query.filter_by(guest_id=participant.id).count()
        if taken >= MAX_SUBSCRIPTIONS:
            return _bad("limit", 409)
        sub = PushSubscription(event_id=ctx.event.id, endpoint=endpoint)
        db.session.add(sub)
    lang = str(data.get("lang", ""))[:2].lower()
    sub.guest_id = participant.id  # même appareil, autre participant : le dernier gagne
    sub.p256dh = keys["p256dh"]
    sub.auth = keys["auth"]
    sub.user_agent = request.headers.get("User-Agent", "")[:200]
    sub.lang = lang if lang in SUPPORTED_LANGS else current_app.config["BABEL_DEFAULT_LOCALE"]
    if not _apply_prefs(sub, data):
        db.session.rollback()
        return _bad("prefs")
    db.session.commit()
    return jsonify(ok=True, prefs=_prefs(sub))


@push_bp.route("/e/<code>/push/unsubscribe", methods=["POST"])
@limiter.limit("60 per hour")
def unsubscribe(code: str) -> Response:
    """Supprime l'abonnement de cet appareil, ou tous ceux du participant (``all``)."""
    ctx = load_event_context(code)
    participant = ctx.participant
    if participant is None:
        abort(403)
    data = _json()
    query = PushSubscription.query.filter_by(event_id=ctx.event.id, guest_id=participant.id)
    if data.get("all") is not True:
        query = query.filter_by(
            endpoint=data.get("endpoint") if isinstance(data.get("endpoint"), str) else ""
        )
    query.delete()
    db.session.commit()
    return jsonify(ok=True)


@push_bp.route("/e/<code>/push/prefs", methods=["POST"])
@limiter.limit("120 per hour")
def prefs(code: str) -> Response | tuple[Response, int]:
    """Met à jour les préférences de cet appareil."""
    ctx = load_event_context(code)
    data = _json()
    sub = _mine(ctx, data.get("endpoint"))
    if sub is None:
        return _bad("unknown", 404)
    if not _apply_prefs(sub, data):
        return _bad("prefs")
    db.session.commit()
    return jsonify(ok=True, prefs=_prefs(sub))


@push_bp.route("/e/<code>/push/status", methods=["POST"])
@limiter.limit("120 per hour")
def status(code: str) -> Response:
    """État de cet appareil : abonné ou non, et préférences."""
    ctx = load_event_context(code)
    sub = _mine(ctx, _json().get("endpoint"))
    return jsonify(ok=True, subscribed=sub is not None, prefs=_prefs(sub) if sub else None)


# --- Déclencheurs -----------------------------------------------------------------------


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= PREVIEW_LENGTH else text[: PREVIEW_LENGTH - 1].rstrip() + "…"


def build_payload(
    sub: PushSubscription,
    event: Event,
    kind: str,
    actor_name: str,
    text: str,
    url: str,
    tag: str,
) -> dict[str, Any]:
    """Payload d'un abonnement : texte dans sa langue, aperçu seulement s'il l'a demandé."""
    _ = _translations(sub.lang).gettext
    preview = sub.show_preview
    clipped = _clip(text)
    if kind == "chat":
        body = (
            _("%(name)s : %(text)s") % {"name": actor_name, "text": clipped}
            if preview
            else _("Nouveau message de %(name)s") % {"name": actor_name}
        )
    elif kind == "polls":
        body = (
            _("%(name)s a créé un sondage : %(text)s") % {"name": actor_name, "text": clipped}
            if preview
            else _("Nouveau sondage de %(name)s") % {"name": actor_name}
        )
    else:  # requests : jamais de montant ni de message
        body = _("Nouvelle demande de paiement de %(name)s") % {"name": actor_name}
    return {
        "title": event.title,
        "body": body,
        "tag": tag,
        "url": url,
        "renotify": kind == "chat",
    }


def _queue() -> Any:
    """File RQ ; connexion à délais courts : une panne Redis ne doit pas bloquer la requête."""
    from redis import Redis
    from rq import Queue  # type: ignore[import-not-found,unused-ignore]

    conn = Redis.from_url(
        current_app.config["REDIS_URL"], socket_connect_timeout=1, socket_timeout=2
    )
    return Queue("default", connection=conn)


def notify(
    event: Event,
    kind: str,
    author: Guest | None,
    text: str,
    url: str,
    tag: str,
    only_guest_id: str | None = None,
) -> int:
    """Met en file un push par abonnement concerné (après commit) ; retourne le nombre mis en file.

    Jamais d'exception : sans clés VAPID, sans Redis ou en cas d'erreur, on journalise et on rend 0.
    """
    try:
        if not push_enabled():
            return 0
        query = (
            PushSubscription.query.join(Guest, Guest.id == PushSubscription.guest_id)
            .filter(PushSubscription.event_id == event.id, Guest.is_active.is_(True))
            .filter(getattr(PushSubscription, KINDS[kind]).is_(True))
        )
        if author is not None:
            query = query.filter(PushSubscription.guest_id != author.id)
        if only_guest_id is not None:
            query = query.filter(PushSubscription.guest_id == only_guest_id)
        subs = query.all()
        if not subs:
            return 0
        from app import tasks

        actor_name = author.display_name if author is not None else event.title
        queue = _queue()
        for sub in subs:
            payload = build_payload(sub, event, kind, actor_name, text, url, tag)
            info = {"id": sub.id, "endpoint": sub.endpoint, "p256dh": sub.p256dh, "auth": sub.auth}
            queue.enqueue(tasks.send_push, info, json.dumps(payload), job_timeout=60)
        return len(subs)
    except Exception:
        logger.warning("push notify failed event=%s kind=%s", event.code, kind, exc_info=True)
        return 0
