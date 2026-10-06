"""Liens conditionnels au module cible (F32, B029) : plus de BuildError."""

from datetime import date, datetime

import pytest

from app.extensions import db
from app.models import Creator, Event, ListItem, Meal, SharedList

ALL_MODULES = ["planning", "meals", "lists", "logistics", "voting", "media", "chat", "costs"]


def _client(app_factory, modules: str):
    built = app_factory({"ENABLED_MODULES": modules})
    creator = Creator(email="l@test.com", email_verified=True, display_name="Camille")
    db.session.add(creator)
    db.session.commit()
    event = Event(
        code="lnk234",
        title="Liens",
        start_date=date.today(),
        end_date=date.today(),
        creator_id=creator.id,
        verified_at=datetime.utcnow(),
    )
    db.session.add(event)
    db.session.commit()
    client = built.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = creator.id
        sess["_fresh"] = True
    return client, event, creator


def _add_meal(event):
    db.session.add(Meal(title="Raclette", date=date.today(), slot="dinner", event_id=event.id))
    db.session.commit()


def test_dashboard_planning_without_meals_renders_200(app_factory):
    client, event, _ = _client(app_factory, "planning,lists")
    _add_meal(event)
    assert client.get(f"/e/{event.code}").status_code == 200


def test_dashboard_planning_without_meals_has_no_meals_link(app_factory):
    client, event, _ = _client(app_factory, "planning,lists")
    _add_meal(event)
    # L'import map liste `ui/meals` (/static/js/ui/meals.*.js) : on teste l'URL de la page, pas « /meals ».
    assert f"/e/{event.code}/meals".encode() not in client.get(f"/e/{event.code}").data


def test_dashboard_meals_without_planning_links_meal_title(app_factory):
    client, event, _ = _client(app_factory, "meals")
    _add_meal(event)
    assert f"/e/{event.code}/meals".encode() in client.get(f"/e/{event.code}").data


def test_dashboard_plan_meals_action_targets_meals(app_factory):
    import re

    client, event, _ = _client(app_factory, "meals,planning")
    html = client.get(f"/e/{event.code}").data.decode()
    match = re.search(r'<a href="([^"]*)"[^>]*data-testid="plan-meals-action"', html)
    assert match is not None
    assert match.group(1).endswith("/meals")


def test_dashboard_lists_disabled_with_assigned_item_renders_200(app_factory):
    client, event, creator = _client(app_factory, "planning")
    from app.models import Guest

    participant = Guest(
        code="tok0000000000009", display_name="Camille", event_id=event.id, creator_id=creator.id
    )
    db.session.add(participant)
    shared = SharedList(title="L", event_id=event.id)
    db.session.add(shared)
    db.session.flush()
    db.session.add(
        ListItem(
            name="Pain", assigned_to="Camille", assigned_to_id=participant.id, list_id=shared.id
        )
    )
    db.session.commit()
    assert client.get(f"/e/{event.code}").status_code == 200


@pytest.mark.parametrize("disabled", ALL_MODULES)
def test_event_pages_render_with_module_disabled(app_factory, disabled):
    enabled = [m for m in ALL_MODULES if m != disabled]
    client, event, _ = _client(app_factory, ",".join(enabled))
    paths = ["", "/members", "/log"]
    paths += [f"/{'voting' if m == 'voting' else m}" for m in enabled]
    statuses = [client.get(f"/e/{event.code}{path}").status_code for path in paths]
    assert max(statuses) < 500
