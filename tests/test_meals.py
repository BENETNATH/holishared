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
        assert b'data-testid="meal-card"' in resp.data  # meal rendered as a card
        assert b'data-testid="meal-sheet"' in resp.data  # edit/delete sheet present

    def test_today_row_highlighted(self, client, creator, event, db):
        _login_creator(client, creator)
        event.start_date = date.today()
        event.end_date = date.today()
        db.session.commit()
        resp = client.get(f"/e/{event.code}/meals")
        assert resp.status_code == 200
        assert b'aria-current="date"' in resp.data

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
        assert (
            Meal.query.filter_by(event_id=event.id, date=date(2026, 12, 4), slot="dinner").first()
            is not None
        )

    def test_create_short_title_rejected(self, client, creator, event):
        _login_creator(client, creator)
        client.post(
            f"/e/{event.code}/meals/create",
            data={"title": "a", "date": "2026-12-4", "slot": "dinner"},
            follow_redirects=True,
        )
        assert (
            Meal.query.filter_by(event_id=event.id, date=date(2026, 12, 4), slot="dinner").first()
            is None
        )

    def test_create_out_of_range_rejected(self, client, creator, event):
        _login_creator(client, creator)
        client.post(
            f"/e/{event.code}/meals/create",
            data={"title": "Pâtes", "date": "2026-11-01", "slot": "dinner"},
            follow_redirects=True,
        )
        assert Meal.query.filter_by(event_id=event.id, date=date(2026, 11, 1)).first() is None

    def test_create_occupied_cell_adds_second_meal(self, client, creator, event, meal):
        _login_creator(client, creator)
        client.post(
            f"/e/{event.code}/meals/create",
            data={"title": "Autre", "date": "2026-12-03", "slot": "lunch"},
            follow_redirects=True,
        )
        # B022 : plusieurs repas par case ; le nouveau passe en fin de case.
        cell = Meal.query.filter_by(event_id=event.id, date=date(2026, 12, 3), slot="lunch")
        assert [m.title for m in cell.order_by(Meal.position)] == ["Roti de porc", "Autre"]


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

    def test_move_onto_occupied_cell_adds_without_swapping(self, client, creator, event, meal):
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
        # B022 : le dépôt sur une case occupée ajoute ; l'échange est l'action `swap`.
        assert (meal.date, meal.slot, meal.position) == (date(2026, 12, 5), "dinner", 1)
        assert (other.date, other.slot, other.position) == (date(2026, 12, 5), "dinner", 0)

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


HX = {"HX-Request": "true"}
D3, D4 = date(2026, 12, 3), date(2026, 12, 4)


def _add(db, event, title, day, slot, position=0, created_by=None):
    m = Meal(
        title=title,
        date=day,
        slot=slot,
        position=position,
        event_id=event.id,
        created_by=created_by,
    )
    db.session.add(m)
    db.session.commit()
    return m


def _cell_titles(event, day, slot):
    cell = Meal.query.filter_by(event_id=event.id, date=day, slot=slot)
    return [m.title for m in cell.order_by(Meal.position)]


def _post(client, event, path, **data):
    return client.post(f"/e/{event.code}/meals/{path}", data=data, headers=HX)


@pytest.fixture
def cell3(db, event):
    """Trois repas dans la case 3 déc. midi, positions 0..2."""
    return [_add(db, event, t, D3, "lunch", i) for i, t in enumerate(("A1", "B2", "C3"))]


class TestCapacity:
    def test_create_beyond_six_is_rejected_with_message(self, creator_client, event, db):
        for i in range(6):
            _add(db, event, f"Repas {i}", D3, "lunch", i)
        resp = _post(
            creator_client, event, "create", title="Septième", date="2026-12-03", slot="lunch"
        )
        assert resp.status_code == 422
        assert Meal.query.filter_by(event_id=event.id, date=D3, slot="lunch").count() == 6
        assert "6" in resp.headers["HX-Trigger"]

    def test_move_into_full_cell_is_rejected(self, creator_client, event, db, cell3):
        for i in range(6):
            _add(db, event, f"Plein {i}", D4, "dinner", i)
        resp = _post(
            creator_client, event, "move", meal_id=cell3[0].id, date="2026-12-04", slot="dinner"
        )
        assert resp.status_code == 422
        assert cell3[0].date == D3

    def test_reorder_inside_full_cell_is_allowed(self, creator_client, event, db):
        full = [_add(db, event, f"R{i}", D3, "lunch", i) for i in range(6)]
        resp = _post(
            creator_client,
            event,
            "move",
            meal_id=full[5].id,
            date="2026-12-03",
            slot="lunch",
            before_id=full[0].id,
        )
        assert resp.status_code == 200
        assert _cell_titles(event, D3, "lunch")[0] == "R5"


