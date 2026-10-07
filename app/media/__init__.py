"""Media blueprint - photo/video sharing with geolocation and dating (B026 : miniatures, envoi multiple, visionneuse)."""

import io
import math
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)
from flask_babel import gettext as _
from sqlalchemy import and_, func, or_
from werkzeug.datastructures import FileStorage
from werkzeug.wrappers import Response

from app.context import EventContext, load_event_context, log_event
from app.extensions import db, limiter
from app.freemium import can_upload_media, consume_media_quota, release_media_quota
from app.i18n import format_filesize
from app.media.thumbs import SIZES, delete_thumbs, ensure_thumb
from app.models import Expense, MediaItem

media_bp = Blueprint("media", __name__)

# HEIC/HEIF : non affichable par la plupart des navigateurs -> refusé (iOS convertit en JPEG si on ne l'annonce pas).
ALLOWED_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "video/mp4",
    "video/webm",
}
ACCEPT = ",".join(sorted(ALLOWED_MIME))
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB per file
PAGE_SIZE = 60
CAPTION_MAX = 500
UPLOAD_LIMIT = "200 per hour"  # un séjour = des dizaines de photos ; 429 géré côté client

_HEIF_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1")


def _is_heif(file: FileStorage) -> bool:
    """HEIC/HEIF reconnu par le type annoncé, l'extension ou la marque ``ftyp`` (jamais accepté)."""
    header = file.read(12)
    file.seek(0)
    name = (file.filename or "").lower()
    return (
        (file.content_type or "") in ("image/heic", "image/heif", "image/heic-sequence")
        or name.endswith((".heic", ".heif"))
        or (header[4:8] == b"ftyp" and header[8:12] in _HEIF_BRANDS)
    )


def _validate_magic_bytes(file: FileStorage, mime: str) -> bool:
    """Verify the file's actual content matches the claimed MIME type."""
    header = file.read(12)
    file.seek(0)
    if mime == "image/jpeg":
        return bool(header.startswith(b"\xff\xd8\xff"))
    if mime == "image/png":
        return bool(header.startswith(b"\x89PNG\r\n\x1a\n"))
    if mime == "image/webp":
        return bool(header[:4] == b"RIFF" and header[8:12] == b"WEBP")
    if mime == "video/mp4":
        return bool(header[4:8] == b"ftyp")
    if mime == "video/webm":
        return bool(header.startswith(b"\x1a\x45\xdf\xa3"))
    return False


# Extension derived from verified MIME (not from user-supplied filename)
_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}
_EXTS = {"image/jpeg": (".jpg", ".jpeg"), "video/mp4": (".mp4", ".m4v")}


