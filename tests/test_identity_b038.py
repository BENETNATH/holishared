"""Tests B038-L1 — identité : email conservé par défaut + lien magique de récupération.

TDD : écrits AVANT le code (spec ``specs/b038-identity-recovery-spec.md`` §3, §9.1).
Les imports des symboles nouveaux (``issue_recovery_token``, ``valid_recovery_token``,
``migrate_identity_recovery``, ``run_identity_recovery_migration``) sont faits DANS les
tests pour que la collecte reste possible à l'état rouge.
"""

import hashlib
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import urlparse

import pytest

from app.models import ActivityLog, Creator, Guest

RECOVER = "/e/recover"


# ---------------------------------------------------------------------------
# Helpers de session (la fixture ``queue`` est partagée depuis conftest.py)
# ---------------------------------------------------------------------------


def _login_creator(client, creator):
    with client.session_transaction() as s:
        s["_user_id"] = creator.id
        s["_fresh"] = True


def _login_guest(client, event, guest):
    with client.session_transaction() as s:
        s[f"guest_{event.code}"] = guest.id


def _commit(db):
    db.session.commit()


def _hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def _persisted(db):
    """Drop everything that is not committed (R2).

    The test client reuses the fixture's outer app context, so an uncommitted token
    would stay visible to the test. After this rollback only what a fresh session
    would read remains.
    """
    db.session.rollback()


def _raw(link):
    """Raw token carried by an e-mailed link (last path segment)."""
    return urlparse(link).path.rstrip("/").rsplit("/", 1)[-1]


def _path(link):
    return urlparse(link).path


def _flashes(client):
    with client.session_transaction() as s:
        return [msg for _cat, msg in s.get("_flashes", [])]


def _fresh_client(app):
    return app.test_client()


@pytest.fixture
def other_creator(db):
    c = Creator(
        email="other@test.com",
        email_verified=True,
        display_name="Other Creator",
        personal_code="other9",
    )
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture
def legacy_app(monkeypatch, tmp_path):
    """Base SQLite fichier au schéma d'AVANT B038 : pas de colonnes de récupération."""
    monkeypatch.setattr("app.load_dotenv", lambda *args, **kwargs: True)
    dbfile = tmp_path / "b038.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{dbfile}")
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path / "inst"))
    monkeypatch.setenv("SKIP_STARTUP_MIGRATION", "1")
    from app import create_app

    application = create_app()
    con = sqlite3.connect(dbfile)
    con.execute("DROP TABLE guests")
    con.execute(
        "CREATE TABLE guests (id VARCHAR(32) NOT NULL, code VARCHAR(16) NOT NULL, "
        "display_name VARCHAR(50) NOT NULL, email VARCHAR(255), is_active BOOLEAN NOT NULL, "
        "joined_at DATETIME, event_id VARCHAR(32) NOT NULL REFERENCES events(id), "
        "creator_id VARCHAR(32) REFERENCES creators(id), PRIMARY KEY (id), "
        "CONSTRAINT uq_guest_event_code UNIQUE (event_id, code))"
    )
    con.execute("DROP TABLE creators")
    con.execute(
        "CREATE TABLE creators (id VARCHAR(32) NOT NULL, email VARCHAR(255), "
        "email_verified BOOLEAN NOT NULL, verification_token VARCHAR(64), "
        "verification_sent_at DATETIME, display_name VARCHAR(100), personal_code VARCHAR(8), "
        "tier VARCHAR(20) NOT NULL, created_at DATETIME, PRIMARY KEY (id))"
    )
    con.commit()
    con.close()
    return application


# ---------------------------------------------------------------------------
# Migration (colonnes de récupération + index unique partiel)
# ---------------------------------------------------------------------------


def _legacy_db_path(legacy_app):
    return legacy_app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")


class TestMigration:
    def test_migration_adds_recovery_columns(self, legacy_app):
        from app.migrations import run_identity_recovery_migration

        with legacy_app.app_context():
            run_identity_recovery_migration(legacy_app)
        con = sqlite3.connect(_legacy_db_path(legacy_app))
        guest_cols = {row[1] for row in con.execute("PRAGMA table_info(guests)")}
        creator_cols = {row[1] for row in con.execute("PRAGMA table_info(creators)")}
        con.close()
        assert {"recovery_token", "recovery_token_expires", "merged_into_id"} <= guest_cols
        assert {"recovery_token", "recovery_token_expires"} <= creator_cols

    def test_migration_is_idempotent(self, legacy_app):
        from app.migrations import run_identity_recovery_migration

        with legacy_app.app_context():
            run_identity_recovery_migration(legacy_app)
            run_identity_recovery_migration(legacy_app)
        con = sqlite3.connect(_legacy_db_path(legacy_app))
        guest_cols = [row[1] for row in con.execute("PRAGMA table_info(guests)")]
        con.close()
        assert guest_cols.count("recovery_token") == 1

    def test_unique_email_migration_creates_partial_index_once(self, legacy_app):
        """R6e : index unique partiel créé par une migration idempotente."""
        from app.extensions import db
        from app.migrations import migrate_guest_email_unique, run_identity_recovery_migration

        with legacy_app.app_context():
            run_identity_recovery_migration(legacy_app)
            assert migrate_guest_email_unique(db.engine) == 1
            assert migrate_guest_email_unique(db.engine) == 0
        con = sqlite3.connect(_legacy_db_path(legacy_app))
        rows = con.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_guest_event_email_active'"
        ).fetchall()
        con.close()
        assert len(rows) == 1
        ddl = rows[0][0].upper()
        assert "UNIQUE" in ddl
        assert "WHERE" in ddl

    def test_unique_email_migration_survives_existing_duplicates(self, legacy_app):
        """Doublons préexistants : pas de crash au démarrage, index non créé (résolution manuelle)."""
        from app.extensions import db
        from app.migrations import migrate_guest_email_unique, run_identity_recovery_migration

        with legacy_app.app_context():
            run_identity_recovery_migration(legacy_app)
            con = sqlite3.connect(_legacy_db_path(legacy_app))
            for gid, code in (("g1", "aaaa1"), ("g2", "bbbb2")):
                con.execute(
                    "INSERT INTO guests (id, code, display_name, email, is_active, event_id) "
                    "VALUES (?, ?, 'X', 'dup@test.com', 1, 'e1')",
                    (gid, code),
                )
            con.commit()
            con.close()
            assert migrate_guest_email_unique(db.engine) == 0

    def test_unique_email_migration_is_a_startup_step_after_recovery_columns(self):
        from app.startup import default_steps

        names = [name for name, _step in default_steps()]
        assert "guest_email_unique" in names
        assert names.index("guest_email_unique") > names.index("identity_recovery")


