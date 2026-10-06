"""Tests des droits (B029) : matrices can_edit / can_delete (table §3.6) et HTTP."""

import pytest

from app.context import EventContext
from app.models import (
    Activity,
    ChatMessage,
    Event,
    Expense,
    Guest,
    Household,
    ListItem,
    LogisticsItem,
    Meal,
    MediaItem,
    PaymentRequest,
    Poll,
    SharedList,
    Transfer,
)

AUTHOR_ID = "author-guest-id"

# type -> colonne d'auteur (None : aucune)
_AUTHOR_COLUMN = {
    Activity: "created_by",
    Meal: "created_by",
    ListItem: "assigned_to_id",
    ChatMessage: "guest_id",
    MediaItem: "uploaded_by",
}

# (type, créateur, auteur, autre invité, visiteur)
EDIT = [
    (Activity, True, True, False, False),
    (Meal, True, True, False, False),
    (SharedList, False, False, False, False),
    (ListItem, True, True, False, False),
    (LogisticsItem, True, True, True, False),
    (Poll, True, False, False, False),
    (ChatMessage, False, False, False, False),
    (MediaItem, False, False, False, False),
    (Household, True, True, True, False),
    (Expense, False, False, False, False),
    (Transfer, False, False, False, False),
    (PaymentRequest, True, True, True, False),
    (Guest, True, False, False, False),
    (Event, True, False, False, False),
]
DELETE = [
    (Activity, True, True, False, False),
    (Meal, True, True, False, False),
    (SharedList, True, False, False, False),
    (ListItem, True, True, True, False),
    (LogisticsItem, True, False, False, False),
    (Poll, True, False, False, False),
    (ChatMessage, True, True, False, False),
    (MediaItem, True, True, False, False),
    (Household, True, False, False, False),
    (Expense, True, False, False, False),
    (Transfer, True, False, False, False),
    (PaymentRequest, True, False, False, False),
    (Guest, True, False, False, False),
    (Event, True, False, False, False),
]
ROLES = ("creator", "author", "other", "visitor")


def _ctx(role: str) -> EventContext:
    event = Event(id="ev", code="abcdef", creator_id="cr")
    if role == "creator":
        return EventContext(event, Guest(id="cg", creator_id="cr"), True)
    if role == "author":
        return EventContext(event, Guest(id=AUTHOR_ID), False)
    if role == "other":
        return EventContext(event, Guest(id="someone-else"), False)
    return EventContext(event, None, False)


def _obj(cls: type) -> object:
    obj = cls()
    column = _AUTHOR_COLUMN.get(cls)
    if column:
        setattr(obj, column, AUTHOR_ID)
    return obj


def _cases(table: list[tuple]) -> list:
    return [
        pytest.param(row[0], role, row[1 + i], id=f"{row[0].__name__}-{role}")
        for row in table
        for i, role in enumerate(ROLES)
    ]


@pytest.mark.parametrize(("cls", "role", "expected"), _cases(EDIT))
def test_can_edit_matches_rights_table(cls, role, expected):
    assert _ctx(role).can_edit(_obj(cls)) is expected


@pytest.mark.parametrize(
    ("cls", "role", "expected"),
    [*_cases(DELETE), pytest.param(Guest, "creator", False, id="Guest-with-creator_id")],
)
def test_can_delete_matches_rights_table(cls, role, expected):
    obj = _obj(cls)
    if cls is Guest and expected is False and role == "creator":
        obj.creator_id = "cr"
    assert _ctx(role).can_delete(obj) is expected


def test_can_edit_unknown_type_raises_type_error():
    with pytest.raises(TypeError):
        _ctx("creator").can_edit(object())


# --- HTTP : RSVP du créateur (D1) --------------------------------------------------


@pytest.fixture
def planned_activity(db, event):
    from datetime import date

    activity = Activity(title="Swim", date=date(2026, 12, 2), event_id=event.id)
    db.session.add(activity)
    db.session.commit()
    return activity


def _rsvp_as_creator(creator_client, event, activity):
    return creator_client.post(
        f"/e/{event.code}/planning/{activity.id}/rsvp", data={"status": "yes"}
    )


def test_rsvp_creator_records_rsvp_under_creator_guest(
    creator_client, event, creator_guest, planned_activity
):
    _rsvp_as_creator(creator_client, event, planned_activity)
    from app.models import ActivityRSVP

    rsvp = ActivityRSVP.query.filter_by(guest_id=creator_guest.id).first()
    assert rsvp.status == "yes"


def test_rsvp_creator_logs_actor_type_creator(
    creator_client, event, creator_guest, planned_activity
):
    _rsvp_as_creator(creator_client, event, planned_activity)
    from app.models import ActivityLog

    log = ActivityLog.query.filter_by(event_id=event.id, action="rsvp.updated").first()
    assert log.actor_type == "creator"


def test_planning_index_shows_rsvp_form_to_creator(
    creator_client, event, creator_guest, planned_activity
):
    resp = creator_client.get(f"/e/{event.code}/planning")
    assert f"/planning/{planned_activity.id}/rsvp".encode() in resp.data


