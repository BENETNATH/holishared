"""Accueil de l'événement (B020a, 20.1 / 20.7) : héros, actions, blocs conditionnés aux modules."""

import re
from datetime import date, datetime, timedelta

import pytest
from tests.ui_helpers import block, tag, testids, text_of

from app.models import ChatMessage, ListItem, LogisticsItem, Meal, Poll, SharedList


def _html(resp):
    return resp.data.decode()


def _home(client, event):
    return _html(client.get(f"/e/{event.code}"))


def _dates(db, event, start_delta, end_delta):
    event.start_date = date.today() + timedelta(days=start_delta)
    event.end_date = date.today() + timedelta(days=end_delta)
    db.session.commit()


# --- Héros -------------------------------------------------------------------


def test_home_hero_shows_event_title(creator_client, event):
    assert "Test Vacation" in text_of(_home(creator_client, event), "event-hero", "header")


def test_home_countdown_upcoming_says_in_n_days(db, creator_client, event):
    _dates(db, event, 12, 18)
    assert text_of(_home(creator_client, event), "event-countdown", "p") == "Dans 12 jours"


def test_home_countdown_ongoing_says_day_of_total(db, creator_client, event):
    _dates(db, event, -1, 5)
    assert text_of(_home(creator_client, event), "event-countdown", "p") == "Jour 2 sur 7"


def test_home_countdown_past_says_finished(db, creator_client, event):
    _dates(db, event, -9, -3)
    assert text_of(_home(creator_client, event), "event-countdown", "p") == "Terminé"


def test_home_status_badge_exposes_phase(db, creator_client, event):
    _dates(db, event, -1, 5)
    assert 'data-status="ongoing"' in tag(_home(creator_client, event), "event-status")


def test_home_long_description_is_folded_in_details(db, creator_client, event):
    event.description = "x" * 300
    db.session.commit()
    assert re.search(
        r"<details[^>]*data-testid=\"event-description\"", _home(creator_client, event)
    )


def test_home_short_description_is_not_folded(creator_client, event):
    assert not re.search(
        r"<details[^>]*data-testid=\"event-description\"", _home(creator_client, event)
    )


# --- Actions rapides ----------------------------------------------------------


def test_home_share_action_copies_public_join_url(app, creator_client, event):
    app.config["APP_URL"] = "https://holi.example"
    html = _home(creator_client, event)
    assert f'data-copy="https://holi.example/e/{event.code}/join"' in tag(html, "share-action")


def test_home_share_action_never_copies_dashboard_url(creator_client, event):
    copied = re.search(r'data-copy="([^"]*)"', tag(_home(creator_client, event), "share-action"))
    assert copied is not None
    assert copied.group(1).endswith("/join")


def test_home_exactly_one_primary_action_for_creator(creator_client, event):
    group = block(_home(creator_client, event), "quick-actions", "div")
    assert group.count("ui-btn--primary") == 1


def test_home_primary_action_is_add_activity(creator_client, event):
    html = _home(creator_client, event)
    assert "ui-btn--primary" in tag(html, "add-activity-action")


def test_home_invite_action_hidden_for_guest(guest_client, event):
    assert 'data-testid="invite-action"' not in _home(guest_client, event)


def test_home_invite_action_shown_for_creator(creator_client, event):
    assert 'data-testid="invite-action"' in _home(creator_client, event)


def test_home_has_no_personal_code_block_for_guest(guest_client, event, guest):
    assert guest.code not in _home(guest_client, event)


def test_home_has_no_management_zone_for_creator(creator_client, event):
    assert "Zone de gestion" not in _home(creator_client, event)


def test_home_has_no_delete_form_for_creator(creator_client, event):
    assert f"/e/{event.code}/delete" not in _home(creator_client, event)


# --- Aujourd'hui --------------------------------------------------------------


def _meal(db, event, title="Raclette"):
    db.session.add(Meal(title=title, date=date.today(), slot="dinner", event_id=event.id))
    db.session.commit()


def test_home_today_meal_links_to_meals_page(db, creator_client, event):
    _meal(db, event)
    block_html = block(_home(creator_client, event), "today", "section")
    assert f'href="/e/{event.code}/meals"' in block_html


def test_home_today_activity_links_to_planning_page(db, creator_client, event):
    from app.models import Activity

    db.session.add(
        Activity(title="Randonnée", date=date.today(), event_id=event.id, created_by=None)
    )
    db.session.commit()
    assert f'href="/e/{event.code}/planning"' in block(
        _home(creator_client, event), "today", "section"
    )


def test_home_today_empty_state_message(creator_client, event):
    assert "Rien de prévu" in text_of(_home(creator_client, event), "today-empty", "p")


def test_home_plan_meals_link_targets_meals_page(creator_client, event):
    html = _home(creator_client, event)
    match = re.search(r'<a href="([^"]*)"[^>]*data-testid="plan-meals-action"', html)
    assert match is not None
    assert match.group(1) == f"/e/{event.code}/meals"


# --- Pour moi -----------------------------------------------------------------


def _my_list(db, event, owner, name="Pain"):
    lst = SharedList(title="Courses", event_id=event.id)
    db.session.add(lst)
    db.session.flush()
    db.session.add(
        ListItem(name=name, assigned_to=owner.display_name, assigned_to_id=owner.id, list_id=lst.id)
    )
    db.session.commit()
    return lst


