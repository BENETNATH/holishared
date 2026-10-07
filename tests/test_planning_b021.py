"""B021 — Planning : programme par jour, carte d'activité, RSVP HTMX, feuille et formulaire."""

import re
from datetime import date, time, timedelta

import pytest
from sqlalchemy import event as sa_event
from tests.ui_helpers import block, tag, text_of

from app.extensions import db as _db
from app.models import Activity, ActivityRSVP, Guest, Meal, generate_guest_code

HX = {"HX-Request": "true"}


def _count(html: str, testid: str) -> int:
    return len(re.findall(rf'data-testid="{re.escape(testid)}"', html))


def _act(db, event, title="Rando", day=date(2026, 12, 3), start=None, **kw):
    a = Activity(title=title, date=day, start_time=start, event_id=event.id, **kw)
    db.session.add(a)
    db.session.commit()
    return a


def _rsvp(db, act, guest, status):
    db.session.add(ActivityRSVP(activity_id=act.id, guest_id=guest.id, status=status))
    db.session.commit()


def _guest(db, event, name):
    g = Guest(code=generate_guest_code(), display_name=name, event_id=event.id)
    db.session.add(g)
    db.session.commit()
    return g


def _page(client, event, query=""):
    return client.get(f"/e/{event.code}/planning{query}").get_data(as_text=True)


def _card(html: str, act) -> str:
    return re.search(rf'<li id="activity-{act.id}".*?</li>\s*(?=<li|</ul>)', html, re.S).group(0)


# --- Vue par jour ---------------------------------------------------------


def test_index_with_one_activity_lists_every_event_day(creator_client, event, db):
    _act(db, event)
    assert _count(_page(creator_client, event), "planning-day") == 7


def test_index_empty_day_shows_empty_message(creator_client, event):
    assert _count(_page(creator_client, event), "day-empty") == 7


def test_index_orders_activities_of_a_day_by_start_time(creator_client, event, db):
    _act(db, event, "Tard", start=time(18, 0))
    _act(db, event, "Tot", start=time(9, 0))
    html = _page(creator_client, event)
    assert html.index("Tot") < html.index("Tard")


def test_index_activity_without_time_shows_journee(creator_client, event, db):
    act = _act(db, event, "Plage")
    assert text_of(_card(_page(creator_client, event), act), "activity-time", "p") == "Journée"


def test_index_activity_time_range_shows_start_and_end(creator_client, event, db):
    act = _act(db, event, "Plage", start=time(9, 0), end_time=time(11, 30))
    assert "09:00" in text_of(_card(_page(creator_client, event), act), "activity-time", "p")


def test_index_selected_day_follows_day_param(creator_client, event):
    html = _page(creator_client, event, "?day=2026-12-04")
    assert 'data-selected-day="2026-12-04"' in tag(html, "program")


def test_index_selected_day_outside_event_falls_back_to_first_day(creator_client, event):
    html = _page(creator_client, event, "?day=2030-01-01")
    assert 'data-selected-day="2026-12-01"' in tag(html, "program")


@pytest.fixture
def ongoing_event(db, event):
    event.start_date = date.today() - timedelta(days=1)
    event.end_date = date.today() + timedelta(days=2)
    db.session.commit()
    return event


def test_index_marks_today_tab_with_aria_current(creator_client, ongoing_event):
    html = _page(creator_client, ongoing_event)
    assert len(re.findall(r'data-testid="planning-day-tab"[^>]*aria-current="date"', html)) == 1


def test_index_today_button_targets_today_when_inside_event(creator_client, ongoing_event):
    html = _page(creator_client, ongoing_event)
    assert f'data-planning-today="{date.today().isoformat()}"' in tag(html, "planning-today")


def test_index_today_button_absent_when_today_outside_event(creator_client, event):
    assert _count(_page(creator_client, event), "planning-today") == 0


def test_index_selects_today_by_default_when_inside_event(creator_client, ongoing_event):
    html = _page(creator_client, ongoing_event)
    assert f'data-selected-day="{date.today().isoformat()}"' in tag(html, "program")


