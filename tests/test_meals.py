"""Tests for the meals blueprint — grille de repas (module distinct de planning)."""

from datetime import date

import pytest

from app.models import Meal


@pytest.fixture
def meal(db, event):
    """Un repas dans la période de l'événement."""
    m = Meal(
        title="Roti de porc",
        date=date(2026, 12, 3),
        slot="lunch",
        event_id=event.id,
    )
    db.session.add(m)
    db.session.commit()
    return m


def _login_creator(client, creator):
    with client.session_transaction() as sess:
        sess["_user_id"] = creator.id
        sess["_fresh"] = True


def _login_guest(client, event, guest):
    with client.session_transaction() as sess:
        sess[f"guest_{event.code}"] = guest.id


class TestMealsIndex:
    def test_index_renders_for_creator(self, client, creator, event, meal):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/meals")
        assert resp.status_code == 200
        assert b"Roti de porc" in resp.data
        assert b"meal-card" in resp.data  # meal rendered as an elegant card
        assert b"meal-modal" in resp.data  # add/edit/delete modal present

    def test_today_row_highlighted(self, client, creator, event, db):
        _login_creator(client, creator)
        event.start_date = date.today()
        event.end_date = date.today()
        db.session.commit()
        resp = client.get(f"/e/{event.code}/meals")
        assert resp.status_code == 200
        assert b"is-today" in resp.data

    def test_index_requires_auth(self, client, event):
        resp = client.get(f"/e/{event.code}/meals")
        assert resp.status_code in (302, 401)

    def test_index_inactive_event_404(self, client, creator, event):
        _login_creator(client, creator)
        event.is_active = False
        from app.extensions import db as _db
        _db.session.commit()
        resp = client.get(f"/e/{event.code}/meals")
        assert resp.status_code == 404


class TestCreateMeal:
    def test_create_valid(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/meals/create",
            data={"title": "Poulet", "date": "2026-12-4", "slot": "dinner"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Poulet" in resp.data
        assert Meal.query.filter_by(event_id=event.id, date=date(2026, 12, 4), slot="dinner").first() is not None

    def test_create_short_title_rejected(self, client, creator, event):
        _login_creator(client, creator)
        client.post(
            f"/e/{event.code}/meals/create",
            data={"title": "a", "date": "2026-12-4", "slot": "dinner"},
            follow_redirects=True,
        )
        assert Meal.query.filter_by(event_id=event.id, date=date(2026, 12, 4), slot="dinner").first() is None

    def test_create_out_of_range_rejected(self, client, creator, event):
        _login_creator(client, creator)
        client.post(
            f"/e/{event.code}/meals/create",
            data={"title": "Pâtes", "date": "2026-11-01", "slot": "dinner"},
            follow_redirects=True,
        )
        assert Meal.query.filter_by(event_id=event.id, date=date(2026, 11, 1)).first() is None

    def test_create_occupied_cell_rejected(self, client, creator, event, meal):
        _login_creator(client, creator)
        client.post(
            f"/e/{event.code}/meals/create",
            data={"title": "Autre", "date": "2026-12-03", "slot": "lunch"},
            follow_redirects=True,
        )
        # The occupied cell keeps the original meal; no second meal created.
        assert Meal.query.filter_by(event_id=event.id, date=date(2026, 12, 3), slot="lunch").count() == 1


class TestEditMeal:
    def test_edit_valid(self, client, creator, event, meal):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/meals/{meal.id}/edit",
            data={"title": "Poulet rôti"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert meal.title == "Poulet rôti"

    def test_edit_forbidden_for_other_guest(self, client, event, guest, other_guest, meal):
        _login_guest(client, event, other_guest)
        client.post(
            f"/e/{event.code}/meals/{meal.id}/edit",
            data={"title": "Hack"},
            follow_redirects=True,
        )
        assert meal.title == "Roti de porc"


class TestDeleteMeal:
    def test_delete_valid(self, client, creator, event, meal):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/meals/{meal.id}/delete", follow_redirects=True)
        assert resp.status_code == 200
        assert Meal.query.get(meal.id) is None

    def test_delete_forbidden_for_other_guest(self, client, event, guest, other_guest, meal):
        _login_guest(client, event, other_guest)
        client.post(f"/e/{event.code}/meals/{meal.id}/delete", follow_redirects=True)
        assert Meal.query.get(meal.id) is not None


class TestMoveMeal:
    def test_move_to_empty_cell(self, client, creator, event, meal):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/meals/move",
            data={"meal_id": meal.id, "date": "2026-12-5", "slot": "dinner"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert meal.date == date(2026, 12, 5)
        assert meal.slot == "dinner"

    def test_move_swaps_when_occupied(self, client, creator, event, meal):
        _login_creator(client, creator)
        other = Meal(title="Soupe", date=date(2026, 12, 5), slot="dinner", event_id=event.id)
        from app.extensions import db as _db
        _db.session.add(other)
        _db.session.commit()

        client.post(
            f"/e/{event.code}/meals/move",
            data={"meal_id": meal.id, "date": "2026-12-05", "slot": "dinner"},
            follow_redirects=True,
        )
        # The two meals swapped their (date, slot).
        assert meal.date == date(2026, 12, 5)
        assert meal.slot == "dinner"
        assert other.date == date(2026, 12, 3)
        assert other.slot == "lunch"

    def test_move_forbidden_for_other_guest(self, client, event, guest, other_guest, meal):
        _login_guest(client, event, other_guest)
        client.post(
            f"/e/{event.code}/meals/move",
            data={"meal_id": meal.id, "date": "2026-12-5", "slot": "dinner"},
            follow_redirects=True,
        )
        assert meal.date == date(2026, 12, 3)


@pytest.fixture
def other_guest(db, event):
    from app.models import Guest, generate_guest_code
    g = Guest(code=generate_guest_code(), display_name="Other Guest", event_id=event.id)
    db.session.add(g)
    db.session.commit()
    return g
