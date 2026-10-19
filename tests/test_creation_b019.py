"""B019 — création d'événement, e-mail de vérification, confirmation du créateur."""

import re

import pytest

from app.models import Event

GOOD = {
    "title": "Été en Corse",
    "start_date": "2026-12-01",
    "end_date": "2026-12-05",
    "email": "alice@test.com",
}


def _create(client, **overrides):
    return client.post("/e/new", data={**GOOD, **overrides})


def _has_error(resp, field):
    return f'data-testid="err-{field}"' in resp.get_data(as_text=True)


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


# --- formulaire --------------------------------------------------------------


def test_create_page_explains_email_verification_before_sending(client):
    assert 'data-testid="create-verify-note"' in client.get("/e/new").get_data(as_text=True)


def test_create_page_mentions_three_day_validity(client):
    note = client.get("/e/new").get_data(as_text=True).split("create-verify-note")[1][:900]
    assert "3 jours" in note


def test_create_page_shows_maximum_duration(app, client):
    app.config["MAX_DURATION_DAYS"] = 14
    assert "Durée max : 14 jours." in client.get("/e/new").get_data(as_text=True)


def test_create_page_keeps_description_collapsed_by_default(client):
    html = client.get("/e/new").get_data(as_text=True)
    assert re.search(r'<details[^>]*data-testid="create-description"[^>]*open', html) is None


def test_create_page_has_single_submit_button(client):
    assert client.get("/e/new").get_data(as_text=True).count('data-testid="create-submit"') == 1


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"title": ""}, "title"),
        ({"start_date": ""}, "start_date"),
        ({"end_date": ""}, "end_date"),
        ({"end_date": "2026-11-01"}, "end_date"),
        ({"end_date": "2027-12-01"}, "end_date"),
        ({"start_date": "pas-une-date"}, "start_date"),
        ({"email": ""}, "email"),
        ({"email": "pas-un-email"}, "email"),
        ({"email": "x@mailinator.com"}, "email"),
    ],
)
def test_create_error_is_attached_to_its_field(client, overrides, field):
    assert _has_error(_create(client, **overrides), field)


def test_create_title_error_does_not_flag_other_fields(client):
    assert not _has_error(_create(client, title=""), "email")


def test_create_error_keeps_typed_values(client):
    html = _create(client, title="", location="Bastia").get_data(as_text=True)
    assert 'value="Bastia"' in html


def test_create_error_renders_status_200(client):
    assert _create(client, title="").status_code == 200


def test_create_over_event_limit_shows_global_error_not_redirect(app, client, db, creator, event):
    app.config["MAX_EVENTS_PER_CREATOR"] = 1
    resp = _create(client, email=creator.email)
    assert (resp.status_code, 'data-testid="form-errors"' in resp.get_data(as_text=True)) == (
        200,
        True,
    )


# --- verify_sent -------------------------------------------------------------


def test_verify_sent_masks_the_email(client, smtp_queue, db):
    _create(client)
    event = Event.query.filter_by(creator_email="alice@test.com").one()
    html = client.get(f"/e/new/sent/{event.code}").get_data(as_text=True)
    assert "a***@test.com" in html


def test_verify_sent_never_shows_full_email(client, smtp_queue, db):
    _create(client)
    event = Event.query.filter_by(creator_email="alice@test.com").one()
    assert "alice@test.com" not in client.get(f"/e/new/sent/{event.code}").get_data(as_text=True)


def test_verify_sent_mentions_three_day_delay(client, smtp_queue, db):
    _create(client)
    event = Event.query.filter_by(creator_email="alice@test.com").one()
    assert "3 jours" in client.get(f"/e/new/sent/{event.code}").get_data(as_text=True)


def test_verify_sent_tells_what_to_do_when_nothing_arrives(client, smtp_queue, db):
    _create(client)
    event = Event.query.filter_by(creator_email="alice@test.com").one()
    html = client.get(f"/e/new/sent/{event.code}").get_data(as_text=True)
    assert 'data-testid="verify-sent-help"' in html


def test_verify_sent_without_smtp_says_mail_was_not_sent(client, unverified_event):
    html = client.get(f"/e/new/sent/{unverified_event.code}").get_data(as_text=True)
    assert 'data-testid="mail-disabled"' in html


def test_verify_sent_with_smtp_has_no_mail_disabled_notice(client, smtp_queue, unverified_event):
    html = client.get(f"/e/new/sent/{unverified_event.code}").get_data(as_text=True)
    assert 'data-testid="mail-disabled"' not in html


