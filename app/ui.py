"""Helpers Jinja du kit UI : icônes, empreintes d'assets (B017)."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from flask import Flask, current_app, url_for
from markupsafe import Markup, escape

from app.icons import ICONS


@lru_cache(maxsize=256)
def _hash_file(path: str, mtime_ns: int) -> str:
    """Empreinte du contenu ; la clé inclut mtime_ns pour suivre les modifications."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:10]


def asset_hash(filename: str) -> str:
    """10 premiers caractères hex du sha256 du fichier statique."""
    path = Path(current_app.static_folder or "", filename)
    return _hash_file(str(path), path.stat().st_mtime_ns)


def asset_url(filename: str) -> str:
    """URL d'un asset statique avec empreinte (cache busting)."""
    return url_for("static", filename=filename, v=asset_hash(filename))


def icon(name: str, label: str | None = None, size: int = 20, class_: str = "") -> Markup:
    """SVG Lucide en ligne ; KeyError si le nom est inconnu."""
    body = ICONS[name]
    classes = f"ui-icon {class_}" if class_ else "ui-icon"
    if label is None:
        a11y = 'aria-hidden="true"'
    else:
        a11y = f'role="img" aria-label="{escape(label)}"'
    return Markup(  # noqa: S704 - label et classes échappés, corps issu de app.icons
        f'<svg class="{escape(classes)}" width="{size}" height="{size}" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round" {a11y} focusable="false">{body}</svg>'
    )


def init_ui(app: Flask) -> None:
    """Enregistre les globaux Jinja du kit UI."""
    app.jinja_env.globals.update(asset_url=asset_url, icon=icon)
