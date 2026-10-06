"""Migrations (B029, B022) : identité unique du créateur, schéma des repas, sauvegarde, vérification.

Idempotentes : une seconde exécution ne fait rien et ne crée aucune sauvegarde.
"""

import json
import logging
import os
import secrets
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Flask
from sqlalchemy.engine import make_url

from app.context import CREATOR_FALLBACK_NAME
from app.extensions import db
from app.models import (
    Activity,
    ChatMessage,
    Creator,
    Event,
    Guest,
    ListItem,
    Meal,
    MediaItem,
    SharedList,
)

logger = logging.getLogger(__name__)

BACKUP_PREFIX = "pre-identity-"
MEALS_BACKUP_PREFIX = "pre-meals-"
LISTS_BACKUP_PREFIX = "pre-lists-"
_KEYS = (
    "creator_guests_reactivated",
    "creator_guests_created",
    "list_items_from_creator_id",
    "list_items_from_name",
    "activities_created_by",
    "meals_created_by",
    "chat_messages_guest_id",
    "media_uploaded_by",
)


def _creator_guests(session: Any, event: Event, *, active: bool) -> list[Guest]:
    query = session.query(Guest).filter(
        Guest.event_id == event.id,
        Guest.creator_id == event.creator_id,
        Guest.is_active.is_(active),
    )
    order = (Guest.joined_at, Guest.id) if active else (Guest.joined_at.desc(), Guest.id)
    return list(query.order_by(*order).all())


def _run_identity_steps(session: Any, *, apply: bool) -> dict[str, int]:
    """Calcule (apply=False) ou applique (apply=True) la migration d'identité."""
    result = dict.fromkeys(_KEYS, 0)
    events = (
        session.query(Event).filter(Event.is_active.is_(True), Event.verified_at.isnot(None)).all()
    )
    # Participants créateurs prévus (calcul à blanc) : event.id -> (id, nom).
    planned: dict[str, tuple[str, str]] = {}
    participant: dict[str, str] = {}

    # Étapes 1-2 : participant créateur (réactivé ou créé).
    for event in events:
        actives = _creator_guests(session, event, active=True)
        if actives:
            participant[event.id] = actives[0].id
            continue
        inactives = _creator_guests(session, event, active=False)
        if inactives:
            guest = inactives[0]
            result["creator_guests_reactivated"] += 1
            if apply:
                guest.is_active = True
            else:
                planned[event.id] = (guest.id, guest.display_name)
            participant[event.id] = guest.id
            continue
        creator = session.get(Creator, event.creator_id)
        name = ((creator.display_name if creator else "") or CREATOR_FALLBACK_NAME)[:50]
        result["creator_guests_created"] += 1
        if apply:
            guest = Guest(
                code=secrets.token_hex(8),
                display_name=name,
                event_id=event.id,
                creator_id=event.creator_id,
            )
            session.add(guest)
            participant[event.id] = guest.id  # remplacé après flush
            planned[event.id] = ("", name)
        else:
            planned[event.id] = (f"planned:{event.id}", name)
            participant[event.id] = f"planned:{event.id}"
    if apply:
        session.flush()
        for event in events:
            if event.id in planned:
                participant[event.id] = _creator_guests(session, event, active=True)[0].id
        planned = {}

    creator_ids = {row[0] for row in session.query(Creator.id).all()}
    # Étapes 3-8, seulement pour les événements actifs et vérifiés.
    for event in events:
        pid = participant[event.id]
        items = (
            session.query(ListItem)
            .join(SharedList, ListItem.list_id == SharedList.id)
            .filter(SharedList.event_id == event.id)
            .all()
        )
        for item in items:
            if item.assigned_to_id in creator_ids:
                if item.assigned_to_id == event.creator_id:
                    result["list_items_from_creator_id"] += 1
                    if apply:
                        item.assigned_to_id = pid
            elif item.assigned_to and item.assigned_to_id is None:
                count = (
                    session.query(Guest)
                    .filter(
                        Guest.event_id == event.id,
                        Guest.is_active.is_(True),
                        Guest.display_name == item.assigned_to,
                    )
                    .count()
                )
                if event.id in planned and planned[event.id][1] == item.assigned_to:
                    count += 1  # participant prévu, pas encore actif en base
                if count == 1:
                    result["list_items_from_name"] += 1
                    if apply:
                        match = (
                            session.query(Guest)
                            .filter_by(
                                event_id=event.id, is_active=True, display_name=item.assigned_to
                            )
                            .first()
                        )
                        item.assigned_to_id = match.id if match else pid
        for model, column, key in (
            (Activity, "created_by", "activities_created_by"),
            (Meal, "created_by", "meals_created_by"),
            (MediaItem, "uploaded_by", "media_uploaded_by"),
        ):
            rows = session.query(model).filter(
                model.event_id == event.id, getattr(model, column).is_(None)
            )
            for row in rows.all():
                result[key] += 1
                if apply:
                    setattr(row, column, pid)
        for message in (
            session.query(ChatMessage)
            .filter(
                ChatMessage.event_id == event.id,
                ChatMessage.author_type == "creator",
                ChatMessage.guest_id.is_(None),
            )
            .all()
        ):
            result["chat_messages_guest_id"] += 1
            if apply:
                message.guest_id = pid
    return result


