"""Nom d'affichage modifiable depuis « Mon profil » (B020, 20.6)."""

from app.models import ActivityLog, ChatMessage, Guest


def _rename(client, event, name, **extra):
    return client.post(f"/e/{event.code}/me", data={"display_name": name, **extra})


def _html(client, event, path=""):
    return client.get(f"/e/{event.code}{path}").get_data(as_text=True)


def test_me_page_shows_rename_form_with_current_name(guest_client, event):
    html = _html(guest_client, event, "/me")
    assert 'value="Test Guest"' in html


def test_rename_by_guest_updates_the_display_name(guest_client, db, event, guest):
    _rename(guest_client, event, "Nouveau Nom")
    assert db.session.get(Guest, guest.id).display_name == "Nouveau Nom"


def test_rename_by_guest_redirects_back_to_profile(guest_client, event):
    resp = _rename(guest_client, event, "Nouveau Nom")
    assert resp.headers["Location"].endswith(f"/e/{event.code}/me")


def test_rename_by_creator_updates_the_participant_name(creator_client, db, event, creator_guest):
    creator_client.get(f"/e/{event.code}")  # le participant créateur existe déjà (fixture)
    _rename(creator_client, event, "Capitaine")
    assert db.session.get(Guest, creator_guest.id).display_name == "Capitaine"


def test_rename_by_creator_updates_the_account_name_used_for_new_events(
    creator_client, db, event, creator, creator_guest
):
    _rename(creator_client, event, "Capitaine")
    assert creator.display_name == "Capitaine"


def test_rename_updates_the_header_chip(guest_client, event):
    _rename(guest_client, event, "Nouveau Nom")
    assert "Nouveau Nom" in _html(guest_client, event)


def test_rename_shows_new_name_in_participants_list(guest_client, event):
    _rename(guest_client, event, "Nouveau Nom")
    assert "Nouveau Nom" in _html(guest_client, event, "/members")


def test_rename_writes_a_participant_renamed_log_entry(guest_client, db, event):
    _rename(guest_client, event, "Nouveau Nom")
    row = ActivityLog.query.filter_by(event_id=event.id, action="participant.renamed").one()
    assert (row.actor_name, row.target) == ("Test Guest", "Nouveau Nom")


def test_rename_to_the_same_name_writes_no_log_entry(guest_client, event):
    _rename(guest_client, event, "Test Guest")
    assert ActivityLog.query.filter_by(action="participant.renamed").count() == 0


def test_rename_keeps_the_author_name_stored_on_existing_chat_messages(
    guest_client, db, event, guest
):
    db.session.add(
        ChatMessage(
            event_id=event.id,
            guest_id=guest.id,
            author_name="Test Guest",
            author_type="guest",
            content="hello",
        )
    )
    db.session.commit()
    _rename(guest_client, event, "Nouveau Nom")
    assert ChatMessage.query.one().author_name == "Test Guest"


def test_rename_too_short_shows_field_error(guest_client, event):
    resp = _rename(guest_client, event, "A")
    assert 'data-testid="err-display_name"' in resp.get_data(as_text=True)


def test_rename_too_short_keeps_the_old_name(guest_client, db, event, guest):
    _rename(guest_client, event, "A")
    assert db.session.get(Guest, guest.id).display_name == "Test Guest"


def test_rename_too_long_shows_field_error(guest_client, event):
    resp = _rename(guest_client, event, "x" * 51)
    assert 'data-testid="err-display_name"' in resp.get_data(as_text=True)


def test_rename_blank_name_shows_field_error(guest_client, event):
    resp = _rename(guest_client, event, "   ")
    assert 'data-testid="err-display_name"' in resp.get_data(as_text=True)


def test_rename_collapses_inner_whitespace(guest_client, db, event, guest):
    _rename(guest_client, event, "  Jean   Paul ")
    assert db.session.get(Guest, guest.id).display_name == "Jean Paul"


def test_rename_cannot_change_another_participants_name(guest_client, db, event, other_guest_c):
    _rename(guest_client, event, "Nouveau Nom", guest_id=other_guest_c.id)
    assert db.session.get(Guest, other_guest_c.id).display_name == "Other Guest"


def test_rename_escapes_markup_in_the_name(guest_client, event):
    _rename(guest_client, event, "<b>Zed</b>")
    assert "<b>Zed</b>" not in _html(guest_client, event)


def test_rename_anonymous_redirects_to_my_code(client, event):
    resp = _rename(client, event, "Nouveau Nom")
    assert "/mycode" in resp.headers["Location"]


def test_me_page_explains_that_old_messages_keep_the_old_name(guest_client, event):
    assert 'data-testid="rename-help"' in _html(guest_client, event, "/me")


def test_me_page_has_a_single_primary_button(guest_client, event):
    html = _html(guest_client, event, "/me")
    assert html.count("ui-btn--primary") == 1