def clean_name(name: str | None, mime: str) -> str:
    """Nom d'origine assaini : sans chemin ni caractères de contrôle, extension cohérente avec le type."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[\x00-\x1f\x7f\"<>|:*?]", "", base).strip(" .")[:150] or "media"
    ext = _MIME_EXT.get(mime, "")
    if ext and not base.lower().endswith(_EXTS.get(mime, (ext,))):
        base += ext
    return base


def _media_dir(event_code: str) -> Path:
    """Get or create the media storage directory for an event."""
    base = Path(current_app.instance_path) / "media" / event_code
    base.mkdir(parents=True, exist_ok=True)
    return base


def _extract_exif(file_storage: FileStorage) -> tuple[float | None, float | None, datetime | None]:
    """Extract GPS and date from EXIF data. Returns (lat, lng, taken_at)."""
    lat: float | None = None
    lng: float | None = None
    taken_at: datetime | None = None
    try:
        from PIL import Image

        file_storage.seek(0)
        img = Image.open(io.BytesIO(file_storage.read()))
        file_storage.seek(0)
        exif = img.getexif()
        raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)  # DateTimeOriginal, sinon DateTime
        if raw:
            taken_at = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
        gps = exif.get_ifd(0x8825)
        if gps.get(2) and gps.get(4):

            def _deg(value: tuple[Any, Any, Any]) -> float:
                return float(value[0]) + float(value[1]) / 60.0 + float(value[2]) / 3600.0

            lat = _deg(gps[2]) * (-1 if gps.get(1) == "S" else 1)
            lng = _deg(gps[4]) * (-1 if gps.get(3) == "W" else 1)
    except Exception:
        file_storage.seek(0)
    return lat, lng, taken_at


def _is_htmx() -> bool:
    return request.headers.get("HX-Request") == "true"


def _wants_json() -> bool:
    return "application/json" in request.headers.get("Accept", "")


def _private(resp: Response) -> Response:
    """Cache navigateur uniquement (contenu réservé aux participants), un jour."""
    resp.cache_control.public = False
    resp.cache_control.private = True
    resp.cache_control.max_age = 86400
    return resp


# --- Ordre de la galerie : jour de prise de vue (EXIF) sinon d'envoi, du plus récent au plus ancien -----------------

_KEY = func.coalesce(MediaItem.taken_at, MediaItem.uploaded_at)


def _ordered(event: Any) -> Any:
    return event.media.order_by(_KEY.desc(), MediaItem.id.desc())


def _newer(event: Any, item: MediaItem) -> Any:
    key = item.display_date
    return event.media.filter(or_(_KEY > key, and_(_KEY == key, MediaItem.id > item.id)))


def _older(event: Any, item: MediaItem) -> Any:
    key = item.display_date
    return event.media.filter(or_(_KEY < key, and_(_KEY == key, MediaItem.id < item.id)))


@media_bp.route("/e/<code>/media/<item_id>/file")
def file(code: str, item_id: str) -> Response:
    """Serve a stored media file (creator or guest only)."""
    ctx = load_event_context(code)
    item = MediaItem.query.filter_by(id=item_id, event_id=ctx.event.id).first_or_404()
    return _private(send_from_directory(_media_dir(code), item.filename, mimetype=item.mime_type))


@media_bp.route("/e/<code>/media/<item_id>/thumb/<int:size>")
def thumb(code: str, item_id: str, size: int) -> Response:
    """Miniature WebP (320 ou 960 px), générée au premier accès puis servie depuis le disque."""
    ctx = load_event_context(code)
    item = MediaItem.query.filter_by(id=item_id, event_id=ctx.event.id).first_or_404()
    if size not in SIZES or not item.mime_type.startswith("image/"):
        abort(404)
    path = ensure_thumb(_media_dir(code), item.filename, item.id, size)
    if path is None:
        abort(404)
    return _private(
        send_file(path, mimetype="image/webp")
    )  # ETag et Last-Modified : requêtes conditionnelles


@media_bp.route("/e/<code>/media/<item_id>/download")
def download(code: str, item_id: str) -> Response:
    """Original en pièce jointe, sous son nom d'origine assaini."""
    ctx = load_event_context(code)
    item = MediaItem.query.filter_by(id=item_id, event_id=ctx.event.id).first_or_404()
    return send_from_directory(
        _media_dir(code),
        item.filename,
        mimetype=item.mime_type,
        as_attachment=True,
        download_name=clean_name(item.original_name, item.mime_type),
    )


