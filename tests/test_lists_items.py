"""Articles de liste (B023) : saisie complète, cocher en un geste, attribution facultative, suppression."""

import json
import re

import pytest
from tests.ui_helpers import block, tag

from app.models import ActivityLog, ListItem, SharedList

HX = {"HX-Request": "true", "HX-Target": "list-items"}


@pytest.fixture
def shopping(db, event):
    lst = SharedList(title="Courses", list_type="shopping", event_id=event.id)
    db.session.add(lst)
    db.session.commit()
    return lst


def _item(db, lst, name="Pain", **kwargs):
    item = ListItem(name=name, list_id=lst.id, **kwargs)
    db.session.add(item)
    db.session.commit()
    return item


def _url(event, lst, item=None, action="items"):
    base = f"/e/{event.code}/lists/{lst.id}"
    if item is None:
        return f"{base}/{action}"
    return f"{base}/items/{item.id}/{action}"


def _page(client, event, lst):
    return client.get(f"/e/{event.code}/lists/{lst.id}").data.decode()


def _row(html, item):
    match = re.search(rf'<li data-testid="list-item" data-item-id="{item.id}".*?</li>', html, re.S)
    assert match, "ligne absente"
    return match.group(0)


def _names(html):
    return re.findall(r'data-testid="item-name">([^<]+)<', html)


# --- Ajout rapide -----------------------------------------------------------------------


def test_add_item_with_quantity_and_section_stores_both(guest_client, event, shopping):
    guest_client.post(
        _url(event, shopping), data={"name": "Pain", "quantity": "3", "section": "Boulangerie"}
    )
    item = ListItem.query.one()
    assert (item.quantity, item.section) == ("3", "Boulangerie")


def test_add_item_without_options_defaults_quantity_to_one(guest_client, event, shopping):
    guest_client.post(_url(event, shopping), data={"name": "Pain"})
    assert ListItem.query.one().quantity == "1"


def test_add_item_records_guest_as_author(guest_client, event, guest, shopping):
    guest_client.post(_url(event, shopping), data={"name": "Pain"})
    assert ListItem.query.one().created_by == guest.id


def test_add_item_records_creator_participant_as_author(
    creator_client, event, creator_guest, shopping
):
    creator_client.post(_url(event, shopping), data={"name": "Pain"})
    assert ListItem.query.one().created_by == creator_guest.id


def test_add_item_htmx_returns_items_fragment_root(guest_client, event, shopping):
    resp = guest_client.post(_url(event, shopping), data={"name": "Pain"}, headers=HX)
    assert resp.data.decode().lstrip().startswith('<div id="list-items"')


def test_add_item_htmx_fragment_contains_new_item(guest_client, event, shopping):
    resp = guest_client.post(_url(event, shopping), data={"name": "Pain"}, headers=HX)
    assert _names(resp.data.decode()) == ["Pain"]


def test_add_item_htmx_without_name_swaps_nothing(guest_client, event, shopping):
    resp = guest_client.post(_url(event, shopping), data={"name": ""}, headers=HX)
    assert resp.headers["HX-Reswap"] == "none"


def test_add_item_htmx_without_name_triggers_error_toast(guest_client, event, shopping):
    resp = guest_client.post(_url(event, shopping), data={"name": ""}, headers=HX)
    toast = json.loads(resp.headers["HX-Trigger"])["ui:toast"]
    assert (toast["tone"], toast["message"]) == ("danger", "Nom requis.")


def test_add_item_htmx_without_name_creates_nothing(guest_client, event, shopping):
    guest_client.post(_url(event, shopping), data={"name": ""}, headers=HX)
    assert ListItem.query.count() == 0


def test_add_item_without_htmx_redirects_to_list(guest_client, event, shopping):
    resp = guest_client.post(_url(event, shopping), data={"name": "Pain"})
    assert resp.headers["Location"].endswith(f"/lists/{shopping.id}")


def test_add_item_too_long_quantity_shows_field_error(guest_client, event, shopping):
    resp = guest_client.post(_url(event, shopping), data={"name": "Pain", "quantity": "x" * 51})
    assert b'id="list-add-quantity-error"' in resp.data


# --- Page de détail ---------------------------------------------------------------------


def test_detail_has_no_autofocus_field(guest_client, event, shopping):
    assert "autofocus" not in block(_page(guest_client, event, shopping), "list-main", "div")


def test_detail_add_form_offers_quantity_and_section_options(guest_client, event, shopping):
    html = _page(guest_client, event, shopping)
    assert 'name="quantity"' in block(html, "list-add-options", "details")
    assert 'name="section"' in block(html, "list-add-options", "details")


