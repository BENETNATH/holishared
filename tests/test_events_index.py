"""« Mes événements » : cartes cliquables, statuts, tri (B020a)."""

import re
from datetime import date, datetime, timedelta

from tests.ui_helpers import tag, testids, text_of

from app.models import Event, Guest, generate_event_code


def _html(resp):
    return resp.data.decode()


def _event(db, creator, title, start, end):
    e = Event(
        code=generate_event_code(),
        title=title,
        start_date=date.today() + timedelta(days=start),
        end_date=date.today() + timedelta(days=end),
        location="Lyon",
        creator_id=creator.id,
        verified_at=datetime.utcnow(),
    )
    db.session.add(e)
    db.session.commit()
    return e


def _titles(html):
    return re.findall(r'data-testid="event-card-link"[^>]*>([^<]*)<', html)


def test_index_card_link_is_stretched_over_the_card(db, creator_client, creator):
    e = _event(db, creator, "Alpes", 3, 9)
    html = _html(creator_client.get("/e/"))
    link = tag(html, "event-card-link")
    assert (f'href="/e/{e.code}"' in link, "ui-card__link" in link) == (True, True)


def test_index_card_is_marked_as_link_card(db, creator_client, creator):
    _event(db, creator, "Alpes", 3, 9)
    assert "ui-card--link" in tag(_html(creator_client.get("/e/")), "event-card")


def test_index_cards_sorted_ongoing_then_upcoming_then_past(db, creator_client, creator):
    _event(db, creator, "Passé", -20, -15)
    _event(db, creator, "Futur lointain", 40, 45)
    _event(db, creator, "En cours", -1, 3)
    _event(db, creator, "Futur proche", 5, 8)
    assert _titles(_html(creator_client.get("/e/"))) == [
        "En cours",
        "Futur proche",
        "Futur lointain",
        "Passé",
    ]


def test_index_status_badges_follow_phase(db, creator_client, creator):
    _event(db, creator, "A", -1, 3)
    _event(db, creator, "B", 5, 8)
    _event(db, creator, "C", -20, -15)
    html = _html(creator_client.get("/e/"))
    assert re.findall(r'data-testid="event-status"[^>]*>([^<]*)<', html) == [
        "En cours",
        "À venir",
        "Terminé",
    ]


def test_index_card_shows_localized_dates(db, creator_client, creator):
    _event(db, creator, "Alpes", 3, 9)
    html = _html(creator_client.get("/e/?lang=en"))
    assert re.search(r"[A-Z][a-z]{2} \d{1,2}, \d{4}", html)


def test_index_card_shows_location(db, creator_client, creator):
    _event(db, creator, "Alpes", 3, 9)
    assert "Lyon" in _html(creator_client.get("/e/"))


def test_index_card_counts_active_participants(db, creator_client, creator):
    e = _event(db, creator, "Alpes", 3, 9)
    db.session.add_all(
        [
            Guest(code="aaaa1111", display_name="A", event_id=e.id),
            Guest(code="bbbb2222", display_name="B", event_id=e.id),
            Guest(code="cccc3333", display_name="C", event_id=e.id, is_active=False),
        ]
    )
    db.session.commit()
    html = _html(creator_client.get("/e/"))
    assert text_of(html, "event-participants", "p") == "2 participants"


def test_index_has_new_event_button(db, creator_client, creator):
    _event(db, creator, "Alpes", 3, 9)
    assert 'href="/e/new"' in tag(_html(creator_client.get("/e/")), "new-event")


def test_index_empty_state_without_events(creator_client, creator):
    html = _html(creator_client.get("/e/"))
    assert "event-list" not in testids(html, "event-")


def test_index_empty_state_message_without_events(creator_client, creator):
    assert "Aucun événement" in _html(creator_client.get("/e/"))


def test_index_hides_inactive_events(db, creator_client, creator):
    e = _event(db, creator, "Caché", 3, 9)
    e.is_active = False
    db.session.commit()
    assert "Caché" not in _html(creator_client.get("/e/"))


def test_index_empty_state_has_a_single_primary_action(creator_client, creator):
    assert _html(creator_client.get("/e/")).count("ui-btn--primary") == 1