# ---------------------------------------------------------------------------
# Helpers access (issue / valid recovery token) — jeton haché (R1)
# ---------------------------------------------------------------------------


class TestAccessToken:
    def test_issue_recovery_token_returns_raw_and_stores_only_its_sha256(self, db, creator):
        from app.access import issue_recovery_token

        raw = issue_recovery_token(creator)
        _commit(db)
        assert isinstance(raw, str)
        assert len(raw) >= 32
        assert creator.recovery_token == _hash(raw)
        assert len(creator.recovery_token) == 64
        assert creator.recovery_token != raw
        assert Creator.query.filter_by(recovery_token=raw).first() is None
        assert (
            datetime.utcnow()
            < creator.recovery_token_expires
            < datetime.utcnow() + timedelta(hours=25)
        )

    def test_issue_recovery_token_overwrites_previous_token(self, db, creator):
        from app.access import issue_recovery_token

        first = issue_recovery_token(creator)
        second = issue_recovery_token(creator)
        _commit(db)
        assert first != second
        assert creator.recovery_token == _hash(second)

    def test_valid_recovery_token_true_when_fresh(self, db, creator):
        from app.access import issue_recovery_token, valid_recovery_token

        issue_recovery_token(creator)
        _commit(db)
        assert valid_recovery_token(creator) is True

    def test_valid_recovery_token_false_when_expired(self, db, creator):
        from app.access import valid_recovery_token

        creator.recovery_token = "tok"
        creator.recovery_token_expires = datetime.utcnow() - timedelta(hours=1)
        _commit(db)
        assert valid_recovery_token(creator) is False

    def test_valid_recovery_token_false_when_absent(self, db, creator):
        from app.access import valid_recovery_token

        creator.recovery_token = None
        creator.recovery_token_expires = None
        _commit(db)
        assert valid_recovery_token(creator) is False


# ---------------------------------------------------------------------------
# Créateur — demande de récupération (magic link, F16)
# ---------------------------------------------------------------------------


class TestCreatorRecoverRequest:
    def test_recover_rate_limited_after_10_attempts(self, client, db, creator, queue):
        """10 per hour / IP : la 11e demande est refusée (429)."""
        creator.personal_code = "keeper9"
        _commit(db)
        codes = [
            client.post(RECOVER, data={"email": "keeper@test.com"}).status_code for _ in range(11)
        ]
        assert codes == [302] * 10 + [429]

    def test_unknown_email_creates_no_token(self, client, db, creator, queue):
        client.post(RECOVER, data={"email": "nobody@test.com"}, follow_redirects=True)
        assert Creator.query.filter_by(email="nobody@test.com").first() is None
        assert queue.creator_recovery() == []

    def test_known_email_stores_hash_and_enqueues_raw_link(self, client, db, creator, queue):
        creator.personal_code = "keeper9"
        _commit(db)
        client.post(RECOVER, data={"email": "creator@test.com"}, follow_redirects=True)
        _persisted(db)  # R2 : seul ce qui est committé survit
        assert len(queue.creator_recovery()) == 1
        email, link = queue.creator_recovery()[0]
        raw = _raw(link)
        assert email == "creator@test.com"
        assert "/e/recover/link/" in link
        assert creator.recovery_token == _hash(raw)
        assert creator.recovery_token != raw
        assert Creator.query.filter_by(recovery_token=raw).first() is None
        assert (
            datetime.utcnow() + timedelta(hours=23)
            < creator.recovery_token_expires
            < datetime.utcnow() + timedelta(hours=25)
        )

    def test_recovery_jobs_do_not_keep_the_raw_token_in_redis(
        self, client, db, event, creator, guest, queue
    ):
        """The job payload carries the raw token: failed jobs expire fast, results are dropped."""
        creator.personal_code = "keeper9"
        guest.email = "known@test.com"
        _commit(db)
        client.post(RECOVER, data={"email": "creator@test.com"})
        client.post(f"/e/{event.code}/recover", data={"email": "known@test.com"})
        assert len(queue.jobs) == 2
        for _args, kwargs in queue.jobs:
            assert kwargs["failure_ttl"] == 3600
            assert kwargs["result_ttl"] == 0
            assert kwargs["description"] == "recovery-link"  # no token/SMTP password in RQ

    def test_emailed_link_works_from_a_fresh_session(self, client, db, creator, queue):
        """R2 : le token est committé AVANT l'enqueue (le lien marche dans une autre session)."""
        creator.personal_code = "keeper9"
        _commit(db)
        client.post(RECOVER, data={"email": "creator@test.com"})
        _persisted(db)
        link = queue.creator_recovery()[0][1]
        resp = client.get(_path(link))
        assert resp.status_code == 200
        assert 'data-testid="recover-link-page"' in resp.get_data(as_text=True)

    def test_creator_without_personal_code_gets_no_token(self, client, db, creator, queue):
        creator.personal_code = None
        _commit(db)
        client.post(RECOVER, data={"email": "creator@test.com"}, follow_redirects=True)
        _persisted(db)
        assert creator.recovery_token is None
        assert queue.creator_recovery() == []

    def test_known_and_unknown_email_same_response_f16(self, client, db, creator, queue):
        creator.personal_code = "keeper9"
        _commit(db)
        known = client.post(RECOVER, data={"email": "creator@test.com"})
        unknown = client.post(RECOVER, data={"email": "nobody@test.com"})
        assert known.status_code == unknown.status_code
        assert known.headers["Location"] == unknown.headers["Location"]

    def test_dev_show_secrets_without_debug_never_shows_link(self, app, client, db, creator):
        """R6f : DEV_SHOW_SECRETS seul ne suffit pas, il faut aussi app.debug."""
        creator.personal_code = "keeper9"
        _commit(db)
        app.config["SMTP_HOST"] = ""
        app.config["DEV_SHOW_SECRETS"] = True
        app.debug = False
        html = client.post(
            RECOVER, data={"email": "creator@test.com"}, follow_redirects=True
        ).get_data(as_text=True)
        assert "/e/recover/link/" not in html


