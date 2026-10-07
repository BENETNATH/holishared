"""B019 — pages 403/404/500 du kit avec chemin de retour, connexion admin."""

import logging
import re

import pytest


def _html(resp):
    return resp.get_data(as_text=True)


@pytest.fixture
def boom(app):
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.route("/_boom")
    def _boom():
        raise RuntimeError("secret-internal-detail")

    return "/_boom"


# --- 404 / 403 ---------------------------------------------------------------


def test_404_is_rendered_by_the_template(client):
    assert 'data-testid="error-404"' in _html(client.get("/nowhere"))


def test_404_status_is_preserved(client):
    assert client.get("/nowhere").status_code == 404


def test_404_offers_home_as_the_way_back(client):
    assert 'data-testid="error-home"' in _html(client.get("/nowhere"))


def test_404_hides_my_events_for_unknown_device(client):
    assert 'data-testid="error-my-events"' not in _html(client.get("/nowhere"))


def test_404_offers_my_events_to_guest_device(guest_client):
    assert 'data-testid="error-my-events"' in _html(guest_client.get("/nowhere"))


def test_404_offers_my_events_to_creator(creator_client, event):
    assert 'data-testid="error-my-events"' in _html(creator_client.get("/nowhere"))


def test_404_inside_event_offers_back_to_event(guest_client, event):
    html = _html(guest_client.get(f"/e/{event.code}/lists/does-not-exist"))
    assert f'href="/e/{event.code}"' in tag_of(html, "error-back-event")


def test_404_has_single_primary_action(guest_client, event):
    html = _html(guest_client.get(f"/e/{event.code}/lists/does-not-exist"))
    assert html.count("ui-btn--primary") == 1


def test_403_status_is_preserved(guest_client, event):
    assert guest_client.get(f"/e/{event.code}/manage").status_code == 403


def test_403_is_rendered_by_the_template(guest_client, event):
    assert 'data-testid="error-403"' in _html(guest_client.get(f"/e/{event.code}/manage"))


def test_403_offers_back_to_event_for_participant(guest_client, event):
    html = _html(guest_client.get(f"/e/{event.code}/manage"))
    assert 'data-testid="error-back-event"' in html


def test_403_explains_creator_only_page(guest_client, event):
    assert "réservée au créateur" in _html(guest_client.get(f"/e/{event.code}/manage"))


def test_error_pages_keep_bottom_navigation(client):
    assert 'data-testid="nav-bottom"' in _html(client.get("/nowhere"))


def test_404_english_has_no_french_title(client):
    html = _html(client.get("/nowhere?lang=en"))
    assert "Page introuvable" not in html


# --- 500 ---------------------------------------------------------------------


def test_500_returns_status_500(client, boom):
    assert client.get(boom).status_code == 500


def test_500_is_rendered_by_the_template(client, boom):
    assert 'data-testid="error-500"' in _html(client.get(boom))


def test_500_shows_no_trace_or_internal_detail(client, boom):
    html = _html(client.get(boom))
    assert "secret-internal-detail" not in html


def test_500_shows_no_traceback_keyword(client, boom):
    assert "Traceback" not in _html(client.get(boom))


def test_500_is_logged(client, boom, caplog):
    with caplog.at_level(logging.ERROR):
        client.get(boom)
    assert any("secret-internal-detail" in (r.exc_text or "") or r.exc_info for r in caplog.records)


def test_500_offers_a_way_back_home(client, boom):
    assert 'data-testid="error-home"' in _html(client.get(boom))


def test_500_falls_back_to_minimal_page_when_template_fails(app, client, boom, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("template down")

    monkeypatch.setattr("flask.render_template", broken)
    body = _html(client.get(boom))
    assert ("<h1>" in body, 'data-testid="error-500"' in body) == (True, False)


# --- connexion admin ---------------------------------------------------------


def test_login_page_uses_the_kit_form(client):
    assert 'data-testid="login-form"' in _html(client.get("/admin/login"))


def test_login_wrong_password_shows_inline_error(client):
    html = _html(client.post("/admin/login", data={"email": "admin@test.com", "password": "x"}))
    assert 'data-testid="form-errors"' in html


def test_login_wrong_password_keeps_email(client):
    html = _html(client.post("/admin/login", data={"email": "admin@test.com", "password": "x"}))
    assert 'value="admin@test.com"' in html


def test_login_wrong_password_never_echoes_the_password(client):
    html = _html(client.post("/admin/login", data={"email": "a@b.co", "password": "hunter2-pw"}))
    assert "hunter2-pw" not in html


def test_login_has_single_submit_button(client):
    assert _html(client.get("/admin/login")).count('data-testid="login-submit"') == 1


def test_login_success_sets_persistent_remember_cookie(client):
    client.post("/admin/login", data={"email": "admin@test.com", "password": "testpass"})
    assert client.get_cookie("remember_token") is not None


def tag_of(html, testid):
    return re.search(rf"<[^>]*data-testid=\"{testid}\"[^>]*>", html).group(0)