def test_index_shows_meals_of_the_day_read_only(creator_client, event, db):
    meal = Meal(title="Barbecue", date=date(2026, 12, 2), slot="dinner", event_id=event.id)
    db.session.add(meal)
    db.session.commit()
    html = _page(creator_client, event)
    assert "Soir" in text_of(html, "program-meal", "li")
    assert "Barbecue" in html


def test_index_meal_has_no_edit_control(creator_client, event, db):
    meal = Meal(title="Barbecue", date=date(2026, 12, 2), slot="dinner", event_id=event.id)
    db.session.add(meal)
    db.session.commit()
    assert f"/meals/{meal.id}" not in _page(creator_client, event)


def test_index_links_to_meals_page_when_module_active(creator_client, event, db):
    db.session.add(Meal(title="Pizza", date=date(2026, 12, 2), slot="lunch", event_id=event.id))
    db.session.commit()
    assert f'href="/e/{event.code}/meals"' in tag(_page(creator_client, event), "meals-link")


def test_index_hides_meals_link_when_module_disabled(app_factory):
    from datetime import datetime

    from app.models import Creator, Event, generate_event_code

    app = app_factory({"ENABLED_MODULES": "planning"})
    c = Creator(email="x@t.com", email_verified=True, display_name="X")
    _db.session.add(c)
    _db.session.commit()
    e = Event(
        code=generate_event_code(),
        title="V",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 3),
        creator_id=c.id,
        verified_at=datetime.utcnow(),
    )
    _db.session.add(e)
    _db.session.commit()
    _db.session.add(Meal(title="Pizza", date=date(2026, 12, 2), slot="lunch", event_id=e.id))
    _db.session.commit()
    client = app.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = c.id
        s["_fresh"] = True
    html = client.get(f"/e/{e.code}/planning").get_data(as_text=True)
    assert "Pizza" in html
    assert _count(html, "meals-link") == 0


def test_index_shows_each_activity_once(guest_client, event, db):
    _act(db, event, "Piscine")
    assert _page(guest_client, event).count("Piscine") == 1


def test_index_has_no_separate_rsvp_section(guest_client, event, db):
    _act(db, event)
    assert "Indiquez votre participation" not in _page(guest_client, event)


# --- Carte : contenu ------------------------------------------------------


def test_card_shows_bring_items(creator_client, event, db):
    act = _act(db, event, bring_items="2 chaises")
    assert "2 chaises" in text_of(_card(_page(creator_client, event), act), "activity-bring", "p")


def test_card_without_bring_items_has_no_bring_block(creator_client, event, db):
    act = _act(db, event)
    assert _count(_card(_page(creator_client, event), act), "activity-bring") == 0


def test_card_long_description_offers_voir_plus(creator_client, event, db):
    act = _act(db, event, description="mot " * 100)
    assert "Voir plus" in _card(_page(creator_client, event), act)


def test_card_short_description_has_no_voir_plus(creator_client, event, db):
    act = _act(db, event, description="Court")
    assert "Voir plus" not in _card(_page(creator_client, event), act)


def test_card_shows_location(creator_client, event, db):
    act = _act(db, event, location="Lac Blanc")
    assert "Lac Blanc" in _card(_page(creator_client, event), act)


def test_card_shows_author_display_name(guest_client, event, guest, db):
    act = _act(db, event, created_by=guest.id)
    assert "Test Guest" in text_of(_card(_page(guest_client, event), act), "activity-author", "p")


# --- Carte : décompte, seuil, participants --------------------------------


def test_card_count_shows_yes_and_maybe(creator_client, event, guest, other_guest_c, db):
    act = _act(db, event)
    _rsvp(db, act, guest, "yes")
    _rsvp(db, act, other_guest_c, "maybe")
    assert (
        text_of(_card(_page(creator_client, event), act), "rsvp-count", "p")
        == "1 oui · 1 peut-être"
    )


def test_card_count_without_answers_says_so(creator_client, event, db):
    act = _act(db, event)
    assert "Aucune réponse" in text_of(_card(_page(creator_client, event), act), "rsvp-count", "p")