class TestVerifyOptOut:
    def test_unchecking_the_email_box_also_clears_a_pending_recovery_token(
        self, client, db, creator, unverified_event
    ):
        from app.access import issue_recovery_token

        issue_recovery_token(creator)
        unverified_event.verification_token = "verif-tok"
        _commit(db)
        client.post(
            "/e/verify/verif-tok",
            data={"display_name": "Test Creator", "personal_code": "newcode9"},
        )
        _persisted(db)
        assert creator.email is None
        assert creator.recovery_token is None
        assert creator.recovery_token_expires is None


class TestPublicRecoverPaths:
    """Anonymous paths: never reveal the link (even in debug), silent per-profile cooldown."""

    def test_creator_recover_never_reveals_link_even_in_debug(self, app, client, db, creator):
        creator.personal_code = "keeper9"
        _commit(db)
        app.config["SMTP_HOST"] = ""
        app.config["DEV_SHOW_SECRETS"] = True
        app.debug = True
        html = client.post(
            RECOVER, data={"email": "creator@test.com"}, follow_redirects=True
        ).get_data(as_text=True)
        assert "/e/recover/link/" not in html

    def test_guest_recover_never_reveals_link_even_in_debug(self, app, client, db, event, guest):
        guest.email = "known@test.com"
        _commit(db)
        app.config["SMTP_HOST"] = ""
        app.config["DEV_SHOW_SECRETS"] = True
        app.debug = True
        html = client.post(
            f"/e/{event.code}/recover", data={"email": "known@test.com"}, follow_redirects=True
        ).get_data(as_text=True)
        assert "/guest-recover/" not in html

    def test_creator_recover_cooldown_is_silent(self, app, db, creator, queue):
        creator.personal_code = "keeper9"
        _commit(db)
        first, second = _fresh_client(app), _fresh_client(app)
        r1 = first.post(RECOVER, data={"email": "creator@test.com"})
        token = creator.recovery_token
        r2 = second.post(RECOVER, data={"email": "creator@test.com"})
        _persisted(db)
        assert len(queue.creator_recovery()) == 1
        assert creator.recovery_token == token  # not re-issued
        assert (r1.status_code, r1.headers["Location"]) == (r2.status_code, r2.headers["Location"])
        assert _flashes(first) == _flashes(second)

    def test_guest_recover_cooldown_is_silent(self, app, db, event, guest, queue):
        guest.email = "known@test.com"
        _commit(db)
        first, second = _fresh_client(app), _fresh_client(app)
        r1 = first.post(f"/e/{event.code}/recover", data={"email": "known@test.com"})
        token = guest.recovery_token
        r2 = second.post(f"/e/{event.code}/recover", data={"email": "known@test.com"})
        _persisted(db)
        assert len(queue.guest_recovery()) == 1
        assert guest.recovery_token == token
        assert (r1.status_code, r1.headers["Location"]) == (r2.status_code, r2.headers["Location"])
        assert _flashes(first) == _flashes(second)

    def test_explicit_actions_are_not_blocked_by_the_cooldown(
        self, client, db, event, guest, creator, creator_client, queue
    ):
        """me / members / reinvite are authenticated, explicit requests: always sent."""
        guest.email = "g@test.com"
        _commit(db)
        for _ in range(2):
            creator_client.post(
                f"/e/{event.code}/members", data={"action": "recovery_link", "guest_id": guest.id}
            )
        assert len(queue.guest_recovery()) == 2

    def test_guest_recover_rate_limited_after_10_attempts(self, client, db, event, guest, queue):
        guest.email = "known@test.com"
        _commit(db)
        codes = [
            client.post(f"/e/{event.code}/recover", data={"email": "known@test.com"}).status_code
            for _ in range(11)
        ]
        assert codes == [302] * 10 + [429]


# ---------------------------------------------------------------------------
# Créateur — page de lien + actions keep / recode
# ---------------------------------------------------------------------------


