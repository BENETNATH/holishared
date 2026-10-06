"""Tests de la migration d'identité (B029) : données héritées -> participant créateur."""

import os
import sqlite3
from datetime import date, datetime

import pytest

from app import create_app
from app.migrations import (
    backup_sqlite_database,
    check_identity,
    migrate_identity,
    plan_identity_migration,
    prune_backups,
    run_identity_migration,
)
from app.models import (
    Activity,
    ChatMessage,
    Creator,
    Event,
    Guest,
    Household,
    ListItem,
    Meal,
    MediaItem,
    SharedList,
)

DAY = date(2026, 12, 2)


def _creator_guests(event_id):
    return Guest.query.filter(Guest.event_id == event_id, Guest.creator_id.isnot(None)).all()


@pytest.fixture
def legacy(db, event):
    """Un événement hérité : aucun participant créateur, auteurs à NULL."""
    activity = Activity(title="A", date=DAY, event_id=event.id)
    meal = Meal(title="M", date=DAY, slot="lunch", event_id=event.id)
    msg_creator = ChatMessage(
        content="c", author_name="Créateur", author_type="creator", event_id=event.id
    )
    msg_guest = ChatMessage(
        content="g", author_name="Test Guest", author_type="guest", event_id=event.id
    )
    media = MediaItem(filename="f.jpg", mime_type="image/jpeg", size_bytes=1, event_id=event.id)
    db.session.add_all([activity, meal, msg_creator, msg_guest, media])
    db.session.commit()
    return {
        "activity": activity,
        "meal": meal,
        "msg_creator": msg_creator,
        "msg_guest": msg_guest,
        "media": media,
    }


def _list_with_item(db, event, **item):
    shared = SharedList(title="L", event_id=event.id)
    db.session.add(shared)
    db.session.flush()
    obj = ListItem(name="x", list_id=shared.id, **item)
    db.session.add(obj)
    db.session.commit()
    return obj


def test_migrate_creates_missing_creator_guest(db, event):
    assert migrate_identity(db.session)["creator_guests_created"] == 1


def test_migrate_created_creator_guest_has_no_household(db, event):
    migrate_identity(db.session)
    assert Household.query.filter_by(event_id=event.id).count() == 0


def test_migrate_skips_unverified_event(db, unverified_event):
    migrate_identity(db.session)
    assert _creator_guests(unverified_event.id) == []


def test_migrate_reactivates_inactive_creator_guest(db, event, creator_guest):
    creator_guest.is_active = False
    db.session.commit()
    assert migrate_identity(db.session)["creator_guests_reactivated"] == 1


def test_migrate_converts_list_item_creator_id(db, event, creator):
    item = _list_with_item(db, event, assigned_to="Créateur", assigned_to_id=creator.id)
    migrate_identity(db.session)
    assert item.assigned_to_id == _creator_guests(event.id)[0].id


def test_migrate_assigns_list_item_by_unique_name(db, event, guest):
    item = _list_with_item(db, event, assigned_to="Test Guest")
    migrate_identity(db.session)
    assert item.assigned_to_id == guest.id


def test_migrate_leaves_ambiguous_name_unassigned(db, event, guest):
    db.session.add(Guest(code="dup00001", display_name="Test Guest", event_id=event.id))
    item = _list_with_item(db, event, assigned_to="Test Guest")
    migrate_identity(db.session)
    assert item.assigned_to_id is None


def test_migrate_sets_activity_null_author_to_creator_guest(db, event, legacy):
    migrate_identity(db.session)
    assert legacy["activity"].created_by == _creator_guests(event.id)[0].id


def test_migrate_sets_meal_null_author_to_creator_guest(db, event, legacy):
    migrate_identity(db.session)
    assert legacy["meal"].created_by == _creator_guests(event.id)[0].id


def test_migrate_sets_creator_chat_message_guest_id(db, event, legacy):
    migrate_identity(db.session)
    assert legacy["msg_creator"].guest_id == _creator_guests(event.id)[0].id