def test_home_for_me_lists_my_assigned_items(db, guest_client, event, guest):
    _my_list(db, event, guest)
    assert "Pain" in block(_home(guest_client, event), "my-items-group", "section")


def test_home_for_me_hides_items_of_other_guests(db, guest_client, event, other_guest_c):
    _my_list(db, event, other_guest_c, "Fromage")
    assert "Fromage" not in _home(guest_client, event)


def test_home_for_me_checkbox_posts_via_htmx(db, guest_client, event, guest):
    lst = _my_list(db, event, guest)
    html = _home(guest_client, event)
    assert f'hx-post="/e/{event.code}/lists/{lst.id}/items/' in html


def test_home_for_me_creator_sees_own_items_by_participant_id(
    db, creator_client, event, creator_guest
):
    _my_list(db, event, creator_guest, "Barbecue")
    assert "Barbecue" in block(_home(creator_client, event), "my-items-group", "section")


def test_home_unassigned_block_offers_claim_button(db, guest_client, event):
    lst = SharedList(title="Courses", event_id=event.id)
    db.session.add(lst)
    db.session.flush()
    db.session.add(ListItem(name="Sel", list_id=lst.id))
    db.session.commit()
    assert "claim-item" in testids(_home(guest_client, event), "claim-")


def test_home_for_me_empty_state_when_nothing_assigned(guest_client, event):
    assert 'data-testid="my-items-empty"' in _home(guest_client, event)


# --- Modules, sondages, chat, infos ---------------------------------------------


def test_home_polls_block_lists_open_poll_with_link(db, creator_client, event):
    poll = Poll(question="Pizza ou crêpes ?", event_id=event.id)
    db.session.add(poll)
    db.session.commit()
    assert f"/voting/{poll.id}" in block(_home(creator_client, event), "polls", "section")


def test_home_chat_block_limited_to_three_messages_server_side(db, creator_client, event):
    for n in range(8):
        db.session.add(
            ChatMessage(
                content=f"msg{n}",
                author_name="A",
                author_type="guest",
                event_id=event.id,
                created_at=datetime.utcnow() + timedelta(seconds=n),
            )
        )
    db.session.commit()
    html = _home(creator_client, event)
    assert (html.count("msg"), "msg7" in html, "msg4" in html) == (3, True, False)


def test_home_info_item_has_copy_button_with_content(db, creator_client, event):
    db.session.add(
        LogisticsItem(title="Code portail", content="A1B2C3", category="access", event_id=event.id)
    )
    db.session.commit()
    assert 'data-copy="A1B2C3"' in tag(_home(creator_client, event), "info-copy")


def test_home_infos_block_links_to_all(db, creator_client, event):
    db.session.add(LogisticsItem(title="Wifi", content="pwd", category="other", event_id=event.id))
    db.session.commit()
    assert tag(_home(creator_client, event), "infos-all").count(f"/e/{event.code}/logistics") == 1


@pytest.mark.parametrize(
    ("module", "marker"),
    [
        ("voting", 'data-testid="polls"'),
        ("chat", 'data-testid="chat-recent"'),
        ("logistics", 'data-testid="infos"'),
        ("lists", 'data-testid="my-items"'),
        ("meals", 'data-testid="plan-meals-action"'),
        ("planning", 'data-testid="add-activity-action"'),
    ],
)
def test_home_block_hidden_when_module_disabled(app_factory, module, marker):
    from app.extensions import db
    from app.models import Creator, Event

    all_modules = ["planning", "meals", "lists", "logistics", "voting", "chat"]
    built = app_factory({"ENABLED_MODULES": ",".join(m for m in all_modules if m != module)})
    creator = Creator(email="m@test.com", email_verified=True, display_name="M")
    db.session.add(creator)
    db.session.commit()
    event = Event(
        code="mod234",
        title="Mod",
        start_date=date.today(),
        end_date=date.today(),
        creator_id=creator.id,
        verified_at=datetime.utcnow(),
    )
    db.session.add(event)
    db.session.commit()
    client = built.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = creator.id
        sess["_fresh"] = True
    resp = client.get(f"/e/{event.code}")
    assert (resp.status_code, marker in resp.data.decode()) == (200, False)


def test_home_without_any_module_renders_for_guest(app_factory):
    from app.extensions import db
    from app.models import Creator, Event, Guest

    built = app_factory({"ENABLED_MODULES": ""})
    creator = Creator(email="n@test.com", email_verified=True, display_name="N")
    db.session.add(creator)
    db.session.commit()
    event = Event(
        code="non234",
        title="Nu",
        start_date=date.today(),
        end_date=date.today(),
        creator_id=creator.id,
        verified_at=datetime.utcnow(),
    )
    db.session.add(event)
    db.session.commit()
    guest = Guest(code="gst23456", display_name="G", event_id=event.id)
    db.session.add(guest)
    db.session.commit()
    client = built.test_client()
    with client.session_transaction() as sess:
        sess[f"guest_{event.code}"] = guest.id
    assert client.get(f"/e/{event.code}").status_code == 200
