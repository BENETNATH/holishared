"""Panneau « Repas & activités » et couverture des listes (B023, contrat §11.5.3)."""

import re
from datetime import date, time, timedelta

import pytest
from tests.ui_helpers import block, tag

from app.models import (
    Activity,
    ActivityLog,
    ListActivityCoverage,
    ListMealCoverage,
    Meal,
    SharedList,
)

HX = {"HX-Request": "true", "HX-Target": "list-panel-content"}
D1, D2 = date(2099, 12, 3), date(2099, 12, 4)


@pytest.fixture
def shopping(db, event):
    lst = SharedList(title="Courses", event_id=event.id)
    db.session.add(lst)
    db.session.commit()
    return lst


def _meal(db, event, title, day=D1, slot="lunch", position=0):
    meal = Meal(title=title, date=day, slot=slot, position=position, event_id=event.id)
    db.session.add(meal)
    db.session.commit()
    return meal


def _act(db, event, title, day=D1, start=None):
    act = Activity(title=title, date=day, start_time=start, event_id=event.id)
    db.session.add(act)
    db.session.commit()
    return act


def _base(event, lst):
    return f"/e/{event.code}/lists/{lst.id}"


def _page(client, event, lst):
    return client.get(_base(event, lst)).data.decode()


def _panel(client, event, lst, **params):
    return client.get(f"{_base(event, lst)}/panel", query_string=params).data.decode()


def _rows(html):
    return re.findall(r'data-testid="panel-row" data-kind="(\w+)" data-id="(\w+)"', html)


def _titles(html):
    return re.findall(r'<span class="break-words">([^<]+)</span>', html)


# --- Bouton et panneau : jamais imposés ---------------------------------------------------


def test_detail_without_meals_nor_activities_has_no_panel_button(guest_client, event, shopping):
    assert 'data-testid="list-panel-toggle"' not in _page(guest_client, event, shopping)


def test_detail_without_meals_nor_activities_has_no_panel(guest_client, event, shopping):
    assert 'data-testid="list-panel"' not in _page(guest_client, event, shopping)


def test_detail_with_a_meal_shows_the_panel_button(db, guest_client, event, shopping):
    _meal(db, event, "Pâtes")
    assert 'data-testid="list-panel-toggle"' in _page(guest_client, event, shopping)


def test_detail_with_only_an_activity_shows_the_panel_button(db, guest_client, event, shopping):
    _act(db, event, "Rando")
    assert 'data-testid="list-panel-toggle"' in _page(guest_client, event, shopping)


def test_detail_panel_starts_closed(db, guest_client, event, shopping):
    _meal(db, event, "Pâtes")
    assert 'data-panel="closed"' in _page(guest_client, event, shopping)


def test_panel_button_declares_the_controlled_panel_and_collapsed_state(
    db, guest_client, event, shopping
):
    _meal(db, event, "Pâtes")
    opening = tag(_page(guest_client, event, shopping), "list-panel-toggle")
    assert 'aria-controls="list-panel"' in opening
    assert 'aria-expanded="false"' in opening


def test_panel_is_not_modal(db, guest_client, event, shopping):
    _meal(db, event, "Pâtes")
    assert "aria-modal" not in tag(_page(guest_client, event, shopping), "list-panel")


def test_list_items_do_not_require_any_coverage(db, guest_client, event, shopping):
    resp = guest_client.post(f"{_base(event, shopping)}/items", data={"name": "Pain"})
    assert resp.status_code == 302


def test_counter_is_hidden_when_the_list_covers_nothing(db, guest_client, event, shopping):
    _meal(db, event, "Pâtes")
    assert " hidden" in tag(_page(guest_client, event, shopping), "list-panel-count")


def test_counter_shows_covered_over_total(db, guest_client, event, guest, shopping):
    meal = _meal(db, event, "Pâtes")
    _meal(db, event, "Soupe", slot="dinner")
    _act(db, event, "Rando")
    db.session.add(ListMealCoverage(list_id=shopping.id, meal_id=meal.id))
    db.session.commit()
    html = _page(guest_client, event, shopping)
    assert (
        re.sub(r"<[^>]+>|&nbsp;", " ", block(html, "list-panel-count", "span")).split()[0] == "1/3"
    )


# --- Contenu : regroupement par jour, ordre chronologique ---------------------------------


