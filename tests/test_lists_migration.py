"""Migration B023 : couverture des listes en clés étrangères + `list_items.created_by`."""

import json
import sqlite3

import pytest

from app import create_app
from app.migrations import migrate_lists, plan_lists_migration, run_lists_migration

LEGACY_ITEMS = (
    "DROP TABLE list_items",
    "CREATE TABLE list_items (id VARCHAR(32) NOT NULL, name VARCHAR(300) NOT NULL, "
    "quantity VARCHAR(50), assigned_to VARCHAR(50), assigned_to_id VARCHAR(32), is_done BOOLEAN, "
    "section VARCHAR(100), created_at DATETIME, list_id VARCHAR(32) NOT NULL, PRIMARY KEY (id), "
    "FOREIGN KEY(list_id) REFERENCES shared_lists (id))",
)


def _count(con, table):
    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608


@pytest.fixture
def legacy_app(monkeypatch, tmp_path):
    """Base fichier au schéma d'avant B023 : tableaux JSON de couverture, pas de created_by."""
    monkeypatch.setattr("app.load_dotenv", lambda *args, **kwargs: True)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path / "inst"))
    monkeypatch.setenv("SKIP_STARTUP_MIGRATION", "1")
    app = create_app()
    con = sqlite3.connect(tmp_path / "t.db")
    for statement in LEGACY_ITEMS:
        con.execute(statement)
    con.execute(
        "INSERT INTO meals (id, title, date, slot, position, event_id) VALUES ('m1','Pâtes','2026-12-03','lunch',0,'e1')"
    )
    con.execute(
        "INSERT INTO meals (id, title, date, slot, position, event_id) VALUES ('m2','Soupe','2026-12-03','dinner',0,'e1')"
    )
    con.execute(
        "INSERT INTO activities (id, title, date, event_id) VALUES ('a1','Rando','2026-12-04','e1')"
    )
    for list_id, meals, acts in (
        ("l1", ["m1", "ghost-meal"], ["a1", "ghost-act"]),
        ("l2", ["m1", "m2"], []),
        ("l3", [], []),
    ):
        con.execute(
            "INSERT INTO shared_lists (id, title, list_type, covered_meals, covered_activities, event_id) "
            "VALUES (?, ?, 'general', ?, ?, 'e1')",
            (list_id, list_id, json.dumps(meals), json.dumps(acts)),
        )
    con.execute("INSERT INTO list_items (id, name, list_id) VALUES ('i1', 'Pain', 'l1')")
    con.commit()
    con.close()
    return app


def _columns(tmp_path):
    con = sqlite3.connect(tmp_path / "t.db")
    cols = {r[1] for r in con.execute("PRAGMA table_info(list_items)")}
    con.close()
    return cols