def test_card_threshold_reached_shows_badge(creator_client, event, guest, other_guest_c, db):
    act = _act(db, event, min_headcount=2)
    _rsvp(db, act, guest, "yes")
    _rsvp(db, act, other_guest_c, "yes")
    assert text_of(_card(_page(creator_client, event), act), "threshold", "span") == "Seuil atteint"


def test_card_threshold_missing_shows_remaining_count(creator_client, event, guest, db):
    act = _act(db, event, min_headcount=3)
    _rsvp(db, act, guest, "yes")
    assert (
        text_of(_card(_page(creator_client, event), act), "threshold", "span")
        == "Il manque 2 participants"
    )


def test_card_threshold_missing_one_is_singular(creator_client, event, guest, db):
    act = _act(db, event, min_headcount=2)
    _rsvp(db, act, guest, "yes")
    assert (
        text_of(_card(_page(creator_client, event), act), "threshold", "span")
        == "Il manque 1 participant"
    )


def test_card_threshold_without_answers_shows_full_gap(creator_client, event, db):
    act = _act(db, event, min_headcount=2)
    assert (
        text_of(_card(_page(creator_client, event), act), "threshold", "span")
        == "Il manque 2 participants"
    )


def test_card_maybe_does_not_count_toward_threshold(creator_client, event, guest, db):
    act = _act(db, event, min_headcount=2)
    _rsvp(db, act, guest, "maybe")
    assert 'data-reached="false"' in tag(_card(_page(creator_client, event), act), "threshold")


def test_card_default_threshold_of_one_shows_no_badge(creator_client, event, db):
    act = _act(db, event)
    assert _count(_card(_page(creator_client, event), act), "threshold") == 0


def test_card_participants_list_names_by_answer(creator_client, event, guest, db):
    act = _act(db, event)
    _rsvp(db, act, guest, "yes")
    assert (
        text_of(_card(_page(creator_client, event), act), "rsvp-names-yes", "div")
        == "Oui : Test Guest"
    )


def test_card_participants_list_never_shows_emails(creator_client, event, guest, db):
    act = _act(db, event)
    _rsvp(db, act, guest, "yes")
    assert "@" not in text_of(
        _card(_page(creator_client, event), act), "rsvp-participants", "details"
    )


def test_card_inactive_guest_is_not_counted(creator_client, event, guest, db):
    act = _act(db, event)
    _rsvp(db, act, guest, "yes")
    guest.is_active = False
    db.session.commit()
    assert "Aucune réponse" in text_of(_card(_page(creator_client, event), act), "rsvp-count", "p")


def test_card_marks_my_answer_as_pressed(guest_client, event, guest, db):
    act = _act(db, event)
    _rsvp(db, act, guest, "maybe")
    assert 'aria-pressed="true"' in tag(_card(_page(guest_client, event), act), "rsvp-maybe")


def test_card_other_answers_are_not_pressed(guest_client, event, guest, db):
    act = _act(db, event)
    _rsvp(db, act, guest, "maybe")
    assert 'aria-pressed="false"' in tag(_card(_page(guest_client, event), act), "rsvp-yes")


def test_card_my_answer_button_posts_none_to_withdraw(guest_client, event, guest, db):
    act = _act(db, event)
    _rsvp(db, act, guest, "yes")
    assert 'value="none"' in tag(_card(_page(guest_client, event), act), "rsvp-yes")


# --- RSVP : écriture ------------------------------------------------------


def _answer(client, event, act, status, headers=None):
    return client.post(
        f"/e/{event.code}/planning/{act.id}/rsvp", data={"status": status}, headers=headers or {}
    )


def test_rsvp_creates_answer_for_guest(guest_client, event, guest, db):
    act = _act(db, event)
    _answer(guest_client, event, act, "yes")
    assert ActivityRSVP.query.filter_by(activity_id=act.id, guest_id=guest.id).one().status == "yes"


def test_rsvp_changes_existing_answer_without_duplicate(guest_client, event, guest, db):
    act = _act(db, event)
    _answer(guest_client, event, act, "yes")
    _answer(guest_client, event, act, "no")
    assert [r.status for r in ActivityRSVP.query.filter_by(activity_id=act.id)] == ["no"]