def plan_identity_migration(session: Any) -> dict[str, int]:
    """Calcul à blanc : aucune écriture."""
    return _run_identity_steps(session, apply=False)


def migrate_identity(session: Any) -> dict[str, int]:
    """Applique la migration en un seul commit (rollback puis propagation en cas d'erreur)."""
    try:
        result = _run_identity_steps(session, apply=True)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return result


def check_identity(session: Any) -> list[str]:
    """Anomalies d'identité (lecture seule), triées, au format "<type>:<id>"."""
    found: list[str] = []
    creator_ids = {row[0] for row in session.query(Creator.id).all()}
    events = (
        session.query(Event).filter(Event.is_active.is_(True), Event.verified_at.isnot(None)).all()
    )
    for event in events:
        actives = _creator_guests(session, event, active=True)
        if not actives:
            found.append(f"missing_creator_guest:{event.id}")
        elif len(actives) > 1:
            found.append(f"duplicate_creator_guest:{event.id}")
        guest_ids = {row[0] for row in session.query(Guest.id).filter_by(event_id=event.id)}
        items = (
            session.query(ListItem)
            .join(SharedList, ListItem.list_id == SharedList.id)
            .filter(SharedList.event_id == event.id)
            .all()
        )
        for item in items:
            if item.assigned_to_id in creator_ids:
                found.append(f"list_item_creator_id:{item.id}")
            elif item.assigned_to_id is not None and item.assigned_to_id not in guest_ids:
                found.append(f"list_item_foreign_guest:{item.id}")
        for model, column, label in (
            (Activity, "created_by", "activity_null_author"),
            (Meal, "created_by", "meal_null_author"),
            (MediaItem, "uploaded_by", "media_null_uploader"),
        ):
            for row in session.query(model).filter(
                model.event_id == event.id, getattr(model, column).is_(None)
            ):
                found.append(f"{label}:{row.id}")
        for message in session.query(ChatMessage).filter(
            ChatMessage.event_id == event.id,
            ChatMessage.author_type == "creator",
            ChatMessage.guest_id.is_(None),
        ):
            found.append(f"chat_creator_null_guest:{message.id}")
    return sorted(found)


def backup_sqlite_database(
    db_uri: str, instance_path: str, prefix: str = BACKUP_PREFIX
) -> Path | None:
    """Copie la base SQLite (compatible WAL) dans <instance>/backups/ ; None sinon."""
    url = make_url(db_uri)
    if not url.drivername.startswith("sqlite") or url.database in (None, "", ":memory:"):
        return None
    target_dir = Path(instance_path) / "backups"
    target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(target_dir, 0o700)  # dossier privé même s'il existait avec d'autres droits
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = target_dir / f"{prefix}{stamp}.db"
    os.close(os.open(target, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600))  # privé dès la création
    source = sqlite3.connect(str(url.database))
    destination = sqlite3.connect(str(target))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    target.chmod(0o600)
    return target


