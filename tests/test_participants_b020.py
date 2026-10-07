"""Page Participants (B020, 20.3 / 20.4) : liste, invitation, ajout, retrait, jauge, limite."""

from tests.ui_helpers import testids

from app.models import ActivityLog, Expense, Guest, Household, Transfer


def _page(client, event, query=""):
    return client.get(f"/e/{event.code}/members{query}").get_data(as_text=True)


def _post(client, event, **data):
    return client.post(f"/e/{event.code}/members", data=data)


def _add(client, event, name="Alice Martin", **extra):
    return _post(client, event, action="add", display_name=name, **extra)


def _expense(db, event, household, **extra):
    row = Expense(
        description="Courses",
        amount_cents=1000,
        paid_by_household_id=household.id,
        event_id=event.id,
        **extra,
    )
    db.session.add(row)
    db.session.commit()
    return row


# --- liste par rôle ----------------------------------------------------------------


def test_participants_page_creator_sees_other_participant_email(
    creator_client, db, event, creator_guest, guest
):
    guest.email = "invite@ex.org"
    db.session.commit()
    assert "invite@ex.org" in _page(creator_client, event)


def test_participants_page_creator_sees_other_code_masked_by_default(
    creator_client, event, creator_guest, guest
):
    html = _page(creator_client, event)
    assert (guest.code in html, 'data-masked="true"' in html) == (True, True)


def test_participants_page_guest_never_sees_another_participants_code(
    guest_client, db, event, other_guest_c
):
    assert other_guest_c.code not in _page(guest_client, event)


def test_participants_page_guest_never_sees_another_participants_email(
    guest_client, db, event, other_guest_c
):
    other_guest_c.email = "secret@ex.org"
    db.session.commit()
    assert "secret@ex.org" not in _page(guest_client, event)


def test_participants_page_guest_does_not_see_own_code(guest_client, event, guest):
    assert guest.code not in _page(guest_client, event)


def test_participants_page_guest_sees_own_email(guest_client, db, event, guest):
    guest.email = "moi@ex.org"
    db.session.commit()
    assert "moi@ex.org" in _page(guest_client, event)


def test_participants_page_guest_lists_names(guest_client, event, other_guest_c):
    assert "Other Guest" in _page(guest_client, event)


def test_participants_page_guest_has_no_admin_action(guest_client, event, other_guest_c):
    ids = set(testids(_page(guest_client, event), ""))
    assert (
        ids & {"remove-participant", "add-participant-form", "invite-block", "resend-invite"}
        == set()
    )


def test_participants_page_guest_has_share_link_button_with_join_url(app, guest_client, event):
    app.config["APP_URL"] = "https://holi.example"
    html = _page(guest_client, event)
    assert f'data-copy="https://holi.example/e/{event.code}/join"' in html


def test_participants_page_guest_has_a_single_primary_button(guest_client, event):
    assert _page(guest_client, event).count("ui-btn--primary") == 1


def test_participants_page_creator_has_a_single_primary_button(
    creator_client, event, creator_guest
):
    assert _page(creator_client, event).count("ui-btn--primary") == 1


def test_participants_page_creator_row_has_creator_badge_and_comes_first(
    creator_client, event, creator_guest, guest
):
    html = _page(creator_client, event)
    assert html.index("badge-creator") < html.index("Test Guest")


def test_participants_page_creator_has_no_code_row_for_own_participant(
    creator_client, event, creator_guest
):
    assert "participant-code" not in _page(creator_client, event)


def test_participants_page_shows_household_and_composition(
    creator_client, db, event, creator_guest, guest
):
    db.session.add(
        Household(
            name="Foyer Dupont", num_adults=2, num_children=1, event_id=event.id, guest_id=guest.id
        )
    )
    db.session.commit()
    html = _page(creator_client, event)
    assert ("Foyer Dupont" in html, "2 adultes, 1 enfant" in html) == (True, True)


def test_participants_page_creator_join_link_uses_app_url(
    app, creator_client, event, creator_guest
):
    app.config["APP_URL"] = "https://holi.example"
    assert f'value="https://holi.example/e/{event.code}/join"' in _page(creator_client, event)