def test_panel_groups_rows_by_day_in_date_order(db, guest_client, event, shopping):
    _meal(db, event, "Tard", day=D2)
    _meal(db, event, "Tôt", day=D1)
    html = _panel(guest_client, event, shopping)
    assert re.findall(r'data-testid="panel-day" data-date="([\d-]+)"', html) == [
        D1.isoformat(),
        D2.isoformat(),
    ]


def test_panel_orders_meals_lunch_before_dinner_then_position(db, guest_client, event, shopping):
    _meal(db, event, "Dîner", slot="dinner")
    _meal(db, event, "Midi B", position=1)
    _meal(db, event, "Midi A", position=0)
    assert _titles(_panel(guest_client, event, shopping)) == ["Midi A", "Midi B", "Dîner"]


def test_panel_interleaves_activities_by_time_between_meals(db, guest_client, event, shopping):
    _meal(db, event, "Déjeuner", slot="lunch")
    _meal(db, event, "Dîner", slot="dinner")
    _act(db, event, "Rando", start=time(9, 0))
    _act(db, event, "Cinéma", start=time(21, 0))
    assert _titles(_panel(guest_client, event, shopping)) == [
        "Rando",
        "Déjeuner",
        "Dîner",
        "Cinéma",
    ]


def test_panel_puts_activity_without_time_after_the_meals_of_the_day(
    db, guest_client, event, shopping
):
    _act(db, event, "Libre")
    _meal(db, event, "Dîner", slot="dinner")
    assert _titles(_panel(guest_client, event, shopping)) == ["Dîner", "Libre"]


def test_panel_row_label_has_full_day_slot_and_title(db, guest_client, event, shopping):
    _meal(db, event, "Pâtes")
    html = _panel(guest_client, event, shopping)
    assert 'aria-label="jeudi 3 décembre, Midi : Pâtes"' in tag(
        block(html, "panel-row", "li"), "panel-check"
    )


def test_panel_activity_row_shows_start_time(db, guest_client, event, shopping):
    _act(db, event, "Rando", start=time(9, 30))
    assert "09:30" in block(_panel(guest_client, event, shopping), "panel-row", "li")


def test_panel_future_day_is_expanded(db, guest_client, event, shopping):
    _meal(db, event, "Pâtes")
    assert " open" in tag(_panel(guest_client, event, shopping), "panel-day")


def test_panel_past_day_is_collapsed(db, guest_client, event, shopping):
    _meal(db, event, "Hier", day=date.today() - timedelta(days=3))
    assert " open" not in tag(_panel(guest_client, event, shopping), "panel-day")


def test_panel_today_is_highlighted(db, guest_client, event, shopping):
    _meal(db, event, "Aujourd'hui", day=date.today())
    assert 'data-today="true"' in tag(_panel(guest_client, event, shopping), "panel-day")


def test_panel_row_checkbox_reflects_coverage(db, guest_client, event, shopping):
    meal = _meal(db, event, "Pâtes")
    db.session.add(ListMealCoverage(list_id=shopping.id, meal_id=meal.id))
    db.session.commit()
    assert " checked" in tag(_panel(guest_client, event, shopping), "panel-check")


# --- Filtres ---------------------------------------------------------------------------


def test_panel_mode_meals_lists_only_meals(db, guest_client, event, shopping):
    _meal(db, event, "Pâtes")
    _act(db, event, "Rando")
    assert {kind for kind, _id in _rows(_panel(guest_client, event, shopping, mode="meals"))} == {
        "meal"
    }


def test_panel_mode_activities_lists_only_activities(db, guest_client, event, shopping):
    _meal(db, event, "Pâtes")
    _act(db, event, "Rando")
    assert {
        kind for kind, _id in _rows(_panel(guest_client, event, shopping, mode="activities"))
    } == {"activity"}


def test_panel_mode_all_lists_meals_and_activities(db, guest_client, event, shopping):
    _meal(db, event, "Pâtes")
    _act(db, event, "Rando")
    assert {kind for kind, _id in _rows(_panel(guest_client, event, shopping, mode="all"))} == {
        "meal",
        "activity",
    }


def test_panel_unknown_mode_falls_back_to_all(db, guest_client, event, shopping):
    _meal(db, event, "Pâtes")
    _act(db, event, "Rando")
    assert len(_rows(_panel(guest_client, event, shopping, mode="bogus"))) == 2


