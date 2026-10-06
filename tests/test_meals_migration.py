"""Migration B022 : `meals` sans unicité de case, avec `position` (reconstruction SQLite)."""

import sqlite3

import pytest

from app import create_app
from app.migrations import migrate_meals_schema, plan_meals_migration, run_meals_migration

LEGACY_DDL = (
    "DROP TABLE meals",
    "CREATE TABLE meals (id VARCHAR(32) NOT NULL, title VARCHAR(200) NOT NULL, "
    "date DATE NOT NULL, slot VARCHAR(10) NOT NULL, created_by VARCHAR(32), "
    "created_at DATETIME, event_id VARCHAR(32) NOT NULL, PRIMARY KEY (id), "
    "CONSTRAINT uq_meal_event_slot UNIQUE (event_id, date, slot), "
    "FOREIGN KEY(created_by) REFERENCES guests (id), FOREIGN KEY(event_id) REFERENCES events (id))",
)
ROWS = (
    ("m1", "Pâtes", "2026-12-03", "lunch", "2026-01-01 10:00:00", "e1"),
    ("m2", "Soupe", "2026-12-03", "dinner", "2026-01-01 11:00:00", "e1"),
    ("m3", "Pizza", "2026-12-04", "lunch", "2026-01-01 12:00:00", "e1"),
    ("m4", "Salade", "2026-12-03", "lunch", "2026-01-01 09:00:00", "e2"),
)


@pytest.fixture
def legacy_app(monkeypatch, tmp_path):
    """Application sur base fichier dont `meals` est au schéma d'avant B022."""
    monkeypatch.setattr("app.load_dotenv", lambda *args, **kwargs: True)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path / "inst"))
    monkeypatch.setenv("SKIP_STARTUP_MIGRATION", "1")
    app = create_app()
    con = sqlite3.connect(tmp_path / "t.db")
    for statement in LEGACY_DDL:
        con.execute(statement)
    con.executemany(
        "INSERT INTO meals (id, title, date, slot, created_at, event_id) VALUES (?,?,?,?,?,?)", ROWS
    )
    con.commit()
    con.close()
    return app


def _uniques(con):
    return [r for r in con.execute("PRAGMA index_list(meals)") if r[2] and r[3] == "u"]


def _dump(tmp_path):
    con = sqlite3.connect(tmp_path / "t.db")
    has_position = any(r[1] == "position" for r in con.execute("PRAGMA table_info(meals)"))
    query = "SELECT id, title, date, slot, {}, event_id FROM meals ORDER BY id"
    rows = con.execute(query.format("position" if has_position else "NULL")).fetchall()
    uniques = _uniques(con)
    indexes = {r[1] for r in con.execute("PRAGMA index_list(meals)")}
    con.close()
    return rows, uniques, indexes


def test_plan_on_legacy_base_reports_rebuild_and_rows_without_writing(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        assert plan_meals_migration(db.engine) == {"meals_rebuild": 1, "meals_rows": 4}
    assert _dump(tmp_path)[1], "contrainte d'unicité toujours présente après le calcul à blanc"


def test_migrate_drops_unique_constraint_and_adds_position_index(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_meals_schema(db.engine)
    rows, uniques, indexes = _dump(tmp_path)
    assert uniques == []
    assert "ix_meal_cell" in indexes
    assert len(rows) == 4


def test_migrate_keeps_ids_and_data(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_meals_schema(db.engine)
    rows, _, _ = _dump(tmp_path)
    assert [(r[0], r[1], r[2], r[3], r[5]) for r in rows] == [
        ("m1", "Pâtes", "2026-12-03", "lunch", "e1"),
        ("m2", "Soupe", "2026-12-03", "dinner", "e1"),
        ("m3", "Pizza", "2026-12-04", "lunch", "e1"),
        ("m4", "Salade", "2026-12-03", "lunch", "e2"),
    ]


def test_migrate_second_run_is_noop_with_same_result(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_meals_schema(db.engine)
        first = _dump(tmp_path)
        assert plan_meals_migration(db.engine) == {"meals_rebuild": 0, "meals_rows": 0}
        migrate_meals_schema(db.engine)
    assert _dump(tmp_path) == first


def test_migrate_allows_two_meals_in_one_cell(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_meals_schema(db.engine)
    con = sqlite3.connect(tmp_path / "t.db")
    con.execute(
        "INSERT INTO meals (id, title, date, slot, position, event_id) "
        "VALUES ('m5', 'Quiche', '2026-12-03', 'lunch', 1, 'e1')"
    )
    con.commit()
    assert (
        con.execute(
            "SELECT COUNT(*) FROM meals WHERE event_id='e1' AND slot='lunch' AND date='2026-12-03'"
        ).fetchone()[0]
        == 2
    )
    con.close()


def test_migrate_numbers_positions_per_cell_by_created_at(monkeypatch, legacy_app, tmp_path):
    con = sqlite3.connect(tmp_path / "t.db")
    con.execute("DROP TABLE meals")
    con.execute(
        "CREATE TABLE meals (id VARCHAR(32) NOT NULL, title VARCHAR(200) NOT NULL, "
        "date DATE NOT NULL, slot VARCHAR(10) NOT NULL, created_by VARCHAR(32), "
        "created_at DATETIME, event_id VARCHAR(32) NOT NULL, PRIMARY KEY (id))"
    )  # sans unicité : état intermédiaire, 3 repas dans la même case
    con.executemany(
        "INSERT INTO meals (id, title, date, slot, created_at, event_id) VALUES (?,?,?,?,?,?)",
        [
            ("b", "B", "2026-12-03", "lunch", "2026-01-01 10:00:00", "e1"),
            ("a", "A", "2026-12-03", "lunch", "2026-01-01 09:00:00", "e1"),
            ("c", "C", "2026-12-03", "lunch", "2026-01-01 11:00:00", "e1"),
            ("d", "D", "2026-12-03", "dinner", "2026-01-01 08:00:00", "e1"),
        ],
    )
    con.commit()
    con.close()
    from app.extensions import db

    with legacy_app.app_context():
        migrate_meals_schema(db.engine)
    rows, _, _ = _dump(tmp_path)
    assert {r[0]: r[4] for r in rows} == {"a": 0, "b": 1, "c": 2, "d": 0}


def test_run_creates_one_backup_then_none(legacy_app, tmp_path):
    with legacy_app.app_context():
        run_meals_migration(legacy_app)
        run_meals_migration(legacy_app)
    backups = sorted((tmp_path / "inst" / "backups").glob("pre-meals-*.db"))
    assert len(backups) == 1
    con = sqlite3.connect(backups[0])
    assert con.execute("SELECT COUNT(*) FROM meals").fetchone()[0] == 4
    assert _uniques(con), "sauvegarde = état d'avant"
    con.close()


def test_run_without_rows_creates_no_backup(legacy_app, tmp_path):
    con = sqlite3.connect(tmp_path / "t.db")
    con.execute("DELETE FROM meals")
    con.commit()
    con.close()
    with legacy_app.app_context():
        run_meals_migration(legacy_app)
    assert not (tmp_path / "inst" / "backups").exists()
    assert _dump(tmp_path)[1] == []


def test_fresh_base_needs_no_migration(app):
    from app.extensions import db

    assert plan_meals_migration(db.engine) == {"meals_rebuild": 0, "meals_rows": 0}


def test_startup_migrates_legacy_meals(legacy_app, tmp_path, monkeypatch):
    monkeypatch.delenv("SKIP_STARTUP_MIGRATION")
    create_app()
    rows, uniques, _ = _dump(tmp_path)
    assert uniques == []
    assert len(rows) == 4
