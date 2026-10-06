"""Page d'index des listes (B023) : cartes cliquables, progression, création rapide, types."""

import re

import pytest
from tests.ui_helpers import block, tag

from app.i18n import LABELS
from app.models import ListItem, SharedList


def _index(client, event):
    return client.get(f"/e/{event.code}/lists").data.decode()


@pytest.fixture
def two_lists(db, event):
    a = SharedList(title="Courses", list_type="shopping", event_id=event.id)
    b = SharedList(title="Valise", list_type="packing", event_id=event.id)
    db.session.add_all([a, b])
    db.session.flush()
    db.session.add_all(
        [
            ListItem(name="Pain", is_done=True, list_id=a.id),
            ListItem(name="Lait", list_id=a.id),
            ListItem(name="Pull", list_id=a.id, is_done=True),
        ]
    )
    db.session.commit()
    return a, b


def test_index_card_is_one_stretched_link_to_the_list(guest_client, event, two_lists):
    a, _b = two_lists
    html = block(_index(guest_client, event), "list-card", "article")
    assert f"/lists/{a.id}" in tag(html, "list-card-link")
    assert "ui-card__link" in tag(html, "list-card-link")


def test_index_card_shows_done_over_total(guest_client, event, two_lists):
    html = block(_index(guest_client, event), "list-card", "article")
    assert (
        re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", block(html, "list-card-progress", "span")))
        == "2/3"
    )


def test_index_card_of_empty_list_shows_zero_over_zero(guest_client, event, two_lists):
    html = _index(guest_client, event)
    assert html.count('data-testid="list-card-progress">0/0<') == 1


def test_index_card_progressbar_exposes_value_and_max(guest_client, event, two_lists):
    html = _index(guest_client, event)
    assert 'aria-valuenow="2"' in html
    assert 'aria-valuemax="3"' in html


def test_index_card_shows_translated_type_label(guest_client, event, two_lists):
    assert "Courses" in block(_index(guest_client, event), "list-card-type", "span")


def test_index_empty_state_without_lists(guest_client, event):
    assert "Rien ici pour l'instant" in _index(guest_client, event)


def test_index_create_form_has_title_type_and_submit(guest_client, event):
    html = block(_index(guest_client, event), "list-create-form", "form")
    assert all(t in html for t in ("list-create-title", "list-create-type", "list-create-submit"))


def test_index_type_select_offers_every_registry_type(guest_client, event):
    html = block(_index(guest_client, event), "list-create-type", "select")
    assert re.findall(r'<option value="(\w+)"', html) == list(LABELS["list_type"])


def test_registry_has_todo_and_packing_types():
    assert {"general", "shopping", "materials", "packing", "todo"} <= set(LABELS["list_type"])


def test_create_list_stores_the_chosen_type(guest_client, event):
    guest_client.post(
        f"/e/{event.code}/lists", data={"title": "Valise Léa", "list_type": "packing"}
    )
    assert SharedList.query.one().list_type == "packing"


def test_create_list_with_unknown_type_falls_back_to_general(guest_client, event):
    guest_client.post(f"/e/{event.code}/lists", data={"title": "Divers", "list_type": "bogus"})
    assert SharedList.query.one().list_type == "general"


def test_create_list_without_type_is_general(guest_client, event):
    guest_client.post(f"/e/{event.code}/lists", data={"title": "Divers"})
    assert SharedList.query.one().list_type == "general"


def test_index_does_not_issue_two_queries_per_list(db, guest_client, event):
    from sqlalchemy import event as sa_event

    for i in range(6):
        db.session.add(SharedList(title=f"L{i}", event_id=event.id))
    db.session.commit()
    statements: list[str] = []

    def count(conn, cursor, statement, *args):
        statements.append(statement)

    sa_event.listen(db.engine, "before_cursor_execute", count)
    try:
        guest_client.get(f"/e/{event.code}/lists")
    finally:
        sa_event.remove(db.engine, "before_cursor_execute", count)
    assert sum("list_items" in s for s in statements) == 1
