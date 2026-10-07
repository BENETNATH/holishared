"""Chat refondu (B025b, 25.3) : composeur, envoi HTMX, récupération incrémentale, pagination, actions."""

import re
from datetime import date, datetime, timedelta

import pytest
from tests.ui_helpers import block, tag, testids

from app.models import ChatMessage, Event

HX = {"HX-Request": "true"}
BASE = datetime(2026, 10, 5, 12, 0, 0)  # noqa: DTZ001 - dates naïves en base


def _msg(db, event, content, who=None, at=0, name="Alice", kind="guest", gid=None):
    m = ChatMessage(
        content=content,
        created_at=BASE + timedelta(seconds=at),
        guest_id=who.id if who is not None else gid,
        author_name=who.display_name if who is not None else name,
        author_type=kind,
        event_id=event.id,
    )
    db.session.add(m)
    db.session.commit()
    return m


def _page(client, event):
    return client.get(f"/e/{event.code}/chat").data.decode()


def _after(client, event, after="", ts=""):
    return client.get(f"/e/{event.code}/chat?after={after}&ts={ts}", headers=HX)


def _contents(html):
    return re.findall(r'data-testid="chat-content"[^>]*>([^<]*)<', html)


@pytest.fixture
def other_event(db, creator):
    e = Event(
        code="OTHER2",
        title="Autre",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 2),
        creator_id=creator.id,
        verified_at=datetime.utcnow(),
    )
    db.session.add(e)
    db.session.commit()
    return e


# --- Structure ---------------------------------------------------------------


def test_index_composer_textarea_has_label(guest_client, event):
    form = block(_page(guest_client, event), "chat-composer", "form")
    assert re.search(r'<label[^>]*for="chat-input"', form)


def test_index_composer_uses_textarea(guest_client, event):
    assert "<textarea" in block(_page(guest_client, event), "chat-composer", "form")


def test_index_send_button_has_accessible_label(guest_client, event):
    assert "aria-label=" in tag(_page(guest_client, event), "chat-send")


def test_index_new_messages_button_is_hidden_initially(guest_client, event):
    assert " hidden" in tag(_page(guest_client, event), "chat-new-messages")


def test_index_shows_empty_state_without_messages(guest_client, event):
    assert 'data-testid="chat-empty"' in _page(guest_client, event)


def test_index_has_no_standalone_delete_button(db, guest_client, event, guest):
    _msg(db, event, "salut", guest)
    assert 'class="chat-delete' not in _page(guest_client, event)


def test_message_exposes_testids(db, guest_client, event):
    _msg(db, event, "salut")
    ids = testids(_page(guest_client, event), "chat-")
    assert {"chat-message", "chat-author", "chat-content"} <= set(ids)


def test_own_message_is_labelled_vous(db, guest_client, event, guest):
    _msg(db, event, "salut", guest)
    assert block(_page(guest_client, event), "chat-author", "span").endswith(">Vous</span>")


def test_own_message_is_flagged_mine(db, guest_client, event, guest):
    _msg(db, event, "salut", guest)
    assert 'data-mine="true"' in tag(_page(guest_client, event), "chat-message")


def test_other_message_shows_author_name(db, guest_client, event):
    _msg(db, event, "salut", name="Bernadette")
    assert "Bernadette" in block(_page(guest_client, event), "chat-author", "span")


def test_other_message_is_not_flagged_mine(db, guest_client, event):
    _msg(db, event, "salut")
    assert 'data-mine="false"' in tag(_page(guest_client, event), "chat-message")


def test_message_content_is_escaped(db, guest_client, event):
    _msg(db, event, "<script>alert(1)</script>")
    assert "<script>alert(1)" not in _page(guest_client, event)


# --- Actions de message ------------------------------------------------------


def test_menu_shown_on_own_message(db, guest_client, event, guest):
    _msg(db, event, "a", guest)
    assert "chat-menu" in testids(_page(guest_client, event), "chat-")


def test_menu_hidden_on_other_message_for_guest(db, guest_client, event):
    _msg(db, event, "a")
    assert "chat-menu" not in testids(_page(guest_client, event), "chat-")


def test_menu_shown_for_creator_on_any_message(db, creator_client, event):
    _msg(db, event, "a")
    assert "chat-menu" in testids(_page(creator_client, event), "chat-")


def test_delete_form_asks_confirmation(db, creator_client, event):
    _msg(db, event, "a")
    assert "data-confirm=" in tag(_page(creator_client, event), "chat-delete-form")


def test_htmx_delete_returns_empty_body(db, creator_client, event):
    m = _msg(db, event, "a")
    r = creator_client.post(f"/e/{event.code}/chat/{m.id}/delete", headers=HX)
    assert (r.status_code, r.text) == (200, "")


def test_htmx_delete_removes_message(db, creator_client, event):
    m = _msg(db, event, "a")
    creator_client.post(f"/e/{event.code}/chat/{m.id}/delete", headers=HX)
    assert db.session.get(ChatMessage, m.id) is None


def test_htmx_delete_of_other_event_message_is_404(db, creator_client, event, other_event):
    m = _msg(db, other_event, "a")
    assert creator_client.post(f"/e/{event.code}/chat/{m.id}/delete", headers=HX).status_code == 404