def test_participants_page_creator_shows_qr_code(creator_client, event, creator_guest):
    assert f"/e/{event.code}/invite/qr" in _page(creator_client, event)


def test_participants_page_anonymous_redirects_to_my_code(client, event):
    assert "/mycode" in client.get(f"/e/{event.code}/members").headers["Location"]


def test_participants_page_escapes_names(creator_client, db, event, creator_guest):
    db.session.add(Guest(code="zzzz1111", display_name="<i>x</i>", event_id=event.id))
    db.session.commit()
    assert "<i>x</i>" not in _page(creator_client, event)


def test_participants_page_other_event_guest_is_not_listed(
    creator_client, db, event, creator_guest, creator
):
    from datetime import UTC, datetime

    from app.models import Event

    other = Event(
        code="OTHER2",
        title="Autre",
        start_date=event.start_date,
        end_date=event.end_date,
        creator_id=creator.id,
        verified_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.session.add(other)
    db.session.flush()
    db.session.add(Guest(code="abcd1234", display_name="Ailleurs", event_id=other.id))
    db.session.commit()
    assert "Ailleurs" not in _page(creator_client, event)


# --- ajout --------------------------------------------------------------------------


def test_add_participant_creates_an_active_guest(creator_client, db, event, creator_guest):
    _add(creator_client, event)
    assert (
        Guest.query.filter_by(
            event_id=event.id, display_name="Alice Martin", is_active=True
        ).count()
        == 1
    )


def test_add_participant_creates_a_household_named_after_them(
    creator_client, db, event, creator_guest
):
    _add(creator_client, event)
    guest = Guest.query.filter_by(display_name="Alice Martin").one()
    assert Household.query.filter_by(guest_id=guest.id).one().name == "Foyer Alice Martin"


def test_add_participant_household_is_visible_in_costs(creator_client, event, creator_guest):
    _add(creator_client, event)
    html = creator_client.get(f"/e/{event.code}/costs").get_data(as_text=True)
    assert "Foyer Alice Martin" in html


def test_add_participant_redirects_to_the_list(creator_client, event, creator_guest):
    resp = _add(creator_client, event)
    assert resp.headers["Location"].endswith(f"/e/{event.code}/members")


def test_add_participant_logs_participant_added(creator_client, event, creator_guest):
    _add(creator_client, event)
    assert (
        ActivityLog.query.filter_by(action="participant.added", target="Alice Martin").count() == 1
    )


def test_add_participant_with_short_name_shows_field_error(creator_client, event, creator_guest):
    html = _add(creator_client, event, "A").get_data(as_text=True)
    assert 'data-testid="err-display_name"' in html


def test_add_participant_with_short_name_creates_nothing(creator_client, db, event, creator_guest):
    _add(creator_client, event, "A")
    assert Guest.query.filter_by(event_id=event.id).count() == 1


def test_add_participant_with_invalid_email_shows_field_error(creator_client, event, creator_guest):
    html = _add(creator_client, event, email="pas-un-mail").get_data(as_text=True)
    assert 'data-testid="err-email"' in html


def test_add_participant_with_disposable_email_is_refused(creator_client, db, event, creator_guest):
    _add(creator_client, event, email="x@mailinator.com")
    assert Guest.query.filter_by(display_name="Alice Martin").count() == 0


def test_add_participant_by_a_guest_is_forbidden(guest_client, event):
    assert _add(guest_client, event).status_code == 403


def test_add_participant_at_limit_creates_nothing(app, creator_client, event, creator_guest):
    app.config["MAX_GUESTS_PER_EVENT"] = 1
    _add(creator_client, event)
    assert Guest.query.filter_by(display_name="Alice Martin").count() == 0


def test_add_participant_unknown_action_is_a_bad_request(creator_client, event, creator_guest):
    assert _post(creator_client, event, action="boom").status_code == 400


# --- retrait ------------------------------------------------------------------------


def test_remove_participant_deactivates_the_guest(creator_client, db, event, creator_guest, guest):
    _post(creator_client, event, action="remove", guest_id=guest.id)
    assert db.session.get(Guest, guest.id).is_active is False


def test_remove_participant_by_a_guest_is_forbidden(guest_client, event, other_guest_c):
    assert _post(guest_client, event, action="remove", guest_id=other_guest_c.id).status_code == 403


def test_remove_creator_participant_is_forbidden(creator_client, event, creator_guest):
    assert (
        _post(creator_client, event, action="remove", guest_id=creator_guest.id).status_code == 403
    )


def test_remove_unknown_participant_is_not_found(creator_client, event, creator_guest):
    assert _post(creator_client, event, action="remove", guest_id="nope").status_code == 404


def test_remove_participant_of_another_event_is_not_found(
    creator_client, db, event, creator_guest, creator
):
    from datetime import UTC, datetime

    from app.models import Event

    other = Event(
        code="OTHER3",
        title="Autre",
        start_date=event.start_date,
        end_date=event.end_date,
        creator_id=creator.id,
        verified_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.session.add(other)
    db.session.flush()
    stranger = Guest(code="qwer1234", display_name="Étranger", event_id=other.id)
    db.session.add(stranger)
    db.session.commit()
    assert _post(creator_client, event, action="remove", guest_id=stranger.id).status_code == 404


def test_remove_participant_deletes_their_unused_household(
    creator_client, db, event, creator_guest
):
    _add(creator_client, event)
    guest = Guest.query.filter_by(display_name="Alice Martin").one()
    _post(creator_client, event, action="remove", guest_id=guest.id)
    assert Household.query.filter_by(guest_id=guest.id).count() == 0


def test_remove_participant_keeps_household_when_the_event_has_expenses(
    creator_client, db, event, creator_guest
):
    _add(creator_client, event)
    guest = Guest.query.filter_by(display_name="Alice Martin").one()
    home = Household.query.filter_by(guest_id=guest.id).one()
    _expense(db, event, home)
    resp = creator_client.post(
        f"/e/{event.code}/members",
        data={"action": "remove", "guest_id": guest.id},
        follow_redirects=True,
    )
    assert (
        Household.query.filter_by(guest_id=guest.id).count(),
        "reste dans les Frais" in resp.get_data(as_text=True),
    ) == (1, True)


def test_remove_participant_keeps_expenses_intact(creator_client, db, event, creator_guest):
    _add(creator_client, event)
    guest = Guest.query.filter_by(display_name="Alice Martin").one()
    _expense(db, event, Household.query.filter_by(guest_id=guest.id).one())
    _post(creator_client, event, action="remove", guest_id=guest.id)
    assert Expense.query.filter_by(event_id=event.id).count() == 1


def test_remove_participant_keeps_household_with_transfers(
    creator_client, db, event, creator_guest, guest
):
    mine = Household(name="Moi", event_id=event.id, guest_id=creator_guest.id)
    theirs = Household(name="Eux", event_id=event.id, guest_id=guest.id)
    db.session.add_all([mine, theirs])
    db.session.flush()
    db.session.add(
        Transfer(
            amount_cents=500,
            from_household_id=theirs.id,
            to_household_id=mine.id,
            event_id=event.id,
        )
    )
    db.session.commit()
    _post(creator_client, event, action="remove", guest_id=guest.id)
    assert Household.query.filter_by(guest_id=guest.id).count() == 1


def test_remove_participant_without_household_succeeds(creator_client, event, creator_guest, guest):
    resp = _post(creator_client, event, action="remove", guest_id=guest.id)
    assert resp.status_code == 302


def test_remove_participant_logs_participant_removed(creator_client, event, creator_guest, guest):
    _post(creator_client, event, action="remove", guest_id=guest.id)
    assert (
        ActivityLog.query.filter_by(action="participant.removed", target="Test Guest").count() == 1
    )


def test_removed_participant_loses_access(app, creator_client, db, event, creator_guest, guest):
    from flask import g

    _post(creator_client, event, action="remove", guest_id=guest.id)
    g.pop("_login_user", None)  # le contexte applicatif des tests est partagé : oublier le créateur
    other = app.test_client()
    with other.session_transaction() as s:
        s[f"guest_{event.code}"] = guest.id
    assert "/mycode" in other.get(f"/e/{event.code}/members").headers["Location"]


def test_remove_participant_frees_a_slot(app, creator_client, db, event, creator_guest, guest):
    from app.freemium import can_add_guest

    app.config["MAX_GUESTS_PER_EVENT"] = 2
    assert can_add_guest(event) is False
    _post(creator_client, event, action="remove", guest_id=guest.id)
    assert can_add_guest(event) is True


def test_remove_button_asks_for_confirmation(creator_client, event, creator_guest, guest):
    assert "data-confirm=" in _page(creator_client, event)


# --- invitation ----------------------------------------------------------------------


def _smtp(app, monkeypatch, sent):
    monkeypatch.setitem(app.config, "SMTP_HOST", "smtp.test.com")
    monkeypatch.setattr(
        "app.events._send_guest_invite_email",
        lambda ev, email, display_name=None: sent.append(email),
    )


def test_resend_sends_the_invitation_when_smtp_is_configured(
    app, creator_client, db, event, creator_guest, guest, monkeypatch
):
    sent: list[str] = []
    _smtp(app, monkeypatch, sent)
    guest.email = "g@ex.org"
    db.session.commit()
    creator_client.post(f"/e/{event.code}/invite/resend/{guest.id}")
    assert sent == ["g@ex.org"]


def test_resend_without_smtp_sends_nothing_and_says_so(
    creator_client, db, event, creator_guest, guest, monkeypatch
):
    monkeypatch.setattr("app.events._send_guest_invite_email", lambda *a, **k: 1 / 0)
    guest.email = "g@ex.org"
    db.session.commit()
    resp = creator_client.post(f"/e/{event.code}/invite/resend/{guest.id}", follow_redirects=True)
    assert "pas configuré" in resp.get_data(as_text=True)


def test_resend_without_email_says_so(
    app, creator_client, event, creator_guest, guest, monkeypatch
):
    _smtp(app, monkeypatch, [])
    resp = creator_client.post(f"/e/{event.code}/invite/resend/{guest.id}", follow_redirects=True)
    assert "Aucun email enregistré" in resp.get_data(as_text=True)


def test_resend_by_a_guest_is_forbidden(guest_client, event, other_guest_c):
    assert guest_client.post(f"/e/{event.code}/invite/resend/{other_guest_c.id}").status_code == 403


def test_resend_button_is_hidden_without_smtp(creator_client, db, event, creator_guest, guest):
    guest.email = "g@ex.org"
    db.session.commit()
    assert "resend-invite" not in _page(creator_client, event)


def test_resend_button_is_shown_with_smtp_and_email(
    app, creator_client, db, event, creator_guest, guest
):
    app.config["SMTP_HOST"] = "smtp.test.com"
    guest.email = "g@ex.org"
    db.session.commit()
    assert "resend-invite" in _page(creator_client, event)


def test_invite_email_form_is_replaced_by_a_note_without_smtp(creator_client, event, creator_guest):
    html = _page(creator_client, event)
    assert ("smtp-note" in html, "invite-email-form" in html) == (True, False)


def test_invite_email_form_is_shown_with_smtp(app, creator_client, event, creator_guest):
    app.config["SMTP_HOST"] = "smtp.test.com"
    assert "invite-email-form" in _page(creator_client, event)


def test_invite_email_without_smtp_sends_nothing(creator_client, event, creator_guest, monkeypatch):
    monkeypatch.setattr("app.events._send_guest_invite_email", lambda *a, **k: 1 / 0)
    resp = creator_client.post(
        f"/e/{event.code}/invite/email", data={"email": "a@ex.org"}, follow_redirects=True
    )
    assert "pas configuré" in resp.get_data(as_text=True)


def test_invite_email_invalid_shows_field_error(app, creator_client, event, creator_guest):
    app.config["SMTP_HOST"] = "smtp.test.com"
    resp = creator_client.post(f"/e/{event.code}/invite/email", data={"email": "nope"})
    assert 'data-testid="err-email"' in resp.get_data(as_text=True)


def test_invite_email_by_a_guest_is_forbidden(guest_client, event):
    assert (
        guest_client.post(f"/e/{event.code}/invite/email", data={"email": "a@ex.org"}).status_code
        == 403
    )


# --- compat /invite --------------------------------------------------------------------


def test_invite_route_redirects_the_creator_to_participants(creator_client, event, creator_guest):
    resp = creator_client.get(f"/e/{event.code}/invite")
    assert resp.headers["Location"].endswith(f"/e/{event.code}/members#invite")


def test_invite_route_redirects_to_participants_even_at_limit(
    app, creator_client, event, creator_guest
):
    app.config["MAX_GUESTS_PER_EVENT"] = 1
    resp = creator_client.get(f"/e/{event.code}/invite")
    assert resp.headers["Location"].endswith("/members#invite")


# --- jauge et limite ---------------------------------------------------------------------


def test_gauge_counts_active_participants_including_the_creator(
    creator_client, event, creator_guest, guest
):
    assert "2 / 10" in _page(creator_client, event)


def test_gauge_does_not_count_removed_participants(creator_client, db, event, creator_guest, guest):
    guest.is_active = False
    db.session.commit()
    assert "1 / 10" in _page(creator_client, event)


def test_gauge_matches_can_add_guest_below_the_limit(app, creator_client, event, creator_guest):
    app.config["MAX_GUESTS_PER_EVENT"] = 2
    assert 'data-at-limit="false"' in _page(creator_client, event)


def test_gauge_matches_can_add_guest_at_the_limit(app, creator_client, event, creator_guest, guest):
    app.config["MAX_GUESTS_PER_EVENT"] = 2
    assert 'data-at-limit="true"' in _page(creator_client, event)


def test_gauge_is_hidden_from_a_guest(guest_client, event):
    assert "guest-gauge" not in _page(guest_client, event)


def test_page_stays_accessible_at_the_limit(app, creator_client, event, creator_guest, guest):
    app.config["MAX_GUESTS_PER_EVENT"] = 2
    assert creator_client.get(f"/e/{event.code}/members").status_code == 200


def test_limit_card_is_honest_at_the_limit(app, creator_client, event, creator_guest, guest):
    app.config["MAX_GUESTS_PER_EVENT"] = 2
    html = _page(creator_client, event)
    assert (
        "Limite du plan gratuit atteinte" in html,
        "Les plans payants arrivent bientôt" in html,
    ) == (True, True)


def test_limit_card_has_no_fake_upgrade_button(app, creator_client, event, creator_guest, guest):
    app.config["MAX_GUESTS_PER_EVENT"] = 2
    html = _page(creator_client, event)
    assert ("data-upgrade" in html, "Passer à Vacances+" in html) == (False, False)


def test_invite_and_add_blocks_are_hidden_at_the_limit(
    app, creator_client, event, creator_guest, guest
):
    app.config["MAX_GUESTS_PER_EVENT"] = 2
    html = _page(creator_client, event)
    assert ("invite-block" in html, "add-participant-form" in html) == (False, False)


def test_participant_list_is_still_listed_at_the_limit(
    app, creator_client, event, creator_guest, guest
):
    app.config["MAX_GUESTS_PER_EVENT"] = 2
    assert "Test Guest" in _page(creator_client, event)


def test_limit_card_is_absent_below_the_limit(creator_client, event, creator_guest):
    assert "limit-card" not in _page(creator_client, event)


def test_unlimited_tier_is_never_at_the_limit(
    app, creator_client, db, event, creator, creator_guest, guest
):
    app.config["MAX_GUESTS_PER_EVENT"] = 2
    creator.tier = "pro"
    db.session.commit()
    html = _page(creator_client, event)
    assert ("Illimité" in html, 'data-at-limit="false"' in html) == (True, True)


def test_event_guest_count_ignores_inactive_guests(db, event, guest):
    guest.is_active = False
    db.session.commit()
    assert event.guest_count == 0
