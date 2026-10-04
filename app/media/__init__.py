"""Media blueprint - photo/video sharing with geolocation and dating."""

import os
import uuid
from pathlib import Path

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, current_app, session, send_from_directory)
from flask_login import current_user
from app.extensions import db
from app.models import Event, MediaItem, Guest
from app.freemium import can_upload_media, consume_media_quota, release_media_quota

media_bp = Blueprint("media", __name__)

ALLOWED_MIME = {
    "image/jpeg", "image/png", "image/webp", "image/heic",
    "video/mp4", "video/webm",
}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB per file


def _media_dir(event_code):
    """Get or create the media storage directory for an event."""
    base = Path(current_app.instance_path) / "media" / event_code
    base.mkdir(parents=True, exist_ok=True)
    return base


def _resolve_actor(event, code):
    """Return (guest, is_creator, denied_redirect_or_None)."""
    if current_user.is_authenticated and current_user.id == event.creator_id:
        return None, True, None
    guest_id = session.get(f"guest_{code}")
    if guest_id:
        guest = Guest.query.filter_by(id=guest_id, event_id=event.id, is_active=True).first()
        if guest is not None:
            return guest, False, None
    return None, False, redirect(url_for("events.guest_access", code=code))


def _extract_exif(file_storage):
    """Extract GPS and date from EXIF data. Returns (lat, lng, taken_at)."""
    try:
        from PIL import Image
        import io

        file_storage.seek(0)
        img = Image.open(io.BytesIO(file_storage.read()))
        file_storage.seek(0)
        exif = img._getexif() or {}
        lat = lng = None
        taken_at = None

        # Date
        if 306 in exif:  # DateTimeOriginal
            from datetime import datetime
            taken_at = datetime.strptime(exif[306], "%Y:%m:%d %H:%M:%S")

        # GPS
        gps_info = exif.get(34853, {})  # GPSInfo tag
        if gps_info:
            def _dms(value):
                d = int(value[0])
                m = int(value[1])
                s = int(value[2])
                return d + m / 60.0 + s / 3600.0

            lat = _dms(gps_info.get(1, (0, 0, 0)))
            if gps_info.get(1, ("N",))[0] == "S":
                lat = -lat
            lng = _dms(gps_info.get(3, (0, 0, 0)))
            if gps_info.get(3, ("E",))[0] == "W":
                lng = -lng

        return lat, lng, taken_at
    except Exception:
        return None, None, None


@media_bp.route("/e/<code>/media/<item_id>/file")
def file(code, item_id):
    """Serve a stored media file (creator or guest only)."""
    event = Event.query.filter_by(code=code, is_active=True).first_or_404()
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied
    item = MediaItem.query.filter_by(id=item_id, event_id=event.id).first_or_404()
    return send_from_directory(_media_dir(code), item.filename, mimetype=item.mime_type)


@media_bp.route("/e/<code>/media", methods=["GET"])
def gallery(code):
    """Media gallery for an event (creator or guest only)."""
    event = Event.query.filter_by(code=code, is_active=True).first_or_404()
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    items = event.media.order_by(MediaItem.uploaded_at.desc()).all()
    return render_template("media/gallery.html", event=event, items=items,
                           guest=guest, is_creator=is_creator)


@media_bp.route("/e/<code>/media/upload", methods=["POST"])
def upload(code):
    """Upload a media file (creator or guest only)."""
    event = Event.query.filter_by(code=code, is_active=True).first_or_404()
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    actor_name = guest.display_name if guest else "Créateur"
    guest_id = guest.id if guest else None

    # Check file
    file = request.files.get("file")
    if not file or file.filename == "":
        flash("Aucun fichier.", "danger")
        return redirect(url_for("media.gallery", code=code))

    if file.content_type not in ALLOWED_MIME:
        flash("Format non supporté.", "danger")
        return redirect(url_for("media.gallery", code=code))

    # Check size
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        flash("Fichier trop volumineux (max 50 Mo).", "danger")
        return redirect(url_for("media.gallery", code=code))

    # Check quota
    creator = event.creator
    if not can_upload_media(creator, size):
        flash("Quota media atteint. Passe au tier supérieur.", "warning")
        return redirect(url_for("media.gallery", code=code))

    # Extract EXIF
    lat, lng, taken_at = _extract_exif(file)

    # Save file
    ext = os.path.splitext(file.filename)[1] or ".bin"
    stored_name = f"{uuid.uuid4().hex}{ext}"
    file.save(str(_media_dir(code) / stored_name))

    # Create record
    item = MediaItem(
        filename=stored_name,
        original_name=file.filename,
        mime_type=file.content_type,
        size_bytes=size,
        caption=request.form.get("caption", "").strip(),
        latitude=lat,
        longitude=lng,
        taken_at=taken_at,
        uploaded_by=guest_id,
        uploaded_by_name=actor_name,
        event_id=event.id,
    )
    db.session.add(item)

    # Consume quota
    consume_media_quota(creator, size)

    # Log
    from app.models import ActivityLog
    log = ActivityLog(
        event_id=event.id,
        actor_name=actor_name,
        actor_type="guest" if guest else "creator",
        action="media.uploaded",
        target=file.filename,
        details=f"{size // 1024} KB, geo={'oui' if lat else 'non'}",
    )
    db.session.add(log)
    db.session.commit()

    flash("Media ajouté.", "success")
    return redirect(url_for("media.gallery", code=code))


@media_bp.route("/e/<code>/media/<item_id>")
def detail(code, item_id):
    """Single media detail (creator or guest only)."""
    event = Event.query.filter_by(code=code, is_active=True).first_or_404()
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    item = MediaItem.query.filter_by(id=item_id, event_id=event.id).first_or_404()
    return render_template("media/detail.html", event=event, item=item,
                           guest=guest, is_creator=is_creator)


@media_bp.route("/e/<code>/media/<item_id>/delete", methods=["POST"])
def delete(code, item_id):
    """Delete a media item (uploader or creator)."""
    event = Event.query.filter_by(code=code, is_active=True).first_or_404()
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    item = MediaItem.query.filter_by(id=item_id, event_id=event.id).first_or_404()
    guest_id = guest.id if guest else None
    if item.uploaded_by != guest_id and not is_creator:
        flash("Pas autorisé.", "danger")
        return redirect(url_for("media.gallery", code=code))

    # Delete file
    path = _media_dir(code) / item.filename
    if path.exists():
        path.unlink()

    # Release quota
    release_media_quota(event.creator, item.size_bytes)

    # Log
    from app.models import ActivityLog
    log = ActivityLog(
        event_id=event.id,
        actor_name=item.uploaded_by_name,
        actor_type="guest" if item.uploaded_by else "creator",
        action="media.deleted",
        target=item.original_name,
    )
    db.session.add(log)
    db.session.delete(item)
    db.session.commit()

    flash("Media supprimé.", "success")
    return redirect(url_for("media.gallery", code=code))