class TestCreatorRecoverLink:
    def _issue(self, db, creator):
        from app.access import issue_recovery_token

        creator.personal_code = "keeper9"
        raw = issue_recovery_token(creator)
        _commit(db)
        return raw

    def test_invalid_token_redirects_neutrally(self, client, db, creator):
        resp = client.get("/e/recover/link/tok-invalide", follow_redirects=True)
        assert resp.status_code == 200
        assert "Lien invalide ou expiré." in resp.get_data(as_text=True)
        with client.session_transaction() as s:
            assert "_user_id" not in s

    def test_stored_hash_is_not_a_valid_link_token(self, client, db, creator):
        """R1 : présenter le hash stocké (fuite de base) ne donne aucun accès."""
        self._issue(db, creator)
        resp = client.post(f"/e/recover/link/{creator.recovery_token}", data={"action": "keep"})
        assert resp.status_code == 302
        with client.session_transaction() as s:
            assert "_user_id" not in s

    def test_keep_code_starts_session_and_clears_token(self, client, db, creator):
        token = self._issue(db, creator)
        client.get(f"/e/recover/link/{token}")
        client.post(f"/e/recover/link/{token}", data={"action": "keep"})
        _persisted(db)
        assert creator.recovery_token is None
        assert creator.recovery_token_expires is None
        with client.session_transaction() as s:
            assert s.get("_user_id") == creator.id

    def test_recode_rejects_short_code(self, client, db, creator):
        token = self._issue(db, creator)
        client.post(f"/e/recover/link/{token}", data={"action": "recode", "personal_code": "ab"})
        _persisted(db)
        assert creator.personal_code == "keeper9"  # unchanged
        assert creator.recovery_token == _hash(token)  # still valid for a retry

    def test_recode_rejects_duplicate_code(self, client, db, creator, other_creator):
        token = self._issue(db, creator)
        client.post(
            f"/e/recover/link/{token}",
            data={"action": "recode", "personal_code": other_creator.personal_code},
        )
        _persisted(db)
        assert creator.personal_code == "keeper9"
        assert creator.recovery_token == _hash(token)

    def test_recode_accepts_valid_code(self, client, db, creator):
        token = self._issue(db, creator)
        client.post(
            f"/e/recover/link/{token}", data={"action": "recode", "personal_code": "newcode9"}
        )
        _persisted(db)
        assert creator.personal_code == "newcode9"
        assert creator.recovery_token is None

    def test_link_is_single_use_recode_replay_keeps_code(self, app, client, db, creator):
        token = self._issue(db, creator)
        client.post(
            f"/e/recover/link/{token}", data={"action": "recode", "personal_code": "newcode9"}
        )
        replay = _fresh_client(app)
        resp = replay.post(
            f"/e/recover/link/{token}", data={"action": "recode", "personal_code": "hijack99"}
        )
        _persisted(db)
        assert creator.personal_code == "newcode9"
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/e/recover")
        with replay.session_transaction() as s:
            assert "_user_id" not in s

    def test_recode_race_on_unique_code_is_a_field_error_not_a_500(
        self, client, db, creator, monkeypatch
    ):
        from sqlalchemy.exc import IntegrityError

        token = self._issue(db, creator)

        def boom():
            raise IntegrityError("UPDATE creators", {}, Exception("unique"))

        with monkeypatch.context() as m:
            m.setattr(db.session, "commit", boom)
            resp = client.post(
                f"/e/recover/link/{token}",
                data={"action": "recode", "personal_code": "newcode9"},
            )
        assert resp.status_code == 200
        assert "Ce code est déjà utilisé." in resp.get_data(as_text=True)
        _persisted(db)
        assert creator.personal_code == "keeper9"
        assert creator.recovery_token == _hash(token)

    def test_expired_token_is_refused(self, app, client, db, creator):
        token = self._issue(db, creator)
        creator.recovery_token_expires = datetime.utcnow() - timedelta(minutes=1)
        _commit(db)
        resp = client.post(
            f"/e/recover/link/{token}", data={"action": "recode", "personal_code": "hijack99"}
        )
        _persisted(db)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/e/recover")
        assert creator.personal_code == "keeper9"
        with client.session_transaction() as s:
            assert "_user_id" not in s
        page = _fresh_client(app).get(f"/e/recover/link/{token}", follow_redirects=True)
        assert "Lien invalide ou expiré." in page.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Invité — demande de récupération (magic link, F16)
# ---------------------------------------------------------------------------