def test_rsvp_none_removes_answer(guest_client, event, guest, db):
    act = _act(db, event)
    _rsvp(db, act, guest, "yes")
    _answer(guest_client, event, act, "none")
    assert ActivityRSVP.query.filter_by(activity_id=act.id).count() == 0


def test_rsvp_none_without_answer_is_harmless(guest_client, event, db):
    act = _act(db, event)
    assert _answer(guest_client, event, act, "none").status_code == 302


def test_rsvp_creator_can_answer(creator_client, event, db):
    act = _act(db, event)
    html = _answer(creator_client, event, act, "yes", HX).get_data(as_text=True)
    assert 'aria-pressed="true"' in tag(html, "rsvp-yes")


def test_rsvp_creator_answer_is_counted(creator_client, event, db):
    act = _act(db, event)
    _answer(creator_client, event, act, "yes")
    assert "1 oui" in text_of(_card(_page(creator_client, event), act), "rsvp-count", "p")


def test_rsvp_unknown_status_is_rejected(guest_client, event, guest, db):
    act = _act(db, event)
    _answer(guest_client, event, act, "peut-etre")
    assert ActivityRSVP.query.count() == 0


def test_rsvp_of_another_event_activity_is_404(guest_client, event, db, creator):
    from datetime import datetime

    from app.models import Event, generate_event_code

    other = Event(
        code=generate_event_code(),
        title="O",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 2),
        creator_id=creator.id,
        verified_at=datetime.utcnow(),
    )
    db.session.add(other)
    db.session.commit()
    foreign = _act(db, other, day=date(2026, 12, 1))
    assert _answer(guest_client, event, foreign, "yes").status_code == 404


# --- HTMX ----------------------------------------------------------------


def test_rsvp_htmx_returns_card_fragment(guest_client, event, db):
    act = _act(db, event, "Piscine")
    html = _answer(guest_client, event, act, "yes", HX).get_data(as_text=True)
    assert html.lstrip().startswith(f'<li id="activity-{act.id}"')


def test_rsvp_htmx_fragment_has_no_page_shell(guest_client, event, db):
    act = _act(db, event)
    assert "<html" not in _answer(guest_client, event, act, "yes", HX).get_data(as_text=True)


def test_rsvp_htmx_fragment_shows_updated_count(guest_client, event, db):
    act = _act(db, event)
    html = _answer(guest_client, event, act, "yes", HX).get_data(as_text=True)
    assert text_of(html, "rsvp-count", "p") == "1 oui · 0 peut-être"


def test_rsvp_without_htmx_redirects_to_program(guest_client, event, db):
    act = _act(db, event)
    resp = _answer(guest_client, event, act, "yes")
    assert (resp.status_code, resp.headers["Location"]) == (302, f"/e/{event.code}/planning")


def test_rsvp_htmx_unknown_status_returns_422(guest_client, event, db):
    act = _act(db, event)
    assert _answer(guest_client, event, act, "zzz", HX).status_code == 422


def test_rsvp_form_targets_its_own_card(guest_client, event, db):
    act = _act(db, event)
    form = tag(_card(_page(guest_client, event), act), "rsvp-form")
    assert f'hx-target="#activity-{act.id}"' in form


# --- Droits --------------------------------------------------------------


def test_card_menu_shown_to_author(guest_client, event, guest, db):
    act = _act(db, event, created_by=guest.id)
    assert _count(_card(_page(guest_client, event), act), "activity-menu") == 1


def test_card_menu_shown_to_creator_on_guest_activity(creator_client, event, guest, db):
    act = _act(db, event, created_by=guest.id)
    assert _count(_card(_page(creator_client, event), act), "activity-menu") == 1


def test_card_menu_hidden_from_other_guest(guest_client, event, other_guest_c, db):
    act = _act(db, event, created_by=other_guest_c.id)
    assert _count(_card(_page(guest_client, event), act), "activity-menu") == 0


def test_card_delete_requires_confirmation(guest_client, event, guest, db):
    act = _act(db, event, created_by=guest.id)
    assert "data-confirm=" in tag(_card(_page(guest_client, event), act), "activity-delete-form")


