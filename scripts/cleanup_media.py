"""Supprime les fichiers media orphelins (B015).

Un fichier est orphelin s'il existe dans ``instance/media/<code>/``
sans record ``MediaItem`` correspondant pour l'événement ``<code>``.

Usage :
    python scripts/cleanup_media.py            # supprime les orphelins
    python scripts/cleanup_media.py --dry-run  # liste sans supprimer
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.extensions import db
from app.models import Event, MediaItem


def find_orphans(media_root: Path) -> list[Path]:
    """Return media files with no matching MediaItem record."""
    orphans: list[Path] = []
    if not media_root.exists():
        return orphans

    for event_dir in sorted(p for p in media_root.iterdir() if p.is_dir()):
        event = Event.query.filter_by(code=event_dir.name).first()
        if event is None:
            # L'événement entier a été supprimé : tout le dossier est orphelin
            orphans.extend(f for f in event_dir.iterdir() if f.is_file())
            continue
        known = {item.filename for item in MediaItem.query.filter_by(event_id=event.id).all()}
        orphans.extend(f for f in event_dir.iterdir() if f.is_file() and f.name not in known)
    return orphans


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="liste les orphelins sans les supprimer"
    )
    args = parser.parse_args()

    from sqlalchemy import inspect

    app = create_app()
    with app.app_context():
        if not inspect(db.engine).has_table("events"):
            print("ERREUR : table 'events' introuvable (base vide ?). Abandon.", file=sys.stderr)
            return 2
        media_root = Path(app.instance_path) / "media"
        orphans = find_orphans(media_root)

        if not orphans:
            print("Aucun fichier orphelin.")
            return 0

        for path in orphans:
            size = path.stat().st_size
            if args.dry_run:
                print(f"[dry-run] orphelin : {path} ({size} octets)")
            else:
                path.unlink()
                print(f"supprimé : {path} ({size} octets)")

        print(f"Total : {len(orphans)} fichier(s) {'listé(s)' if args.dry_run else 'supprimé(s)'}.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