def test_detail_add_form_targets_items_fragment_without_reload(guest_client, event, shopping):
    html = _page(guest_client, event, shopping)
    assert 'hx-target="#list-items"' in tag(html, "list-add-form")


def test_detail_groups_open_items_by_section_in_order_of_appearance(
    db, guest_client, event, shopping
):
    _item(db, shopping, "Lait", section="Crèmerie")
    _item(db, shopping, "Pain", section="Boulangerie")
    _item(db, shopping, "Beurre", section="Crèmerie")
    html = _page(guest_client, event, shopping)
    assert _names(html) == ["Lait", "Beurre", "Pain"]


def test_detail_puts_items_without_section_last_under_own_heading(
    db, guest_client, event, shopping
):
    _item(db, shopping, "Sel")
    _item(db, shopping, "Pain", section="Boulangerie")
    html = _page(guest_client, event, shopping)
    assert re.findall(r'data-section="([^"]*)"', html) == ["Boulangerie", ""]


def test_detail_without_any_section_has_no_section_heading(db, guest_client, event, shopping):
    _item(db, shopping, "Sel")
    assert "<h3" not in block(_page(guest_client, event, shopping), "list-items", "div")


def test_detail_lists_open_items_before_done_items(db, guest_client, event, shopping):
    _item(db, shopping, "Fait", is_done=True)
    _item(db, shopping, "Ouvert")
    assert _names(_page(guest_client, event, shopping)) == ["Ouvert", "Fait"]


def test_detail_puts_done_items_in_collapsible_group(db, guest_client, event, shopping):
    _item(db, shopping, "Fait", is_done=True)
    html = _page(guest_client, event, shopping)
    assert "Fait" in block(html, "list-done-group", "details")


def test_detail_without_done_items_has_no_done_group(db, guest_client, event, shopping):
    _item(db, shopping, "Ouvert")
    assert 'data-testid="list-done-group"' not in _page(guest_client, event, shopping)


def test_detail_empty_list_shows_empty_message(guest_client, event, shopping):
    assert 'data-testid="list-empty"' in _page(guest_client, event, shopping)


def test_detail_hides_quantity_one_and_shows_other_quantities(db, guest_client, event, shopping):
    _item(db, shopping, "Pain", quantity="3")
    assert "× 3" in _row(_page(guest_client, event, shopping), ListItem.query.one())  # noqa: RUF001


# --- Cocher en un geste ------------------------------------------------------------------


def test_toggle_unassigned_item_checks_it_without_claim(db, guest_client, event, shopping):
    item = _item(db, shopping)
    guest_client.post(_url(event, shopping, item, "toggle"))
    assert db.session.get(ListItem, item.id).is_done is True


def test_toggle_unassigned_item_leaves_it_unassigned(db, guest_client, event, shopping):
    item = _item(db, shopping)
    guest_client.post(_url(event, shopping, item, "toggle"))
    assert db.session.get(ListItem, item.id).assigned_to_id is None


def test_toggle_htmx_with_list_target_returns_list_fragment(db, guest_client, event, shopping):
    item = _item(db, shopping)
    resp = guest_client.post(_url(event, shopping, item, "toggle"), headers=HX)
    assert resp.data.decode().lstrip().startswith('<div id="list-items"')


def test_toggle_htmx_with_list_target_moves_item_to_done_group(db, guest_client, event, shopping):
    item = _item(db, shopping)
    html = guest_client.post(_url(event, shopping, item, "toggle"), headers=HX).data.decode()
    assert "Pain" in block(html, "list-done-group", "details")


def test_toggle_item_taken_by_other_guest_is_forbidden(
    db, guest_client, event, other_guest_c, shopping
):
    item = _item(db, shopping, assigned_to="Other Guest", assigned_to_id=other_guest_c.id)
    assert guest_client.post(_url(event, shopping, item, "toggle")).status_code == 403


def test_creator_can_toggle_item_taken_by_a_guest(
    db, creator_client, event, creator_guest, guest, shopping
):
    item = _item(db, shopping, assigned_to="Test Guest", assigned_to_id=guest.id)
    creator_client.post(_url(event, shopping, item, "toggle"))
    assert db.session.get(ListItem, item.id).is_done is True


def test_detail_disables_checkbox_of_item_taken_by_other(
    db, guest_client, event, other_guest_c, shopping
):
    item = _item(db, shopping, assigned_to="Other Guest", assigned_to_id=other_guest_c.id)
    assert " disabled" in tag(_row(_page(guest_client, event, shopping), item), "item-check")