def test_panel_hide_covered_removes_covered_rows(db, guest_client, event, shopping):
    meal = _meal(db, event, "Pâtes")
    _meal(db, event, "Soupe", slot="dinner")
    db.session.add(ListMealCoverage(list_id=shopping.id, meal_id=meal.id))
    db.session.commit()
    assert _titles(_panel(guest_client, event, shopping, hide="1")) == ["Soupe"]


def test_panel_hide_covered_keeps_the_counter_total(db, guest_client, event, shopping):
    meal = _meal(db, event, "Pâtes")
    db.session.add(ListMealCoverage(list_id=shopping.id, meal_id=meal.id))
    db.session.commit()
    assert "1/1" in block(_panel(guest_client, event, shopping, hide="1"), "panel-summary", "p")


def test_panel_hide_covered_drops_days_left_empty(db, guest_client, event, shopping):
    meal = _meal(db, event, "Pâtes", day=D1)
    _meal(db, event, "Soupe", day=D2)
    db.session.add(ListMealCoverage(list_id=shopping.id, meal_id=meal.id))
    db.session.commit()
    html = _panel(guest_client, event, shopping, hide="1")
    assert re.findall(r'data-date="([\d-]+)"', html) == [D2.isoformat()]


def test_panel_hide_checkbox_is_checked_when_filter_is_on(db, guest_client, event, shopping):
    _meal(db, event, "Pâtes")
    assert " checked" in tag(_panel(guest_client, event, shopping, hide="1"), "panel-hide-covered")


def test_panel_meals_mode_is_disabled_when_meals_module_is_off(app_factory):
    app = app_factory({"ENABLED_MODULES": "planning,lists"})
    assert "meals" not in app.blueprints


def test_panel_mode_buttons_are_disabled_for_inactive_modules(app_factory):
    from app.extensions import db
    from app.models import Creator, Event, Guest, generate_event_code

    app = app_factory({"ENABLED_MODULES": "planning,lists"})
    creator = Creator(email="c@t.com", email_verified=True)
    db.session.add(creator)
    db.session.flush()
    event = Event(
        code=generate_event_code(),
        title="T",
        start_date=D1,
        end_date=D2,
        creator_id=creator.id,
        verified_at=date.today(),
    )
    db.session.add(event)
    db.session.flush()
    guest = Guest(code="g1234567", display_name="G", event_id=event.id)
    shopping = SharedList(title="L", event_id=event.id)
    db.session.add_all(
        [
            guest,
            shopping,
            Meal(title="Pâtes", date=D1, slot="lunch", event_id=event.id),
            Activity(title="Rando", date=D1, event_id=event.id),
        ]
    )
    db.session.commit()
    client = app.test_client()
    with client.session_transaction() as s:
        s[f"guest_{event.code}"] = guest.id
    html = client.get(f"/e/{event.code}/lists/{shopping.id}/panel").data.decode()
    assert (
        " disabled" in tag(html, "panel-mode-meals"),
        "meal" in {k for k, _i in _rows(html)},
    ) == (True, False)


# --- Cocher (HTMX) ----------------------------------------------------------------------


def _toggle(client, event, lst, kind, target, **data):
    segment = "meals" if kind == "meal" else "activities"
    return client.post(f"{_base(event, lst)}/{segment}/{target.id}/toggle", data=data, headers=HX)


def test_toggle_meal_creates_the_coverage_row(db, guest_client, event, shopping):
    meal = _meal(db, event, "Pâtes")
    _toggle(guest_client, event, shopping, "meal", meal)
    assert ListMealCoverage.query.filter_by(list_id=shopping.id, meal_id=meal.id).count() == 1


def test_toggle_meal_twice_removes_the_coverage_row(db, guest_client, event, shopping):
    meal = _meal(db, event, "Pâtes")
    _toggle(guest_client, event, shopping, "meal", meal)
    _toggle(guest_client, event, shopping, "meal", meal)
    assert ListMealCoverage.query.count() == 0


def test_toggle_meal_records_who_covered_it(db, guest_client, event, guest, shopping):
    meal = _meal(db, event, "Pâtes")
    _toggle(guest_client, event, shopping, "meal", meal)
    assert ListMealCoverage.query.one().covered_by == guest.id


