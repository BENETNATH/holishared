"""Tests B034 — modèle ApiKey + routes de gestion des clés (UI).

TDD : écrits avant le code (spec ``specs/b034-api-spec.md`` §9.1).
Chaque test est mappé à une exigence de la spec ; les imports des modules
nouveaux (``ApiKey``, ``create_api_key``, ``run_api_keys_migration``) sont
faits dans les tests pour que la collecte reste possible à l'état rouge.
"""

import hashlib
import re
from datetime import date, datetime

import pytest

from app.extensions import db as _db
from app.models import Creator, Event, generate_event_code


def make_key(db, event, *, guest=None, creator=None, label=""):
    """Crée une clé via ``create_api_key`` ; renvoie ``(api_key, key)``."""
    from app.apikeys import create_api_key

    return create_api_key(event, guest=guest, creator=creator, label=label)


def auth(key):
    return {"Authorization": f"Bearer {key}"}


def _login_creator(client, creator):
    with client.session_transaction() as sess:
        sess["_user_id"] = creator.id
        sess["_fresh"] = True


@pytest.fixture
def csrf_app(monkeypatch):
    """App avec CSRF activé (conftest.py le désactive) — pattern ``gated_app``."""
    monkeypatch.setattr("app.load_dotenv", lambda *args, **kwargs: True)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ENABLED_MODULES", "planning,meals,lists,logistics,voting,media,chat,costs")
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = True
    with app.app_context():
        _db.create_all()
        yield app
        _db.drop_all()


@pytest.fixture
def apikeys_migration_app(monkeypatch, tmp_path):
    """Base fichier sans la table ``api_keys`` (migration de démarrage sautée)."""
    monkeypatch.setattr("app.load_dotenv", lambda *args, **kwargs: True)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path / "inst"))
    monkeypatch.setenv("SKIP_STARTUP_MIGRATION", "1")
    from app import create_app

    app = create_app()
    with app.app_context():
        _db.create_all()
        # À l'état rouge la table n'existe pas (modèle absent) : on ne la supprime
        # que si elle a été créée par ``create_all``.
        from sqlalchemy import inspect

        if "api_keys" in inspect(_db.engine).get_table_names():
            _db.session.execute(_db.text("DROP TABLE api_keys"))
            _db.session.commit()
    yield app
    with app.app_context():
        _db.drop_all()


class TestApiKeyModel:
    def test_apikey_stores_hash_not_key(self, db, event, creator):
        """§3.3 : key_hash == sha256(key) ; la clé complète n'est dans aucun champ."""
        api_key, key = make_key(db, event, creator=creator, label="Agent")
        assert api_key.key_hash == hashlib.sha256(key.encode("utf-8")).hexdigest()
        # La clé complète n'apparaît dans aucune colonne de la ligne brute.
        row = db.session.execute(
            db.text("SELECT * FROM api_keys WHERE id = :id"), {"id": api_key.id}
        ).fetchone()
        assert row is not None
        for value in row:
            assert value is None or key not in str(value)

    def test_apikey_key_format(self, db, event, creator):
        """§3.1/A5 : clé = ``hs_`` + 48 hex, longueur 51."""
        _, key = make_key(db, event, creator=creator)
        assert key.startswith("hs_")
        assert len(key) == 51
        hex_part = key[3:]
        assert len(hex_part) == 48
        assert all(c in "0123456789abcdef" for c in hex_part)

    def test_apikey_key_prefix_is_first_12(self, db, event, creator):
        """§3.1/A6 : key_prefix == key[:12], longueur 12."""
        api_key, key = make_key(db, event, creator=creator)
        assert api_key.key_prefix == key[:12]
        assert len(api_key.key_prefix) == 12

    def test_apikey_exactly_one_owner(self, db, event, creator, guest):
        """§3.2 : ValueError si 0 ou 2 owners ; sinon exactement un non nul."""
        with pytest.raises(ValueError):
            make_key(db, event)
        with pytest.raises(ValueError):
            make_key(db, event, guest=guest, creator=creator)
        api_key, _ = make_key(db, event, creator=creator)
        assert api_key.owner_creator_id == creator.id
        assert api_key.owner_guest_id is None
        api_key, _ = make_key(db, event, guest=guest)
        assert api_key.owner_guest_id == guest.id
        assert api_key.owner_creator_id is None

    def test_apikey_cascade_delete_event(self, db, event, creator, guest):
        """§3.4 : suppression de l'événement → toutes ses clés supprimées."""
        from app.models import ApiKey

        make_key(db, event, creator=creator)
        make_key(db, event, guest=guest)
        assert ApiKey.query.filter_by(event_id=event.id).count() == 2
        db.session.delete(event)
        db.session.commit()
        assert ApiKey.query.filter_by(event_id=event.id).count() == 0

    def test_apikey_cascade_delete_guest(self, db, event, guest):
        """§3.4 : suppression physique d'un invité → ses clés supprimées."""
        from app.models import ApiKey

        make_key(db, event, guest=guest)
        assert ApiKey.query.filter_by(owner_guest_id=guest.id).count() == 1
        db.session.delete(guest)
        db.session.commit()
        assert ApiKey.query.filter_by(owner_guest_id=guest.id).count() == 0

    def test_apikey_cascade_delete_creator(self, db, event, creator):
        """§3.4 : suppression du créateur → ses clés supprimées."""
        from app.models import ApiKey

        make_key(db, event, creator=creator)
        assert ApiKey.query.filter_by(owner_creator_id=creator.id).count() == 1
        # L'événement référence le créateur (FK sans cascade) : on le supprime d'abord.
        db.session.delete(event)
        db.session.commit()
        db.session.delete(creator)
        db.session.commit()
        assert ApiKey.query.filter_by(owner_creator_id=creator.id).count() == 0

    def test_apikey_migration_idempotent(self, apikeys_migration_app, tmp_path):
        """§3.5 : run_api_keys_migration crée la table ; 2e exécution → 0, pas de sauvegarde."""
        from app.migrations import run_api_keys_migration

        with apikeys_migration_app.app_context():
            first = run_api_keys_migration(apikeys_migration_app)
            second = run_api_keys_migration(apikeys_migration_app)
        assert first == {"api_keys_table_created": 1}
        assert second == {"api_keys_table_created": 0}
        # Création de table seule (pattern migrate_push) : aucune sauvegarde.
        backups = tmp_path / "inst" / "backups"
        assert not backups.exists() or not any(backups.iterdir())