def test_plan_reports_valid_coverages_orphans_and_column_without_writing(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        plan = plan_lists_migration(db.engine)
    assert plan == {
        "list_items_created_by_column": 1,
        "meal_coverages": 3,
        "activity_coverages": 1,
        "orphans_ignored": 2,
        "json_cleared": 2,
    }
    assert "created_by" not in _columns(tmp_path)


def test_migrate_creates_meal_coverage_rows_for_valid_ids(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_lists(db.engine)
    con = sqlite3.connect(tmp_path / "t.db")
    rows = set(con.execute("SELECT list_id, meal_id FROM list_meal_coverages"))
    assert rows == {("l1", "m1"), ("l2", "m1"), ("l2", "m2")}


def test_migrate_creates_activity_coverage_rows_and_ignores_orphans(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_lists(db.engine)
    con = sqlite3.connect(tmp_path / "t.db")
    assert set(con.execute("SELECT list_id, activity_id FROM list_activity_coverages")) == {
        ("l1", "a1")
    }


def test_migrate_adds_created_by_column_and_keeps_items(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_lists(db.engine)
    con = sqlite3.connect(tmp_path / "t.db")
    assert "created_by" in _columns(tmp_path)
    assert con.execute("SELECT name, created_by FROM list_items").fetchall() == [("Pain", None)]


def test_migrate_empties_json_columns_so_they_are_not_read_again(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_lists(db.engine)
    con = sqlite3.connect(tmp_path / "t.db")
    rows = con.execute("SELECT covered_meals, covered_activities FROM shared_lists").fetchall()
    assert set(rows) == {("[]", "[]")}


def test_migrate_second_run_plans_nothing(legacy_app):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_lists(db.engine)
        assert not any(plan_lists_migration(db.engine).values())


def test_migrate_second_run_keeps_coverage_unchecked_in_between(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_lists(db.engine)
        con = sqlite3.connect(tmp_path / "t.db")
        con.execute("DELETE FROM list_meal_coverages WHERE list_id='l2' AND meal_id='m1'")
        con.commit()
        con.close()
        migrate_lists(db.engine)
    con = sqlite3.connect(tmp_path / "t.db")
    assert _count(con, "list_meal_coverages") == 2


def test_run_creates_one_backup_then_none(legacy_app, tmp_path):
    from app.extensions import db  # noqa: F401

    with legacy_app.app_context():
        run_lists_migration(legacy_app)
        run_lists_migration(legacy_app)
    backups = list((tmp_path / "inst" / "backups").glob("pre-lists-*.db"))
    assert len(backups) == 1


def test_run_on_fresh_base_plans_nothing_and_makes_no_backup(app, tmp_path):
    assert not any(run_lists_migration(app).values())
    assert not (tmp_path / "backups").exists()


def test_startup_migrates_legacy_lists(monkeypatch, legacy_app, tmp_path):
    monkeypatch.delenv("SKIP_STARTUP_MIGRATION")
    monkeypatch.setattr("app.load_dotenv", lambda *args, **kwargs: True)
    create_app()
    con = sqlite3.connect(tmp_path / "t.db")
    assert _count(con, "list_meal_coverages") == 3


# --- Intégrité : cascades ON DELETE (connexion avec foreign_keys=ON) ---------------------


@pytest.fixture
def covered(db, event, guest):
    from datetime import date

    from app.models import Activity, ListActivityCoverage, ListMealCoverage, Meal, SharedList

    meal = Meal(title="Pâtes", date=date(2026, 12, 2), slot="lunch", event_id=event.id)
    act = Activity(title="Rando", date=date(2026, 12, 3), event_id=event.id)
    shared = SharedList(title="Courses", event_id=event.id)
    db.session.add_all([meal, act, shared])
    db.session.flush()
    db.session.add_all(
        [
            ListMealCoverage(list_id=shared.id, meal_id=meal.id, covered_by=guest.id),
            ListActivityCoverage(list_id=shared.id, activity_id=act.id, covered_by=guest.id),
        ]
    )
    db.session.commit()
    return {"meal": meal, "act": act, "list": shared, "guest": guest}


def test_connection_enforces_foreign_keys(db):
    assert db.session.execute(db.text("PRAGMA foreign_keys")).scalar() == 1


def test_delete_meal_cascades_to_meal_coverage(db, covered):
    from app.models import ListMealCoverage

    db.session.delete(covered["meal"])
    db.session.commit()
    assert ListMealCoverage.query.count() == 0


def test_delete_activity_cascades_to_activity_coverage(db, covered):
    from app.models import ListActivityCoverage

    db.session.delete(covered["act"])
    db.session.commit()
    assert ListActivityCoverage.query.count() == 0


def test_delete_list_cascades_to_both_coverage_tables(db, covered):
    from app.models import ListActivityCoverage, ListMealCoverage

    db.session.delete(covered["list"])
    db.session.commit()
    assert ListMealCoverage.query.count() + ListActivityCoverage.query.count() == 0


def test_delete_guest_keeps_coverage_with_null_author(db, covered):
    from app.models import ListMealCoverage

    db.session.delete(covered["guest"])
    db.session.commit()
    assert ListMealCoverage.query.one().covered_by is None


def test_coverage_of_unknown_meal_is_rejected(db, covered):
    from sqlalchemy.exc import IntegrityError

    from app.models import ListMealCoverage

    db.session.add(ListMealCoverage(list_id=covered["list"].id, meal_id="ghost"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_coverage_primary_key_rejects_duplicates(db, covered):
    from sqlalchemy.exc import IntegrityError

    from app.models import ListMealCoverage

    db.session.add(ListMealCoverage(list_id=covered["list"].id, meal_id=covered["meal"].id))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
