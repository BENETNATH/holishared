"""Tests for RQ background tasks (email sending)."""

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
