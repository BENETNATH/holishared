"""Lot B031 : « Mon foyer » sur la page Mon profil (/e/<code>/me)."""

from tests.ui_helpers import block, tag

from app.costs import _per_expense_shares
from app.models import ActivityLog, Expense, Household


def _hh(db, event, owner=None, name="Foyer Test", adults=2, children=0):
    row = Household(
        name=name,
        num_adults=adults,
        num_children=children,
        event_id=event.id,
        guest_id=owner.id if owner else None,
    )
    db.session.add(row)
    db.session.commit()
    return row


def _post(client, event, **data):
    return client.post(f"/e/{event.code}/me/household", data=data)


def _page(client, event, path="me"):
    return client.get(f"/e/{event.code}/{path}").get_data(as_text=True)


def test_me_page_owner_sees_household_form_prefilled(guest_client, db, event, guest):
    _hh(db, event, guest, name="Famille Durand", adults=2, children=3)
    html = _page(guest_client, event)
    form = block(html, "household-form", "form")
    assert ('value="Famille Durand"' in form, 'value="3"' in form) == (True, True)


def test_me_page_without_household_offers_creation(guest_client, event):
    html = _page(guest_client, event)
    assert "Créer mon foyer" in block(html, "household-form", "form")


def test_me_page_creator_without_household_offers_creation(creator_client, event, creator_guest):
    assert "Créer mon foyer" in block(_page(creator_client, event), "household-form", "form")


def test_post_household_updates_composition_and_logs(guest_client, db, event, guest):
    hh = _hh(db, event, guest)
    resp = _post(guest_client, event, name="Les Durand", num_adults="3", num_children="2")
    db.session.refresh(hh)
    assert (resp.status_code, hh.name, hh.num_adults, hh.num_children) == (302, "Les Durand", 3, 2)
    assert ActivityLog.query.filter_by(event_id=event.id, action="household.updated").count() == 1


def test_post_household_shows_success_toast(guest_client, db, event, guest):
    _hh(db, event, guest)
    _post(guest_client, event, name="Les Durand", num_adults="1", num_children="0")
    assert "Foyer enregistré." in _page(guest_client, event)


def test_post_household_creates_for_participant_without_household(guest_client, db, event, guest):
    resp = _post(guest_client, event, name="Les Neufs", num_adults="2", num_children="1")
    hh = Household.query.filter_by(event_id=event.id, guest_id=guest.id).one()
    assert (resp.status_code, hh.name, hh.total_people) == (302, "Les Neufs", 3)
    assert ActivityLog.query.filter_by(event_id=event.id, action="household.created").count() == 1


def test_post_household_creator_without_household_creates_one(
    creator_client, db, event, creator_guest
):
    _post(creator_client, event, name="Orga", num_adults="1", num_children="0")
    assert Household.query.filter_by(event_id=event.id, guest_id=creator_guest.id).count() == 1


def test_post_household_zero_adults_returns_field_error(guest_client, db, event, guest):
    hh = _hh(db, event, guest)
    resp = _post(guest_client, event, name="Les Durand", num_adults="0", num_children="0")
    html = resp.get_data(as_text=True)
    db.session.refresh(hh)
    assert (resp.status_code, "Adultes : entre 1 et 50." in html, hh.name) == (
        200,
        True,
        "Foyer Test",
    )


def test_post_household_short_name_returns_field_error(guest_client, event):
    resp = _post(guest_client, event, name="A", num_adults="1", num_children="0")
    assert (resp.status_code, "Nom du foyer requis" in resp.get_data(as_text=True)) == (200, True)


def test_post_household_negative_children_returns_field_error(guest_client, event):
    resp = _post(guest_client, event, name="Les Durand", num_adults="1", num_children="-1")
    assert "Enfants : entre 0 et 50." in resp.get_data(as_text=True)


def test_post_household_never_touches_another_participants_household(
    guest_client, db, event, guest, other_guest_c
):
    other = _hh(db, event, other_guest_c, name="Foyer Autre")
    _post(guest_client, event, name="Mien", num_adults="4", num_children="0")
    db.session.refresh(other)
    assert (other.name, other.num_adults) == ("Foyer Autre", 2)


def test_post_household_with_foreign_household_id_edit_route_is_403(
    guest_client, db, event, guest, other_guest_c
):
    other = _hh(db, event, other_guest_c)
    resp = guest_client.post(
        f"/e/{event.code}/costs/households/{other.id}/edit",
        data={"name": "Pirate", "num_adults": "1", "num_children": "0"},
    )
    assert resp.status_code == 403


def test_post_household_requires_participant(client, event):
    assert _post(client, event, name="X Y", num_adults="1", num_children="0").status_code in (
        302,
        401,
        403,
        404,
    )


def test_post_household_changes_cost_shares(guest_client, db, event, guest, other_guest_c):
    mine = _hh(db, event, guest, adults=1)
    other = _hh(db, event, other_guest_c, name="Foyer Autre", adults=1)
    exp = Expense(
        description="Courses",
        amount_cents=3000,
        paid_by_household_id=other.id,
        event_id=event.id,
        is_shared=True,
    )
    db.session.add(exp)
    db.session.commit()
    hs = [mine, other]
    before = _per_expense_shares(hs, [exp])[0][mine.id]
    _post(guest_client, event, name=mine.name, num_adults="1", num_children="2")
    db.session.refresh(mine)
    after = _per_expense_shares(hs, [exp])[0][mine.id]
    assert (before, after) == (1500, 2000)


def test_costs_page_links_to_my_household_from_balance_card(guest_client, db, event, guest):
    _hh(db, event, guest)
    href = tag(_page(guest_client, event, "costs"), "my-household-edit")
    assert f"/e/{event.code}/me#h-household" in href


def test_costs_page_without_household_links_to_creation(guest_client, event):
    assert "#h-household" in tag(_page(guest_client, event, "costs"), "my-household-create")


def test_members_page_links_household_on_own_row_only(
    guest_client, db, event, guest, other_guest_c
):
    html = _page(guest_client, event, "members")
    assert html.count('data-testid="my-household-link"') == 1