def test_detail_keeps_checkbox_enabled_for_unassigned_item(db, guest_client, event, shopping):
    item = _item(db, shopping)
    assert " disabled" not in tag(_row(_page(guest_client, event, shopping), item), "item-check")


# --- Attribution facultative -------------------------------------------------------------


def test_claim_htmx_with_list_target_shows_assignee_in_fragment(db, guest_client, event, shopping):
    item = _item(db, shopping)
    html = guest_client.post(_url(event, shopping, item, "claim"), headers=HX).data.decode()
    assert 'data-testid="item-assignee"' in html


def test_claim_sets_assignee_by_guest_id(db, guest_client, event, guest, shopping):
    item = _item(db, shopping)
    guest_client.post(_url(event, shopping, item, "claim"), headers=HX)
    assert db.session.get(ListItem, item.id).assigned_to_id == guest.id


def test_claim_item_taken_by_other_is_forbidden(db, guest_client, event, other_guest_c, shopping):
    item = _item(db, shopping, assigned_to_id=other_guest_c.id, assigned_to="Other Guest")
    assert guest_client.post(_url(event, shopping, item, "claim")).status_code == 403


def test_unclaim_htmx_with_list_target_returns_list_fragment(
    db, guest_client, event, guest, shopping
):
    item = _item(db, shopping, assigned_to="Test Guest", assigned_to_id=guest.id)
    resp = guest_client.post(_url(event, shopping, item, "unclaim"), headers=HX)
    assert resp.data.decode().lstrip().startswith('<div id="list-items"')


def test_detail_offers_claim_on_unassigned_item(db, guest_client, event, shopping):
    item = _item(db, shopping)
    assert 'data-testid="item-claim"' in _row(_page(guest_client, event, shopping), item)


def test_detail_offers_release_on_own_item(db, guest_client, event, guest, shopping):
    item = _item(db, shopping, assigned_to="Test Guest", assigned_to_id=guest.id)
    assert 'data-testid="item-release"' in _row(_page(guest_client, event, shopping), item)


def test_detail_hides_claim_and_release_on_item_of_other(
    db, guest_client, event, other_guest_c, shopping
):
    item = _item(db, shopping, assigned_to="Other Guest", assigned_to_id=other_guest_c.id)
    row = _row(_page(guest_client, event, shopping), item)
    assert ("item-claim" in row, "item-release" in row) == (False, False)


def test_detail_shows_assignee_name_for_item_of_other(
    db, guest_client, event, other_guest_c, shopping
):
    item = _item(db, shopping, assigned_to="Other Guest", assigned_to_id=other_guest_c.id)
    assert (
        "Other Guest" in _row(_page(guest_client, event, shopping), item).split("item-assignee")[1]
    )


# --- Suppression et annulation -----------------------------------------------------------


def test_guest_deletes_own_item(db, guest_client, event, guest, shopping):
    item = _item(db, shopping, created_by=guest.id)
    guest_client.post(_url(event, shopping, item, "delete"))
    assert db.session.get(ListItem, item.id) is None


def test_guest_cannot_delete_item_of_other_guest(db, guest_client, event, other_guest_c, shopping):
    item = _item(db, shopping, created_by=other_guest_c.id)
    assert guest_client.post(_url(event, shopping, item, "delete")).status_code == 403


def test_guest_cannot_delete_legacy_item_without_author(db, guest_client, event, shopping):
    item = _item(db, shopping)
    assert guest_client.post(_url(event, shopping, item, "delete")).status_code == 403


def test_creator_deletes_item_of_any_guest(
    db, creator_client, event, creator_guest, guest, shopping
):
    item = _item(db, shopping, created_by=guest.id)
    creator_client.post(_url(event, shopping, item, "delete"))
    assert db.session.get(ListItem, item.id) is None


def test_delete_without_htmx_redirects(db, guest_client, event, guest, shopping):
    item = _item(db, shopping, created_by=guest.id)
    resp = guest_client.post(_url(event, shopping, item, "delete"))
    assert resp.status_code == 302


def test_delete_htmx_returns_fragment_without_the_item(db, guest_client, event, guest, shopping):
    item = _item(db, shopping, created_by=guest.id)
    html = guest_client.post(_url(event, shopping, item, "delete"), headers=HX).data.decode()
    assert _names(html) == []