def test_htmx_delete_forbidden_for_non_author(db, guest_client, event):
    m = _msg(db, event, "a")
    assert guest_client.post(f"/e/{event.code}/chat/{m.id}/delete", headers=HX).status_code == 403


# --- Groupes et dates --------------------------------------------------------


def _flags(html):
    return re.findall(r'data-testid="chat-message"[^>]*data-continued="(true|false)"', html)


def test_same_author_within_five_minutes_is_grouped(db, guest_client, event, guest):
    _msg(db, event, "a", guest, 0)
    _msg(db, event, "b", guest, 60)
    assert _flags(_page(guest_client, event)) == ["false", "true"]


def test_same_author_after_five_minutes_starts_new_group(db, guest_client, event, guest):
    _msg(db, event, "a", guest, 0)
    _msg(db, event, "b", guest, 301)
    assert _flags(_page(guest_client, event)) == ["false", "false"]


def test_other_author_starts_new_group(db, guest_client, event, guest, other_guest_c):
    _msg(db, event, "a", guest, 0)
    _msg(db, event, "b", other_guest_c, 10)
    assert _flags(_page(guest_client, event)) == ["false", "false"]


def test_date_separator_precedes_first_message(db, guest_client, event):
    _msg(db, event, "a")
    assert "chat-date" in testids(_page(guest_client, event), "chat-")


def test_date_separator_added_when_day_changes(db, guest_client, event, guest):
    _msg(db, event, "a", guest, 0)
    _msg(db, event, "b", guest, 86400)
    assert testids(_page(guest_client, event), "chat-date") == ["chat-date", "chat-date"]


def test_no_date_separator_within_same_day(db, guest_client, event, guest):
    _msg(db, event, "a", guest, 0)
    _msg(db, event, "b", guest, 3600)
    assert len(testids(_page(guest_client, event), "chat-date")) == 1


def test_day_change_breaks_group(db, guest_client, event, guest):
    _msg(db, event, "a", guest, 43000)
    _msg(db, event, "b", guest, 43100)
    _msg(db, event, "c", guest, 43100 + 3600)  # lendemain, même auteur
    assert _flags(_page(guest_client, event))[-1] == "false"


# --- Envoi HTMX --------------------------------------------------------------


def test_htmx_send_returns_fragment_with_message(db, guest_client, event):
    r = guest_client.post(f"/e/{event.code}/chat/send", data={"content": "Coucou"}, headers=HX)
    assert (r.status_code, "Coucou" in r.text, "<html" in r.text) == (200, True, False)


def test_htmx_send_stores_message(db, guest_client, event):
    guest_client.post(f"/e/{event.code}/chat/send", data={"content": "Coucou"}, headers=HX)
    assert ChatMessage.query.filter_by(event_id=event.id).one().content == "Coucou"


def test_htmx_send_returns_missed_messages_before_mine_in_order(db, guest_client, event):
    m1 = _msg(db, event, "vu", at=-100)
    _msg(db, event, "manque", at=-50)
    r = guest_client.post(
        f"/e/{event.code}/chat/send",
        data={"content": "moi", "after": m1.id, "ts": m1.created_at.isoformat()},
        headers=HX,
    )
    assert _contents(r.text) == ["manque", "moi"]


def test_htmx_send_empty_is_422_with_toast(guest_client, event):
    r = guest_client.post(f"/e/{event.code}/chat/send", data={"content": "  "}, headers=HX)
    assert (r.status_code, "ui:toast" in r.headers["HX-Trigger"]) == (422, True)


def test_htmx_send_too_long_is_422_and_not_stored(db, guest_client, event):
    r = guest_client.post(f"/e/{event.code}/chat/send", data={"content": "x" * 2001}, headers=HX)
    assert (r.status_code, ChatMessage.query.count()) == (422, 0)


def test_htmx_send_rate_limited_returns_429_with_toast(db, guest_client, event):
    codes = [
        guest_client.post(f"/e/{event.code}/chat/send", data={"content": "a"}, headers=HX)
        for _ in range(31)
    ]
    assert (codes[-1].status_code, "ui:toast" in codes[-1].headers.get("HX-Trigger", "")) == (
        429,
        True,
    )


def test_plain_send_still_redirects(guest_client, event):
    r = guest_client.post(f"/e/{event.code}/chat/send", data={"content": "Coucou"})
    assert r.status_code == 302


# --- Récupération incrémentale -----------------------------------------------


def test_after_returns_only_newer_messages_in_order(db, guest_client, event):
    ms = [_msg(db, event, f"m{i}", at=i) for i in range(4)]
    assert _contents(_after(guest_client, event, ms[1].id).text) == ["m2", "m3"]


def test_after_is_idempotent(db, guest_client, event):
    ms = [_msg(db, event, f"m{i}", at=i) for i in range(3)]
    first = _after(guest_client, event, ms[0].id).text
    assert _after(guest_client, event, ms[0].id).text == first


