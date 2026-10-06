"""« Pour moi » / « À répartir » : fragments HTMX des routes de listes (B020a, 20.7)."""

import pytest
from tests.ui_helpers import block, text_of

from app.models import ListItem, SharedList

HX = {"HX-Request": "true"}


@pytest.fixture
def groceries(db, event):
    lst = SharedList(title="Courses du samedi", event_id=event.id)
    db.session.add(lst)
    db.session.commit()
    return lst


def _item(db, lst, name, owner=None, done=False):
    item = ListItem(
        name=name,
        list_id=lst.id,
        assigned_to=owner.display_name if owner else "",
        assigned_to_id=owner.id if owner else None,
        is_done=done,
    )
    db.session.add(item)
    db.session.commit()
    return item


def _url(event, lst, item, action):
    return f"/e/{event.code}/lists/{lst.id}/items/{item.id}/{action}"


def _html(resp):
    return resp.data.decode()


def test_toggle_htmx_returns_fragment_with_my_items_root(db, guest_client, event, guest, groceries):
    item = _item(db, groceries, "Pain", guest)
    resp = guest_client.post(_url(event, groceries, item, "toggle"), headers=HX)
    assert 'data-testid="my-items"' in _html(resp)


def test_toggle_htmx_fragment_is_not_a_full_page(db, guest_client, event, guest, groceries):
    item = _item(db, groceries, "Pain", guest)
    resp = guest_client.post(_url(event, groceries, item, "toggle"), headers=HX)
    assert "<html" not in _html(resp)


def test_toggle_without_htmx_redirects_to_list(db, guest_client, event, guest, groceries):
    item = _item(db, groceries, "Pain", guest)
    resp = guest_client.post(_url(event, groceries, item, "toggle"))
    assert resp.headers["Location"].endswith(f"/lists/{groceries.id}")


def test_toggle_htmx_marks_item_done_in_database(db, guest_client, event, guest, groceries):
    item = _item(db, groceries, "Pain", guest)
    guest_client.post(_url(event, groceries, item, "toggle"), headers=HX)
    assert db.session.get(ListItem, item.id).is_done is True


def test_toggle_htmx_done_item_goes_to_collapsed_done_group(
    db, guest_client, event, guest, groceries
):
    item = _item(db, groceries, "Pain", guest)
    html = _html(guest_client.post(_url(event, groceries, item, "toggle"), headers=HX))
    assert "Pain" in block(html, "my-items-done", "details")


def test_toggle_htmx_counter_shows_done_over_total(db, guest_client, event, guest, groceries):
    item = _item(db, groceries, "Pain", guest)
    _item(db, groceries, "Lait", guest)
    html = _html(guest_client.post(_url(event, groceries, item, "toggle"), headers=HX))
    assert text_of(html, "my-items-count", "span") == "1/2 pris"


def test_toggle_htmx_undo_restores_item_to_open(db, guest_client, event, guest, groceries):
    item = _item(db, groceries, "Pain", guest, done=True)
    guest_client.post(_url(event, groceries, item, "toggle"), headers=HX, data={"is_done": "0"})
    assert db.session.get(ListItem, item.id).is_done is False


def test_toggle_with_explicit_is_done_is_idempotent(db, guest_client, event, guest, groceries):
    item = _item(db, groceries, "Pain", guest, done=True)
    guest_client.post(_url(event, groceries, item, "toggle"), headers=HX, data={"is_done": "1"})
    assert db.session.get(ListItem, item.id).is_done is True


def test_toggle_item_of_other_guest_returns_403(db, guest_client, event, other_guest_c, groceries):
    item = _item(db, groceries, "Pain", other_guest_c)
    resp = guest_client.post(_url(event, groceries, item, "toggle"), headers=HX)
    assert resp.status_code == 403


def test_toggle_item_of_other_guest_leaves_item_unchanged(
    db, guest_client, event, other_guest_c, groceries
):
    item = _item(db, groceries, "Pain", other_guest_c)
    guest_client.post(_url(event, groceries, item, "toggle"), headers=HX)
    assert db.session.get(ListItem, item.id).is_done is False


def test_toggle_item_of_other_guest_creator_may_toggle(
    db, creator_client, event, creator_guest, other_guest_c, groceries
):
    item = _item(db, groceries, "Pain", other_guest_c)
    resp = creator_client.post(_url(event, groceries, item, "toggle"), headers=HX)
    assert resp.status_code == 200


def test_claim_htmx_moves_item_to_my_group(db, guest_client, event, guest, groceries):
    item = _item(db, groceries, "Pain")
    html = _html(guest_client.post(_url(event, groceries, item, "claim"), headers=HX))
    assert "Pain" in block(html, "my-items-group", "section")


def test_claim_htmx_assigns_item_by_participant_id(db, guest_client, event, guest, groceries):
    item = _item(db, groceries, "Pain")
    guest_client.post(_url(event, groceries, item, "claim"), headers=HX)
    assert db.session.get(ListItem, item.id).assigned_to_id == guest.id


def test_claim_htmx_does_not_queue_a_flash_message(db, guest_client, event, guest, groceries):
    item = _item(db, groceries, "Pain")
    guest_client.post(_url(event, groceries, item, "claim"), headers=HX)
    with guest_client.session_transaction() as sess:
        assert sess.get("_flashes") is None


def test_claim_without_htmx_still_redirects_to_list(db, guest_client, event, guest, groceries):
    item = _item(db, groceries, "Pain")
    resp = guest_client.post(_url(event, groceries, item, "claim"))
    assert resp.headers["Location"].endswith(f"/lists/{groceries.id}")


def test_claim_item_taken_by_other_guest_htmx_returns_403(
    db, guest_client, event, other_guest_c, groceries
):
    item = _item(db, groceries, "Pain", other_guest_c)
    resp = guest_client.post(_url(event, groceries, item, "claim"), headers=HX)
    assert resp.status_code == 403


def test_fragment_unassigned_block_limited_to_five_items(db, guest_client, event, guest, groceries):
    for n in range(7):
        _item(db, groceries, f"Libre{n}")
    seed = _item(db, groceries, "Pain", guest)
    html = _html(guest_client.post(_url(event, groceries, seed, "toggle"), headers=HX))
    assert html.count('data-testid="unassigned-item"') == 5


def test_fragment_unassigned_block_links_to_lists_with_total(
    db, guest_client, event, guest, groceries
):
    for n in range(7):
        _item(db, groceries, f"Libre{n}")
    seed = _item(db, groceries, "Pain", guest)
    html = _html(guest_client.post(_url(event, groceries, seed, "toggle"), headers=HX))
    assert "7" in text_of(html, "unassigned-all", "a")