def prune_backups(instance_path: str, *, keep: int = 3, max_age_days: int = 30) -> int:
    """Supprime les sauvegardes trop vieilles, puis toutes sauf les `keep` plus récentes."""
    folder = Path(instance_path) / "backups"
    if not folder.is_dir():
        return 0
    files = sorted(folder.glob("pre-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).timestamp()
    removed = 0
    for index, path in enumerate(files):
        if index >= keep or path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
    return removed


def run_identity_migration(app: Flask) -> dict[str, int]:
    """Migration au démarrage : sauvegarde seulement si des écritures sont prévues."""
    plan = plan_identity_migration(db.session)
    if sum(plan.values()) == 0:
        return plan
    backup = backup_sqlite_database(app.config["SQLALCHEMY_DATABASE_URI"], app.instance_path)
    prune_backups(app.instance_path)
    result = migrate_identity(db.session)
    logger.info("identity migration %s backup=%s", result, backup or "-")
    return result


def _meals_rebuild_needed(conn: Any) -> bool:
    """Vrai si `meals` a encore l'unicité (event, date, slot) ou n'a pas `position`."""
    columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(meals)")}
    if not columns:
        return False  # table absente : create_all la créera au bon schéma
    if "position" not in columns:
        return True
    for index in conn.exec_driver_sql("PRAGMA index_list(meals)").fetchall():
        if index[2]:  # unique
            info = conn.exec_driver_sql(f'PRAGMA index_info("{index[1]}")').fetchall()
            if [row[2] for row in info] == ["event_id", "date", "slot"]:
                return True
    return False


def plan_meals_migration(engine: Any) -> dict[str, int]:
    """Calcul à blanc : `meals_rebuild` (0/1) et `meals_rows` (lignes à recopier)."""
    if engine.dialect.name != "sqlite":
        return {"meals_rebuild": 0, "meals_rows": 0}
    with engine.connect() as conn:
        if not _meals_rebuild_needed(conn):
            return {"meals_rebuild": 0, "meals_rows": 0}
        rows = conn.exec_driver_sql("SELECT COUNT(*) FROM meals").scalar() or 0
    return {"meals_rebuild": 1, "meals_rows": int(rows)}


_MEALS_REBUILD = (
    "DROP TABLE IF EXISTS meals_new",
    "CREATE TABLE meals_new (id VARCHAR(32) NOT NULL, title VARCHAR(200) NOT NULL, "
    "date DATE NOT NULL, slot VARCHAR(10) NOT NULL, position INTEGER DEFAULT 0 NOT NULL, "
    "created_by VARCHAR(32), created_at DATETIME, event_id VARCHAR(32) NOT NULL, "
    "PRIMARY KEY (id), FOREIGN KEY(created_by) REFERENCES guests (id), "
    "FOREIGN KEY(event_id) REFERENCES events (id))",
    "INSERT INTO meals_new (id, title, date, slot, position, created_by, created_at, event_id) "
    "SELECT id, title, date, slot, "
    "ROW_NUMBER() OVER (PARTITION BY event_id, date, slot ORDER BY created_at, id) - 1, "
    "created_by, created_at, event_id FROM meals",
    "DROP TABLE meals",
    "ALTER TABLE meals_new RENAME TO meals",
    "CREATE INDEX ix_meal_cell ON meals (event_id, date, slot, position)",
)


def migrate_meals_schema(engine: Any) -> dict[str, int]:
    """Reconstruit `meals` (sans unicité de case, avec `position`) en une transaction."""
    plan = plan_meals_migration(engine)
    if not plan["meals_rebuild"]:
        return plan
    with engine.connect() as conn:
        # Reconstruction de table SQLite : clés étrangères suspendues (sans effet dans une transaction).
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            conn.exec_driver_sql("BEGIN")
            try:
                for statement in _MEALS_REBUILD:
                    conn.exec_driver_sql(statement)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        finally:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    return plan


def run_meals_migration(app: Flask) -> dict[str, int]:
    """Migration des repas au démarrage : sauvegarde seulement s'il y a des lignes à recopier."""
    plan = plan_meals_migration(db.engine)
    if not plan["meals_rebuild"]:
        return plan
    backup = None
    if plan["meals_rows"]:
        backup = backup_sqlite_database(
            app.config["SQLALCHEMY_DATABASE_URI"], app.instance_path, MEALS_BACKUP_PREFIX
        )
        prune_backups(app.instance_path)
    result = migrate_meals_schema(db.engine)
    logger.info("meals migration %s backup=%s", result, backup or "-")
    return result


def _legacy_ids(raw: Any) -> list[str]:
    """Identifiants d'un tableau JSON historique (texte SQLite ou liste) ; valeurs invalides ignorées."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(i for i in raw if isinstance(i, str)))


def _lists_state(conn: Any) -> dict[str, Any]:
    """Calcul à blanc B023 : colonne `created_by` manquante, couvertures JSON à transférer."""
    columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(list_items)")}
    column_missing = bool(columns) and "created_by" not in columns
    valid = {
        "meal": {r[0] for r in conn.exec_driver_sql("SELECT id FROM meals")},
        "activity": {r[0] for r in conn.exec_driver_sql("SELECT id FROM activities")},
    }
    existing = {
        "meal": set(
            conn.exec_driver_sql("SELECT list_id, meal_id FROM list_meal_coverages").fetchall()
        ),
        "activity": set(
            conn.exec_driver_sql(
                "SELECT list_id, activity_id FROM list_activity_coverages"
            ).fetchall()
        ),
    }
    inserts: dict[str, list[tuple[str, str]]] = {"meal": [], "activity": []}
    orphans = 0
    to_clear: list[str] = []
    for list_id, raw_meals, raw_acts in conn.exec_driver_sql(
        "SELECT id, covered_meals, covered_activities FROM shared_lists"
    ).fetchall():
        ids = {"meal": _legacy_ids(raw_meals), "activity": _legacy_ids(raw_acts)}
        if (
            ids["meal"]
            or ids["activity"]
            or raw_meals not in (None, "[]")
            or raw_acts not in (None, "[]")
        ):
            to_clear.append(list_id)
        for kind, values in ids.items():
            for target in values:
                if target not in valid[kind]:
                    orphans += 1
                elif (list_id, target) not in existing[kind]:
                    inserts[kind].append((list_id, target))
    return {
        "column_missing": column_missing,
        "inserts": inserts,
        "orphans": orphans,
        "to_clear": to_clear,
    }


def _lists_plan(state: dict[str, Any]) -> dict[str, int]:
    return {
        "list_items_created_by_column": int(state["column_missing"]),
        "meal_coverages": len(state["inserts"]["meal"]),
        "activity_coverages": len(state["inserts"]["activity"]),
        "orphans_ignored": state["orphans"],
        "json_cleared": len(state["to_clear"]),
    }


def plan_lists_migration(engine: Any) -> dict[str, int]:
    """Calcul à blanc B023 (aucune écriture)."""
    with engine.connect() as conn:
        return _lists_plan(_lists_state(conn))


def migrate_lists(engine: Any) -> dict[str, int]:
    """Colonne `list_items.created_by` + tableaux JSON de couverture -> tables d'association.

    Une seule transaction ; les tableaux JSON sont vidés une fois transférés (sinon une
    seconde exécution rétablirait une couverture décochée entre-temps).
    """
    with engine.begin() as conn:
        state = _lists_state(conn)
        plan = _lists_plan(state)
        if not any(plan.values()):
            return plan
        if state["column_missing"]:
            conn.exec_driver_sql(
                "ALTER TABLE list_items ADD COLUMN created_by VARCHAR(32) REFERENCES guests (id)"
            )
        now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
        for kind, table, column in (
            ("meal", "list_meal_coverages", "meal_id"),
            ("activity", "list_activity_coverages", "activity_id"),
        ):
            for list_id, target in state["inserts"][kind]:
                conn.exec_driver_sql(
                    f"INSERT INTO {table} (list_id, {column}, covered_at) VALUES (?, ?, ?)",  # noqa: S608 - identifiants constants
                    (list_id, target, now),
                )
        for list_id in state["to_clear"]:
            conn.exec_driver_sql(
                "UPDATE shared_lists SET covered_meals = '[]', covered_activities = '[]' WHERE id = ?",
                (list_id,),
            )
    return plan


def run_lists_migration(app: Flask) -> dict[str, int]:
    """Migration des listes au démarrage : sauvegarde seulement si des écritures sont prévues."""
    plan = plan_lists_migration(db.engine)
    if not any(plan.values()):
        return plan
    backup = backup_sqlite_database(
        app.config["SQLALCHEMY_DATABASE_URI"], app.instance_path, LISTS_BACKUP_PREFIX
    )
    prune_backups(app.instance_path)
    result = migrate_lists(db.engine)
    logger.info("lists migration %s backup=%s", result, backup or "-")
    return result


def main(argv: list[str]) -> int:
    if argv[1:] != ["check"]:
        print("Usage: python -m app.migrations check")
        return 2
    os.environ["SKIP_STARTUP_MIGRATION"] = "1"  # `check` ne doit rien écrire
    from app import create_app

    app = create_app()
    with app.app_context():
        problems = check_identity(db.session)
    for line in problems:
        print(line)
    if not problems:
        print("[OK] identity consistent")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
