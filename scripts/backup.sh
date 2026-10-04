#!/bin/bash
# Backup SQLite quotidien (B015)
# Usage : scripts/backup.sh [chemin_racine_projet]
# Planifier via cron : 0 3 * * * /chemin/vers/saas/scripts/backup.sh
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DB="$ROOT/instance/holishared.db"
BACKUP_DIR="$ROOT/backups"
KEEP_DAYS=7

if [[ ! -f "$DB" ]]; then
    echo "ERREUR : base introuvable : $DB" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
TARGET="$BACKUP_DIR/holishared_$STAMP.db"

if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB" ".backup '$TARGET'"
else
    # Fallback : module sqlite3 Python (même mécanisme de backup en ligne)
    python3 -c "
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
src.close()
dst.close()
" "$DB" "$TARGET"
fi

echo "Backup créé : $TARGET ($(du -h "$TARGET" | cut -f1))"

# Garder 7 jours
find "$BACKUP_DIR" -name "holishared_*.db" -mtime +$KEEP_DAYS -delete
echo "Purge des backups de plus de $KEEP_DAYS jours terminée."