def test_delete_htmx_triggers_undo_toast_of_about_eight_seconds(
    db, guest_client, event, guest, shopping
):
    item = _item(db, shopping, created_by=guest.id)
    resp = guest_client.post(_url(event, shopping, item, "delete"), headers=HX)
    assert json.loads(resp.headers["HX-Trigger"])["ui:toast"]["timeout"] == 8000


def test_delete_htmx_undo_action_posts_to_restore_route(db, guest_client, event, guest, shopping):
    item = _item(db, shopping, created_by=guest.id)
    resp = guest_client.post(_url(event, shopping, item, "delete"), headers=HX)
    action = json.loads(resp.headers["HX-Trigger"])["ui:toast"]["action"]
    assert action["post"] == _url(event, shopping, action="items/restore")


def test_delete_htmx_trigger_header_is_ascii_for_accented_names(
    db, guest_client, event, guest, shopping
):
    item = _item(db, shopping, "Crème brûlée", created_by=guest.id)
    resp = guest_client.post(_url(event, shopping, item, "delete"), headers=HX)
    assert resp.headers["HX-Trigger"].isascii()


def test_detail_shows_delete_only_on_own_items(
    db, guest_client, event, guest, other_guest_c, shopping
):
    mine = _item(db, shopping, "Mien", created_by=guest.id)
    theirs = _item(db, shopping, "Leur", created_by=other_guest_c.id)
    html = _page(guest_client, event, shopping)
    assert ("item-delete" in _row(html, mine), "item-delete" in _row(html, theirs)) == (True, False)


def test_detail_shows_delete_on_every_item_for_creator(
    db, creator_client, event, creator_guest, guest, shopping
):
    item = _item(db, shopping, created_by=guest.id)
    assert "item-delete" in _row(_page(creator_client, event, shopping), item)


def test_restore_recreates_item_with_same_data(db, guest_client, event, guest, shopping):
    guest_client.post(
        _url(event, shopping, action="items/restore"),
        data={"name": "Pain", "quantity": "3", "section": "Boulangerie", "is_done": "1"},
    )
    item = ListItem.query.one()
    assert (item.name, item.quantity, item.section, item.is_done) == (
        "Pain",
        "3",
        "Boulangerie",
        True,
    )


def test_restore_keeps_assignment_to_self(db, guest_client, event, guest, shopping):
    guest_client.post(
        _url(event, shopping, action="items/restore"),
        data={"name": "Pain", "assigned_to_id": guest.id},
    )
    assert ListItem.query.one().assigned_to_id == guest.id


def test_restore_drops_assignment_to_someone_else_for_a_guest(
    db, guest_client, event, other_guest_c, shopping
):
    guest_client.post(
        _url(event, shopping, action="items/restore"),
        data={"name": "Pain", "assigned_to_id": other_guest_c.id},
    )
    assert ListItem.query.one().assigned_to_id is None


def test_restore_records_author_for_a_guest(
    db, guest_client, event, guest, other_guest_c, shopping
):
    guest_client.post(
        _url(event, shopping, action="items/restore"),
        data={"name": "Pain", "created_by": other_guest_c.id},
    )
    assert ListItem.query.one().created_by == guest.id


def test_restore_keeps_original_author_for_creator(
    db, creator_client, event, creator_guest, guest, shopping
):
    creator_client.post(
        _url(event, shopping, action="items/restore"), data={"name": "Pain", "created_by": guest.id}
    )
    assert ListItem.query.one().created_by == guest.id


def test_restore_without_name_is_rejected(db, guest_client, event, shopping):
    resp = guest_client.post(_url(event, shopping, action="items/restore"), data={"name": ""})
    assert resp.status_code == 400


def test_restore_logs_action(db, guest_client, event, shopping):
    guest_client.post(_url(event, shopping, action="items/restore"), data={"name": "Pain"})
    assert ActivityLog.query.filter_by(action="list_item.restored").count() == 1


# --- Suppression de la liste (dépriorisée) -----------------------------------------------


def test_list_deletion_lives_in_creator_menu_with_confirmation(
    creator_client, event, creator_guest, shopping
):
    html = _page(creator_client, event, shopping)
    assert "data-confirm=" in block(html, "list-menu", "details")


def test_list_menu_is_hidden_for_guests(guest_client, event, shopping):
    assert 'data-testid="list-menu"' not in _page(guest_client, event, shopping)


def test_detail_has_a_single_primary_button_in_the_page(guest_client, event, shopping):
    html = block(_page(guest_client, event, shopping), "list-main", "div")
    assert html.count("ui-btn--primary") == 1