class TestCreateHtmx:
    def test_create_returns_grid_fragment_with_trigger(self, creator_client, event):
        resp = _post(
            creator_client, event, "create", title="Poulet", date="2026-12-04", slot="dinner"
        )
        assert resp.status_code == 200
        assert b'data-testid="meal-grid"' in resp.data
        assert b"Poulet" in resp.data
        assert b"<html" not in resp.data  # fragment, pas la page entière
        assert "meals:message" in resp.headers["HX-Trigger"]

    def test_create_without_htmx_redirects(self, creator_client, event):
        resp = creator_client.post(
            f"/e/{event.code}/meals/create",
            data={"title": "Poulet", "date": "2026-12-04", "slot": "dinner"},
        )
        assert resp.status_code == 302

    @pytest.mark.parametrize(
        "data",
        [
            {"title": "x", "date": "2026-12-04", "slot": "dinner"},
            {"title": "Poulet", "date": "2026-11-01", "slot": "dinner"},
            {"title": "Poulet", "date": "2026-12-04", "slot": "brunch"},
            {"title": "Poulet", "date": "nope", "slot": "dinner"},
        ],
    )
    def test_create_invalid_returns_422_and_creates_nothing(self, creator_client, event, data):
        resp = _post(creator_client, event, "create", **data)
        assert resp.status_code == 422
        assert Meal.query.filter_by(event_id=event.id).count() == 0

    def test_create_position_is_end_of_cell(self, creator_client, event, cell3):
        _post(creator_client, event, "create", title="D4", date="2026-12-03", slot="lunch")
        assert _cell_titles(event, D3, "lunch") == ["A1", "B2", "C3", "D4"]

    def test_create_logs_activity(self, creator_client, event):
        from app.models import ActivityLog

        _post(creator_client, event, "create", title="Poulet", date="2026-12-04", slot="dinner")
        assert ActivityLog.query.filter_by(event_id=event.id, action="meal.created").count() == 1


class TestMoveReorder:
    def test_move_keeps_id_and_appends_to_end(self, creator_client, event, cell3, db):
        mover = _add(db, event, "Z", D4, "dinner", 0)
        mover_id = mover.id
        _post(creator_client, event, "move", meal_id=mover_id, date="2026-12-03", slot="lunch")
        assert _cell_titles(event, D3, "lunch") == ["A1", "B2", "C3", "Z"]
        assert Meal.query.get(mover_id).title == "Z"

    def test_move_before_card_inserts_there_and_renumbers(self, creator_client, event, cell3, db):
        mover = _add(db, event, "Z", D4, "dinner", 0)
        _post(
            creator_client,
            event,
            "move",
            meal_id=mover.id,
            date="2026-12-03",
            slot="lunch",
            before_id=cell3[1].id,
        )
        assert _cell_titles(event, D3, "lunch") == ["A1", "Z", "B2", "C3"]
        assert [m.position for m in Meal.query.filter_by(date=D3).order_by(Meal.position)] == [
            0,
            1,
            2,
            3,
        ]

    def test_move_renumbers_source_cell(self, creator_client, event, cell3):
        _post(creator_client, event, "move", meal_id=cell3[0].id, date="2026-12-04", slot="dinner")
        assert _cell_titles(event, D3, "lunch") == ["B2", "C3"]
        assert [m.position for m in Meal.query.filter_by(date=D3).order_by(Meal.position)] == [0, 1]

    def test_reorder_same_cell_before(self, creator_client, event, cell3):
        _post(
            creator_client,
            event,
            "move",
            meal_id=cell3[2].id,
            date="2026-12-03",
            slot="lunch",
            before_id=cell3[0].id,
        )
        assert _cell_titles(event, D3, "lunch") == ["C3", "A1", "B2"]

    def test_same_cell_without_before_moves_to_end(self, creator_client, event, cell3):
        resp = _post(
            creator_client, event, "move", meal_id=cell3[0].id, date="2026-12-03", slot="lunch"
        )
        assert resp.status_code == 200
        assert _cell_titles(event, D3, "lunch") == ["B2", "C3", "A1"]

    def test_unknown_before_id_appends(self, creator_client, event, cell3):
        _post(
            creator_client,
            event,
            "move",
            meal_id=cell3[0].id,
            date="2026-12-04",
            slot="dinner",
            before_id="nope",
        )
        assert _cell_titles(event, D4, "dinner") == ["A1"]

    def test_move_out_of_period_rejected(self, creator_client, event, cell3):
        resp = _post(
            creator_client, event, "move", meal_id=cell3[0].id, date="2026-12-09", slot="lunch"
        )
        assert resp.status_code == 422
        assert cell3[0].date == D3

    def test_move_invalid_slot_rejected(self, creator_client, event, cell3):
        resp = _post(
            creator_client, event, "move", meal_id=cell3[0].id, date="2026-12-04", slot="tmp"
        )
        assert resp.status_code == 422
        assert cell3[0].slot == "lunch"

    def test_move_htmx_returns_fragment(self, creator_client, event, cell3):
        resp = _post(
            creator_client, event, "move", meal_id=cell3[0].id, date="2026-12-04", slot="dinner"
        )
        assert b'data-testid="meal-grid"' in resp.data

    def test_move_logs_activity(self, creator_client, event, cell3):
        from app.models import ActivityLog

        _post(creator_client, event, "move", meal_id=cell3[0].id, date="2026-12-04", slot="dinner")
        assert ActivityLog.query.filter_by(event_id=event.id, action="meal.moved").count() == 1


