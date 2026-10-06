"""Tests for access codes: generation, resolution, limitation (B029)."""

import logging
import re

import pytest
from sqlalchemy.exc import IntegrityError

from app.access import is_code_format, resolve_event_code, resolve_home_code
from app.models import (
    CODE_ALPHABET,
    Creator,
    Guest,
    generate_event_code,
    generate_guest_code,
)


def test_generate_guest_code_length_8():
    assert len(generate_guest_code()) == 8


def test_generate_guest_code_uses_unambiguous_alphabet():
    chars = set("".join(generate_guest_code() for _ in range(200)))
    assert chars <= set(CODE_ALPHABET)


def test_generate_event_code_skips_reserved(monkeypatch):
    forced = iter("access")
    real_choice = __import__("secrets").choice

    def fake_choice(seq):
        return next(forced, None) or real_choice(seq)

    monkeypatch.setattr("app.models.secrets.choice", fake_choice)
    assert generate_event_code() != "access"


# --- Résolution -----------------------------------------------------------------


def _ip(n: int) -> dict[str, str]:
    return {"REMOTE_ADDR": f"10.1.{n // 200}.{n % 200 + 1}"}


def _post(app, url, data, n=0, client=None):
    return (client or app.test_client()).post(url, data=data, environ_overrides=_ip(n))


def _fail(app, event, n=0):
    return _post(app, f"/e/{event.code}/mycode", {"guest_code": "zzzzzzzz"}, n)


def test_is_code_format_accepts_4_chars():
    assert is_code_format("ab12") is True


def test_is_code_format_rejects_9_chars():
    assert is_code_format("abcdefghi") is False


def test_is_code_format_rejects_symbols():
    assert is_code_format("ab-cd") is False


def test_resolve_home_code_event_code_returns_event(event):
    assert resolve_home_code(event.code).kind == "event"


def test_resolve_home_code_creator_code_returns_creator(db, creator):
    creator.personal_code = "abcd2345"
    db.session.commit()
    assert resolve_home_code("ABCD2345").kind == "creator"


def test_resolve_home_code_event_wins_over_same_creator_code(db, event, creator):
    creator.personal_code = event.code
    db.session.commit()
    assert resolve_home_code(event.code).kind == "event"


def test_resolve_home_code_unverified_event_returns_none(unverified_event):
    assert resolve_home_code(unverified_event.code) is None


def test_resolve_home_code_unknown_returns_none(event):
    assert resolve_home_code("zzzzzzzz") is None


def test_resolve_event_code_guest_returns_guest(event, guest):
    assert resolve_event_code(event, guest.code).guest.id == guest.id


def test_resolve_event_code_creator_code_returns_creator(db, event, creator):
    creator.personal_code = "abcd2345"
    db.session.commit()
    assert resolve_event_code(event, "abcd2345").kind == "creator"


def test_resolve_event_code_other_creator_code_returns_none(db, event):
    other = Creator(email="o@test.com", display_name="O", personal_code="other123")
    db.session.add(other)
    db.session.commit()
    assert resolve_event_code(event, "other123") is None


def test_resolve_event_code_creator_guest_token_returns_none(event, creator_guest):
    assert resolve_event_code(event, creator_guest.code) is None


def test_resolve_event_code_inactive_guest_returns_none(db, event, guest):
    guest.is_active = False
    db.session.commit()
    assert resolve_event_code(event, guest.code) is None


# --- Accueil --------------------------------------------------------------------


def _session_user(client):
    with client.session_transaction() as sess:
        return sess.get("_user_id")


def test_access_six_char_creator_code_logs_in(app, db, creator):
    creator.personal_code = "abc123"
    db.session.commit()
    client = app.test_client()
    client.post("/e/access", data={"code": "abc123"})
    assert _session_user(client) == creator.id


def test_access_legacy_four_char_creator_code_logs_in(app, db, creator):
    creator.personal_code = "ab12"
    db.session.commit()
    client = app.test_client()
    client.post("/e/access", data={"code": "ab12"})
    assert _session_user(client) == creator.id


def test_access_event_code_redirects_mycode(client, event):
    resp = client.post("/e/access", data={"code": event.code})
    assert resp.headers["Location"].endswith(f"/e/{event.code}/mycode")


def test_access_bad_format_and_unknown_same_flash(app):
    flashes = []
    for code in ("ab", "zzzzzzzz"):
        client = app.test_client()
        client.post("/e/access", data={"code": code})
        with client.session_transaction() as sess:
            flashes.append(sess["_flashes"])
    assert flashes[0] == flashes[1]


def test_mycode_creator_code_logs_in_creator(app, db, event, creator):
    creator.personal_code = "abcd2345"
    db.session.commit()
    client = app.test_client()
    client.post(f"/e/{event.code}/mycode", data={"guest_code": "abcd2345"})
    assert _session_user(client) == creator.id


# --- Limitation -----------------------------------------------------------------


