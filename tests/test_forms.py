"""B018 — FormErrors : erreurs par champ, indépendantes du texte des messages."""

import pytest

from app.forms import FormErrors


def test_errors_are_grouped_by_field_and_iterable_as_a_list():
    e = FormErrors()
    e.add("title", "Titre requis.")
    e.add("email", "Email requis.")
    e.add("title", "Titre trop long.")
    assert list(e) == ["Titre requis.", "Email requis.", "Titre trop long."]
    assert e.for_field("title") == ["Titre requis.", "Titre trop long."]
    assert e.text("title") == "Titre requis. Titre trop long."
    assert e.as_dict() == {
        "title": ["Titre requis.", "Titre trop long."],
        "email": ["Email requis."],
    }
    assert len(e) == 3
    assert "Email requis." in e


def test_empty_errors_are_falsy_and_unknown_field_is_empty():
    e = FormErrors()
    assert not e
    assert e.for_field("x") == []
    assert e.text("x") is None
    assert not e.has("x")


def test_global_errors_and_remaining():
    e = FormErrors()
    e.add("title", "A")
    e.add_global("G")
    e.add("quantity", "Q")
    assert e.global_errors == ["G"]
    assert e.remaining("title") == ["G", "Q"]
    assert e.remaining("title", "quantity") == ["G"]


def test_empty_field_name_is_refused():
    with pytest.raises(ValueError, match="field"):
        FormErrors().add("", "x")


def test_flash_all_flashes_each_message_in_order(app):
    e = FormErrors()
    e.add("a", "un")
    e.add_global("deux")
    with app.test_request_context():
        from flask import get_flashed_messages, session

        e.flash_all("danger")
        assert session["_flashes"] == [("danger", "un"), ("danger", "deux")]
        assert get_flashed_messages() == ["un", "deux"]
