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