def test_migrate_leaves_guest_chat_message_without_id(db, event, legacy):
    migrate_identity(db.session)
    assert legacy["msg_guest"].guest_id is None


def test_migrate_sets_media_null_uploader_to_creator_guest(db, event, legacy):
    migrate_identity(db.session)
    assert legacy["media"].uploaded_by == _creator_guests(event.id)[0].id


def test_migrate_does_not_rewrite_denormalized_names(db, event, legacy):
    migrate_identity(db.session)
    assert legacy["msg_creator"].author_name == "Créateur"


def test_migrate_second_run_reports_all_zero(db, event, legacy):
    migrate_identity(db.session)
    assert set(migrate_identity(db.session).values()) == {0}


def test_migrate_second_run_keeps_single_creator_guest(db, event, legacy):
    migrate_identity(db.session)
    migrate_identity(db.session)
    assert len(_creator_guests(event.id)) == 1


def test_check_identity_clean_database_empty(db, event, creator_guest):
    assert check_identity(db.session) == []


def test_check_identity_reports_duplicate_creator_guests(db, event, creator, creator_guest):
    db.session.add(
        Guest(code="dup0000000000002", display_name="D", event_id=event.id, creator_id=creator.id)
    )
    db.session.commit()
    assert f"duplicate_creator_guest:{event.id}" in check_identity(db.session)


def test_check_identity_reports_null_activity_author(db, event, creator_guest, legacy):
    assert f"activity_null_author:{legacy['activity'].id}" in check_identity(db.session)


def test_check_identity_clean_after_migration(db, event, legacy):
    migrate_identity(db.session)
    assert check_identity(db.session) == []


def test_backup_sqlite_database_copies_file(tmp_path):
    source = tmp_path / "src.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE events (id TEXT)")
    conn.commit()
    conn.close()
    path = backup_sqlite_database(f"sqlite:///{source}", str(tmp_path))
    tables = sqlite3.connect(path).execute("SELECT name FROM sqlite_master").fetchall()
    assert ("events",) in tables


def test_backup_sqlite_database_memory_returns_none(tmp_path):
    assert backup_sqlite_database("sqlite:///:memory:", str(tmp_path)) is None


@pytest.fixture
def file_app(monkeypatch, tmp_path):
    """Application sur base fichier, instance dans tmp_path."""

    def build(skip_migration: bool = False):
        monkeypatch.setattr("app.load_dotenv", lambda *args, **kwargs: True)
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
        monkeypatch.setenv("INSTANCE_PATH", str(tmp_path / "inst"))
        monkeypatch.setenv("ENABLED_MODULES", "planning")
        if skip_migration:
            monkeypatch.setenv("SKIP_STARTUP_MIGRATION", "1")
        else:
            monkeypatch.delenv("SKIP_STARTUP_MIGRATION", raising=False)
        return create_app()

    return build


def _seed_event(db, *, with_creator_guest: bool) -> Event:
    creator = Creator(email="f@t.com", email_verified=True, display_name="F")
    db.session.add(creator)
    db.session.flush()
    event = Event(
        code="fileev",
        title="F",
        start_date=DAY,
        end_date=DAY,
        creator_id=creator.id,
        verified_at=datetime.utcnow(),
    )
    db.session.add(event)
    db.session.flush()
    if with_creator_guest:
        db.session.add(
            Guest(
                code="tok0000000000001", display_name="F", event_id=event.id, creator_id=creator.id
            )
        )
    db.session.commit()
    return event


def _backups(tmp_path):
    folder = tmp_path / "inst" / "backups"
    return sorted(folder.glob("pre-identity-*.db")) if folder.exists() else []


def test_startup_runs_identity_migration(file_app, tmp_path):
    from app.extensions import db

    first = file_app()
    with first.app_context():
        event = _seed_event(db, with_creator_guest=False)
        event_id = event.id
    second = file_app()
    with second.app_context():
        assert len(_creator_guests(event_id)) == 1