class TestApiKeyRoutes:
    def test_create_key_as_creator(self, creator_client, event, creator, db):
        """§4.1 : POST (créateur) → 200 rendu direct ; clé complète + prefix + avertissement + code."""
        from app.models import ApiKey

        resp = creator_client.post(f"/e/{event.code}/api-keys", data={"label": "Agent"})
        assert resp.status_code == 200
        api_key = ApiKey.query.filter_by(event_id=event.id, owner_creator_id=creator.id).first()
        assert api_key is not None
        assert api_key.owner_guest_id is None
        html = resp.get_data(as_text=True)
        match = re.search(r"hs_[0-9a-f]{48}", html)
        assert match is not None
        key = match.group(0)
        assert hashlib.sha256(key.encode("utf-8")).hexdigest() == api_key.key_hash
        assert api_key.key_prefix in html
        assert event.code in html
        assert "ne sera pas réaffichée" in html
        assert f"/e/{event.code}/api-keys" in html

    def test_create_key_as_guest(self, guest_client, event, guest, db):
        """§4.1 : POST (invité) → 200 ; ApiKey avec owner_guest_id ; clé complète dans la réponse."""
        from app.models import ApiKey

        resp = guest_client.post(f"/e/{event.code}/api-keys", data={})
        assert resp.status_code == 200
        api_key = ApiKey.query.filter_by(event_id=event.id, owner_guest_id=guest.id).first()
        assert api_key is not None
        assert api_key.owner_creator_id is None
        match = re.search(r"hs_[0-9a-f]{48}", resp.get_data(as_text=True))
        assert match is not None
        assert hashlib.sha256(match.group(0).encode("utf-8")).hexdigest() == api_key.key_hash

    def test_create_key_label_optional(self, creator_client, event, db):
        """§4.1 : label absent → "" ; label présent → stocké."""
        from app.models import ApiKey

        resp = creator_client.post(f"/e/{event.code}/api-keys", data={})
        assert resp.status_code == 200
        api_key = ApiKey.query.filter_by(event_id=event.id).first()
        assert api_key is not None
        assert api_key.label == ""
        resp = creator_client.post(f"/e/{event.code}/api-keys", data={"label": "Agent IA"})
        assert resp.status_code == 200
        assert ApiKey.query.filter_by(event_id=event.id, label="Agent IA").first() is not None

    def test_create_key_shown_once_not_in_list(self, creator_client, event, db):
        """§3.3/§4.2 : clé complète dans la confirmation, absente de la liste."""
        from app.models import ApiKey

        resp = creator_client.post(f"/e/{event.code}/api-keys", data={"label": "X"})
        assert resp.status_code == 200
        key = re.search(r"hs_[0-9a-f]{48}", resp.get_data(as_text=True)).group(0)
        listing = creator_client.get(f"/e/{event.code}/api-keys")
        assert listing.status_code == 200
        assert key not in listing.get_data(as_text=True)
        api_key = ApiKey.query.filter_by(event_id=event.id).first()
        assert api_key.key_prefix in listing.get_data(as_text=True)

    def test_list_keys_only_own(self, creator_client, guest_client, event, creator, guest, db):
        """§4.2 : le créateur ne voit que ses clés ; l'invité ne voit que les siennes."""
        make_key(db, event, creator=creator, label="Ckey")
        make_key(db, event, guest=guest, label="Gkey")
        creator_html = creator_client.get(f"/e/{event.code}/api-keys").get_data(as_text=True)
        assert "Ckey" in creator_html
        assert "Gkey" not in creator_html
        # Un invité réel n'est pas connecté en tant que créateur : on déconnecte le
        # créateur (session + cache flask-login ``g._login_user``, partagé car le
        # fixture ``app`` pousse un app context réutilisé par le test client) pour
        # que la requête guest ne soit pas traitée comme une requête créateur.
        from flask_login import logout_user

        logout_user()
        with guest_client.session_transaction() as s:
            s.pop("_user_id", None)
        guest_html = guest_client.get(f"/e/{event.code}/api-keys").get_data(as_text=True)
        assert "Gkey" in guest_html
        assert "Ckey" not in guest_html

    def test_list_keys_fields(self, creator_client, event, creator, db):
        """§4.2 : la liste expose prefix/label/created_at ; jamais key_hash ni la clé."""
        api_key, key = make_key(db, event, creator=creator, label="MonAgent")
        html = creator_client.get(f"/e/{event.code}/api-keys").get_data(as_text=True)
        assert api_key.key_prefix in html
        assert "MonAgent" in html
        # La date de création est affichée (format ISO, pattern des gabarits du projet).
        assert api_key.created_at.isoformat() in html
        assert api_key.key_hash not in html
        assert key not in html

    def test_revoke_own_key(self, creator_client, event, creator, db):
        """§4.3 : DELETE de sa propre clé → 302 ; revoked_at posé."""
        api_key, _ = make_key(db, event, creator=creator)
        resp = creator_client.delete(f"/e/{event.code}/api-keys/{api_key.id}")
        assert resp.status_code == 302
        db.session.refresh(api_key)
        assert api_key.revoked_at is not None

    def test_revoke_not_own_key_is_404(self, creator_client, event, creator, guest, db):
        """§4.3/S7 : DELETE d'une clé d'autrui → 404 (ne révèle pas l'existence)."""
        api_key, _ = make_key(db, event, guest=guest)
        resp = creator_client.delete(f"/e/{event.code}/api-keys/{api_key.id}")
        assert resp.status_code == 404
        db.session.refresh(api_key)
        assert api_key.revoked_at is None

    def test_create_key_unknown_event_is_404(self, client, creator):
        """§4.1 : POST /e/xxxxxx/api-keys → 404."""
        _login_creator(client, creator)
        resp = client.post("/e/xxxxxx/api-keys", data={"label": "X"})
        assert resp.status_code == 404

    def test_create_key_no_access_redirects(self, client, event):
        """§4.1 : visiteur (pas de session) → 302 vers /mycode."""
        resp = client.post(f"/e/{event.code}/api-keys", data={"label": "X"})
        assert resp.status_code == 302
        assert "/mycode" in resp.headers["Location"]

    def test_create_key_rate_limited(self, creator_client, event, db):
        """§4.1 : 429 après la limite (10/h)."""
        codes = [
            creator_client.post(f"/e/{event.code}/api-keys", data={"label": f"k{i}"}).status_code
            for i in range(11)
        ]
        assert codes[:10] == [200] * 10
        assert codes[10] == 429

    def test_create_key_requires_csrf(self, csrf_app):
        """§4.1 : POST sans token CSRF → rejet (400/401), aucune clé créée."""
        from app.models import ApiKey

        c = Creator(email="csrf@test.com", email_verified=True, display_name="C")
        _db.session.add(c)
        _db.session.commit()
        e = Event(
            code=generate_event_code(),
            title="V",
            start_date=date(2026, 12, 1),
            end_date=date(2026, 12, 7),
            creator_id=c.id,
            verified_at=datetime.utcnow(),
        )
        _db.session.add(e)
        _db.session.commit()
        client = csrf_app.test_client()
        with client.session_transaction() as s:
            s["_user_id"] = c.id
            s["_fresh"] = True
        resp = client.post(f"/e/{e.code}/api-keys", data={"label": "X"})
        assert resp.status_code in (400, 401)
        assert ApiKey.query.filter_by(event_id=e.id).count() == 0