def test_edit_forbidden_for_other_guest(guest_client, event, other_guest_c, db):
    act = _act(db, event, created_by=other_guest_c.id)
    resp = guest_client.post(
        f"/e/{event.code}/planning/{act.id}/edit", data={"title": "Piraté", "date": "2026-12-02"}
    )
    assert resp.status_code == 403


def test_delete_forbidden_for_other_guest(guest_client, event, other_guest_c, db):
    act = _act(db, event, created_by=other_guest_c.id)
    assert guest_client.post(f"/e/{event.code}/planning/{act.id}/delete").status_code == 403


def test_edit_allowed_for_creator_on_guest_activity(creator_client, event, guest, db):
    act = _act(db, event, created_by=guest.id)
    resp = creator_client.post(
        f"/e/{event.code}/planning/{act.id}/edit", data={"title": "Corrigé", "date": "2026-12-03"}
    )
    assert resp.status_code == 302


# --- Feuille d'ajout et formulaire ---------------------------------------


def test_index_has_one_primary_add_button(guest_client, event):
    assert (
        _page(guest_client, event).count("ui-btn--primary") == 2
    )  # bouton de page + envoi de la feuille


def test_index_add_button_links_to_full_form(guest_client, event):
    assert f'href="/e/{event.code}/planning/new?date=2026-12-01"' in tag(
        _page(guest_client, event), "planning-add"
    )


def test_index_sheet_defaults_date_to_selected_day(guest_client, event):
    html = _page(guest_client, event, "?day=2026-12-04")
    assert 'value="2026-12-04"' in re.search(r'<input[^>]*id="sheet-date"[^>]*>', html).group(0)


def test_index_sheet_date_is_bounded_by_event(guest_client, event):
    tagged = re.search(r'<input[^>]*id="sheet-date"[^>]*>', _page(guest_client, event)).group(0)
    assert 'min="2026-12-01"' in tagged
    assert 'max="2026-12-07"' in tagged


def test_index_sheet_keeps_extra_fields_under_more_options(guest_client, event):
    html = _page(guest_client, event)
    more = block(html, "activity-more-options", "details")
    assert all(
        f'name="{n}"' in more
        for n in ("end_time", "location", "description", "min_headcount", "bring_items")
    )


def test_index_sheet_essentials_are_outside_more_options(guest_client, event):
    more = block(_page(guest_client, event), "activity-more-options", "details")
    assert 'name="title"' not in more


def test_index_edit_link_carries_prefill_data(guest_client, event, guest, db):
    act = _act(db, event, "Rando", created_by=guest.id, location="Lac")
    assert "&#34;" not in tag(_card(_page(guest_client, event), act), "activity-edit")
    assert '"location": "Lac"' in tag(_card(_page(guest_client, event), act), "activity-edit")


def test_sheet_submit_creates_activity_and_redirects(guest_client, event, db):
    resp = guest_client.post(
        f"/e/{event.code}/planning/new",
        data={
            "title": "Pique-nique",
            "date": "2026-12-02",
            "start_time": "12:00",
            "min_headcount": "1",
        },
    )
    assert resp.status_code == 302
    assert Activity.query.filter_by(title="Pique-nique").count() == 1


def test_form_page_has_sections_and_single_primary_button(guest_client, event):
    html = guest_client.get(f"/e/{event.code}/planning/new").get_data(as_text=True)
    assert ("L'essentiel" in html, "Détails" in html, html.count("ui-btn--primary")) == (
        True,
        True,
        1,
    )


def test_form_page_defaults_date_from_query(guest_client, event):
    html = guest_client.get(f"/e/{event.code}/planning/new?date=2026-12-05").get_data(as_text=True)
    assert 'value="2026-12-05"' in re.search(r'<input[^>]*id="f-date"[^>]*>', html).group(0)


def test_form_page_ignores_default_date_outside_event(guest_client, event):
    html = guest_client.get(f"/e/{event.code}/planning/new?date=2030-01-01").get_data(as_text=True)
    assert 'value="2026-12-01"' in re.search(r'<input[^>]*id="f-date"[^>]*>', html).group(0)