def test_run_identity_migration_noop_creates_no_backup(file_app, tmp_path):
    from app.extensions import db

    app = file_app()
    with app.app_context():
        _seed_event(db, with_creator_guest=True)
        run_identity_migration(app)
    assert _backups(tmp_path) == []


def test_run_identity_migration_unfixable_anomaly_creates_no_backup(file_app, tmp_path):
    from app.extensions import db

    app = file_app()
    with app.app_context():
        event = _seed_event(db, with_creator_guest=True)
        db.session.add(
            Guest(
                code="tok0000000000002",
                display_name="D",
                event_id=event.id,
                creator_id=event.creator_id,
            )
        )
        db.session.commit()
        run_identity_migration(app)
        run_identity_migration(app)
    assert _backups(tmp_path) == []


def _touch_backups(tmp_path, count, age_days=0):
    folder = tmp_path / "inst" / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    import time

    paths = []
    for index in range(count):
        path = folder / f"pre-identity-2026010{index}T000000Z.db"
        path.write_bytes(b"x")
        stamp = time.time() - age_days * 86400 - (count - index) * 10
        os.utime(path, (stamp, stamp))
        paths.append(path)
    return paths


def test_prune_backups_keeps_three_latest(tmp_path):
    paths = _touch_backups(tmp_path, 5)
    prune_backups(str(tmp_path / "inst"))
    assert [p.exists() for p in paths] == [False, False, True, True, True]


def test_prune_backups_removes_files_older_than_30_days(tmp_path):
    (path,) = _touch_backups(tmp_path, 1, age_days=31)
    prune_backups(str(tmp_path / "inst"))
    assert not path.exists()


def test_plan_identity_migration_writes_nothing(db, event, legacy):
    before = Guest.query.count()
    plan_identity_migration(db.session)
    assert (Guest.query.count(), len(db.session.new)) == (before, 0)


def test_check_identity_ignores_unverified_event_null_author(db, unverified_event):
    activity = Activity(title="U", date=DAY, event_id=unverified_event.id)
    db.session.add(activity)
    db.session.commit()
    assert f"activity_null_author:{activity.id}" not in check_identity(db.session)


def test_migrate_truncates_long_creator_name_to_50_chars(db, event, creator):
    creator.display_name = "x" * 80
    db.session.commit()
    migrate_identity(db.session)
    assert len(_creator_guests(event.id)[0].display_name) == 50


def test_backup_creation_prunes_backups_older_than_30_days(file_app, tmp_path):
    from app.extensions import db

    app = file_app()
    with app.app_context():
        _seed_event(db, with_creator_guest=False)
        (old,) = _touch_backups(tmp_path, 1, age_days=31)
        run_identity_migration(app)
    assert (old.exists(), len(_backups(tmp_path))) == (False, 1)


def test_plan_counts_equal_migrate_counts_on_legacy_base(db, event, creator, guest, legacy):
    _list_with_item(db, event, assigned_to=creator.display_name)  # seul le futur participant
    _list_with_item(db, event, assigned_to="Test Guest")
    _list_with_item(db, event, assigned_to="Créateur", assigned_to_id=creator.id)
    planned = plan_identity_migration(db.session)
    assert planned == migrate_identity(db.session)


def test_backup_dir_and_file_are_private_even_with_open_umask(tmp_path):
    import os
    import stat

    source = tmp_path / "src.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE events (id TEXT)")
    conn.commit()
    conn.close()
    previous = os.umask(0)
    try:
        path = backup_sqlite_database(f"sqlite:///{source}", str(tmp_path / "inst"))
    finally:
        os.umask(previous)
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("value", "runs"), [("1", False), ("0", True), ("false", True), ("", True)]
)
def test_only_skip_startup_migration_1_disables_the_startup_migration(
    monkeypatch, file_app, value, runs
):
    calls = []
    monkeypatch.setattr("app.migrations.run_identity_migration", lambda app: calls.append(1))
    file_app()  # pose l'environnement de base
    monkeypatch.setenv("SKIP_STARTUP_MIGRATION", value)
    calls.clear()
    create_app()
    assert bool(calls) is runs
