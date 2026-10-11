"""Tests for chat blueprint — B008.

14 tests, déterministes, un comportement = un test.
Ces tests DOIVENT échouer avant le codage (TDD).
"""

import re
from datetime import UTC, datetime, timedelta

import pytest

from app.models import ActivityLog, ChatMessage, Guest, generate_guest_code


def _login_creator(client, creator):
    """Helper : simule le login du créateur."""
    with client.session_transaction() as sess:
        sess["_user_id"] = creator.id
        sess["_fresh"] = True


def _login_guest(client, event, guest):
    """Helper : simule la session d'un guest."""
    with client.session_transaction() as sess:
        sess[f"guest_{event.code}"] = guest.id


@pytest.fixture
def other_guest(db, event):
    """Un second guest sur le même événement."""
    g = Guest(
        code=generate_guest_code(),
        display_name="Other Guest",
        event_id=event.id,
    )
    db.session.add(g)
    db.session.commit()
    return g


@pytest.fixture
def message(db, event, guest):
    """Un message envoyé par le guest."""
    m = ChatMessage(
        content="Hello everyone",
        guest_id=guest.id,
        author_name="Test Guest",
        author_type="guest",
        event_id=event.id,
    )
    db.session.add(m)
    db.session.commit()
    return m


# === TestChatIndex (4 tests) ===


class TestChatIndex:
    def test_index_renders_for_creator(self, client, creator, event, message):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/chat")
        assert resp.status_code == 200
        assert b"Chat" in resp.data
        assert b"Hello everyone" in resp.data

    def test_index_renders_for_guest(self, client, event, guest, message):
        _login_guest(client, event, guest)
        resp = client.get(f"/e/{event.code}/chat")
        assert resp.status_code == 200
        assert b"Hello everyone" in resp.data
        assert b"Test Guest" in resp.data

    def test_index_404_invalid_code(self, client, creator):
        _login_creator(client, creator)
        resp = client.get("/e/xxxxxx/chat")
        assert resp.status_code == 404

    def test_index_redirects_no_access(self, client, event):
        resp = client.get(f"/e/{event.code}/chat")
        assert resp.status_code == 302
        assert "/mycode" in resp.headers["Location"]


# === TestChatSend (5 tests) ===


class TestChatSend:
    def test_send_message_success(self, client, creator, event, db):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/chat/send", data={"content": "Bonjour tout le monde"})
        assert resp.status_code == 302
        assert f"/e/{event.code}/chat" in resp.headers["Location"]
        msg = ChatMessage.query.filter_by(event_id=event.id).first()
        assert msg is not None
        assert msg.content == "Bonjour tout le monde"
        assert msg.author_type == "creator"
        assert (
            msg.guest_id
            == Guest.query.filter_by(creator_id=creator.id, event_id=event.id).first().id
        )

    def test_send_message_empty(self, client, creator, event, db):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/chat/send", data={"content": "   "}, follow_redirects=True
        )
        assert resp.status_code == 200
        assert b"Message vide" in resp.data
        assert ChatMessage.query.filter_by(event_id=event.id).count() == 0

    def test_send_message_too_long(self, client, creator, event, db):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/chat/send",
            data={"content": "x" * 2001},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Message trop long" in resp.data
        assert ChatMessage.query.filter_by(event_id=event.id).count() == 0

    def test_send_message_logs(self, client, creator, event, db):
        _login_creator(client, creator)
        client.post(f"/e/{event.code}/chat/send", data={"content": "Logged message"})
        log = ActivityLog.query.filter_by(event_id=event.id, action="chat.message").first()
        assert log is not None
        assert log.target == "Logged message"
        assert log.actor_type == "creator"

    def test_send_as_guest(self, client, event, guest, db):
        _login_guest(client, event, guest)
        resp = client.post(
            f"/e/{event.code}/chat/send", data={"content": "Salut de la part du guest"}
        )
        assert resp.status_code == 302
        msg = ChatMessage.query.filter_by(event_id=event.id).first()
        assert msg is not None
        assert msg.guest_id == guest.id
        assert msg.author_type == "guest"
        assert msg.author_name == "Test Guest"


# === TestChatDelete (4 tests) ===


class TestChatDelete:
    def test_delete_own_message(self, client, event, guest, message, db):
        _login_guest(client, event, guest)
        resp = client.post(f"/e/{event.code}/chat/{message.id}/delete")
        assert resp.status_code == 302
        assert ChatMessage.query.get(message.id) is None

    def test_delete_message_as_creator(self, client, creator, event, message, db):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/chat/{message.id}/delete")
        assert resp.status_code == 302
        assert ChatMessage.query.get(message.id) is None

    def test_delete_forbidden_for_other(self, client, event, other_guest, message):
        _login_guest(client, event, other_guest)
        resp = client.post(f"/e/{event.code}/chat/{message.id}/delete")
        assert resp.status_code == 403
        assert ChatMessage.query.get(message.id) is not None

    def test_delete_404_invalid_id(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/chat/invalid_id/delete")
        assert resp.status_code == 404


# === TestChatHistory (1 test) ===


class TestChatHistory:
    def test_history_shows_50_max(self, client, creator, event, db):
        _login_creator(client, creator)
        base = datetime(2026, 12, 1, 12, 0, 0, tzinfo=UTC)
        for i in range(60):
            db.session.add(
                ChatMessage(
                    content=f"msg-{i:02d}",
                    created_at=base + timedelta(seconds=i),
                    guest_id=None,
                    author_name="Test Creator",
                    author_type="creator",
                    event_id=event.id,
                )
            )
        db.session.commit()
        resp = client.get(f"/e/{event.code}/chat")
        assert resp.status_code == 200
        # Les 10 plus anciens (msg-00..msg-09) sont coupés, les 50 derniers restent.
        # On lit le texte des messages : l'attribut id="msg-<hex>" de chaque <li> peut contenir « msg-09 ».
        texts = re.findall(r'data-testid="chat-content"[^>]*>([^<]*)<', resp.get_data(as_text=True))
        assert texts == [f"msg-{i:02d}" for i in range(10, 60)]
