"""Migration B025 : colonnes des sondages d'activités, valeurs par défaut, idempotence, FK SET NULL."""

import sqlite3

import pytest

from app import create_app
from app.migrations import migrate_polls, plan_polls_migration, run_polls_migration
from app.models import Activity, Poll, PollOption

LEGACY = (
    "DROP TABLE poll_options",
    "DROP TABLE polls",
    "DROP TABLE activities",
    "CREATE TABLE activities (id VARCHAR(32) NOT NULL, title VARCHAR(200) NOT NULL, description TEXT, "
    "date DATE NOT NULL, start_time TIME, end_time TIME, location VARCHAR(300), min_headcount INTEGER, "
    "bring_items TEXT, created_by VARCHAR(32), created_at DATETIME, event_id VARCHAR(32) NOT NULL, "
    "PRIMARY KEY (id))",
    "CREATE TABLE polls (id VARCHAR(32) NOT NULL, question VARCHAR(300) NOT NULL, is_closed BOOLEAN, "
    "created_at DATETIME, event_id VARCHAR(32) NOT NULL, PRIMARY KEY (id))",
    "CREATE TABLE poll_options (id VARCHAR(32) NOT NULL, label VARCHAR(200) NOT NULL, `order` INTEGER, "
    "poll_id VARCHAR(32) NOT NULL, PRIMARY KEY (id))",
)


@pytest.fixture
def legacy_app(monkeypatch, tmp_path):
    """Base fichier au schéma d'avant B025 : une activité et un sondage existants."""
    monkeypatch.setattr("app.load_dotenv", lambda *args, **kwargs: True)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path / "inst"))
    monkeypatch.setenv("SKIP_STARTUP_MIGRATION", "1")
    app = create_app()
    con = sqlite3.connect(tmp_path / "t.db")
    for statement in LEGACY:
        con.execute(statement)
    con.execute(
        "INSERT INTO activities (id, title, date, event_id) VALUES ('a1', 'Rando', '2026-12-02', 'e1')"
    )
    con.execute(
        "INSERT INTO polls (id, question, is_closed, event_id) VALUES ('p1', 'Q ?', 0, 'e1')"
    )
    con.commit()
    con.close()
    return app


def _query(tmp_path, sql):
    con = sqlite3.connect(tmp_path / "t.db")
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_plan_reports_missing_columns_without_writing(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        plan = plan_polls_migration(db.engine)
    assert plan == {"poll_columns": 4, "poll_rows": 2}
    assert "kind" not in {row[1] for row in _query(tmp_path, "PRAGMA table_info(polls)")}


def test_migrate_gives_existing_poll_kind_free(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_polls(db.engine)
    assert _query(tmp_path, "SELECT kind, created_by FROM polls") == [("free", None)]


def test_migrate_gives_existing_activity_status_planned(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_polls(db.engine)
    assert _query(tmp_path, "SELECT status FROM activities") == [("planned",)]


def test_migrate_adds_activity_id_with_on_delete_set_null(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_polls(db.engine)
    fks = _query(tmp_path, "PRAGMA foreign_key_list(poll_options)")
    assert [(row[2], row[3], row[6]) for row in fks] == [("activities", "activity_id", "SET NULL")]


def test_migrate_second_run_plans_nothing(legacy_app):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_polls(db.engine)
        assert plan_polls_migration(db.engine) == {"poll_columns": 0, "poll_rows": 0}


def test_run_creates_backup_when_rows_exist(legacy_app, tmp_path):
    with legacy_app.app_context():
        run_polls_migration(legacy_app)
    assert len(list((tmp_path / "inst" / "backups").glob("pre-polls-*.db"))) == 1


def test_run_second_time_creates_no_new_backup(legacy_app, tmp_path):
    with legacy_app.app_context():
        run_polls_migration(legacy_app)
        run_polls_migration(legacy_app)
    assert len(list((tmp_path / "inst" / "backups").glob("pre-polls-*.db"))) == 1


def test_run_on_fresh_schema_plans_nothing(app, db):
    assert plan_polls_migration(db.engine) == {"poll_columns": 0, "poll_rows": 0}


def test_delete_activity_sets_option_activity_id_to_null_and_keeps_label(db, event):
    activity = Activity(title="Rando", date=event.start_date, event_id=event.id)
    poll = Poll(question="Q ?", kind="activities", event_id=event.id)
    db.session.add_all([activity, poll])
    db.session.flush()
    option = PollOption(
        label="Rando — mer. 2 déc.", order=0, poll_id=poll.id, activity_id=activity.id
    )
    db.session.add(option)
    db.session.commit()
    db.session.delete(activity)
    db.session.commit()
    db.session.refresh(option)
    assert (option.activity_id, option.label) == (None, "Rando — mer. 2 déc.")