class TestGuestRecoverRequest:
    def test_unknown_email_creates_no_token(self, client, db, event, guest, queue):
        guest.email = "known@test.com"
        _commit(db)
        client.post(
            f"/e/{event.code}/recover", data={"email": "nobody@test.com"}, follow_redirects=True
        )
        _persisted(db)
        assert guest.recovery_token is None
        assert queue.guest_recovery() == []

    def test_known_email_stores_hash_and_enqueues_raw_link(self, client, db, event, guest, queue):
        guest.email = "known@test.com"
        _commit(db)
        client.post(
            f"/e/{event.code}/recover", data={"email": "known@test.com"}, follow_redirects=True
        )
        _persisted(db)  # R2
        assert len(queue.guest_recovery()) == 1
        email, _title, link = queue.guest_recovery()[0]
        raw = _raw(link)
        assert email == "known@test.com"
        assert f"/e/{event.code}/guest-recover/" in link
        assert guest.recovery_token == _hash(raw)
        assert Guest.query.filter_by(recovery_token=raw).first() is None

    def test_emailed_link_works_from_a_fresh_session(self, client, db, event, guest, queue):
        guest.email = "known@test.com"
        _commit(db)
        client.post(f"/e/{event.code}/recover", data={"email": "known@test.com"})
        _persisted(db)
        link = queue.guest_recovery()[0][2]
        resp = client.get(_path(link))
        assert resp.status_code == 200
        assert 'data-testid="guest-recover-link-page"' in resp.get_data(as_text=True)

    def test_creator_participant_is_excluded(
        self, client, db, event, creator, creator_guest, queue
    ):
        # The creator's participant identity must never receive a guest recovery link.
        creator_guest.email = "creator@test.com"
        creator.email = "creator@test.com"
        _commit(db)
        client.post(
            f"/e/{event.code}/recover", data={"email": "creator@test.com"}, follow_redirects=True
        )
        _persisted(db)
        assert creator_guest.recovery_token is None
        assert queue.guest_recovery() == []

    def test_retired_profile_gets_no_token_and_no_link(self, app, db, event, guest, queue):
        """R4 : un profil retiré ne reçoit rien, et la réponse reste indiscernable (F16)."""
        guest.email = "retired@test.com"
        guest.is_active = False
        _commit(db)
        retired, unknown = _fresh_client(app), _fresh_client(app)
        r1 = retired.post(f"/e/{event.code}/recover", data={"email": "retired@test.com"})
        r2 = unknown.post(f"/e/{event.code}/recover", data={"email": "ghost@test.com"})
        _persisted(db)
        assert queue.guest_recovery() == []
        assert guest.recovery_token is None
        assert guest.is_active is False
        assert (r1.status_code, r1.headers["Location"]) == (r2.status_code, r2.headers["Location"])
        assert _flashes(retired) == _flashes(unknown)

    def test_dev_show_secrets_without_debug_never_shows_link(self, app, client, db, event, guest):
        """R6f côté invité."""
        guest.email = "known@test.com"
        _commit(db)
        app.config["SMTP_HOST"] = ""
        app.config["DEV_SHOW_SECRETS"] = True
        html = client.post(
            f"/e/{event.code}/recover", data={"email": "known@test.com"}, follow_redirects=True
        ).get_data(as_text=True)
        assert "/guest-recover/" not in html


# ---------------------------------------------------------------------------
# Invité — page de lien + actions (keep / recode) — pas de réactivation (R4)
# ---------------------------------------------------------------------------


class TestGuestRecoverLink:
    def _setup(self, db, guest):
        from app.access import issue_recovery_token

        raw = issue_recovery_token(guest)
        _commit(db)
        return raw

    def test_wrong_event_token_rejected(self, client, db, event, other_event, guest):
        token = self._setup(db, guest)
        resp = client.get(f"/e/{other_event.code}/guest-recover/{token}", follow_redirects=True)
        assert resp.status_code == 200
        assert "Lien invalide ou expiré." in resp.get_data(as_text=True)
        _persisted(db)
        assert guest.recovery_token == _hash(token)  # not consumed

    def test_keep_clears_token_and_starts_session(self, client, db, event, guest):
        token = self._setup(db, guest)
        client.post(f"/e/{event.code}/guest-recover/{token}", data={"action": "keep"})
        _persisted(db)
        assert guest.recovery_token is None
        with client.session_transaction() as s:
            assert s.get(f"guest_{event.code}") == guest.id

    def test_retired_profile_link_cannot_reactivate(self, client, db, event, guest):
        """R4 : un lien (même valide) ne réactive jamais un profil retiré."""
        guest.is_active = False
        token = self._setup(db, guest)
        original_code = guest.code
        page = client.get(f"/e/{event.code}/guest-recover/{token}", follow_redirects=True)
        assert "Lien invalide ou expiré." in page.get_data(as_text=True)
        client.post(f"/e/{event.code}/guest-recover/{token}", data={"action": "keep"})
        client.post(
            f"/e/{event.code}/guest-recover/{token}",
            data={"action": "recode", "code": "fresh99"},
        )
        _persisted(db)
        assert guest.is_active is False
        assert guest.code == original_code
        with client.session_transaction() as s:
            assert f"guest_{event.code}" not in s

    def test_recode_rejects_code_taken_in_event(self, client, db, event, guest, other_guest_c):
        token = self._setup(db, guest)
        original = guest.code
        client.post(
            f"/e/{event.code}/guest-recover/{token}",
            data={"action": "recode", "code": other_guest_c.code},
        )
        _persisted(db)
        assert guest.code == original  # unchanged: code already taken in the event
        assert guest.recovery_token == _hash(token)  # token still valid for a retry

    def test_recode_rejects_creator_code(self, client, db, event, guest, creator):
        creator.personal_code = "creator9"
        _commit(db)
        token = self._setup(db, guest)
        original = guest.code
        client.post(
            f"/e/{event.code}/guest-recover/{token}", data={"action": "recode", "code": "creator9"}
        )
        _persisted(db)
        assert guest.code == original

    def test_recode_accepts_free_code_and_consumes_token(self, client, db, event, guest):
        token = self._setup(db, guest)
        client.post(
            f"/e/{event.code}/guest-recover/{token}", data={"action": "recode", "code": "fresh99"}
        )
        _persisted(db)
        assert guest.code == "fresh99"
        assert guest.recovery_token is None

    def test_link_is_single_use_recode_replay_keeps_code(self, app, client, db, event, guest):
        token = self._setup(db, guest)
        client.post(
            f"/e/{event.code}/guest-recover/{token}", data={"action": "recode", "code": "fresh99"}
        )
        replay = _fresh_client(app)
        resp = replay.post(
            f"/e/{event.code}/guest-recover/{token}", data={"action": "recode", "code": "hijack9"}
        )
        _persisted(db)
        assert guest.code == "fresh99"
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(f"/e/{event.code}/mycode")
        with replay.session_transaction() as s:
            assert f"guest_{event.code}" not in s

    def test_recode_race_on_unique_code_is_a_field_error_not_a_500(
        self, client, db, event, guest, monkeypatch
    ):
        from sqlalchemy.exc import IntegrityError

        token = self._setup(db, guest)
        original = guest.code

        def boom():
            raise IntegrityError("UPDATE guests", {}, Exception("unique"))

        with monkeypatch.context() as m:
            m.setattr(db.session, "commit", boom)
            resp = client.post(
                f"/e/{event.code}/guest-recover/{token}",
                data={"action": "recode", "code": "fresh99"},
            )
        assert resp.status_code == 200
        assert "Code déjà utilisé." in resp.get_data(as_text=True)
        _persisted(db)
        assert guest.code == original
        assert guest.recovery_token == _hash(token)

    def test_expired_token_is_refused(self, client, db, event, guest):
        token = self._setup(db, guest)
        guest.recovery_token_expires = datetime.utcnow() - timedelta(minutes=1)
        _commit(db)
        original = guest.code
        resp = client.post(
            f"/e/{event.code}/guest-recover/{token}", data={"action": "recode", "code": "hijack9"}
        )
        _persisted(db)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(f"/e/{event.code}/mycode")
        assert guest.code == original
        with client.session_transaction() as s:
            assert f"guest_{event.code}" not in s