def test_after_last_message_returns_nothing(db, guest_client, event):
    m = _msg(db, event, "x")
    assert _contents(_after(guest_client, event, m.id).text) == []


def test_after_cursor_advance_has_no_duplicates(db, guest_client, event):
    ms = [_msg(db, event, f"m{i}", at=i) for i in range(3)]
    a = _contents(_after(guest_client, event, ms[0].id).text)
    b = _contents(_after(guest_client, event, ms[2].id).text)
    assert a + b == ["m1", "m2"]


def test_after_same_timestamp_breaks_tie_by_id(db, guest_client, event):
    a, b = _msg(db, event, "a", at=0), _msg(db, event, "b", at=0)
    low, high = sorted([a, b], key=lambda m: m.id)
    assert _contents(_after(guest_client, event, low.id).text) == [high.content]


def test_after_unknown_id_falls_back_to_timestamp(db, guest_client, event):
    _msg(db, event, "old", at=0)
    _msg(db, event, "new", at=60)
    r = _after(guest_client, event, "deleted", (BASE + timedelta(seconds=30)).isoformat())
    assert _contents(r.text) == ["new"]


def test_after_unknown_id_without_timestamp_returns_nothing(db, guest_client, event):
    _msg(db, event, "old")
    assert _contents(_after(guest_client, event, "nope").text) == []


def test_after_ignores_cursor_from_other_event(db, guest_client, event, other_event):
    foreign = _msg(db, other_event, "secret", at=0)
    _msg(db, event, "mine", at=10)
    assert _contents(_after(guest_client, event, foreign.id).text) == []


def test_after_never_returns_other_event_messages(db, guest_client, event, other_event):
    m = _msg(db, event, "a", at=0)
    _msg(db, other_event, "secret", at=10)
    assert "secret" not in _after(guest_client, event, m.id).text


def test_after_requires_participant(db, client, event):
    assert client.get(f"/e/{event.code}/chat?after=x").status_code == 302


def test_after_fragment_continues_group_of_cursor(db, guest_client, event, guest):
    m1 = _msg(db, event, "a", guest, 0)
    _msg(db, event, "b", guest, 30)
    assert _flags(_after(guest_client, event, m1.id).text) == ["true"]


def test_after_fragment_has_no_date_separator_same_day(db, guest_client, event):
    m1 = _msg(db, event, "a", at=0)
    _msg(db, event, "b", at=30)
    assert "chat-date" not in _after(guest_client, event, m1.id).text


# --- Historique --------------------------------------------------------------


def _many(db, event, n):
    return [_msg(db, event, f"msg-{i:02d}", at=i) for i in range(n)]


def test_page_shows_older_button_beyond_fifty(db, guest_client, event):
    _many(db, event, 51)
    assert "chat-older" in testids(_page(guest_client, event), "chat-")


def test_page_has_no_older_button_up_to_fifty(db, guest_client, event):
    _many(db, event, 50)
    assert "chat-older" not in testids(_page(guest_client, event), "chat-")


def test_older_button_points_to_first_displayed_message(db, guest_client, event):
    ms = _many(db, event, 60)
    assert f'data-before="{ms[10].id}"' in tag(_page(guest_client, event), "chat-older")


def test_before_returns_previous_messages_in_order(db, guest_client, event):
    ms = _many(db, event, 60)
    r = guest_client.get(f"/e/{event.code}/chat?before={ms[10].id}", headers=HX)
    assert _contents(r.text) == [f"msg-{i:02d}" for i in range(10)]


def test_before_pages_by_fifty(db, guest_client, event):
    ms = _many(db, event, 120)
    r = guest_client.get(f"/e/{event.code}/chat?before={ms[70].id}", headers=HX)
    assert _contents(r.text) == [f"msg-{i:02d}" for i in range(20, 70)]


def test_before_reports_more_when_history_remains(db, guest_client, event):
    ms = _many(db, event, 120)
    r = guest_client.get(f"/e/{event.code}/chat?before={ms[70].id}", headers=HX)
    assert r.headers["X-Chat-Has-More"] == "true"


def test_before_reports_no_more_at_history_start(db, guest_client, event):
    ms = _many(db, event, 60)
    r = guest_client.get(f"/e/{event.code}/chat?before={ms[10].id}", headers=HX)
    assert r.headers["X-Chat-Has-More"] == "false"


def test_before_ignores_cursor_from_other_event(db, guest_client, event, other_event):
    foreign = _msg(db, other_event, "secret", at=10)
    _msg(db, event, "mine", at=0)
    r = guest_client.get(f"/e/{event.code}/chat?before={foreign.id}", headers=HX)
    assert _contents(r.text) == []


def test_before_without_htmx_renders_full_page(db, guest_client, event):
    ms = _many(db, event, 60)
    html = guest_client.get(f"/e/{event.code}/chat?before={ms[10].id}").text
    assert ("<html" in html, "msg-09" in html, "msg-10" in html) == (True, True, False)


def test_htmx_index_still_returns_fragment(db, guest_client, event):
    _msg(db, event, "salut")
    r = guest_client.get(f"/e/{event.code}/chat", headers=HX)
    assert ("<html" in r.text, "salut" in r.text) == (False, True)