def test_mycode_sixth_failure_same_ip_event_returns_429(app, event):
    codes = [_fail(app, event).status_code for _ in range(6)]
    assert codes == [200, 200, 200, 200, 200, 429]


def test_mycode_successes_do_not_consume_quota(app, event, guest):
    for _ in range(10):
        _post(app, f"/e/{event.code}/mycode", {"guest_code": guest.code})
    assert _fail(app, event).status_code == 200


def test_join_code_rejection_shares_ip_event_quota_with_mycode(app, event, guest):
    for _ in range(5):
        _fail(app, event)
    resp = _post(app, f"/e/{event.code}/join", {"display_name": "Zed", "code": guest.code})
    assert resp.status_code == 429


def test_mycode_correct_code_other_ip_after_attack_succeeds(app, event, guest):
    for i in range(60):
        _fail(app, event, n=i % 20)
    resp = _post(app, f"/e/{event.code}/mycode", {"guest_code": guest.code}, n=21)
    assert resp.headers["Location"].endswith(f"/e/{event.code}")


def test_access_failure_log_omits_code(app, event, caplog):
    with caplog.at_level(logging.WARNING, logger="app.security"):
        _post(app, "/e/access", {"code": "qwertyui"})
    records = [r.getMessage() for r in caplog.records if r.name == "app.security"]
    assert (len(records), "qwertyui" in records[0]) == (1, False)


def test_access_twenty_first_failure_same_ip_returns_429(app):
    codes = [_post(app, "/e/access", {"code": "zzzzzzzz"}).status_code for _ in range(21)]
    assert codes[-1] == 429


def test_access_correct_code_other_ip_after_many_failures_succeeds(app, db, creator):
    creator.personal_code = "abcd2345"
    db.session.commit()
    for i in range(30):
        _post(app, "/e/access", {"code": "zzzzzzzz"}, n=i % 10)
    client = app.test_client()
    _post(app, "/e/access", {"code": "abcd2345"}, n=11, client=client)
    assert _session_user(client) == creator.id


def test_join_event_full_does_not_consume_quota(app, event, guest):
    app.config["MAX_GUESTS_PER_EVENT"] = 1
    data = {"display_name": "Zed", "code": "zed12345"}
    codes = [_post(app, f"/e/{event.code}/join", data).status_code for _ in range(5)]
    assert codes == [200] * 5


def test_target_alert_logged_after_threshold(app, event, caplog):
    with caplog.at_level(logging.WARNING, logger="app.security"):
        for i in range(51):
            _fail(app, event, n=i)
    assert "code_target_alert event=" in caplog.text