def test_toggle_meal_with_explicit_covered_is_idempotent(db, guest_client, event, shopping):
    meal = _meal(db, event, "Pâtes")
    _toggle(guest_client, event, shopping, "meal", meal, covered="1")
    _toggle(guest_client, event, shopping, "meal", meal, covered="1")
    assert ListMealCoverage.query.count() == 1


def test_toggle_meal_uncovering_an_uncovered_meal_is_a_noop(db, guest_client, event, shopping):
    meal = _meal(db, event, "Pâtes")
    resp = _toggle(guest_client, event, shopping, "meal", meal, covered="0")
    assert (resp.status_code, ListMealCoverage.query.count()) == (200, 0)


def test_toggle_activity_creates_and_removes_the_coverage_row(db, guest_client, event, shopping):
    act = _act(db, event, "Rando")
    _toggle(guest_client, event, shopping, "activity", act)
    assert (
        ListActivityCoverage.query.filter_by(list_id=shopping.id, activity_id=act.id).count() == 1
    )


def test_toggle_activity_twice_removes_the_coverage_row(db, guest_client, event, shopping):
    act = _act(db, event, "Rando")
    _toggle(guest_client, event, shopping, "activity", act)
    _toggle(guest_client, event, shopping, "activity", act)
    assert ListActivityCoverage.query.count() == 0


def test_toggle_htmx_returns_the_panel_fragment(db, guest_client, event, shopping):
    meal = _meal(db, event, "Pâtes")
    resp = _toggle(guest_client, event, shopping, "meal", meal)
    assert resp.data.decode().lstrip().startswith('<div id="list-panel-content"')


def test_toggle_htmx_fragment_contains_the_updated_panel(db, guest_client, event, shopping):
    meal = _meal(db, event, "Pâtes")
    html = _toggle(guest_client, event, shopping, "meal", meal).data.decode()
    assert 'id="list-panel-content"' in html
    assert " checked" in tag(html, "panel-check")


def test_toggle_htmx_fragment_updates_counter_out_of_band(db, guest_client, event, shopping):
    meal = _meal(db, event, "Pâtes")
    html = _toggle(guest_client, event, shopping, "meal", meal).data.decode()
    assert 'hx-swap-oob="true"' in tag(html, "list-panel-count")
    assert "1/1" in html


def test_toggle_htmx_keeps_mode_and_filter_of_the_panel(db, guest_client, event, shopping):
    meal = _meal(db, event, "Pâtes")
    _act(db, event, "Rando")
    html = _toggle(
        guest_client, event, shopping, "meal", meal, mode="meals", hide="0"
    ).data.decode()
    assert 'data-mode="meals"' in html


def test_toggle_without_htmx_redirects_to_the_list(db, guest_client, event, shopping):
    meal = _meal(db, event, "Pâtes")
    resp = guest_client.post(f"{_base(event, shopping)}/meals/{meal.id}/toggle")
    assert resp.headers["Location"].endswith(f"/lists/{shopping.id}")


def test_toggle_meal_logs_covered_action(db, guest_client, event, shopping):
    meal = _meal(db, event, "Pâtes")
    _toggle(guest_client, event, shopping, "meal", meal)
    assert ActivityLog.query.filter_by(action="list.meal_covered", target="Pâtes").count() == 1


def test_toggle_meal_logs_uncovered_action(db, guest_client, event, shopping):
    meal = _meal(db, event, "Pâtes")
    _toggle(guest_client, event, shopping, "meal", meal)
    _toggle(guest_client, event, shopping, "meal", meal)
    assert ActivityLog.query.filter_by(action="list.meal_uncovered").count() == 1


def test_toggle_activity_logs_covered_action(db, guest_client, event, shopping):
    act = _act(db, event, "Rando")
    _toggle(guest_client, event, shopping, "activity", act)
    assert ActivityLog.query.filter_by(action="list.activity_covered").count() == 1


def test_toggle_idempotent_repeat_does_not_log_twice(db, guest_client, event, shopping):
    meal = _meal(db, event, "Pâtes")
    _toggle(guest_client, event, shopping, "meal", meal, covered="1")
    _toggle(guest_client, event, shopping, "meal", meal, covered="1")
    assert ActivityLog.query.filter_by(action="list.meal_covered").count() == 1