class TestRetiredProfileStaysRetired:
    def test_no_self_service_route_reactivates_a_retired_profile(
        self, app, db, event, guest, queue
    ):
        """R4 : /recover, join avec son e-mail, saisie de son code — rien ne le réactive."""
        guest.email = "retired@test.com"
        guest.is_active = False
        _commit(db)
        code = guest.code
        c = _fresh_client(app)
        c.post(f"/e/{event.code}/recover", data={"email": "retired@test.com"})
        c.post(
            f"/e/{event.code}/join",
            data={
                "display_name": "Retour",
                "code": "retour9",
                "email": "retired@test.com",
                "num_adults": "1",
                "num_children": "0",
            },
        )
        c.post(f"/e/{event.code}/mycode", data={"guest_code": code})
        _persisted(db)
        assert guest.is_active is False
        assert queue.guest_recovery() == []
        with c.session_transaction() as s:
            assert f"guest_{event.code}" not in s


# ---------------------------------------------------------------------------
# Mon profil — section Accès & récupération
# ---------------------------------------------------------------------------


class TestMeAccessSection:
    def test_me_shows_access_section_for_guest(self, client, db, event, guest):
        guest.email = "g@test.com"
        _commit(db)
        _login_guest(client, event, guest)
        html = client.get(f"/e/{event.code}/me").get_data(as_text=True)
        assert 'data-testid="access-card"' in html
        assert "g***@test.com" in html  # masked

    def test_me_recovery_link_sends_hashed_persisted_token(self, client, db, event, guest, queue):
        guest.email = "g@test.com"
        _commit(db)
        _login_guest(client, event, guest)
        client.post(f"/e/{event.code}/me", data={"action": "recovery_link"})
        _persisted(db)  # R2
        assert len(queue.guest_recovery()) == 1
        email, _title, link = queue.guest_recovery()[0]
        assert email == "g@test.com"
        assert guest.recovery_token == _hash(_raw(link))

    def test_me_recovery_link_without_smtp_sends_and_claims_nothing(
        self, app, client, db, event, guest
    ):
        guest.email = "g@test.com"
        _commit(db)
        app.config["SMTP_HOST"] = ""
        _login_guest(client, event, guest)
        resp = client.post(f"/e/{event.code}/me", data={"action": "recovery_link"})
        _persisted(db)
        assert resp.status_code == 302
        assert _flashes(client) == ["L'envoi d'emails n'est pas configuré sur ce serveur."]
        assert guest.recovery_token is None
        assert ActivityLog.query.filter_by(action="participant.recovery_sent").count() == 0

    def test_me_recovery_link_journal_survives_the_request(self, client, db, event, guest, queue):
        guest.email = "g@test.com"
        _commit(db)
        _login_guest(client, event, guest)
        client.post(f"/e/{event.code}/me", data={"action": "recovery_link"})
        _persisted(db)
        assert ActivityLog.query.filter_by(action="participant.recovery_sent").count() == 1

    def test_me_creator_recovery_link_sends_hashed_persisted_token(
        self, client, db, event, creator, creator_client, queue
    ):
        creator.email = "creator@test.com"
        _commit(db)
        creator_client.post(f"/e/{event.code}/me", data={"action": "recovery_link"})
        _persisted(db)  # R2
        assert len(queue.creator_recovery()) == 1
        email, link = queue.creator_recovery()[0]
        assert email == "creator@test.com"
        assert creator.recovery_token == _hash(_raw(link))

    def test_me_recovery_link_rate_limited_10_per_hour(self, client, db, event, guest, queue):
        guest.email = "g@test.com"
        _commit(db)
        _login_guest(client, event, guest)
        codes = [
            client.post(f"/e/{event.code}/me", data={"action": "recovery_link"}).status_code
            for _ in range(11)
        ]
        assert codes == [302] * 10 + [429]

    def test_me_rate_limit_only_counts_recovery_link_action(self, client, db, event, guest):
        _login_guest(client, event, guest)
        codes = [
            client.post(
                f"/e/{event.code}/me", data={"display_name": guest.display_name}
            ).status_code
            for _ in range(12)
        ]
        assert codes == [302] * 12

    def test_me_erase_email_removes_it_and_clears_token(self, client, db, event, guest):
        from app.access import issue_recovery_token

        guest.email = "g@test.com"
        issue_recovery_token(guest)
        _commit(db)
        _login_guest(client, event, guest)
        client.post(f"/e/{event.code}/me", data={"action": "erase_email"})
        _persisted(db)
        assert guest.email is None
        assert guest.recovery_token is None
        assert guest.recovery_token_expires is None

    def test_me_creator_erases_creator_email_and_clears_token(
        self, client, db, event, creator, creator_client
    ):
        from app.access import issue_recovery_token

        creator.email = "creator@test.com"
        issue_recovery_token(creator)
        _commit(db)
        creator_client.post(f"/e/{event.code}/me", data={"action": "erase_email"})
        _persisted(db)
        assert creator.email is None
        assert creator.recovery_token is None
        assert creator.recovery_token_expires is None


