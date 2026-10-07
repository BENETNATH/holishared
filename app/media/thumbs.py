"""Dérivés d'images (B026.1) : miniatures WebP générées à la demande, mises en cache sur disque.

``<instance>/media/<code>/thumbs/<id>-<taille>.webp`` ; orientation EXIF appliquée, métadonnées (EXIF/GPS)
absentes des dérivés. Fichier non décodable ou trop grand : ``None`` (le contrôleur répond 404, jamais 500).
"""

import logging
import os
import warnings
from pathlib import Path

from PIL import Image, ImageOps

log = logging.getLogger(__name__)

SIZES = (320, 960)  # côté long, en pixels
MAX_PIXELS = 50_000_000  # au-delà : refus (bombe de décompression) ; 48 Mpx des téléphones passent
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def thumb_dir(media_dir: Path) -> Path:
    return media_dir / "thumbs"


def thumb_path(media_dir: Path, item_id: str, size: int) -> Path:
    return thumb_dir(media_dir) / f"{item_id}-{size}.webp"


def delete_thumbs(media_dir: Path, item_id: str) -> None:
    """Supprime les dérivés d'un média (appelé après le commit de sa suppression)."""
    for size in SIZES:
        thumb_path(media_dir, item_id, size).unlink(missing_ok=True)


def _render(src: Path, dest: Path, size: int) -> bool:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(src) as opened:
            if opened.width * opened.height > MAX_PIXELS:
                return False
            opened.draft("RGB", (size, size))  # JPEG : décodage réduit, bien plus rapide
            img: Image.Image = ImageOps.exif_transpose(opened)
            img.thumbnail((size, size))
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert(
                    "RGBA" if "transparency" in img.info or img.mode in ("LA", "PA") else "RGB"
                )
            tmp = dest.with_name(f".{dest.name}.{os.getpid()}.{id(img)}.tmp")
            try:
                img.save(
                    tmp, "WEBP", quality=80, method=4
                )  # aucun exif=/icc_profile= : rien n'est recopié
                os.replace(tmp, dest)
            finally:
                tmp.unlink(missing_ok=True)
    return True


def ensure_thumb(media_dir: Path, filename: str, item_id: str, size: int) -> Path | None:
    """Chemin du dérivé (créé au premier accès), ``None`` si l'original est absent ou inutilisable."""
    dest = thumb_path(media_dir, item_id, size)
    if dest.is_file():
        return dest
    src = media_dir / filename
    if not src.is_file():
        return None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        return dest if _render(src, dest, size) else None
    except (
        Exception
    ) as exc:  # image non fiable : tout échec de décodage = pas de miniature, jamais de 500
        log.warning("miniature impossible pour %s : %s", item_id, exc)
        return None