def test_form_page_labels_headcount_clearly(guest_client, event):
    html = guest_client.get(f"/e/{event.code}/planning/new").get_data(as_text=True)
    assert "Nombre minimum de participants" in html
    assert "Seuil atteint" in html


def test_form_page_shows_error_on_title_field(guest_client, event):
    html = guest_client.post(
        f"/e/{event.code}/planning/new", data={"title": "a", "date": "2026-12-02"}
    ).get_data(as_text=True)
    assert "min 2" in text_of(html, "err-title", "p")


def test_form_page_shows_error_on_date_field(guest_client, event):
    html = guest_client.post(
        f"/e/{event.code}/planning/new", data={"title": "Ok", "date": "2030-01-01"}
    ).get_data(as_text=True)
    assert "période" in text_of(html, "err-date", "p")


def test_form_page_marks_invalid_field_aria_invalid(guest_client, event):
    html = guest_client.post(
        f"/e/{event.code}/planning/new", data={"title": "a", "date": "2026-12-02"}
    ).get_data(as_text=True)
    assert 'aria-invalid="true"' in re.search(r'<input[^>]*id="f-title"[^>]*>', html).group(0)


def test_form_page_error_keeps_entered_values(guest_client, event):
    html = guest_client.post(
        f"/e/{event.code}/planning/new",
        data={"title": "a", "date": "2026-12-02", "location": "Lac"},
    ).get_data(as_text=True)
    assert 'value="Lac"' in html


def test_form_page_end_before_start_error_on_end_field(guest_client, event):
    html = guest_client.post(
        f"/e/{event.code}/planning/new",
        data={"title": "Ok", "date": "2026-12-02", "start_time": "10:00", "end_time": "09:00"},
    ).get_data(as_text=True)
    assert "fin" in text_of(html, "err-end_time", "p")


def test_edit_form_is_prefilled(creator_client, event, db):
    act = _act(db, event, "Rando", bring_items="Thermos")
    html = creator_client.get(f"/e/{event.code}/planning/{act.id}/edit").get_data(as_text=True)
    assert 'value="Thermos"' in html


# --- Requêtes -------------------------------------------------------------


def _queries_for_index(client, event) -> int:
    client.get(
        f"/e/{event.code}/planning"
    )  # réchauffe : le test et l'app partagent la session (objets expirés)
    _db.session.expire_all()
    statements: list[str] = []

    def record(conn, cursor, statement, *a):
        statements.append(statement)

    sa_event.listen(_db.engine, "before_cursor_execute", record)
    try:
        client.get(f"/e/{event.code}/planning")
    finally:
        sa_event.remove(_db.engine, "before_cursor_execute", record)
    return len(statements)


def test_index_query_count_does_not_grow_with_activities(creator_client, event, guest, db):
    for i in range(2):
        _rsvp(db, _act(db, event, f"A{i}", created_by=guest.id), guest, "yes")
    few = _queries_for_index(creator_client, event)
    for i in range(18):
        a = _act(db, event, f"B{i}", created_by=guest.id, day=date(2026, 12, 1 + i % 7))
        _rsvp(db, a, guest, "maybe")
        _rsvp(db, a, _guest(db, event, f"G{i}"), "yes")
    assert _queries_for_index(creator_client, event) == few


def test_planning_page_tolerates_null_min_headcount(creator_client, db, event):
    act = _act(db, event)
    db.session.execute(
        db.text("UPDATE activities SET min_headcount = NULL WHERE id = :i"), {"i": act.id}
    )
    db.session.commit()
    assert creator_client.get(f"/e/{event.code}/planning").status_code == 200


def test_edit_form_tolerates_null_min_headcount(creator_client, db, event):
    act = _act(db, event)
    db.session.execute(
        db.text("UPDATE activities SET min_headcount = NULL WHERE id = :i"), {"i": act.id}
    )
    db.session.commit()
    resp = creator_client.get(f"/e/{event.code}/planning/{act.id}/edit")
    assert 'value="1"' in resp.get_data(as_text=True)