# ---------------------------------------------------------------------------
# Participants — email masqué + corriger + lien de récupération
# ---------------------------------------------------------------------------


class TestMembersEmailRecovery:
    def test_members_shows_masked_email(self, client, db, event, guest, creator, creator_client):
        guest.email = "g@test.com"
        _commit(db)
        _login_creator(creator_client, creator)
        html = creator_client.get(f"/e/{event.code}/members").get_data(as_text=True)
        # The list row shows the masked address only.
        assert 'data-testid="participant-email">g***@test.com<' in html
        # The creator may edit it in the dedicated fix form (creator-gated, like code reveal).
        assert 'data-testid="fix-email-form"' in html
        assert "fix-email-" in html

    def test_members_fix_email_by_creator(self, client, db, event, guest, creator, creator_client):
        guest.email = "g@test.com"
        _commit(db)
        _login_creator(creator_client, creator)
        creator_client.post(
            f"/e/{event.code}/members",
            data={"action": "fix_email", "guest_id": guest.id, "email": "fixed@test.com"},
        )
        assert guest.email == "fixed@test.com"

    def test_members_fix_email_journal_survives_the_request(
        self, client, db, event, guest, creator, creator_client
    ):
        guest.email = "g@test.com"
        _commit(db)
        creator_client.post(
            f"/e/{event.code}/members",
            data={"action": "fix_email", "guest_id": guest.id, "email": "fixed@test.com"},
        )
        _persisted(db)
        assert ActivityLog.query.filter_by(action="participant.email_fixed").count() == 1

    def test_members_recovery_link_journal_survives_the_request(
        self, client, db, event, guest, creator, creator_client, queue
    ):
        guest.email = "g@test.com"
        _commit(db)
        creator_client.post(
            f"/e/{event.code}/members", data={"action": "recovery_link", "guest_id": guest.id}
        )
        _persisted(db)
        assert ActivityLog.query.filter_by(action="participant.recovery_sent").count() == 1

    def test_members_fix_email_clears_pending_recovery_token(
        self, client, db, event, guest, creator, creator_client
    ):
        """A link issued for the old address must not survive an address change."""
        from app.access import issue_recovery_token

        guest.email = "old@test.com"
        issue_recovery_token(guest)
        _commit(db)
        creator_client.post(
            f"/e/{event.code}/members",
            data={"action": "fix_email", "guest_id": guest.id, "email": "new@test.com"},
        )
        _persisted(db)
        assert guest.email == "new@test.com"
        assert guest.recovery_token is None
        assert guest.recovery_token_expires is None

    def test_members_fix_email_guest_forbidden(
        self, client, db, event, guest, other_guest_c, guest_client
    ):
        guest.email = "g@test.com"
        _commit(db)
        with client.session_transaction() as s:
            s[f"guest_{event.code}"] = other_guest_c.id
        resp = client.post(
            f"/e/{event.code}/members",
            data={"action": "fix_email", "guest_id": guest.id, "email": "x@test.com"},
        )
        assert resp.status_code == 403

    def test_members_recovery_link_by_creator_hashed_persisted_token(
        self, client, db, event, guest, creator, creator_client, queue
    ):
        guest.email = "g@test.com"
        _commit(db)
        _login_creator(creator_client, creator)
        creator_client.post(
            f"/e/{event.code}/members",
            data={"action": "recovery_link", "guest_id": guest.id},
        )
        _persisted(db)  # R2
        assert len(queue.guest_recovery()) == 1
        email, _title, link = queue.guest_recovery()[0]
        assert email == "g@test.com"
        assert guest.recovery_token == _hash(_raw(link))

    def test_members_recovery_link_no_email_no_send(
        self, client, db, event, guest, creator, creator_client, queue
    ):
        guest.email = None
        _commit(db)
        _login_creator(creator_client, creator)
        creator_client.post(
            f"/e/{event.code}/members",
            data={"action": "recovery_link", "guest_id": guest.id},
        )
        assert queue.guest_recovery() == []

    def test_members_recovery_link_rate_limited_20_per_hour(
        self, client, db, event, guest, creator, creator_client, queue
    ):
        guest.email = "g@test.com"
        _commit(db)
        codes = [
            creator_client.post(
                f"/e/{event.code}/members", data={"action": "recovery_link", "guest_id": guest.id}
            ).status_code
            for _ in range(21)
        ]
        assert codes == [302] * 20 + [429]


# ---------------------------------------------------------------------------
# Réinvitation par le créateur (seul chemin de réactivation, R4)
# ---------------------------------------------------------------------------