class TestSwap:
    def test_swap_exchanges_cells_and_positions_keeping_ids(self, creator_client, event, cell3, db):
        other = _add(db, event, "Soupe", D4, "dinner", 0)
        ids = (cell3[1].id, other.id)
        resp = _post(creator_client, event, "swap", meal_id=cell3[1].id, other_id=other.id)
        assert resp.status_code == 200
        first, second = (Meal.query.get(i) for i in ids)
        assert (first.date, first.slot, first.position) == (D4, "dinner", 0)
        assert (second.date, second.slot, second.position) == (D3, "lunch", 1)

    def test_swap_with_itself_rejected(self, creator_client, event, cell3):
        resp = _post(creator_client, event, "swap", meal_id=cell3[0].id, other_id=cell3[0].id)
        assert resp.status_code == 422

    def test_swap_unknown_other_is_404(self, creator_client, event, cell3):
        assert (
            _post(creator_client, event, "swap", meal_id=cell3[0].id, other_id="nope").status_code
            == 404
        )

    def test_swap_requires_rights_on_both_meals(self, guest_client, event, guest, db):
        mine = _add(db, event, "Mien", D3, "lunch", 0, created_by=guest.id)
        theirs = _add(db, event, "Autre", D4, "dinner", 0)
        assert (
            _post(guest_client, event, "swap", meal_id=mine.id, other_id=theirs.id).status_code
            == 403
        )
        assert (mine.date, mine.slot) == (D3, "lunch")

    def test_swap_logs_activity(self, creator_client, event, cell3):
        from app.models import ActivityLog

        _post(creator_client, event, "swap", meal_id=cell3[0].id, other_id=cell3[1].id)
        assert ActivityLog.query.filter_by(event_id=event.id, action="meal.swapped").count() == 1


