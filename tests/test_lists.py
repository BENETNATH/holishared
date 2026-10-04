"""Tests for lists blueprint — B004.

19 tests, déterministes, un comportement = un test.
Ces tests DOIVENT échouer avant le codage (TDD).
"""

import pytest

from app.models import ActivityLog, ListItem, SharedList

# === Fixtures locales (complètent conftest.py) ===


@pytest.fixture
def shared_list(db, event):
    """Une liste partagée sur l'événement."""
    sl = SharedList(title="Shopping", list_type="shopping", event_id=event.id)
    db.session.add(sl)
    db.session.commit()
    return sl


@pytest.fixture
def list_item(db, shared_list):
    """Un article dans la liste."""
    item = ListItem(
        name="Milk",
        quantity="2",
        section="Dairy",
        assigned_to="Test Guest",
        list_id=shared_list.id,
    )
    db.session.add(item)
    db.session.commit()
    return item


def _login_creator(client, creator):
    """Helper : simule le login du créateur."""
    with client.session_transaction() as sess:
        sess["_user_id"] = creator.id
        sess["_fresh"] = True


def _login_guest(client, event, guest):
    """Helper : simule la session d'un guest."""
    with client.session_transaction() as sess:
        sess[f"guest_{event.code}"] = guest.id


# === TestListsIndex (4 tests) ===


class TestListsIndex:
    def test_index_renders_for_creator(self, client, creator, event, shared_list):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/lists")
        assert resp.status_code == 200
        assert b"Shopping" in resp.data

    def test_index_renders_for_guest(self, client, event, guest, shared_list):
        _login_guest(client, event, guest)
        resp = client.get(f"/e/{event.code}/lists")
        assert resp.status_code == 200
        assert b"Shopping" in resp.data

    def test_index_404_invalid_code(self, client, creator):
        _login_creator(client, creator)
        resp = client.get("/e/xxxxxx/lists")
        assert resp.status_code == 404

    def test_index_redirects_no_access(self, client, event):
        resp = client.get(f"/e/{event.code}/lists")
        assert resp.status_code == 302
        assert "/mycode" in resp.headers["Location"]


# === TestCreateList (3 tests) ===


class TestCreateList:
    def test_create_list_success(self, client, creator, event, db):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/lists/new", data={
            "title": "Buffet",
            "list_type": "buffet",
        })
        assert resp.status_code == 302
        sl = SharedList.query.filter_by(title="Buffet").first()
        assert sl is not None
        assert sl.list_type == "buffet"
        assert sl.event_id == event.id

    def test_create_list_missing_title(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/lists/new", data={
            "title": "",
            "list_type": "general",
        })
        assert resp.status_code == 200
        assert b"Titre requis" in resp.data

    def test_create_list_logs(self, client, creator, event, db):
        _login_creator(client, creator)
        client.post(f"/e/{event.code}/lists/new", data={
            "title": "Logged List",
            "list_type": "packing",
        })
        log = ActivityLog.query.filter_by(
            event_id=event.id, action="list.created"
        ).first()
        assert log is not None
        assert log.target == "Logged List"
        assert log.actor_type == "creator"


# === TestListDetail (1 test) ===


class TestListDetail:
    def test_detail_shows_items(self, client, creator, event, shared_list, list_item):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/lists/{shared_list.id}")
        assert resp.status_code == 200
        assert b"Milk" in resp.data
        assert b"Dairy" in resp.data


# === TestAddItem (3 tests) ===


class TestAddItem:
    def test_add_item_success(self, client, creator, event, shared_list, db):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/lists/{shared_list.id}/items", data={
            "name": "Bread",
            "quantity": "3",
            "section": "Bakery",
            "assigned_to": "Test Guest",
        })
        assert resp.status_code == 302
        item = ListItem.query.filter_by(name="Bread").first()
        assert item is not None
        assert item.quantity == "3"
        assert item.section == "Bakery"
        assert item.assigned_to == "Test Guest"
        assert item.list_id == shared_list.id

    def test_add_item_missing_name(self, client, creator, event, shared_list):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/lists/{shared_list.id}/items", data={
            "name": "",
        })
        assert resp.status_code == 200
        assert b"Nom requis" in resp.data

    def test_add_item_logs(self, client, creator, event, shared_list, db):
        _login_creator(client, creator)
        client.post(f"/e/{event.code}/lists/{shared_list.id}/items", data={
            "name": "Logged Item",
        })
        log = ActivityLog.query.filter_by(
            event_id=event.id, action="list_item.created"
        ).first()
        assert log is not None
        assert log.target == "Logged Item"
        assert log.actor_type == "creator"


# === TestToggleItem (2 tests) ===