class TestReinvite:
    def _retired(self, db, guest, email="back@test.com"):
        guest.email = email
        guest.is_active = False
        _commit(db)

    def _post(self, client, event, guest_id):
        return client.post(
            f"/e/{event.code}/members", data={"action": "reinvite", "guest_id": guest_id}
        )

    def test_creator_reinvite_reactivates_and_sends_hashed_persisted_link(
        self, client, db, event, guest, creator, creator_client, queue
    ):
        self._retired(db, guest)
        resp = self._post(creator_client, event, guest.id)
        _persisted(db)  # R2
        assert resp.status_code == 302
        assert guest.is_active is True
        assert len(queue.guest_recovery()) == 1
        email, _title, link = queue.guest_recovery()[0]
        assert email == "back@test.com"
        assert guest.recovery_token == _hash(_raw(link))
        assert ActivityLog.query.filter_by(action="participant.reinvited").count() == 1

    def test_reinvite_may_reveal_the_link_in_debug_without_smtp(
        self, app, client, db, event, guest, creator, creator_client
    ):
        """An authenticated creator action is the one place the dev link may be shown."""
        self._retired(db, guest)
        app.config["SMTP_HOST"] = ""
        app.config["DEV_SHOW_SECRETS"] = True
        app.debug = True
        self._post(creator_client, event, guest.id)
        assert any(f"/e/{event.code}/guest-recover/" in msg for msg in _flashes(creator_client))

    def test_reinvite_without_email_reactivates_without_mail(
        self, client, db, event, guest, creator, creator_client, queue
    ):
        self._retired(db, guest, email=None)
        resp = self._post(creator_client, event, guest.id)
        _persisted(db)
        assert resp.status_code == 302
        assert guest.is_active is True
        assert queue.jobs == []

    def test_reinvite_requires_creator(
        self, client, db, event, guest, other_guest_c, guest_client, queue
    ):
        self._retired(db, other_guest_c)
        resp = self._post(guest_client, event, other_guest_c.id)
        _persisted(db)
        assert resp.status_code == 403
        assert other_guest_c.is_active is False
        assert queue.jobs == []

    def test_reinvite_refused_when_guest_cap_reached(
        self, app, client, db, event, guest, other_guest_c, creator, creator_client, queue
    ):
        """R6b : le plafond can_add_guest s'applique à la réactivation."""
        app.config["MAX_GUESTS_PER_EVENT"] = 1  # `guest` occupe déjà la seule place
        self._retired(db, other_guest_c)
        resp = self._post(creator_client, event, other_guest_c.id)
        _persisted(db)
        assert resp.status_code == 422
        assert other_guest_c.is_active is False
        assert other_guest_c.recovery_token is None
        assert queue.jobs == []

    @pytest.mark.parametrize("target", ["unknown", "active", "merged", "creator", "other_event"])
    def test_reinvite_invalid_targets_are_404(
        self, db, event, other_event, guest, other_guest_c, creator_guest, creator_client, target
    ):
        ids = {
            "unknown": "nope",
            "active": guest.id,
            "creator": creator_guest.id,
        }
        if target == "merged":
            other_guest_c.is_active = False
            other_guest_c.merged_into_id = guest.id
            _commit(db)
            ids["merged"] = other_guest_c.id
        if target == "other_event":
            foreign = Guest(
                code="forgn1", display_name="Foreign", event_id=other_event.id, is_active=False
            )
            db.session.add(foreign)
            _commit(db)
            ids["other_event"] = foreign.id
        resp = self._post(creator_client, event, ids[target])
        assert resp.status_code == 404

    def test_members_page_lists_retired_profiles_with_reinvite_button(
        self, client, db, event, guest, other_guest_c, creator, creator_client
    ):
        html = creator_client.get(f"/e/{event.code}/members").get_data(as_text=True)
        assert 'data-testid="reinvite-participant"' not in html
        self._retired(db, other_guest_c)
        html = creator_client.get(f"/e/{event.code}/members").get_data(as_text=True)
        assert html.count('data-testid="reinvite-participant"') == 1


# ---------------------------------------------------------------------------
# Email RQ (nouveaux)
# ---------------------------------------------------------------------------


class TestRecoveryLinkEmailTasks:
    def test_send_recovery_link_email_smtp(self):
        from unittest.mock import MagicMock, patch

        from app import tasks

        with patch("app.tasks.smtplib.SMTP") as mock_smtp:
            conn = MagicMock()
            mock_smtp.return_value.__enter__.return_value = conn
            tasks.send_recovery_link_email(
                "smtp.test",
                587,
                "u",
                "p",
                "f@x",
                "to@test.com",
                "http://t/e/recover/link/abc",
                "fr",
            )
            conn.send_message.assert_called_once()

    def test_send_guest_recovery_link_email_smtp(self):
        from unittest.mock import MagicMock, patch

        from app import tasks

        with patch("app.tasks.smtplib.SMTP") as mock_smtp:
            conn = MagicMock()
            mock_smtp.return_value.__enter__.return_value = conn
            tasks.send_guest_recovery_link_email(
                "smtp.test",
                587,
                "u",
                "p",
                "f@x",
                "to@test.com",
                "Weekend",
                "http://t/e/XYZ/guest-recover/abc",
                "fr",
            )
            conn.send_message.assert_called_once()


# ---------------------------------------------------------------------------
# API v1 — ne doit rien exposer
# ---------------------------------------------------------------------------


class TestApiNonExposure:
    def test_api_does_not_expose_emails_or_tokens(self, client, db, event, creator, creator_client):
        from app.apikeys import create_api_key

        _, key = create_api_key(event, creator=creator)
        _login_creator(client, creator)
        resp = client.get(f"/api/events/{event.code}", headers={"Authorization": f"Bearer {key}"})
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "recovery_token" not in body
        assert "email" not in body.lower()


# ---------------------------------------------------------------------------
# i18n — actions de journal B038
# ---------------------------------------------------------------------------


class TestI18nJournal:
    def test_b038_l1_journal_actions_defined(self):
        from app.i18n import ACTION_LABELS, ACTION_SENTENCES

        for code in (
            "participant.email_fixed",
            "participant.recovery_sent",
            "participant.restored",
            "participant.reinvited",
            "account.email_erased",
            "account.code_changed",
        ):
            assert code in ACTION_LABELS
            assert code in ACTION_SENTENCES