@media_bp.route("/e/<code>/media", methods=["GET"])
def gallery(code: str) -> str | Response:
    """Galerie : tuiles groupées par jour, 60 par page (HTMX ``?page=N`` = tuiles suivantes)."""
    ctx = load_event_context(code)
    event = ctx.event

    page = max(1, request.args.get("page", 1, type=int))
    upto = min(
        max(request.args.get("upto", 0, type=int), 0), 5000
    )  # retour de la visionneuse à la bonne position
    count = PAGE_SIZE * math.ceil(upto / PAGE_SIZE) if upto else PAGE_SIZE
    start = 0 if upto else (page - 1) * PAGE_SIZE
    query = _ordered(event)
    total = query.count()
    items = query.offset(start).limit(count).all()
    before = query.offset(start - 1).limit(1).first() if start else None
    rows: list[tuple[MediaItem, bool]] = []
    previous = before.display_date.date() if before and before.display_date else None
    for item in items:
        day = item.display_date.date() if item.display_date else None
        rows.append((item, day != previous))
        previous = day
    next_page = page + 1 if not upto else count // PAGE_SIZE + 1
    more_url = (
        url_for("media.gallery", code=code, page=next_page) if start + len(items) < total else None
    )
    if _is_htmx() and (page > 1 and not upto):
        return render_template("media/_tiles.html", event=event, rows=rows, more_url=more_url)

    gauge = None
    if ctx.is_creator:
        from app.freemium import get_media_quota

        quota = get_media_quota(event.creator)
        pct = min(100.0, quota.used_bytes / quota.max_bytes * 100.0) if quota.max_bytes else 0.0
        gauge = {
            "used": quota.used_bytes,
            "max": quota.max_bytes,
            "pct": round(pct),
            "exceeded": quota.is_exceeded,
        }
    template = "media/_gallery.html" if _is_htmx() else "media/gallery.html"
    return render_template(
        template,
        event=event,
        rows=rows,
        total=total,
        more_url=more_url,
        gauge=gauge,
        accept=ACCEPT,
        max_bytes=MAX_FILE_SIZE,
        max_label=format_filesize(MAX_FILE_SIZE),
    )


def _store(
    ctx: EventContext, file: FileStorage | None, caption: str
) -> tuple[MediaItem | None, str | None, int]:
    """Valide et enregistre un fichier ; renvoie (média, message d'erreur, statut HTTP)."""
    if not file or not file.filename:
        return None, _("Aucun fichier."), 400

    if _is_heif(file):
        return (
            None,
            _(
                "Ce format n'est pas pris en charge. Choisissez JPEG, PNG, WebP, MP4 ou WebM"
                " — sur iPhone, activez “Le plus compatible” dans Réglages > Appareil photo > Formats."
            ),
            415,
        )
    mime = file.content_type or ""
    if mime not in ALLOWED_MIME:
        return (
            None,
            _("Ce format n'est pas pris en charge. Choisissez JPEG, PNG, WebP, MP4 ou WebM."),
            415,
        )
    # Validate magic bytes (content must match claimed MIME)
    if not _validate_magic_bytes(file, mime):
        return None, _("Fichier invalide (contenu ne correspond pas au format déclaré)."), 415

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        return (
            None,
            _("Fichier trop volumineux (max %(max)s).", max=format_filesize(MAX_FILE_SIZE)),
            413,
        )

    event = ctx.event
    creator = event.creator
    if not can_upload_media(creator, size):
        if ctx.is_creator:
            return (
                None,
                _("Votre espace de stockage est plein. Supprimez des médias pour en ajouter."),
                409,
            )
        return (
            None,
            _("L'espace de stockage de l'événement est plein. Prévenez l'organisateur."),
            409,
        )

    lat, lng, taken_at = _extract_exif(file)

    # Save file (extension derived from verified MIME, not user filename)
    stored_name = f"{uuid.uuid4().hex}{_MIME_EXT[mime]}"
    path = _media_dir(event.code) / stored_name
    file.save(str(path))

    item = MediaItem(
        filename=stored_name,
        original_name=clean_name(file.filename, mime),
        mime_type=mime,
        size_bytes=size,
        caption=caption,
        latitude=lat,
        longitude=lng,
        taken_at=taken_at,
        uploaded_by=ctx.participant.id if ctx.participant else None,
        uploaded_by_name=ctx.actor.name,
        event_id=event.id,
    )
    db.session.add(item)
    consume_media_quota(creator, size)
    log_event(
        ctx,
        "media.uploaded",
        target=item.original_name,
        details=f"{size // 1024} KB, geo={1 if lat else 0}",
    )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        path.unlink(missing_ok=True)
        return None, _("L'envoi a échoué. Réessayez."), 500
    return item, None, 201


