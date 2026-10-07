"""B019 (F15) — sessions durables, déconnexion et oubli de l'appareil."""

from datetime import UTC, datetime, timedelta

from app.models import Guest

THIRTY_DAYS = timedelta(days=30)


def _joined(client, event, name="Zoé", code="zoe12345"):
    return client.post(
        f"/e/{event.code}/join", data={"display_name": name, "code": code}, follow_redirects=False
    )


def _lifetime(cookie):
    expires = cookie.expires
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires - datetime.now(UTC)


def test_default_session_lifetime_is_thirty_days(app):
    assert app.config["PERMANENT_SESSION_LIFETIME"] == int(THIRTY_DAYS.total_seconds())


def test_remember_cookie_duration_matches_session_lifetime(app):
    assert app.config["REMEMBER_COOKIE_DURATION"] == THIRTY_DAYS


def test_session_lifetime_is_configurable_from_environment(app_factory):
    custom = app_factory(
        {
            "SECRET_KEY": "x" * 40,
            "SUPERADMIN_PASSWORD": "pw-long-enough",
            "PERMANENT_SESSION_LIFETIME": "3600",
        }
    )
    assert custom.config["REMEMBER_COOKIE_DURATION"] == timedelta(hours=1)


def test_guest_join_sets_persistent_session_cookie(client, event):
    _joined(client, event)
    assert abs(_lifetime(client.get_cookie("session")) - THIRTY_DAYS) < timedelta(minutes=5)


def test_guest_session_cookie_is_httponly(client, event):
    assert "HttpOnly" in _joined(client, event).headers.get("Set-Cookie")


def test_guest_session_cookie_is_samesite_lax(client, event):
    assert "SameSite=Lax" in _joined(client, event).headers.get("Set-Cookie")


def test_creator_code_login_sets_persistent_remember_cookie(client, creator, db):
    creator.personal_code = "abcd2345"
    db.session.commit()
    client.post("/e/access", data={"code": "abcd2345"})
    assert abs(_lifetime(client.get_cookie("remember_token")) - THIRTY_DAYS) < timedelta(minutes=5)


def test_creator_code_login_sets_persistent_session_cookie(client, creator, db):
    creator.personal_code = "abcd2345"
    db.session.commit()
    client.post("/e/access", data={"code": "abcd2345"})
    assert abs(_lifetime(client.get_cookie("session")) - THIRTY_DAYS) < timedelta(minutes=5)


def test_anonymous_session_cookie_is_not_persistent(client):
    client.get("/")
    assert client.get_cookie("session").expires is None


def test_logout_get_is_not_allowed(creator_client):
    assert creator_client.get("/admin/logout").status_code == 405


def test_logout_post_clears_creator_session(creator_client):
    creator_client.post("/admin/logout")
    with creator_client.session_transaction() as sess:
        assert "_user_id" not in sess


def test_logout_post_clears_guest_access_of_the_device(guest_client, event):
    guest_client.post("/admin/logout")
    with guest_client.session_transaction() as sess:
        assert f"guest_{event.code}" not in sess


def test_logout_post_keeps_language_choice(client, event, guest):
    client.get("/?lang=en")
    with client.session_transaction() as sess:
        sess[f"guest_{event.code}"] = guest.id
    client.post("/admin/logout")
    with client.session_transaction() as sess:
        assert sess.get("lang") == "en"


def test_logout_post_redirects_to_home(guest_client):
    assert guest_client.post("/admin/logout").headers["Location"] == "/"


def test_forgotten_device_cannot_open_event_any_more(guest_client, event):
    guest_client.post("/admin/logout")
    assert guest_client.get(f"/e/{event.code}").headers["Location"].endswith("/mycode")


def test_guest_menu_offers_forget_device(guest_client, event):
    html = guest_client.get(f"/e/{event.code}").get_data(as_text=True)
    assert 'data-testid="more-item-forget"' in html


def test_creator_menu_offers_logout_as_post_form(creator_client, event):
    html = creator_client.get(f"/e/{event.code}").get_data(as_text=True)
    assert 'action="/admin/logout"' in html


def test_join_creates_guest_row_once(client, event, db):
    _joined(client, event)
    assert Guest.query.filter_by(event_id=event.id, code="zoe12345").count() == 1
