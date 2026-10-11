"""Clés API par utilisateur d'événement (B034) : création, liste, révocation (UI).

La clé complète n'est jamais stockée (hash sha256 uniquement) et n'est montrée
qu'une seule fois : dans la réponse directe du POST de création (pas de
redirection — la page de liste ne peut pas la reconstituer).
"""

import hashlib
import secrets
from datetime import datetime

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.wrappers import Response

from app.context import EventContext, load_event_context, log_event
from app.extensions import db, limiter
from app.models import ApiKey, Creator, Event, Guest

apikeys_bp = Blueprint("apikeys", __name__)


def create_api_key(
    event: Event, *, guest: Guest | None = None, creator: Creator | None = None, label: str = ""
) -> tuple[ApiKey, str]:
    """Crée une clé API (B034) ; renvoie ``(ligne, clé complète)``.

    Contrainte « exactement un owner » (check en application) : ``ValueError`` si
    ``guest`` et ``creator`` ne sont pas exactement l'un des deux. La clé complète
    (``hs_`` + 48 hex) n'est jamais persistée : seul son sha256 hex est stocké.
    """
    if (guest is None) == (creator is None):
        raise ValueError("exactly one of guest/creator must be provided")
    key = "hs_" + secrets.token_hex(24)
    api_key = ApiKey(
        event_id=event.id,
        owner_guest_id=guest.id if guest is not None else None,
        owner_creator_id=creator.id if creator is not None else None,
        key_hash=hashlib.sha256(key.encode("utf-8")).hexdigest(),
        key_prefix=key[:12],
        label=label[:100],
    )
    db.session.add(api_key)
    db.session.flush()
    return api_key, key


def _own_keys(ctx: EventContext) -> list[ApiKey]:
    """Les clés de l'appelant uniquement (jamais celles des autres), plus récentes d'abord."""
    if ctx.is_creator:
        query = ApiKey.query.filter_by(event_id=ctx.event.id, owner_creator_id=current_user.id)
    else:
        participant = ctx.participant
        if participant is None:  # inatteignable : load_event_context exige un participant
            abort(403)
        query = ApiKey.query.filter_by(event_id=ctx.event.id, owner_guest_id=participant.id)
    return list(query.order_by(ApiKey.created_at.desc(), ApiKey.id))


@apikeys_bp.before_request
def _method_override() -> None:
    """Formulaire HTML « DELETE » : le navigateur n'envoie que POST (``_method=DELETE``)."""
    if request.method == "POST" and request.form.get("_method", "").upper() == "DELETE":
        request.method = "DELETE"


@apikeys_bp.route("/<code>/api-keys")
def index(code: str) -> str:
    """Mes clés API (créateur ou invité) : préfixes, libellés, dates ; jamais la clé complète."""
    ctx = load_event_context(code)
    return render_template("apikeys/index.html", event=ctx.event, keys=_own_keys(ctx), created=None)


@apikeys_bp.route("/<code>/api-keys", methods=["POST"])
@limiter.limit("10 per hour")
def create(code: str) -> str:
    """Crée une clé ; la clé complète est montrée une seule fois (rendu direct, pas de redirection)."""
    ctx = load_event_context(code)
    label = request.form.get("label", "").strip()[:100]
    if ctx.is_creator:
        api_key, key = create_api_key(ctx.event, creator=current_user, label=label)
    else:
        participant = ctx.participant
        if participant is None:  # inatteignable : load_event_context exige un participant
            abort(403)
        api_key, key = create_api_key(ctx.event, guest=participant, label=label)
    log_event(ctx, "api_key.created", target=label or api_key.key_prefix)
    db.session.commit()
    return render_template(
        "apikeys/index.html",
        event=ctx.event,
        keys=_own_keys(ctx),
        created={"api_key": api_key, "key": key},
    )


@apikeys_bp.route("/<code>/api-keys/<key_id>", methods=["POST", "DELETE"])
@limiter.limit("10 per hour")
def revoke(code: str, key_id: str) -> Response:
    """Révoque SA clé (idempotent) ; une clé d'autrui → 404 (ne révèle pas son existence).

    FN2 : la route accepte POST (formulaire ``_method=DELETE``) en plus de DELETE ;
    le ``before_request`` ``_method_override`` convertit POST→DELETE avant le view.
    """
    if request.method != "DELETE":
        abort(405)
    ctx = load_event_context(code)
    if ctx.is_creator:
        api_key = ApiKey.query.filter_by(
            id=key_id, event_id=ctx.event.id, owner_creator_id=current_user.id
        ).first()
    else:
        participant = ctx.participant
        if participant is None:  # inatteignable : load_event_context exige un participant
            abort(403)
        api_key = ApiKey.query.filter_by(
            id=key_id, event_id=ctx.event.id, owner_guest_id=participant.id
        ).first()
    if api_key is None:
        abort(404)
    if api_key.revoked_at is None:
        api_key.revoked_at = datetime.utcnow()
        log_event(ctx, "api_key.revoked", target=api_key.key_prefix)
        db.session.commit()
    return redirect(url_for("apikeys.index", code=code))