@media_bp.route("/e/<code>/media/upload", methods=["POST"])
@limiter.limit(UPLOAD_LIMIT)
def upload(code: str) -> Response:
    """Envoi d'un média (le client envoie un fichier par requête ; sans JS, plusieurs fichiers sont acceptés)."""
    ctx = load_event_context(code)
    request.max_content_length = MAX_FILE_SIZE + 1024 * 1024  # au-delà : 413 sans tout lire
    caption = request.form.get("caption", "").strip()[:CAPTION_MAX]
    files: list[FileStorage | None] = [*request.files.getlist("file")] or [None]

    if _wants_json():
        item, error, status = _store(ctx, files[0], caption)
        if error:
            return jsonify(ok=False, message=error), status  # type: ignore[return-value]
        return jsonify(ok=True, id=item.id if item else None), status  # type: ignore[return-value]

    stored = 0
    errors: list[str] = []
    for file in files:
        item, error, _status = _store(ctx, file, caption)
        if error:
            if error not in errors:
                errors.append(error)
        else:
            stored += 1
    for error in errors:
        flash(error, "danger")
    if stored:
        flash(
            _("Média ajouté.") if stored == 1 else _("%(count)s médias ajoutés.", count=stored),
            "success",
        )
    return redirect(url_for("media.gallery", code=code))


@media_bp.route("/e/<code>/media/<item_id>")
def detail(code: str, item_id: str) -> str | Response:
    """Visionneuse : un média, précédent/suivant dans l'ordre de la galerie."""
    ctx = load_event_context(code)
    event = ctx.event
    item = MediaItem.query.filter_by(id=item_id, event_id=event.id).first_or_404()
    newer = _newer(event, item)
    previous_item = newer.order_by(_KEY.asc(), MediaItem.id.asc()).first()
    next_item = _older(event, item).order_by(_KEY.desc(), MediaItem.id.desc()).first()
    position = newer.count() + 1
    return render_template(
        "media/detail.html",
        event=event,
        item=item,
        previous_item=previous_item,
        next_item=next_item,
        position=position,
        total=event.media.count(),
        caption_max=CAPTION_MAX,
        download_name=clean_name(item.original_name, item.mime_type),
    )


@media_bp.route("/e/<code>/media/<item_id>/caption", methods=["POST"])
def caption(code: str, item_id: str) -> Response:
    """Légende modifiable par l'auteur ou le créateur."""
    ctx = load_event_context(code)
    item = MediaItem.query.filter_by(id=item_id, event_id=ctx.event.id).first_or_404()
    if not ctx.can_edit(item):
        abort(403)
    text = request.form.get("caption", "").strip()
    if len(text) > CAPTION_MAX:
        flash(
            _("La légende est trop longue (%(max)s caractères maximum).", max=CAPTION_MAX), "danger"
        )
    else:
        item.caption = text
        db.session.commit()
        flash(_("Légende enregistrée."), "success")
    return redirect(url_for("media.detail", code=code, item_id=item_id))


@media_bp.route("/e/<code>/media/<item_id>/delete", methods=["POST"])
def delete(code: str, item_id: str) -> Response:
    """Delete a media item (uploader or creator)."""
    ctx = load_event_context(code)
    event = ctx.event

    item = MediaItem.query.filter_by(id=item_id, event_id=event.id).first_or_404()
    if not ctx.can_delete(item):
        abort(403)

    # Références (justificatifs de frais) mises à NULL ; fichiers et quota seulement après le commit réussi.
    media_dir = _media_dir(code)
    path = media_dir / item.filename
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
    delete_thumbs(media_dir, item_id)

    flash(_("Média supprimé."), "success")
    return redirect(url_for("media.gallery", code=code))