def test_create_with_smtp_enqueues_the_verification_mail(client, smtp_queue):
    _create(client)
    assert len(smtp_queue.jobs) == 1


def test_resend_button_shown_to_the_browser_that_created_the_event(client, smtp_queue, db):
    _create(client)
    event = Event.query.filter_by(creator_email="alice@test.com").one()
    html = client.get(f"/e/new/sent/{event.code}").get_data(as_text=True)
    assert 'data-testid="resend-verification"' in html


def test_resend_button_hidden_from_other_browsers(app, client, smtp_queue, db):
    _create(client)
    event = Event.query.filter_by(creator_email="alice@test.com").one()
    html = app.test_client().get(f"/e/new/sent/{event.code}").get_data(as_text=True)
    assert 'data-testid="resend-verification"' not in html


def test_resend_sends_one_more_mail(client, smtp_queue, db):
    _create(client)
    event = Event.query.filter_by(creator_email="alice@test.com").one()
    client.post(f"/e/new/sent/{event.code}/resend")
    assert len(smtp_queue.jobs) == 2


def test_resend_from_other_browser_is_refused_and_sends_nothing(app, client, smtp_queue, db):
    _create(client)
    event = Event.query.filter_by(creator_email="alice@test.com").one()
    resp = app.test_client().post(f"/e/new/sent/{event.code}/resend")
    assert (resp.status_code, len(smtp_queue.jobs)) == (404, 1)


def test_resend_is_rate_limited_to_three_per_hour(client, smtp_queue, db):
    _create(client)
    event = Event.query.filter_by(creator_email="alice@test.com").one()
    codes = [client.post(f"/e/new/sent/{event.code}/resend").status_code for _ in range(4)]
    assert codes[-1] == 429


def test_resend_for_verified_event_is_404(client, smtp_queue, db):
    _create(client)
    event = Event.query.filter_by(creator_email="alice@test.com").one()
    from datetime import datetime

    event.verified_at = datetime.utcnow()
    db.session.commit()
    assert client.post(f"/e/new/sent/{event.code}/resend").status_code == 404


# --- confirmation (verify) ---------------------------------------------------


@pytest.fixture
def pending(client, db):
    _create(client)
    return Event.query.filter_by(creator_email="alice@test.com").one()


def _verify(client, event, **data):
    return client.post(f"/e/verify/{event.verification_token}", data=data)


def test_verify_page_prefills_a_server_suggested_code(client, pending):
    html = client.get(f"/e/verify/{pending.verification_token}").get_data(as_text=True)
    assert re.search(r'name="personal_code"[^>]*value="[a-z0-9]{8}"', html) is not None


def test_verify_page_explains_keeping_the_email_honestly(client, pending):
    html = client.get(f"/e/verify/{pending.verification_token}").get_data(as_text=True)
    # B038-L1 (D1) : l'email est conservé par défaut pour la récupération ; si on le
    # décoche, le code ne pourra plus être renvoyé (la page l'explique honnêtement).
    assert "votre code ne pourra plus être renvoyé" in html
    # Le lien de récupération est le mécanisme (plus le code en clair).
    assert "lien de récupération" in html


def test_verify_page_household_is_collapsed_optional(client, pending):
    html = client.get(f"/e/verify/{pending.verification_token}").get_data(as_text=True)
    assert re.search(r'<details[^>]*data-testid="verify-household"[^>]*open', html) is None


def test_verify_page_hides_invites_without_smtp(client, pending):
    html = client.get(f"/e/verify/{pending.verification_token}").get_data(as_text=True)
    assert 'data-testid="verify-invites"' not in html


def test_verify_page_offers_invites_with_smtp(client, smtp_queue, pending):
    html = client.get(f"/e/verify/{pending.verification_token}").get_data(as_text=True)
    assert 'data-testid="verify-invites"' in html


def test_verify_nickname_error_is_attached_to_its_field(client, pending):
    assert _has_error(
        _verify(client, pending, display_name="", personal_code="abcd2345"), "display_name"
    )


def test_verify_short_code_error_is_attached_to_its_field(client, pending):
    assert _has_error(
        _verify(client, pending, display_name="Alice", personal_code="abc"), "personal_code"
    )


def test_verify_error_keeps_nickname(client, pending):
    html = _verify(client, pending, display_name="Alice", personal_code="abc").get_data(
        as_text=True
    )
    assert 'value="Alice"' in html


def test_verify_success_creates_persistent_session(client, pending):
    _verify(client, pending, display_name="Alice", personal_code="abcd2345")
    assert client.get_cookie("remember_token") is not None
