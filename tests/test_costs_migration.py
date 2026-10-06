"""Migration B024 : colonnes `created_by` des frais + dates NULL renseignées (date de création)."""

import sqlite3

import pytest

from app import create_app
from app.migrations import migrate_costs, plan_costs_migration, run_costs_migration

LEGACY = (
    "DROP TABLE expenses",
    "DROP TABLE transfers",
    "DROP TABLE payment_requests",
    "CREATE TABLE expenses (id VARCHAR(32) NOT NULL, description VARCHAR(300) NOT NULL, "
    "amount_cents INTEGER NOT NULL, currency VARCHAR(3), exchange_rate FLOAT, "
    "paid_by_household_id VARCHAR(32) NOT NULL, date DATE, category VARCHAR(50), "
    "is_shared BOOLEAN NOT NULL, receipt_media_id VARCHAR(32), custom_split TEXT, "
    "created_at DATETIME, event_id VARCHAR(32) NOT NULL, PRIMARY KEY (id))",
    "CREATE TABLE transfers (id VARCHAR(32) NOT NULL, from_household_id VARCHAR(32) NOT NULL, "
    "to_household_id VARCHAR(32) NOT NULL, amount_cents INTEGER NOT NULL, currency VARCHAR(3), "
    "exchange_rate FLOAT, note VARCHAR(300), date DATE, created_at DATETIME, "
    "event_id VARCHAR(32) NOT NULL, PRIMARY KEY (id))",
    "CREATE TABLE payment_requests (id VARCHAR(32) NOT NULL, from_household_id VARCHAR(32) NOT NULL, "
    "to_household_id VARCHAR(32) NOT NULL, amount_cents INTEGER NOT NULL, message VARCHAR(500), "
    "is_resolved BOOLEAN, resolved_at DATETIME, created_at DATETIME, "
    "event_id VARCHAR(32) NOT NULL, PRIMARY KEY (id))",
)


@pytest.fixture
def legacy_app(monkeypatch, tmp_path):
    """Base fichier au schéma d'avant B024 : pas de created_by, des dates NULL."""
    monkeypatch.setattr("app.load_dotenv", lambda *args, **kwargs: True)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path / "inst"))
    monkeypatch.setenv("SKIP_STARTUP_MIGRATION", "1")
    app = create_app()
    con = sqlite3.connect(tmp_path / "t.db")
    for statement in LEGACY:
        con.execute(statement)
    con.execute(
        "INSERT INTO expenses (id, description, amount_cents, paid_by_household_id, date, is_shared, created_at, event_id) "
        "VALUES ('x1', 'Sans date', 1000, 'h1', NULL, 1, '2026-03-04 10:30:00.123456', 'e1')"
    )
    con.execute(
        "INSERT INTO expenses (id, description, amount_cents, paid_by_household_id, date, is_shared, created_at, event_id) "
        "VALUES ('x2', 'Datée', 500, 'h1', '2026-01-02', 1, '2026-03-04 10:30:00', 'e1')"
    )
    con.execute(
        "INSERT INTO transfers (id, from_household_id, to_household_id, amount_cents, date, created_at, event_id) "
        "VALUES ('t1', 'h1', 'h2', 100, NULL, '2026-02-05 08:00:00', 'e1')"
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


def test_plan_reports_columns_and_null_dates_without_writing(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        plan = plan_costs_migration(db.engine)
    assert plan == {"created_by_columns": 3, "expense_dates": 1, "transfer_dates": 1}
    assert _query(tmp_path, "SELECT date FROM expenses WHERE id='x1'") == [(None,)]


def test_migrate_fills_null_expense_date_with_created_at_date(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_costs(db.engine)
    assert _query(tmp_path, "SELECT date FROM expenses WHERE id='x1'") == [("2026-03-04",)]


def test_migrate_keeps_existing_expense_date(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_costs(db.engine)
    assert _query(tmp_path, "SELECT date FROM expenses WHERE id='x2'") == [("2026-01-02",)]


def test_migrate_fills_null_transfer_date_with_created_at_date(legacy_app, tmp_path):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_costs(db.engine)
    assert _query(tmp_path, "SELECT date FROM transfers") == [("2026-02-05",)]


@pytest.mark.parametrize("table", ["expenses", "transfers", "payment_requests"])
def test_migrate_adds_created_by_column(legacy_app, tmp_path, table):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_costs(db.engine)
    columns = {row[1] for row in _query(tmp_path, f"PRAGMA table_info({table})")}
    assert "created_by" in columns


def test_migrate_second_run_plans_nothing(legacy_app):
    from app.extensions import db

    with legacy_app.app_context():
        migrate_costs(db.engine)
        assert not any(plan_costs_migration(db.engine).values())


def test_run_creates_backup_when_dates_are_rewritten(legacy_app, tmp_path):
    with legacy_app.app_context():
        run_costs_migration(legacy_app)
    assert len(list((tmp_path / "inst" / "backups").glob("pre-costs-*.db"))) == 1


def test_run_second_time_creates_no_new_backup(legacy_app, tmp_path):
    with legacy_app.app_context():
        run_costs_migration(legacy_app)
        run_costs_migration(legacy_app)
    assert len(list((tmp_path / "inst" / "backups").glob("pre-costs-*.db"))) == 1