# --- HTTP : listes (identité par identifiant) ---------------------------------------


@pytest.fixture
def shared_list(db, event):
    shared = SharedList(title="Courses", event_id=event.id)
    db.session.add(shared)
    db.session.commit()
    return shared


@pytest.fixture
def open_item(db, shared_list):
    item = ListItem(name="Pain", list_id=shared_list.id)
    db.session.add(item)
    db.session.commit()
    return item


def _item_url(event, shared_list, item, action):
    return f"/e/{event.code}/lists/{shared_list.id}/items/{item.id}/{action}"


def test_list_claim_creator_sets_creator_guest_id(
    creator_client, event, creator_guest, shared_list, open_item
):
    creator_client.post(_item_url(event, shared_list, open_item, "claim"))
    assert open_item.assigned_to_id == creator_guest.id


def test_list_detail_same_name_without_id_not_mine(guest_client, db, event, guest, shared_list):
    item = ListItem(name="Pain", assigned_to="Test Guest", list_id=shared_list.id)
    db.session.add(item)
    db.session.commit()
    resp = guest_client.get(f"/e/{event.code}/lists/{shared_list.id}")
    assert _item_url(event, shared_list, item, "unclaim").encode() not in resp.data


def _add_item(client, event, shared_list, assigned_to):
    return client.post(
        f"/e/{event.code}/lists/{shared_list.id}/items",
        data={"name": "Vin", "assigned_to": assigned_to},
    )


def test_add_item_assigned_unique_name_sets_guest_id(guest_client, event, guest, shared_list):
    _add_item(guest_client, event, shared_list, "Test Guest")
    assert ListItem.query.filter_by(name="Vin").first().assigned_to_id == guest.id


def test_add_item_assigned_ambiguous_name_keeps_none(
    db, guest_client, event, guest, shared_list
):
    db.session.add(Guest(code="twin0001", display_name="Test Guest", event_id=event.id))
    db.session.commit()
    _add_item(guest_client, event, shared_list, "Test Guest")
    assert ListItem.query.filter_by(name="Vin").first().assigned_to_id is None


def test_list_delete_item_guest_allowed(guest_client, event, shared_list, open_item):
    resp = guest_client.post(_item_url(event, shared_list, open_item, "delete"))
    assert (resp.status_code, ListItem.query.filter_by(id=open_item.id).first()) == (302, None)


def test_logistics_delete_guest_403(guest_client, db, event):
    item = LogisticsItem(title="Parking", event_id=event.id)
    db.session.add(item)
    db.session.commit()
    resp = guest_client.post(f"/e/{event.code}/logistics/{item.id}/delete")
    assert resp.status_code == 403


def test_vote_creator_creates_no_household(creator_client, db, event):
    from app.models import Household, Poll, PollOption

    poll = Poll(question="Q?", event_id=event.id)
    poll.options.append(PollOption(label="A", order=0))
    db.session.add(poll)
    db.session.commit()
    option = poll.options.first()
    creator_client.post(f"/e/{event.code}/voting/{poll.id}/vote", data={"option_id": option.id})
    assert Household.query.filter_by(event_id=event.id).count() == 0


def test_chat_other_guest_cannot_delete_creator_message_403(
    db, guest_client, event, creator_guest
):
    message = ChatMessage(
        content="hi",
        author_name="Test Creator",
        author_type="creator",
        guest_id=creator_guest.id,
        event_id=event.id,
    )
    db.session.add(message)
    db.session.commit()
    assert guest_client.post(f"/e/{event.code}/chat/{message.id}/delete").status_code == 403


def test_chat_send_creator_guest_id_is_creator_guest(creator_client, event, creator_guest):
    creator_client.post(f"/e/{event.code}/chat/send", data={"content": "salut"})
    assert ChatMessage.query.filter_by(event_id=event.id).first().guest_id == creator_guest.id


# --- HTTP : frais -----------------------------------------------------------------


def _expense_payload(household):
    return {"description": "Loyer", "amount": "10", "household_id": household.id, "date": "2026-12-01"}


def _household(db, event):
    household = Household(name="Foyer A", num_adults=1, num_children=0, event_id=event.id)
    db.session.add(household)
    db.session.commit()
    return household


def test_costs_creator_log_uses_display_name(creator_client, db, event):
    from app.models import ActivityLog

    creator_client.post(f"/e/{event.code}/costs/expenses/new", data=_expense_payload(_household(db, event)))
    log = ActivityLog.query.filter_by(event_id=event.id, action="expense.created").first()
    assert log.actor_name == "Test Creator"


def test_costs_creator_with_guest_session_logs_creator(creator_client, db, event, guest):
    from app.models import ActivityLog

    with creator_client.session_transaction() as sess:
        sess[f"guest_{event.code}"] = guest.id
    creator_client.post(f"/e/{event.code}/costs/expenses/new", data=_expense_payload(_household(db, event)))
    log = ActivityLog.query.filter_by(event_id=event.id, action="expense.created").first()
    assert log.actor_type == "creator"