class TestToggleItem:
    def test_toggle_item(self, client, creator, event, shared_list, list_item, db):
        _login_creator(client, creator)
        assert list_item.is_done is False
        resp = client.post(
            f"/e/{event.code}/lists/{shared_list.id}/items/{list_item.id}/toggle"
        )
        assert resp.status_code == 302
        db.session.refresh(list_item)
        assert list_item.is_done is True

    def test_toggle_item_logs(self, client, creator, event, shared_list, list_item, db):
        _login_creator(client, creator)
        client.post(f"/e/{event.code}/lists/{shared_list.id}/items/{list_item.id}/toggle")
        log = ActivityLog.query.filter_by(
            event_id=event.id, action="list_item.toggled"
        ).first()
        assert log is not None
        assert log.target == "Milk"
        assert log.details == "done"


# === TestDeleteItem (2 tests) ===


class TestDeleteItem:
    def test_delete_item(self, client, creator, event, shared_list, list_item, db):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/lists/{shared_list.id}/items/{list_item.id}/delete"
        )
        assert resp.status_code == 302
        assert ListItem.query.get(list_item.id) is None

    def test_delete_item_logs(self, client, creator, event, shared_list, list_item, db):
        _login_creator(client, creator)
        client.post(f"/e/{event.code}/lists/{shared_list.id}/items/{list_item.id}/delete")
        log = ActivityLog.query.filter_by(
            event_id=event.id, action="list_item.deleted"
        ).first()
        assert log is not None
        assert log.target == "Milk"


# === TestDeleteList (4 tests) ===


class TestDeleteList:
    def test_delete_list_as_creator(self, client, creator, event, shared_list, db):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/lists/{shared_list.id}/delete")
        assert resp.status_code == 302
        assert SharedList.query.get(shared_list.id) is None

    def test_delete_list_forbidden_for_guest(self, client, event, guest, shared_list):
        _login_guest(client, event, guest)
        resp = client.post(f"/e/{event.code}/lists/{shared_list.id}/delete")
        assert resp.status_code == 403

    def test_delete_list_cascades_items(self, client, creator, event, shared_list, list_item, db):
        _login_creator(client, creator)
        assert ListItem.query.get(list_item.id) is not None
        client.post(f"/e/{event.code}/lists/{shared_list.id}/delete")
        assert ListItem.query.get(list_item.id) is None

    def test_delete_list_logs(self, client, creator, event, shared_list, db):
        _login_creator(client, creator)
        client.post(f"/e/{event.code}/lists/{shared_list.id}/delete")
        log = ActivityLog.query.filter_by(
            event_id=event.id, action="list.deleted"
        ).first()
        assert log is not None
        assert log.target == "Shopping"
        assert log.actor_type == "creator"


# === TestClaim (auto-attribution, to-do list) ===


class TestClaim:
    def test_guest_claims_item(self, client, event, guest, shared_list, db):
        item = ListItem(name="Tâche", list_id=shared_list.id)
        db.session.add(item)
        db.session.commit()
        _login_guest(client, event, guest)
        resp = client.post(
            f"/e/{event.code}/lists/{shared_list.id}/items/{item.id}/claim"
        )
        assert resp.status_code == 302
        db.session.refresh(item)
        assert item.assigned_to == guest.display_name

    def test_claim_creates_log(self, client, event, guest, shared_list, db):
        item = ListItem(name="Tâche log", list_id=shared_list.id)
        db.session.add(item)
        db.session.commit()
        _login_guest(client, event, guest)
        client.post(f"/e/{event.code}/lists/{shared_list.id}/items/{item.id}/claim")
        log = ActivityLog.query.filter_by(
            event_id=event.id, action="list_item.claimed"
        ).first()
        assert log is not None
        assert log.actor_type == "guest"

    def test_assignee_can_unclaim(self, client, event, guest, shared_list, db):
        item = ListItem(name="Tâche", assigned_to=guest.display_name, list_id=shared_list.id)
        db.session.add(item)
        db.session.commit()
        _login_guest(client, event, guest)
        resp = client.post(
            f"/e/{event.code}/lists/{shared_list.id}/items/{item.id}/unclaim"
        )
        assert resp.status_code == 302
        db.session.refresh(item)
        assert item.assigned_to == ""

    def test_unclaim_forbidden_for_other_guest(self, client, event, guest, shared_list, db):
        other = "Autre"
        item = ListItem(name="Tâche", assigned_to=other, list_id=shared_list.id)
        db.session.add(item)
        db.session.commit()
        _login_guest(client, event, guest)
        resp = client.post(
            f"/e/{event.code}/lists/{shared_list.id}/items/{item.id}/unclaim"
        )
        assert resp.status_code == 403
        db.session.refresh(item)
        assert item.assigned_to == other

    def test_creator_can_unclaim_any(self, client, creator, event, shared_list, db):
        item = ListItem(name="Tâche", assigned_to="Quelqu'un", list_id=shared_list.id)
        db.session.add(item)
        db.session.commit()
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/lists/{shared_list.id}/items/{item.id}/unclaim"
        )
        assert resp.status_code == 302
        db.session.refresh(item)
        assert item.assigned_to == ""