def test_limiter_created_with_memory_fallback(monkeypatch):
    captured = {}

    def fake_limiter(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("app.extensions.Limiter", fake_limiter)
    from app.extensions import _create_limiter

    _create_limiter()
    assert captured["in_memory_fallback_enabled"] is True


def test_mycode_failure_renders_page_status_200(client, event):
    assert (
        client.post(f"/e/{event.code}/mycode", data={"guest_code": "zzzz9999"}).status_code == 200
    )


def test_mycode_post_with_participant_redirects_dashboard(guest_client, event):
    resp = guest_client.post(f"/e/{event.code}/mycode", data={"guest_code": "zzzz9999"})
    assert resp.headers["Location"].endswith(f"/e/{event.code}")


def test_ip_failure_counter_shared_across_routes(app, event):
    for _ in range(20):
        _post(app, "/e/access", {"code": "zzzzzzzz"})
    assert _fail(app, event).status_code == 429


def test_target_alert_storage_error_does_not_break_view(app, event, caplog, monkeypatch):
    from app.extensions import limiter

    def boom(self, *args, **kwargs):
        raise RuntimeError("storage down")

    monkeypatch.setattr(type(limiter.limiter), "hit", boom)
    with caplog.at_level(logging.WARNING, logger="app.security"):
        resp = _fail(app, event)
    assert (resp.status_code, "code_target_alert_failed" in caplog.text) == (200, True)


# --- verify et join ---------------------------------------------------------------


def _verify(client, token, **data):
    payload = {"display_name": "Chef", **data}
    return client.post(f"/e/verify/{token}", data=payload)


@pytest.fixture
def pending(db, unverified_event):
    unverified_event.verification_token = "tok-pending"
    db.session.commit()
    return unverified_event


def test_verify_rejects_seven_char_new_creator_code(client, creator, pending):
    _verify(client, "tok-pending", personal_code="abcd234")
    assert creator.personal_code is None


def test_verify_accepts_eight_char_creator_code(client, creator, pending):
    _verify(client, "tok-pending", personal_code="abcd2345")
    assert creator.personal_code == "abcd2345"


def test_verify_rejects_code_of_other_creator(client, db, pending):
    db.session.add(Creator(email="o@test.com", display_name="O", personal_code="abcd2345"))
    db.session.commit()
    resp = _verify(client, "tok-pending", personal_code="abcd2345")
    assert (resp.status_code, pending.verified_at) == (200, None)


def test_verify_keeps_existing_short_code_of_same_creator(client, db, creator, pending):
    creator.personal_code = "ab12"
    db.session.commit()
    _verify(client, "tok-pending", personal_code="ab12")
    assert pending.verified_at is not None


def _field_value(html: bytes, name: str) -> str:
    match = re.search(rf'name="{name}"[^>]*value="([^"]*)"', html.decode())
    return match.group(1) if match else ""


def test_verify_form_prefilled_with_server_suggestion(client, pending):
    value = _field_value(client.get("/e/verify/tok-pending").data, "personal_code")
    assert (len(value), set(value) <= set(CODE_ALPHABET)) == (8, True)


def test_join_form_prefilled_with_server_suggestion(client, event):
    value = _field_value(client.get(f"/e/{event.code}/join").data, "code")
    assert (len(value), set(value) <= set(CODE_ALPHABET)) == (8, True)


def test_join_rejects_code_equal_to_creator_code(client, db, event, creator):
    creator.personal_code = "crea1234"
    db.session.commit()
    client.post(f"/e/{event.code}/join", data={"display_name": "Zed", "code": "crea1234"})
    assert Guest.query.filter_by(event_id=event.id).count() == 0


def test_join_page_has_no_math_random(client, event):
    assert b"Math.random" not in client.get(f"/e/{event.code}/join").data


def test_verify_page_has_no_math_random(client, pending):
    assert b"Math.random" not in client.get("/e/verify/tok-pending").data


def test_verify_existing_creator_empty_code_keeps_code(client, db, creator, pending):
    creator.personal_code = "oldc0de1"
    db.session.commit()
    _verify(client, "tok-pending", personal_code="")
    assert (creator.personal_code, pending.verified_at is not None) == ("oldc0de1", True)


def test_verify_existing_creator_page_shows_no_code(client, db, creator, pending):
    creator.personal_code = "oldc0de1"
    db.session.commit()
    resp = client.get("/e/verify/tok-pending")
    assert (b"oldc0de1" in resp.data, _field_value(resp.data, "personal_code")) == (False, "")


def test_verify_integrity_error_renders_code_taken(client, db, pending, monkeypatch):
    original = db.session.commit
    calls = []

    def flaky():
        if not calls:
            calls.append(1)
            raise IntegrityError("stmt", {}, Exception("unique"))
        original()

    monkeypatch.setattr(db.session, "commit", flaky)
    resp = _verify(client, "tok-pending", personal_code="abcd2345")
    monkeypatch.undo()
    db.session.refresh(pending)
    assert (resp.status_code, pending.verified_at) == (200, None)


# --- /join : pas d'oracle de codes, création limitée par IP (audit B017/B029 #1) ------


def test_join_invalid_name_does_not_reveal_taken_code(app, event, guest):
    resp = _post(app, f"/e/{event.code}/join", {"display_name": "", "code": guest.code})
    assert "Code déjà utilisé".encode() not in resp.data


def test_join_invalid_name_with_creator_code_does_not_reveal(app, db, event, creator):
    creator.personal_code = "abcd2345"
    db.session.commit()
    resp = _post(app, f"/e/{event.code}/join", {"display_name": "", "code": "abcd2345"})
    assert "Code déjà utilisé".encode() not in resp.data


def test_join_invalid_email_does_not_reveal_taken_code(app, event, guest):
    data = {"display_name": "Zed", "code": guest.code, "email": "not-an-email"}
    assert "Code déjà utilisé".encode() not in _post(app, f"/e/{event.code}/join", data).data


def test_join_taken_code_is_still_refused_when_form_is_otherwise_valid(app, event, guest):
    resp = _post(app, f"/e/{event.code}/join", {"display_name": "Zed", "code": guest.code})
    assert "Code déjà utilisé".encode() in resp.data


def test_join_twenty_first_creation_same_ip_is_refused_and_mycode_still_works(
    app, db, event, guest
):
    app.config["MAX_GUESTS_PER_EVENT"] = 100
    statuses = []
    for i in range(21):
        data = {"display_name": f"Zed{i}", "code": f"zed{i:05d}"}
        statuses.append(_post(app, f"/e/{event.code}/join", data).status_code)
    assert statuses == [302] * 20 + [429]
    assert Guest.query.filter_by(event_id=event.id, code="zed00020").first() is None
    resp = _post(app, f"/e/{event.code}/mycode", {"guest_code": guest.code})
    assert resp.status_code == 302


def test_join_creation_limit_is_per_ip(app, event):
    app.config["MAX_GUESTS_PER_EVENT"] = 100
    for i in range(20):
        _post(app, f"/e/{event.code}/join", {"display_name": f"Zed{i}", "code": f"zed{i:05d}"})
    resp = _post(app, f"/e/{event.code}/join", {"display_name": "Other", "code": "other123"}, n=5)
    assert resp.status_code == 302
