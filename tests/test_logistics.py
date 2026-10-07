"""Tests for logistics blueprint — B005.

Infos pratiques : liste groupée par catégorie, création, édition et
suppression (créateur uniquement pour edit/delete).
"""

import pytest

from app.models import ActivityLog, LogisticsItem


def _login_creator(client, creator):
    """Helper : simule le login du créateur."""
    with client.session_transaction() as sess:
        sess["_user_id"] = creator.id
        sess["_fresh"] = True


def _login_guest(client, event, guest):
    """Helper : simule la session d'un guest."""
    with client.session_transaction() as sess:
        sess[f"guest_{event.code}"] = guest.id


@pytest.fixture
def logistics_item(db, event):
    """Une info pratique dans l'événement."""
    item = LogisticsItem(
        title="Adresse du gîte",
        content="12 rue des Vignes, 67000 Strasbourg",
        category="address",
        order=0,
        event_id=event.id,
    )
    db.session.add(item)
    db.session.commit()
    return item


# === TestLogisticsIndex ===


class TestLogisticsIndex:
    def test_index_renders_for_creator(self, client, creator, event, logistics_item):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/logistics")
        assert resp.status_code == 200
        assert "Adresse du gîte".encode() in resp.data

    def test_index_renders_for_guest(self, client, event, guest, logistics_item):
        _login_guest(client, event, guest)
        resp = client.get(f"/e/{event.code}/logistics")
        assert resp.status_code == 200
        assert "Adresse du gîte".encode() in resp.data

    def test_index_404_invalid_code(self, client, creator):
        _login_creator(client, creator)
        resp = client.get("/e/xxxxxx/logistics")
        assert resp.status_code == 404

    def test_index_redirects_no_access(self, client, event):
        resp = client.get(f"/e/{event.code}/logistics")
        assert resp.status_code == 302
        assert "/mycode" in resp.headers["Location"]

    def test_index_groups_by_category(self, client, creator, event, db):
        _login_creator(client, creator)
        db.session.add_all(
            [
                LogisticsItem(
                    title="Item Access", content="c", category="access", order=0, event_id=event.id
                ),
                LogisticsItem(
                    title="Item Address",
                    content="c",
                    category="address",
                    order=0,
                    event_id=event.id,
                ),
            ]
        )
        db.session.commit()
        resp = client.get(f"/e/{event.code}/logistics")
        data = resp.data
        # B025b : ordre logique du registre (adresse avant accès), plus l'ordre alphabétique des clés
        assert data.index(b"Item Address") < data.index(b"Item Access")
        # En-têtes de sections par catégorie
        assert "Accès / Parking".encode() in data
        assert b"Adresse" in data

    def test_index_sorts_by_order_within_category(self, client, creator, event, db):
        _login_creator(client, creator)
        db.session.add_all(
            [
                LogisticsItem(
                    title="Second", content="c", category="notes", order=2, event_id=event.id
                ),
                LogisticsItem(
                    title="First", content="c", category="notes", order=1, event_id=event.id
                ),
            ]
        )
        db.session.commit()
        resp = client.get(f"/e/{event.code}/logistics")
        data = resp.data
        assert data.index(b"First") < data.index(b"Second")

    def test_index_shows_empty_message(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/logistics")
        assert b"Aucune info pratique" in resp.data

    def test_index_shows_edit_for_guest_delete_only_for_creator(self, client, event, guest, logistics_item):
        _login_guest(client, event, guest)
        resp = client.get(f"/e/{event.code}/logistics")
        assert resp.status_code == 200
        # Collaboratif : le guest peut éditer, mais pas supprimer
        assert f"/logistics/{logistics_item.id}/edit".encode() in resp.data
        assert f"/logistics/{logistics_item.id}/delete".encode() not in resp.data


# === TestCreateLogistics ===


class TestCreateLogistics:
    def test_create_get_renders_form(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/logistics/new")
        assert resp.status_code == 200
        assert b'name="title"' in resp.data
        assert b'name="content"' in resp.data
        assert b'name="category"' in resp.data
        assert b'name="order"' not in resp.data  # B025b : champ retiré de l'interface

    def test_create_success(self, client, creator, event, db):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/logistics/new",
            data={
                "title": "Parking",
                "content": "Parking gratuit derrière la maison",
                "category": "access",
                "order": "3",
            },
        )
        assert resp.status_code == 302
        assert f"/e/{event.code}/logistics" in resp.headers["Location"]
        item = LogisticsItem.query.filter_by(title="Parking").first()
        assert item is not None
        assert item.content == "Parking gratuit derrière la maison"
        assert item.category == "access"
        assert item.order == 0  # B025b : l'ordre posté est ignoré
        assert item.event_id == event.id

    def test_create_success_as_guest(self, client, event, guest, db):
        _login_guest(client, event, guest)
        resp = client.post(
            f"/e/{event.code}/logistics/new",
            data={"title": "Horaires repas", "content": "Déjeuner 12h30", "category": "timing"},
        )
        assert resp.status_code == 302
        item = LogisticsItem.query.filter_by(title="Horaires repas").first()
        assert item is not None
        assert item.category == "timing"
        assert item.order == 0

    def test_create_default_category_general(self, client, creator, event, db):
        _login_creator(client, creator)
        client.post(
            f"/e/{event.code}/logistics/new",
            data={"title": "Sans catégorie", "content": "x"},
        )
        item = LogisticsItem.query.filter_by(title="Sans catégorie").first()
        assert item is not None
        assert item.category == "general"

    def test_create_missing_title(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/logistics/new",
            data={"title": "", "content": "Contenu"},
        )
        assert resp.status_code == 200
        assert b"Titre requis" in resp.data
        assert LogisticsItem.query.count() == 0

    def test_create_title_too_short(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/logistics/new",
            data={"title": "A", "content": "Contenu"},
        )
        assert resp.status_code == 200
        assert b"Titre requis" in resp.data

    def test_create_missing_content(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/logistics/new",
            data={"title": "Titre valide", "content": ""},
        )
        assert resp.status_code == 200
        assert b"Contenu requis" in resp.data
        assert LogisticsItem.query.count() == 0

    def test_create_content_too_long(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/logistics/new",
            data={"title": "Titre valide", "content": "x" * 5001},
        )
        assert resp.status_code == 200
        assert b"Contenu trop long" in resp.data

    def test_create_invalid_category(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/logistics/new",
            data={"title": "Titre valide", "content": "x", "category": "hacked"},
        )
        assert resp.status_code == 200
        assert "Catégorie invalide".encode() in resp.data

    def test_create_non_numeric_order_is_ignored(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/logistics/new",
            data={"title": "Titre valide", "content": "x", "order": "abc"},
        )
        assert resp.status_code == 302  # B025b : le champ n'existe plus

    def test_create_logs(self, client, creator, event, db):
        _login_creator(client, creator)
        client.post(
            f"/e/{event.code}/logistics/new",
            data={"title": "Logged Info", "content": "x"},
        )
        log = ActivityLog.query.filter_by(event_id=event.id, action="logistics.created").first()
        assert log is not None
        assert log.target == "Logged Info"
        assert log.actor_type == "creator"

    def test_create_logs_as_guest(self, client, event, guest, db):
        _login_guest(client, event, guest)
        client.post(
            f"/e/{event.code}/logistics/new",
            data={"title": "Guest Info", "content": "x"},
        )
        log = ActivityLog.query.filter_by(event_id=event.id, action="logistics.created").first()
        assert log is not None
        assert log.actor_type == "guest"
        assert log.actor_name == "Test Guest"


# === TestEditLogistics ===


class TestEditLogistics:
    def test_edit_get_renders_prefilled(self, client, creator, event, logistics_item):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/logistics/{logistics_item.id}/edit")
        assert resp.status_code == 200
        assert "Adresse du gîte".encode() in resp.data
        assert b'name="category"' in resp.data

    def test_edit_as_creator(self, client, creator, event, logistics_item, db):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/logistics/{logistics_item.id}/edit",
            data={
                "title": "Adresse mise à jour",
                "content": "14 rue des Vignes",
                "category": "address",
                "order": "1",
            },
        )
        assert resp.status_code == 302
        db.session.refresh(logistics_item)
        assert logistics_item.title == "Adresse mise à jour"
        assert logistics_item.content == "14 rue des Vignes"
        assert logistics_item.order == 0  # B025b : l'ordre n'est plus modifiable

    def test_edit_allowed_for_guest(self, client, event, guest, logistics_item, db):
        _login_guest(client, event, guest)
        resp = client.post(
            f"/e/{event.code}/logistics/{logistics_item.id}/edit",
            data={"title": "Adresse corrigée", "content": "14 rue des Vignes", "category": "address"},
        )
        assert resp.status_code == 302
        db.session.refresh(logistics_item)
        assert logistics_item.title == "Adresse corrigée"

    def test_edit_404_invalid_id(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/logistics/invalid_id/edit",
            data={"title": "Test", "content": "x"},
        )
        assert resp.status_code == 404

    def test_edit_404_item_from_other_event(self, client, creator, db, logistics_item):
        """Un item d'un autre événement n'est pas modifiable via ce code."""
        from datetime import date, datetime

        from app.models import Event, generate_event_code

        other = Event(
            code=generate_event_code(),
            title="Other",
            start_date=date(2026, 12, 1),
            end_date=date(2026, 12, 2),
            creator_id=creator.id,
            verified_at=datetime.utcnow(),
        )
        db.session.add(other)
        db.session.commit()
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{other.code}/logistics/{logistics_item.id}/edit",
            data={"title": "Hacked", "content": "x"},
        )
        assert resp.status_code == 404

    def test_edit_logs(self, client, creator, event, logistics_item, db):
        _login_creator(client, creator)
        client.post(
            f"/e/{event.code}/logistics/{logistics_item.id}/edit",
            data={"title": "Logged Edit", "content": "x"},
        )
        log = ActivityLog.query.filter_by(event_id=event.id, action="logistics.updated").first()
        assert log is not None
        assert log.target == "Logged Edit"
        assert log.actor_type == "creator"


# === TestDeleteLogistics ===


class TestDeleteLogistics:
    def test_delete_as_creator(self, client, creator, event, logistics_item, db):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/logistics/{logistics_item.id}/delete")
        assert resp.status_code == 302
        assert f"/e/{event.code}/logistics" in resp.headers["Location"]
        assert LogisticsItem.query.get(logistics_item.id) is None

    def test_delete_forbidden_for_guest(self, client, event, guest, logistics_item):
        _login_guest(client, event, guest)
        resp = client.post(f"/e/{event.code}/logistics/{logistics_item.id}/delete")
        assert resp.status_code == 403
        assert LogisticsItem.query.get(logistics_item.id) is not None

    def test_delete_404_invalid_id(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/logistics/invalid_id/delete")
        assert resp.status_code == 404

    def test_delete_logs(self, client, creator, event, logistics_item, db):
        _login_creator(client, creator)
        client.post(f"/e/{event.code}/logistics/{logistics_item.id}/delete")
        log = ActivityLog.query.filter_by(event_id=event.id, action="logistics.deleted").first()
        assert log is not None
        assert log.target == "Adresse du gîte"
        assert log.actor_type == "creator"