def test_coverage_is_shared_between_participants(
    db, guest_client, client, event, other_guest_c, shopping
):
    meal = _meal(db, event, "Pâtes")
    _toggle(guest_client, event, shopping, "meal", meal)
    with client.session_transaction() as s:
        s[f"guest_{event.code}"] = other_guest_c.id
    assert " checked" in tag(_panel(client, event, shopping), "panel-check")


def test_toggle_meal_of_another_event_is_404(
    db, creator, event, unverified_event, guest_client, shopping
):
    foreign = Meal(title="Autre", date=D1, slot="lunch", event_id=unverified_event.id)
    db.session.add(foreign)
    db.session.commit()
    assert _toggle(guest_client, event, shopping, "meal", foreign).status_code == 404


def test_toggle_meal_by_visitor_is_refused(db, client, event, shopping):
    meal = _meal(db, event, "Pâtes")
    resp = client.post(f"{_base(event, shopping)}/meals/{meal.id}/toggle")
    assert resp.status_code == 302
    assert ListMealCoverage.query.count() == 0


def test_toggle_meal_is_404_when_meals_module_is_off(app_factory):
    from app.extensions import db
    from app.models import Creator, Event, Guest, generate_event_code

    app = app_factory({"ENABLED_MODULES": "planning,lists"})
    creator = Creator(email="c@t.com", email_verified=True)
    db.session.add(creator)
    db.session.flush()
    event = Event(
        code=generate_event_code(),
        title="T",
        start_date=D1,
        end_date=D2,
        creator_id=creator.id,
        verified_at=date.today(),
    )
    db.session.add(event)
    db.session.flush()
    guest = Guest(code="g1234567", display_name="G", event_id=event.id)
    shopping = SharedList(title="L", event_id=event.id)
    meal = Meal(title="Pâtes", date=D1, slot="lunch", event_id=event.id)
    db.session.add_all([guest, shopping, meal])
    db.session.commit()
    client = app.test_client()
    with client.session_transaction() as s:
        s[f"guest_{event.code}"] = guest.id
    assert (
        client.post(f"/e/{event.code}/lists/{shopping.id}/meals/{meal.id}/toggle").status_code
        == 404
    )


# --- Sens unique : rien côté Repas / Planning ----------------------------------------------


def test_meals_page_shows_no_list_coverage_status(db, guest_client, event, shopping):
    meal = _meal(db, event, "Pâtes")
    db.session.add(ListMealCoverage(list_id=shopping.id, meal_id=meal.id))
    db.session.commit()
    html = guest_client.get(f"/e/{event.code}/meals").data.decode()
    assert "pris en compte" not in html


def test_planning_page_shows_no_list_coverage_status(db, guest_client, event, shopping):
    act = _act(db, event, "Rando")
    db.session.add(ListActivityCoverage(list_id=shopping.id, activity_id=act.id))
    db.session.commit()
    html = guest_client.get(f"/e/{event.code}/planning").data.decode()
    assert "pris en compte" not in html


# --- Accueil : badge « Courses notées » = union des couvertures ----------------------------


def _timeline_badges(html):
    return re.findall(r'data-testid="(timeline-[\w-]*)"', html)


def test_dashboard_marks_meal_covered_by_any_list_through_new_tables(
    db, guest_client, event, shopping
):
    meal = _meal(db, event, "Pâtes", day=date.today())
    other = SharedList(title="Autre", event_id=event.id)
    db.session.add(other)
    db.session.flush()
    db.session.add(ListMealCoverage(list_id=other.id, meal_id=meal.id))
    db.session.commit()
    html = guest_client.get(f"/e/{event.code}").data.decode()
    assert "Courses notées" in html
    assert "À lister" not in html


def test_dashboard_marks_meal_without_coverage_as_to_list(db, guest_client, event, shopping):
    _meal(db, event, "Pâtes", day=date.today())
    html = guest_client.get(f"/e/{event.code}").data.decode()
    assert "À lister" in html
    assert "Courses notées" not in html


def test_dashboard_ignores_coverage_of_another_event(
    db, guest_client, event, unverified_event, shopping
):
    meal = _meal(db, event, "Pâtes", day=date.today())
    foreign_list = SharedList(title="Autre événement", event_id=unverified_event.id)
    db.session.add(foreign_list)
    db.session.flush()
    db.session.add(ListMealCoverage(list_id=foreign_list.id, meal_id=meal.id))
    db.session.commit()
    assert "À lister" in guest_client.get(f"/e/{event.code}").data.decode()
