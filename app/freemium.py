"""Freemium feature flags and limits."""

from collections.abc import Callable
from functools import wraps
from typing import Any, cast

from flask import current_app, render_template, request, session
from flask_babel import lazy_gettext as _l

from app.models import Creator, Event, MediaQuota

# ============================================================================
# Feature tiers (declarative)
# ============================================================================
# Tiers are ordered by capability. A creator "has" a feature when their tier is
# at or above the tier that unlocks it. This keeps paywall logic declarative
# instead of scattering ad-hoc conditionals through the code.

TIER_FREE = "free"
TIER_PRO = "pro"
TIER_UNLIMITED = "unlimited"

TIER_ORDER: dict[str, int] = {
    TIER_FREE: 0,
    TIER_PRO: 1,
    TIER_UNLIMITED: 2,
}

# A feature is unlocked at the tier listed (and every tier above it).
FEATURES: dict[str, str] = {
    "pdf_export": TIER_PRO,  # certified accountancy PDF export
    "unlimited_guests": TIER_PRO,  # more than the free guest cap
    "hd_video": TIER_UNLIMITED,  # high-resolution video uploads
}


def get_tier(creator: Creator | None) -> str:
    """Return the feature tier for a creator (defaults to "free")."""
    if creator is None:
        return TIER_FREE
    tier = getattr(creator, "tier", None)
    return tier if tier in TIER_ORDER else TIER_FREE


def tier_at_least(creator: Creator | None, min_tier: str) -> bool:
    """True if the creator's tier is >= min_tier."""
    if min_tier not in TIER_ORDER:
        raise ValueError(f"Unknown tier: {min_tier}")
    return TIER_ORDER[get_tier(creator)] >= TIER_ORDER[min_tier]


def has_feature(creator: Creator | None, feature_name: str) -> bool:
    """Functional feature check. Unknown features are treated as free."""
    min_tier = FEATURES.get(feature_name, TIER_FREE)
    return tier_at_least(creator, min_tier)


def _upgrade_target(code: str | None) -> str | None:
    """Best-effort target to return to after the upgrade flow (hook point)."""
    if code and request and request.path:
        # Remember where the paywall was hit so the CTA can deep-link back.
        session["upgrade_intent"] = request.path
    return code


def require_tier(min_tier: str) -> Callable[..., Callable[..., Any]]:
    """Soft paywall decorator.

    When the acting creator lacks ``min_tier`` for an event-scoped view, it does
    NOT raise a raw 400/403 — it renders a well-crafted upgrade teaser page with
    an (as-yet-fake) upgrade CTA, ready to be wired to Stripe/LemonSqueezy.
    Guests are left alone (the paywall is a creator decision); only the creator
    is redirected to the upgrade view.

    Usage::

        @events_bp.route("/<code>/export/pdf")
        @require_tier("pro")
        @login_required
        def export_pdf(code): ...
    """
    if min_tier not in TIER_ORDER:
        raise ValueError(f"Unknown tier: {min_tier}")

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            from flask_login import current_user

            # Non-creators (guests / anonymous): let the view handle access.
            if not current_user.is_authenticated:
                return func(*args, **kwargs)

            # Resolve the creator: the authenticated user, when they own a tier.
            creator = None
            # The route may pass an `event` kwarg; otherwise look it up by code.
            event = kwargs.get("event")
            if event is None and "code" in kwargs:
                event = Event.query.filter_by(code=kwargs["code"], is_active=True).first()
            if event is not None and event.creator_id == current_user.id:
                creator = event.creator

            if creator is not None and not tier_at_least(creator, min_tier):
                _upgrade_target(kwargs.get("code"))
                feature_name = _feature_name_for_tier(min_tier)
                feature_label = (
                    FEATURE_LABELS.get(feature_name, FALLBACK_FEATURE_LABEL)
                    if feature_name
                    else FALLBACK_FEATURE_LABEL
                )
                return render_template(
                    "freemium/paywall.html",
                    min_tier=min_tier,
                    feature_label=feature_label,
                )
            return func(*args, **kwargs)

        return wrapper

    return decorator


def _feature_name_for_tier(tier: str) -> str | None:
    """First feature name unlocked at/above a tier (for paywall copy)."""
    for name, min_t in FEATURES.items():
        if TIER_ORDER.get(min_t, 0) >= TIER_ORDER.get(tier, 0):
            return name
    return None


