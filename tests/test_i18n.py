"""B018 — libellés centraux, formats localisés, journal (infrastructure)."""

from datetime import UTC, date, datetime, time

import pytest

from app import i18n


def _in_lang(app, lang, fn, *args, **kwargs):
    # Contexte applicatif neuf : Flask-Babel met la locale en cache sur ``g``.
    with app.app_context(), app.test_request_context(f"/?lang={lang}"):
        return fn(*args, **kwargs)


@pytest.mark.parametrize(
    ("kind", "key", "fr", "en"),
    [
        ("expense_category", "food", "Alimentation", "Food"),
        ("expense_category", "lodging", "Hébergement", "Lodging"),
        ("info_category", "timing", "Horaires", "Schedule"),
        ("list_type", "shopping", "Courses", "Shopping"),
        ("rsvp_status", "maybe", "Peut-être", "Maybe"),
        ("meal_slot", "lunch", "Midi", "Lunch"),
        ("meal_slot", "dinner", "Soir", "Dinner"),
    ],
)
def test_label_translates_key_in_each_language(app, kind, key, fr, en):
    assert _in_lang(app, "fr", i18n.label, key, kind) == fr
    assert _in_lang(app, "en", i18n.label, key, kind) == en


def test_label_unknown_key_falls_back_never_raw_key(app):
    assert _in_lang(app, "fr", i18n.label, "zzz", "expense_category") == "Autre"
    assert _in_lang(app, "fr", i18n.label, None, "expense_category") == "Autre"
    assert _in_lang(app, "fr", i18n.label, "zzz", "rsvp_status") == ""


def test_choices_keep_registry_order(app):
    keys = [k for k, _ in _in_lang(app, "en", i18n.choices, "expense_category")]
    assert keys == ["general", "food", "transport", "lodging", "activities", "other"]


def test_is_valid_checks_registry(app):
    assert i18n.is_valid("expense_category", "food")
    assert not i18n.is_valid("expense_category", "Food")
    assert not i18n.is_valid("meal_slot", None)


def test_every_label_differs_between_languages(app):
    same_in_both = {"Transport", "Documents", "Buffet"}
    for kind, table in i18n.LABELS.items():
        for key in table:
            fr = _in_lang(app, "fr", i18n.label, key, kind)
            en = _in_lang(app, "en", i18n.label, key, kind)
            assert en, (kind, key)
            assert en != fr or fr in same_in_both, (kind, key)


def test_money_fr_and_en(app):
    assert _in_lang(app, "fr", i18n.format_money, 30) == "30,00\xa0€"
    assert _in_lang(app, "en", i18n.format_money, 30) == "€30.00"
    assert _in_lang(app, "en", i18n.format_money, 12, sign=True) == "+€12.00"
    assert _in_lang(app, "en", i18n.format_money, None) == ""
    assert _in_lang(app, "en", i18n.format_money, 1, "XXX") == "€1.00"


def test_number_and_time_and_dates_follow_language(app):
    assert _in_lang(app, "fr", i18n.format_number, 142.5, 2) == "142,50"
    assert _in_lang(app, "en", i18n.format_number, 142.5, 2) == "142.50"
    assert _in_lang(app, "fr", i18n.format_time_short, time(20, 5)) == "20:05"
    assert "8:05" in _in_lang(app, "en", i18n.format_time_short, time(20, 5))
    assert _in_lang(app, "fr", i18n.format_date_short, date(2026, 12, 1)) == "01/12"
    assert _in_lang(app, "en", i18n.format_date_short, date(2026, 12, 1)) == "12/1"
    assert _in_lang(
        app, "fr", i18n.format_datetime_short, datetime(2026, 12, 1, 20, 5, tzinfo=UTC)
    ).startswith("01/12/2026")


def test_none_values_render_empty_not_today(app):
    for fn in (
        i18n.format_date_safe,
        i18n.format_datetime_safe,
        i18n.format_time_short,
        i18n.format_date_short,
        i18n.format_datetime_short,
    ):
        assert _in_lang(app, "fr", fn, None) == ""


def test_currency_label_follows_language(app):
    assert _in_lang(app, "fr", i18n.currency_label, "EUR") == "EUR — euro"
    assert _in_lang(app, "en", i18n.currency_label, "EUR") == "EUR — Euro"


def test_action_label_registry(app):
    assert _in_lang(app, "fr", i18n.action_label, "expense.created") == "Dépense ajoutée"
    assert _in_lang(app, "en", i18n.action_label, "expense.created") == "Expense added"
    assert i18n.action_label("custom.code") == "custom.code"
    assert i18n.action_label(None) == ""


def test_costs_page_never_shows_raw_category_keys(creator_client, db, event, creator_guest):
    from app.models import Expense, Household

    h = Household(name="Foyer A", event_id=event.id, guest_id=creator_guest.id)
    db.session.add(h)
    db.session.flush()
    db.session.add(
        Expense(
            description="Pizza",
            amount_cents=1000,
            paid_by_household_id=h.id,
            event_id=event.id,
            category="food",
        )
    )
    db.session.commit()
    html = creator_client.get(f"/e/{event.code}/costs?lang=fr").get_data(as_text=True)
    assert "Alimentation" in html
    assert "Hébergement" in html
    for raw in (">General<", ">Lodging<", ">Food<", ">Food ", ">food<", 'title="food"'):
        assert raw not in html
    html_en = creator_client.get(f"/e/{event.code}/costs?lang=en").get_data(as_text=True)
    assert "Food" in html_en
    assert "Alimentation" not in html_en
    assert "€10.00" in html_en


def test_expense_with_unknown_category_is_refused(creator_client, db, event, creator_guest):
    from app.models import Expense, Household

    h = Household(name="Foyer A", event_id=event.id, guest_id=creator_guest.id)
    db.session.add(h)
    db.session.commit()
    resp = creator_client.post(
        f"/e/{event.code}/costs/expenses/new",
        data={"description": "X", "amount": "5", "household_id": h.id, "category": "bogus"},
        follow_redirects=True,
    )
    assert "Catégorie invalide." in resp.get_data(as_text=True)
    assert Expense.query.filter_by(event_id=event.id).count() == 0
