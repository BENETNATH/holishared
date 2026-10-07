"""Infos pratiques (B025b) : ordre logique et texte avec liens http(s) cliquables."""

from __future__ import annotations

import re
from datetime import datetime

from markupsafe import Markup, escape

from app.i18n import LABELS
from app.models import LogisticsItem

_RANK = {key: i for i, key in enumerate(LABELS["info_category"])}
_URL = re.compile(r"https?://[^\s<>\"']+")
_TRAILING = ".,;:!?)]}»"


def ordered_infos(event_id: str, limit: int | None = None) -> list[LogisticsItem]:
    """Catégorie dans l'ordre du registre (inconnues à la fin, par clé), puis ``order``, puis ancienneté."""
    items: list[LogisticsItem] = LogisticsItem.query.filter_by(event_id=event_id).all()
    items.sort(
        key=lambda i: (
            _RANK.get(i.category, len(_RANK)),
            i.category or "",
            i.order or 0,
            i.created_at or datetime.min,  # noqa: DTZ901 - dates naïves en base
            i.id,
        )
    )
    return items[:limit] if limit else items


def linkify(text: str | None) -> Markup:
    """Échappe ``text`` et rend les URL http(s) cliquables (aucun HTML brut accepté)."""
    out: list[str] = []
    pos = 0
    text = text or ""
    for match in _URL.finditer(text):
        url = match.group(0).rstrip(_TRAILING)
        end = match.start() + len(url)
        out.append(str(escape(text[pos : match.start()])))
        out.append(
            f'<a class="ui-link break-all" href="{escape(url)}" target="_blank" '
            f'rel="noopener noreferrer">{escape(url)}</a>'
        )
        pos = end
    out.append(str(escape(text[pos:])))
    return Markup("".join(out))  # noqa: S704 - segments et URL échappés ci-dessus
