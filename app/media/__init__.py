"""Media blueprint - photo/video sharing with geolocation and dating."""

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_babel import gettext as _
from werkzeug.datastructures import FileStorage
from werkzeug.wrappers import Response

from app.context import load_event_context, log_event
from app.extensions import db, limiter
from app.freemium import can_upload_media, consume_media_quota, release_media_quota
from app.i18n import format_filesize
from app.models import Expense, MediaItem

media_bp = Blueprint("media", __name__)

ALLOWED_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "video/mp4",
    "video/webm",
}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB per file

# Magic byte signatures for content validation
_MAGIC_BYTES = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/webp": b"RIFF",
    "video/mp4": b"\x00\x00\x00",  # checked at offset 4: 'ftyp'
    "video/webm": b"\x1a\x45\xdf\xa3",
}


def _validate_magic_bytes(file: FileStorage, mime: str) -> bool:
    """Verify the file's actual content matches the claimed MIME type."""
    header = file.read(12)
    file.seek(0)
    if mime == "image/jpeg":
        return header.startswith(b"\xff\xd8\xff")
    if mime == "image/png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/webp":
        return header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    if mime == "video/mp4":
        return header[4:8] == b"ftyp"
    if mime == "video/webm":
        return header.startswith(b"\x1a\x45\xdf\xa3")
    if mime == "image/heic":
        # HEIF: 'ftyp' at offset 4, brand at offset 8 (heic/heix/mif1/hevc)
        return header[4:8] == b"ftyp" and header[8:12] in (b"heic", b"heix", b"mif1", b"hevc")
    return False


# Extension derived from verified MIME (not from user-supplied filename)
_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}


def _media_dir(event_code: str) -> Path:
    """Get or create the media storage directory for an event."""
    base = Path(current_app.instance_path) / "media" / event_code
    base.mkdir(parents=True, exist_ok=True)
    return base


def _extract_exif(file_storage: FileStorage) -> tuple[float | None, float | None, datetime | None]:
    """Extract GPS and date from EXIF data. Returns (lat, lng, taken_at)."""
    try:
        import io

        from PIL import Image

        file_storage.seek(0)
        img = Image.open(io.BytesIO(file_storage.read()))
        file_storage.seek(0)
        exif = img._getexif() or {}  # type: ignore[attr-defined]
        lat: float | None = None
        lng: float | None = None
        taken_at: datetime | None = None

        # Date
        if 306 in exif:  # DateTimeOriginal
            taken_at = datetime.strptime(exif[306], "%Y:%m:%d %H:%M:%S")

        # GPS
        gps_info = exif.get(34853, {})  # GPSInfo tag
        if gps_info:

            def _dms(value: tuple[Any, Any, Any]) -> float:
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
def file(code: str, item_id: str) -> Response:
    """Serve a stored media file (creator or guest only)."""
    ctx = load_event_context(code)
    event = ctx.event
    item = MediaItem.query.filter_by(id=item_id, event_id=event.id).first_or_404()
    return send_from_directory(_media_dir(code), item.filename, mimetype=item.mime_type)


@media_bp.route("/e/<code>/media", methods=["GET"])
def gallery(code: str) -> str | Response:
    """Media gallery for an event (creator or guest only)."""
    ctx = load_event_context(code)
    event = ctx.event

    items = event.media.order_by(MediaItem.uploaded_at.desc()).all()

    # Storage gauge context (creator sees their quota + soft upgrade).
    from app.freemium import get_media_quota

    quota = None
    gauge = None
    if ctx.is_creator:
        quota = get_media_quota(event.creator)
        used = quota.used_bytes
        pct = min(100.0, (used / quota.max_bytes * 100.0)) if quota.max_bytes else 0.0
        gauge = {
            "used": used,
            "max": quota.max_bytes,
            "pct": round(pct),
            "exceeded": quota.is_exceeded,
        }

    return render_template("media/gallery.html", event=event, items=items, gauge=gauge)


@media_bp.route("/e/<code>/media/upload", methods=["POST"])
@limiter.limit("10 per hour")
def upload(code: str) -> Response:
    """Upload a media file (creator or guest only)."""
    ctx = load_event_context(code)
    event = ctx.event

    # Check file
    file = request.files.get("file")
    if not file or file.filename == "":
        flash(_("Aucun fichier."), "danger")
        return redirect(url_for("media.gallery", code=code))

    if file.content_type not in ALLOWED_MIME:
        flash(_("Format non supporté."), "danger")
        return redirect(url_for("media.gallery", code=code))

    # Validate magic bytes (content must match claimed MIME)
    if not _validate_magic_bytes(file, file.content_type):
        flash(_("Fichier invalide (contenu ne correspond pas au format déclaré)."), "danger")
        return redirect(url_for("media.gallery", code=code))

    # Check size
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        flash(
            _("Fichier trop volumineux (max %(max)s).", max=format_filesize(MAX_FILE_SIZE)),
            "danger",
        )
        return redirect(url_for("media.gallery", code=code))

    # Check quota
    creator = event.creator
    if not can_upload_media(creator, size):
        flash(_("Quota de stockage atteint. Passez à l'offre supérieure."), "warning")
        return redirect(url_for("media.gallery", code=code))

    # Extract EXIF
    lat, lng, taken_at = _extract_exif(file)

    # Save file (extension derived from verified MIME, not user filename)
    ext = _MIME_EXT.get(file.content_type, ".bin")
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
        uploaded_by=ctx.participant.id if ctx.participant else None,
        uploaded_by_name=ctx.actor.name,
        event_id=event.id,
    )
    db.session.add(item)

    # Consume quota
    consume_media_quota(creator, size)

    # Log
    log_event(
        ctx,
        "media.uploaded",
        target=file.filename,
        details=f"{size // 1024} KB, geo={1 if lat else 0}",
    )
    db.session.commit()

    flash(_("Média ajouté."), "success")
    return redirect(url_for("media.gallery", code=code))


@media_bp.route("/e/<code>/media/<item_id>")
def detail(code: str, item_id: str) -> str | Response:
    """Single media detail (creator or guest only)."""
    ctx = load_event_context(code)
    event = ctx.event

    item = MediaItem.query.filter_by(id=item_id, event_id=event.id).first_or_404()
    return render_template("media/detail.html", event=event, item=item)


@media_bp.route("/e/<code>/media/<item_id>/delete", methods=["POST"])
def delete(code: str, item_id: str) -> Response:
    """Delete a media item (uploader or creator)."""
    ctx = load_event_context(code)
    event = ctx.event

    item = MediaItem.query.filter_by(id=item_id, event_id=event.id).first_or_404()
    if not ctx.can_delete(item):
        abort(403)

    # Références (justificatifs de frais) mises à NULL ; fichier et quota seulement après le commit réussi.
    path = _media_dir(code) / item.filename
    Expense.query.filter_by(receipt_media_id=item.id).update({"receipt_media_id": None})
    release_media_quota(event.creator, item.size_bytes, commit=False)
    log_event(ctx, "media.deleted", target=item.original_name)
    db.session.delete(item)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash(_("La suppression a échoué. Réessayez."), "danger")
        return redirect(url_for("media.detail", code=code, item_id=item_id))
    path.unlink(missing_ok=True)

    flash(_("Média supprimé."), "success")
    return redirect(url_for("media.gallery", code=code))