class TestRights:
    def test_author_guest_can_move_edit_delete_own_meal(self, guest_client, event, guest, db):
        mine = _add(db, event, "Mien", D3, "lunch", 0, created_by=guest.id)
        assert (
            _post(
                guest_client, event, "move", meal_id=mine.id, date="2026-12-04", slot="dinner"
            ).status_code
            == 200
        )
        assert _post(guest_client, event, f"{mine.id}/edit", title="Nouveau").status_code == 200
        assert _post(guest_client, event, f"{mine.id}/delete").status_code == 200
        assert Meal.query.get(mine.id) is None

    def test_other_guest_cannot_act_on_someone_elses_meal(
        self, guest_client, event, other_guest_c, db
    ):
        theirs = _add(db, event, "Autre", D3, "lunch", 0, created_by=other_guest_c.id)
        assert (
            _post(
                guest_client, event, "move", meal_id=theirs.id, date="2026-12-04", slot="dinner"
            ).status_code
            == 403
        )
        assert _post(guest_client, event, f"{theirs.id}/edit", title="Hack").status_code == 403
        assert _post(guest_client, event, f"{theirs.id}/delete").status_code == 403
        assert (theirs.title, theirs.date) == ("Autre", D3)

    def test_creator_can_act_on_any_meal(self, creator_client, event, other_guest_c, db):
        theirs = _add(db, event, "Autre", D3, "lunch", 0, created_by=other_guest_c.id)
        assert (
            _post(
                creator_client, event, "move", meal_id=theirs.id, date="2026-12-04", slot="dinner"
            ).status_code
            == 200
        )

    def test_foreign_event_meal_is_404(self, creator_client, event, db):
        from datetime import datetime

        from app.models import Creator, Event

        stranger = Creator(email="s@test.com", email_verified=True, display_name="S")
        db.session.add(stranger)
        db.session.flush()
        foreign = Event(
            code="foreign1", title="F", start_date=D3, end_date=D4,
            creator_id=stranger.id, verified_at=datetime.utcnow(),
        )  # fmt: skip
        db.session.add(foreign)
        db.session.flush()
        meal = _add(db, foreign, "Etranger", D3, "lunch", 0)
        assert (
            _post(
                creator_client, event, "move", meal_id=meal.id, date="2026-12-04", slot="dinner"
            ).status_code
            == 404
        )
        assert _post(creator_client, event, f"{meal.id}/delete").status_code == 404

    def test_delete_renumbers_cell(self, creator_client, event, cell3):
        _post(creator_client, event, f"{cell3[0].id}/delete")
        assert [m.position for m in Meal.query.filter_by(date=D3).order_by(Meal.position)] == [0, 1]


class TestConsumers:
    def test_dashboard_lists_every_meal_of_today_in_slot_then_position_order(
        self, creator_client, event, db
    ):
        event.start_date = event.end_date = date.today()
        _add(db, event, "Soir-1", date.today(), "dinner", 0)
        _add(db, event, "Midi-2", date.today(), "lunch", 1)
        _add(db, event, "Midi-1", date.today(), "lunch", 0)
        html = creator_client.get(f"/e/{event.code}").get_data(as_text=True)
        assert html.index("Midi-1") < html.index("Midi-2") < html.index("Soir-1")

    def test_list_chips_show_every_meal_in_order(self, creator_client, event, db):
        from app.models import SharedList

        shared = SharedList(title="Courses", event_id=event.id)
        db.session.add(shared)
        _add(db, event, "Soir-1", D3, "dinner", 0)
        _add(db, event, "Midi-2", D3, "lunch", 1)
        _add(db, event, "Midi-1", D3, "lunch", 0)
        db.session.commit()
        html = creator_client.get(f"/e/{event.code}/lists/{shared.id}").get_data(as_text=True)
        assert html.index("Midi-1") < html.index("Midi-2") < html.index("Soir-1")


class TestGridRender:
    def test_cell_label_and_every_card_rendered(self, creator_client, event, cell3):
        html = creator_client.get(f"/e/{event.code}/meals").get_data(as_text=True)
        assert html.count('data-testid="meal-card"') == 3
        assert "3 repas" in html  # libellé accessible de la case
        assert html.count('data-testid="meal-add"') == 14  # 7 jours x 2 créneaux

    def test_read_only_card_for_non_author(self, guest_client, event, other_guest_c, db):
        _add(db, event, "Autre", D3, "lunch", 0, created_by=other_guest_c.id)
        html = guest_client.get(f"/e/{event.code}/meals").get_data(as_text=True)
        assert 'data-editable="0"' in html
        assert "data-meal-handle" not in html

    def test_full_cell_disables_add_button(self, creator_client, event, db):
        for i in range(6):
            _add(db, event, f"R{i}", D3, "lunch", i)
        html = creator_client.get(f"/e/{event.code}/meals").get_data(as_text=True)
        import re

        def add_button(day, slot):
            pattern = rf'<button[^>]*data-meal-add[^>]*data-date="{day}" data-slot="{slot}"[^>]*>'
            return re.search(pattern, html).group(0)

        assert " disabled" in add_button("2026-12-03", "lunch")
        assert " disabled" not in add_button("2026-12-03", "dinner")