# Human-readable names for the paywall copy (FR source; i18n covers EN).
FALLBACK_FEATURE_LABEL = _l("Fonctionnalité avancée")
FEATURE_LABELS = {
    "pdf_export": _l("Export PDF des comptes certifié"),
    "unlimited_guests": _l("Participants illimités"),
    "hd_video": _l("Vidéos haute résolution"),
}


def can_add_guest(event: Event) -> bool:
    """Check if the event can accept more participants.

    The count is ``Event.guest_count``: active participants, the creator included
    (the creator is a participant of their own event). Unlimited on a paid tier.
    """
    if has_feature(event.creator, "unlimited_guests"):
        return True
    limit: int = current_app.config["MAX_GUESTS_PER_EVENT"]
    return event.guest_count < limit


def guest_gauge(event: Event) -> dict[str, Any]:
    """Jauge de participants (n / max), cohérente avec ``can_add_guest`` (B020)."""
    maximum = int(current_app.config["MAX_GUESTS_PER_EVENT"])
    count = event.guest_count
    return {
        "count": count,
        "max": maximum,
        "pct": min(100, round(count * 100 / maximum)) if maximum else 0,
        "unlimited": has_feature(event.creator, "unlimited_guests"),
        "at_limit": not can_add_guest(event),
    }


def can_create_event(creator: Creator) -> bool:
    """Check if the creator can create another event."""
    limit: int = current_app.config["MAX_EVENTS_PER_CREATOR"]
    count: int = creator.events.filter_by(is_active=True).count()
    return count < limit


def max_duration_days() -> int:
    """Return the max event duration in days."""
    return cast("int", current_app.config["MAX_DURATION_DAYS"])


def is_module_enabled(module_name: str) -> bool:
    """Check if a module is enabled in the current tier."""
    return module_name in current_app.config["ENABLED_MODULES"]


def get_limits() -> dict[str, object]:
    """Return all current limits (for display in UI)."""
    return {
        "max_guests": current_app.config["MAX_GUESTS_PER_EVENT"],
        "max_duration_days": current_app.config["MAX_DURATION_DAYS"],
        "max_events": current_app.config["MAX_EVENTS_PER_CREATOR"],
        "enabled_modules": current_app.config["ENABLED_MODULES"],
        "media_quota_mb": current_app.config.get("MEDIA_QUOTA_FREE_MB", 500),
    }


# --- Media quota (freemium tiers) ---

MEDIA_TIERS: dict[str, dict[str, int]] = {
    "free": {"max_bytes": 524_288_000},  # 500 MB
    "basic": {"max_bytes": 5_242_880_000},  # 5 GB
    "premium": {"max_bytes": 52_428_800_000},  # 50 GB
}


def get_media_quota(creator: Creator) -> MediaQuota:
    """Get or create the media quota for a creator."""
    from app.extensions import db

    quota = creator.media_quota
    if not quota:
        quota = MediaQuota(
            creator_id=creator.id,
            tier="free",
            max_bytes=MEDIA_TIERS["free"]["max_bytes"],
        )
        db.session.add(quota)
        db.session.commit()
    return cast("MediaQuota", quota)


def can_upload_media(creator: Creator, size_bytes: int) -> bool:
    """Check if the creator can upload more media."""
    quota = get_media_quota(creator)
    return quota.can_upload(size_bytes)


def consume_media_quota(creator: Creator, size_bytes: int) -> None:
    """Record media upload against the quota."""
    quota = get_media_quota(creator)
    quota.used_bytes += size_bytes
    from app.extensions import db

    db.session.commit()


def release_media_quota(creator: Creator, size_bytes: int, *, commit: bool = True) -> None:
    """Release quota when media is deleted (``commit=False`` : le commit est à la charge de l'appelant)."""
    quota = get_media_quota(creator)
    quota.used_bytes = max(0, quota.used_bytes - size_bytes)
    if commit:
        from app.extensions import db

        db.session.commit()


def set_media_tier(creator: Creator, tier: str) -> None:
    """Change the media tier (called by payment webhook in the future)."""
    if tier not in MEDIA_TIERS:
        raise ValueError(f"Unknown tier: {tier}")
    quota = get_media_quota(creator)
    quota.tier = tier
    quota.max_bytes = MEDIA_TIERS[tier]["max_bytes"]
    from app.extensions import db

    db.session.commit()
