"""B017 — root service worker, offline page, manifest (spec §8)."""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _manifest() -> dict:
    return json.loads((REPO / "app/static/manifest.json").read_text(encoding="utf-8"))


# --- /sw.js ------------------------------------------------------------------------
























# --- /offline ------------------------------------------------------------------------












# --- Manifest and base markers --------------------------------------------------------
















def test_alpine_asset_removed():
    assert not (REPO / "app/static/js/alpine.min.js").exists()
