"""Freemium feature flags and limits."""

from flask import current_app


def can_add_guest(event):
    """Check if the event can accept more guests."""
    limit = current_app.config["MAX_GUESTS_PER_EVENT"]
    return event.guest_count < limit


def can_create_event(creator):
    """Check if the creator can create another event."""
    limit = current_app.config["MAX_EVENTS_PER_CREATOR"]
    return creator.events.filter_by(is_active=True).count() < limit


def max_duration_days():
    """Return the max event duration in days."""
    return current_app.config["MAX_DURATION_DAYS"]


def is_module_enabled(module_name):
    """Check if a module is enabled in the current tier."""
    return module_name in current_app.config["ENABLED_MODULES"]


def get_limits():
    """Return all current limits (for display in UI)."""
    return {
        "max_guests": current_app.config["MAX_GUESTS_PER_EVENT"],
        "max_duration_days": current_app.config["MAX_DURATION_DAYS"],
        "max_events": current_app.config["MAX_EVENTS_PER_CREATOR"],
        "enabled_modules": current_app.config["ENABLED_MODULES"],
        "media_quota_mb": current_app.config["MEDIA_QUOTA_FREE_MB"],
    }


# --- Media quota (freemium tiers) ---

MEDIA_TIERS = {
    "free": {"max_bytes": 524_288_000},       # 500 MB
    "basic": {"max_bytes": 5_242_880_000},    # 5 GB
    "premium": {"max_bytes": 52_428_800_000}, # 50 GB
}


def get_media_quota(creator):
    """Get or create the media quota for a creator."""
    from app.models import MediaQuota
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
    return quota


def can_upload_media(creator, size_bytes):
    """Check if the creator can upload more media."""
    quota = get_media_quota(creator)
    return quota.can_upload(size_bytes)


def consume_media_quota(creator, size_bytes):
    """Record media upload against the quota."""
    quota = get_media_quota(creator)
    quota.used_bytes += size_bytes
    from app.extensions import db
    db.session.commit()


def release_media_quota(creator, size_bytes):
    """Release quota when media is deleted."""
    quota = get_media_quota(creator)
    quota.used_bytes = max(0, quota.used_bytes - size_bytes)
    from app.extensions import db
    db.session.commit()


def set_media_tier(creator, tier):
    """Change the media tier (called by payment webhook in the future)."""
    if tier not in MEDIA_TIERS:
        raise ValueError(f"Unknown tier: {tier}")
    quota = get_media_quota(creator)
    quota.tier = tier
    quota.max_bytes = MEDIA_TIERS[tier]["max_bytes"]
    from app.extensions import db
    db.session.commit()
