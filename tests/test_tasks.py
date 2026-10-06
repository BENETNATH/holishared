"""Tests for RQ background tasks (email sending)."""

import re
from unittest.mock import MagicMock, patch

import pytest

from app import tasks


@pytest.fixture
def smtp_config():
    return {
        "host": "smtp.test.com",
        "port": 587,
        "user": "user@test.com",
        "password": "pass",
        "from": "holishared@test.com",
    }


def test_send_verification_email(smtp_config):
    with patch("app.tasks.smtplib.SMTP") as mock_smtp:
        mock_conn = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_conn
        tasks.send_verification_email(
            smtp_config["host"], smtp_config["port"],
            smtp_config["user"], smtp_config["password"],
            smtp_config["from"], "to@test.com",
            "Test Event", "http://test.com/verify/abc",
        )
        mock_smtp.assert_called_once_with("smtp.test.com", 587)
        mock_conn.starttls.assert_called_once()
        mock_conn.login.assert_called_once_with("user@test.com", "pass")
        mock_conn.send_message.assert_called_once()


def test_send_invite_email(smtp_config):
    with patch("app.tasks.smtplib.SMTP") as mock_smtp:
        mock_conn = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_conn
        tasks.send_invite_email(
            smtp_config["host"], smtp_config["port"],
            smtp_config["user"], smtp_config["password"],
            smtp_config["from"], "to@test.com",
            "Test Event", "01/12/2026", "07/12/2026",
            "Strasbourg", "http://test.com/e/abc/join",
        )
        mock_smtp.assert_called_once()


def test_send_guest_invite_email(smtp_config):
    with patch("app.tasks.smtplib.SMTP") as mock_smtp:
        mock_conn = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_conn
        tasks.send_guest_invite_email(
            smtp_config["host"], smtp_config["port"],
            smtp_config["user"], smtp_config["password"],
            smtp_config["from"], "to@test.com",
            "Test Event", "01/12/2026", "07/12/2026",
            "http://test.com/e/abc/join", "Alice",
        )
        mock_smtp.assert_called_once()


def test_send_guest_invite_email_no_name(smtp_config):
    with patch("app.tasks.smtplib.SMTP") as mock_smtp:
        mock_conn = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_conn
        tasks.send_guest_invite_email(
            smtp_config["host"], smtp_config["port"],
            smtp_config["user"], smtp_config["password"],
            smtp_config["from"], "to@test.com",
            "Test Event", "01/12/2026", "07/12/2026",
            "http://test.com/e/abc/join",
        )
        mock_smtp.assert_called_once()


def test_send_recovery_email(smtp_config):
    with patch("app.tasks.smtplib.SMTP") as mock_smtp:
        mock_conn = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_conn
        tasks.send_recovery_email(
            smtp_config["host"], smtp_config["port"],
            smtp_config["user"], smtp_config["password"],
            smtp_config["from"], "to@test.com",
            "abc123", "Alice",
        )
        mock_smtp.assert_called_once()


def _sent(call_name, lang=None, **extra):
    """Appelle une tâche avec un SMTP factice ; renvoie (sujet, corps)."""
    args = {
        "send_verification_email": ("to@test.com", "Fête", "http://t/verify/x"),
        "send_invite_email": ("to@test.com", "Fête", "1 décembre 2026", "7 décembre 2026", "Lyon", "http://t/join"),
        "send_guest_invite_email": ("to@test.com", "Fête", "1 décembre 2026", "7 décembre 2026", "http://t/join", "Alice"),
        "send_recovery_email": ("to@test.com", "abc12345", "Alice"),
    }[call_name]
    kwargs = dict(extra)
    if lang:
        kwargs["lang"] = lang
    with patch("app.tasks.smtplib.SMTP") as mock_smtp:
        conn = MagicMock()
        mock_smtp.return_value.__enter__.return_value = conn
        getattr(tasks, call_name)("h", 25, "u", "p", "f@x", *args, **kwargs)
        msg = conn.send_message.call_args[0][0]
    return msg["Subject"], msg.get_payload(decode=True).decode("utf-8")


@pytest.mark.parametrize(
    "name",
    ["send_verification_email", "send_invite_email", "send_guest_invite_email", "send_recovery_email"],
)
def test_emails_default_to_formal_french(name):
    subject, body = _sent(name)
    text = f"{subject}\n{body}"
    assert "Bonjour" in body
    assert not re.search(r"\b(tu|toi|ton|ta|tes|te|clique|crée|choisis)\b", text, re.I)


@pytest.mark.parametrize(
    "name",
    ["send_verification_email", "send_invite_email", "send_guest_invite_email", "send_recovery_email"],
)
def test_emails_are_sent_in_the_requested_language(name):
    subject, body = _sent(name, lang="en")
    assert "Hello" in body
    assert "Bonjour" not in body
    assert "Bonjour" not in subject
    assert "événement" not in body


def test_guest_invite_email_keeps_event_title_and_dates_verbatim():
    _subject, body = _sent("send_guest_invite_email", lang="en")
    assert "Fête" in body
    assert "1 décembre 2026" in body
    assert "http://t/join" in body


def test_unknown_language_falls_back_to_french():
    subject, _body = _sent("send_recovery_email", lang="xx")
    assert "code" in subject.lower()
    assert "Your" not in subject


def test_invitation_is_enqueued_in_the_inviters_language(creator_client, event, monkeypatch):
    from flask import current_app

    monkeypatch.setitem(current_app.config, "SMTP_HOST", "smtp.test.com")
    queued = []

    class FakeQueue:
        def enqueue(self, fn, *args, **kwargs):
            queued.append((fn.__name__, args, kwargs))

    monkeypatch.setattr("app.events._rq_queue", lambda: FakeQueue())
    creator_client.post(
        f"/e/{event.code}/invite/email?lang=en", data={"email": "friend@test.com"}
    )
    name, args, kwargs = queued[0]
    assert name == "send_guest_invite_email"
    assert kwargs == {"lang": "en"}
    assert "December" in args[7]  # date longue dans la langue de l'invitant
