"""B019 (F16) — aucune fuite de secret sans SMTP, réponse de récupération indifférenciée."""

import pytest

from app.models import Creator, Event

CODE = "secret42"


@pytest.fixture
def keeper(db):
    c = Creator(email="keeper@test.com", personal_code=CODE, display_name="Keeper")
    db.session.add(c)
    db.session.commit()
    return c


def _recover(client, email):
    return client.post("/e/recover", data={"email": email}, follow_redirects=True)


def _create(client, email="new@test.com"):
    return client.post(
        "/e/new",
        data={"title": "Été", "start_date": "2026-12-01", "end_date": "2026-12-03", "email": email},
        follow_redirects=True,
    )


class _Queue:
    def __init__(self):
        self.jobs = []

    def enqueue(self, *args, **kwargs):
        self.jobs.append(args)


@pytest.fixture
def smtp_queue(app, monkeypatch):
    queue = _Queue()
    app.config["SMTP_HOST"] = "smtp.test"
    monkeypatch.setattr("app.events._rq_queue", lambda: queue)
    return queue


def test_recover_without_smtp_never_shows_personal_code(client, keeper):
    assert CODE not in _recover(client, "keeper@test.com").get_data(as_text=True)


def test_recover_with_dev_show_secrets_never_shows_link_on_the_public_path(app, client, keeper):
    """B038 : /recover est anonyme, même DEV_SHOW_SECRETS + debug n'y affiche ni code ni lien."""
    app.config["DEV_SHOW_SECRETS"] = True
    app.debug = True
    html = _recover(client, "keeper@test.com").get_data(as_text=True)
    assert CODE not in html
    assert "/e/recover/link/" not in html


def test_recover_with_smtp_never_shows_code_even_with_dev_flag(app, client, keeper, smtp_queue):
    app.config["DEV_SHOW_SECRETS"] = True
    assert CODE not in _recover(client, "keeper@test.com").get_data(as_text=True)


def test_recover_with_smtp_enqueues_one_mail_for_known_email(client, keeper, smtp_queue):
    _recover(client, "keeper@test.com")
    assert len(smtp_queue.jobs) == 1


def test_recover_with_smtp_enqueues_nothing_for_unknown_email(client, keeper, smtp_queue):
    _recover(client, "nobody@test.com")
    assert smtp_queue.jobs == []


def test_recover_known_and_unknown_email_get_same_status(client, keeper):
    known = client.post("/e/recover", data={"email": "keeper@test.com"})
    unknown = client.post("/e/recover", data={"email": "nobody@test.com"})
    assert known.status_code == unknown.status_code


def test_recover_known_and_unknown_email_get_same_destination(client, keeper):
    known = client.post("/e/recover", data={"email": "keeper@test.com"})
    unknown = client.post("/e/recover", data={"email": "nobody@test.com"})
    assert known.headers["Location"] == unknown.headers["Location"]


def test_recover_known_and_unknown_email_get_same_flash(app, keeper):
    flashes = []
    for email in ("keeper@test.com", "nobody@test.com"):
        c = app.test_client()
        c.post("/e/recover", data={"email": email})
        with c.session_transaction() as sess:
            flashes.append(sess["_flashes"])
    assert flashes[0] == flashes[1]


def test_recover_invalid_email_shows_field_error(client):
    html = client.post("/e/recover", data={"email": "pas-un-email"}).get_data(as_text=True)
    assert 'data-testid="err-email"' in html


def test_recover_page_has_no_informal_tutoiement(client):
    html = client.get("/e/recover").get_data(as_text=True)
    assert "Ton code" not in html


def test_create_without_smtp_does_not_leak_link_on_next_page(client, db):
    html = _create(client).get_data(as_text=True)
    token = Event.query.filter_by(creator_email="new@test.com").one().verification_token
    assert token not in html


def test_create_with_dev_show_secrets_shows_verification_link(app, client, db):
    app.config["DEV_SHOW_SECRETS"] = True
    html = _create(client).get_data(as_text=True)
    token = Event.query.filter_by(creator_email="new@test.com").one().verification_token
    assert f"/e/verify/{token}" in html


def test_dev_show_secrets_defaults_to_disabled(app):
    assert app.config["DEV_SHOW_SECRETS"] is False


def test_dev_show_secrets_enabled_from_environment(app_factory):
    custom = app_factory(
        {
            "SECRET_KEY": "x" * 40,
            "SUPERADMIN_PASSWORD": "pw-long-enough",
            "DEV_SHOW_SECRETS": "true",
        }
    )
    assert custom.config["DEV_SHOW_SECRETS"] is True
