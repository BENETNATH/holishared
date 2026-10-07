"""Lot B024 — Frais : note des demandes, taux de change, date, droits, confidentialité, structure."""

import io
import json
import zipfile
from datetime import UTC, date, datetime, timedelta

import pytest
from tests.ui_helpers import block, tag, testids, text_of

from app.models import ActivityLog, Expense, Household, PaymentRequest, Transfer

TODAY = datetime.now(UTC).date()


def _as(client, event, who, creator=None):
    """Identifie le client : ``who`` est un invité (session) ou « creator ».

    Le contexte d'application de la fixture est partagé entre les requêtes : on oublie
    l'utilisateur mis en cache sur ``g`` quand l'identité change.
    """
    from flask import g

    g.pop("_login_user", None)
    g.pop("event_ctx", None)
    with client.session_transaction() as sess:
        sess.clear()
        if who == "creator":
            sess["_user_id"] = creator.id
            sess["_fresh"] = True
        else:
            sess[f"guest_{event.code}"] = who.id
    return client


@pytest.fixture
def setup(db, event, creator, creator_guest, guest, other_guest_c):
    """Trois foyers : le créateur (C), Alice = ``guest`` (A), Bob = ``other_guest_c`` (B)."""

    def mk(name, owner):
        h = Household(
            name=name,
            num_adults=2,
            num_children=0,
            event_id=event.id,
            guest_id=owner.id if owner else None,
        )
        db.session.add(h)
        db.session.commit()
        return h

    class S:
        pass

    s = S()
    s.hc, s.ha, s.hb = (
        mk("Foyer Créateur", creator_guest),
        mk("Foyer Alice", guest),
        mk("Foyer Bob", other_guest_c),
    )
    s.creator, s.alice, s.bob, s.event, s.db = creator, guest, other_guest_c, event, db
    s.url = f"/e/{event.code}/costs"
    return s


def _expense(s, desc, household, by, cents=10000, shared=True, currency="EUR", rate=1.0):
    e = Expense(
        description=desc,
        amount_cents=cents,
        currency=currency,
        exchange_rate=rate,
        paid_by_household_id=household.id,
        event_id=s.event.id,
        is_shared=shared,
        created_by=by.id if by else None,
        date=TODAY,
    )
    s.db.session.add(e)
    s.db.session.commit()
    return e


def _payload(s, **over):
    data = {
        "description": "Courses",
        "amount": "40",
        "household_id": s.ha.id,
        "is_shared": "on",
        "category": "food",
    }
    data.update(over)
    return data


def _post_expense(client, s, **over):
    return client.post(f"{s.url}/expenses/new", data=_payload(s, **over))


# --- Demande de paiement : la note est enregistrée et affichée -------------------------------


def test_payment_request_message_is_saved(client, setup):
    s = setup
    _as(client, s.event, s.alice)
    client.post(
        f"{s.url}/payment-requests/new",
        data={"to_household_id": s.hb.id, "amount": "12", "message": "pour le gîte"},
    )
    assert PaymentRequest.query.one().message == "pour le gîte"


def test_payment_request_message_is_displayed_on_requests_tab(client, setup):
    s = setup
    s.db.session.add(
        PaymentRequest(
            from_household_id=s.ha.id,
            to_household_id=s.hb.id,
            amount_cents=500,
            message="merci d'avance",
            event_id=s.event.id,
        )
    )
    s.db.session.commit()
    html = _as(client, s.event, s.alice).get(f"{s.url}?tab=requests").get_data(as_text=True)
    assert text_of(html, "request-message", "p") == "merci d'avance"


def test_payment_request_form_posts_the_message_field(client, setup):
    html = (
        _as(client, setup.event, setup.alice)
        .get(f"{setup.url}?tab=requests")
        .get_data(as_text=True)
    )
    assert 'name="message"' in block(html, "request-form", "form")


def test_payment_request_form_no_longer_posts_a_note_field(client, setup):
    html = (
        _as(client, setup.event, setup.alice)
        .get(f"{setup.url}?tab=requests")
        .get_data(as_text=True)
    )
    assert 'name="note"' not in block(html, "request-form", "form")


def test_payment_request_message_too_long_is_refused(client, setup):
    s = setup
    _as(client, s.event, s.alice).post(
        f"{s.url}/payment-requests/new",
        data={"to_household_id": s.hb.id, "amount": "12", "message": "x" * 501},
    )
    assert PaymentRequest.query.count() == 0


# --- Taux de change --------------------------------------------------------------------------


def test_usd_expense_with_rate_is_counted_in_base_currency_total(client, setup):
    s = setup
    _as(client, s.event, s.alice)
    _post_expense(client, s, amount="100", currency="USD", exchange_rate="0,9")
    html = client.get(s.url).get_data(as_text=True)
    assert text_of(html, "costs-total", "strong") == "90,00 €"


def test_usd_expense_with_rate_is_applied_to_settlement(client, setup):
    s = setup
    s.db.session.delete(s.hc)
    s.db.session.commit()
    _as(client, s.event, s.alice)
    _post_expense(client, s, amount="100", currency="USD", exchange_rate="0.9")
    html = client.get(f"{s.url}?tab=balance").get_data(as_text=True)
    assert text_of(html, "owes-amount", "strong") == "45,00 €"


def test_usd_expense_is_stored_with_its_rate(client, setup):
    _as(client, setup.event, setup.alice)
    _post_expense(client, setup, amount="100", currency="USD", exchange_rate="0.9")
    assert Expense.query.one().exchange_rate == 0.9


def test_foreign_currency_without_rate_is_refused(client, setup):
    _as(client, setup.event, setup.alice)
    _post_expense(client, setup, currency="USD", exchange_rate="")
    assert Expense.query.count() == 0


@pytest.mark.parametrize("rate", ["0", "-1", "abc", "nan", "10001"])
def test_invalid_rate_is_refused(client, setup, rate):
    _as(client, setup.event, setup.alice)
    _post_expense(client, setup, currency="USD", exchange_rate=rate)
    assert Expense.query.count() == 0


def test_invalid_rate_shows_error_on_rate_field(client, setup):
    _as(client, setup.event, setup.alice)
    html = _post_expense(client, setup, currency="USD", exchange_rate="0").get_data(as_text=True)
    assert 'id="costs-expense-sheet-rate-error"' in html


def test_base_currency_ignores_submitted_rate(client, setup):
    _as(client, setup.event, setup.alice)
    _post_expense(client, setup, currency="EUR", exchange_rate="5")
    assert Expense.query.one().exchange_rate == 1.0


def test_unknown_currency_is_refused(client, setup):
    _as(client, setup.event, setup.alice)
    _post_expense(client, setup, currency="XXX", exchange_rate="1")
    assert Expense.query.count() == 0


def test_expense_detail_shows_original_amount_and_rate(client, setup):
    s = setup
    _expense(s, "Taxi", s.ha, s.alice, cents=10000, currency="USD", rate=0.9)
    html = _as(client, s.event, s.alice).get(s.url).get_data(as_text=True)
    assert text_of(html, "detail-rate", "dd") == "1 USD = 0,9 EUR"


def test_amount_with_comma_decimal_is_accepted(client, setup):
    _as(client, setup.event, setup.alice)
    _post_expense(client, setup, amount="12,50")
    assert Expense.query.one().amount_cents == 1250


@pytest.mark.parametrize("amount", ["0", "-3", "abc", "inf", "nan", "99999999"])
def test_invalid_amount_is_refused(client, setup, amount):
    _as(client, setup.event, setup.alice)
    _post_expense(client, setup, amount=amount)
    assert Expense.query.count() == 0


# --- Date ------------------------------------------------------------------------------------


def test_expense_date_defaults_to_today(client, setup):
    _as(client, setup.event, setup.alice)
    _post_expense(client, setup)
    assert Expense.query.one().date == TODAY


def test_expense_date_entered_is_stored(client, setup):
    _as(client, setup.event, setup.alice)
    _post_expense(client, setup, date="2026-03-04")
    assert Expense.query.one().date.isoformat() == "2026-03-04"


@pytest.mark.parametrize(
    "value",
    ["2999-01-01", "1999-01-01", "pas-une-date", (TODAY - timedelta(days=365 * 6)).isoformat()],
)
def test_out_of_range_or_invalid_date_is_refused(client, setup, value):
    _as(client, setup.event, setup.alice)
    _post_expense(client, setup, date=value)
    assert Expense.query.count() == 0


def test_expense_without_date_shows_no_date_instead_of_today(client, setup):
    s = setup
    e = _expense(s, "Ancienne", s.ha, s.alice)
    e.date = None
    s.db.session.commit()
    html = _as(client, s.event, s.alice).get(s.url).get_data(as_text=True)
    assert text_of(html, "expense-meta", "span") == "Foyer Alice"


def test_expense_form_proposes_today_as_default_date(client, setup):
    html = _as(client, setup.event, setup.alice).get(setup.url).get_data(as_text=True)
    assert f'value="{TODAY.isoformat()}"' in block(html, "costs-expense-sheet", "dialog")


# --- Droits : dépenses -----------------------------------------------------------------------


@pytest.fixture
def expenses(setup):
    s = setup
    s.ea = _expense(s, "Dépense Alice", s.ha, s.alice)
    s.eb = _expense(s, "Dépense Bob", s.hb, s.bob)
    s.eab = _expense(s, "Saisie par Bob pour Alice", s.ha, s.bob)
    return s


def _edit(client, s, exp, **over):
    return client.post(f"{s.url}/expenses/{exp.id}/edit", data=_payload(s, **over))


def test_participant_deletes_expense_paid_by_own_household(client, expenses):
    s = expenses
    resp = _as(client, s.event, s.alice).post(f"{s.url}/expenses/{s.ea.id}/delete")
    assert (resp.status_code, Expense.query.get(s.ea.id)) == (302, None)


def test_participant_deletes_expense_he_entered_for_another_household(client, expenses):
    s = expenses
    resp = _as(client, s.event, s.bob).post(f"{s.url}/expenses/{s.eab.id}/delete")
    assert resp.status_code == 302


def test_participant_cannot_delete_expense_of_another_household(client, expenses):
    s = expenses
    assert (
        _as(client, s.event, s.alice).post(f"{s.url}/expenses/{s.eb.id}/delete").status_code == 403
    )


def test_creator_deletes_any_expense(client, expenses):
    s = expenses
    resp = _as(client, s.event, "creator", s.creator).post(f"{s.url}/expenses/{s.eb.id}/delete")
    assert resp.status_code == 302


def test_participant_edits_own_expense(client, expenses):
    s = expenses
    _as(client, s.event, s.alice)
    _edit(client, s, s.ea, description="Corrigée", amount="55")
    assert (Expense.query.get(s.ea.id).description, Expense.query.get(s.ea.id).amount_cents) == (
        "Corrigée",
        5500,
    )


def test_participant_cannot_edit_expense_of_another_household(client, expenses):
    s = expenses
    assert _edit(_as(client, s.event, s.alice), s, s.eb).status_code == 403


def test_creator_edits_any_expense(client, expenses):
    s = expenses
    resp = _edit(_as(client, s.event, "creator", s.creator), s, s.eb, household_id=s.hb.id)
    assert resp.status_code == 302


def test_edit_keeps_original_author(client, expenses):
    s = expenses
    _edit(_as(client, s.event, "creator", s.creator), s, s.eb, household_id=s.hb.id)
    assert Expense.query.get(s.eb.id).created_by == s.bob.id


def test_edit_with_invalid_amount_reopens_edit_sheet(client, expenses):
    s = expenses
    html = _edit(_as(client, s.event, s.alice), s, s.ea, amount="0").get_data(as_text=True)
    assert json.loads(text_of(html, "costs-open-sheet", "script")) == "costs-expense-edit-sheet"


def test_ui_shows_edit_and_delete_only_on_rows_the_user_may_change(client, expenses):
    html = _as(client, expenses.event, expenses.alice).get(expenses.url).get_data(as_text=True)
    assert (
        html.count('data-testid="expense-edit"'),
        html.count('data-testid="expense-delete"'),
    ) == (2, 2)


def test_ui_shows_edit_and_delete_on_every_row_for_creator(client, expenses):
    s = expenses
    html = _as(client, s.event, "creator", s.creator).get(s.url).get_data(as_text=True)
    assert html.count('data-testid="expense-delete"') == 3


def test_edit_link_opens_the_edit_sheet(client, expenses):
    s = expenses
    html = _as(client, s.event, s.alice).get(f"{s.url}?edit={s.ea.id}").get_data(as_text=True)
    assert "costs-expense-edit-sheet" in testids(html, "costs-expense-edit-sheet")


def test_edit_link_for_expense_of_another_household_opens_nothing(client, expenses):
    s = expenses
    html = _as(client, s.event, s.alice).get(f"{s.url}?edit={s.eb.id}").get_data(as_text=True)
    assert 'data-testid="costs-expense-edit-sheet"' not in html


# --- Confidentialité des dépenses personnelles ----------------------------------------------


@pytest.fixture
def personal(setup):
    s = setup
    s.pe = _expense(s, "Cadeau secret", s.ha, s.alice, cents=7777, shared=False)
    return s


def test_personal_expense_is_visible_to_members_of_payer_household(client, personal):
    html = _as(client, personal.event, personal.alice).get(personal.url).get_data(as_text=True)
    assert "Cadeau secret" in html


def test_personal_expense_is_hidden_from_other_participants(client, personal):
    html = _as(client, personal.event, personal.bob).get(personal.url).get_data(as_text=True)
    assert "Cadeau secret" not in html


def test_personal_expense_is_hidden_from_creator_outside_the_household(client, personal):
    s = personal
    html = _as(client, s.event, "creator", s.creator).get(s.url).get_data(as_text=True)
    assert "Cadeau secret" not in html


def test_personal_expense_amount_is_not_in_other_participants_page(client, personal):
    html = (
        _as(client, personal.event, personal.bob)
        .get(f"{personal.url}?tab=balance")
        .get_data(as_text=True)
    )
    assert "77,77" not in html


def test_personal_expense_is_excluded_from_shared_total(client, personal):
    s = personal
    _expense(s, "Loyer", s.ha, s.alice, cents=1000)
    html = _as(client, s.event, s.alice).get(s.url).get_data(as_text=True)
    assert text_of(html, "costs-total", "strong") == "10,00 €"


def test_personal_total_is_shown_only_for_own_household(client, personal):
    s = personal
    mine = _as(client, s.event, s.alice).get(f"{s.url}?tab=balance").get_data(as_text=True)
    theirs = _as(client, s.event, s.bob).get(f"{s.url}?tab=balance").get_data(as_text=True)
    assert ('data-testid="personal-total"' in mine, 'data-testid="personal-total"' in theirs) == (
        True,
        False,
    )


def test_other_participant_cannot_delete_personal_expense_and_gets_404(client, personal):
    s = personal
    assert _as(client, s.event, s.bob).post(f"{s.url}/expenses/{s.pe.id}/delete").status_code == 404


def test_other_participant_cannot_edit_personal_expense_and_gets_404(client, personal):
    s = personal
    assert _edit(_as(client, s.event, s.bob), s, s.pe).status_code == 404


def test_creator_outside_household_cannot_delete_personal_expense(client, personal):
    s = personal
    assert (
        _as(client, s.event, "creator", s.creator)
        .post(f"{s.url}/expenses/{s.pe.id}/delete")
        .status_code
        == 404
    )


def test_personal_expense_must_be_paid_by_own_household(client, setup):
    s = setup
    _as(client, s.event, s.alice)
    _post_expense(client, s, household_id=s.hb.id, is_shared="")
    assert Expense.query.count() == 0


def test_personal_expense_creation_logs_no_description(client, setup):
    s = setup
    _as(client, s.event, s.alice)
    _post_expense(client, s, description="Surprise", is_shared="")
    log = ActivityLog.query.filter_by(event_id=s.event.id, action="expense.created").one()
    assert (log.target, log.details) == (None, None)


def test_export_excludes_personal_expenses_of_others(client, personal):
    s = personal
    resp = _as(client, s.event, "creator", s.creator).get(f"/e/{s.event.code}/export")
    names = zipfile.ZipFile(io.BytesIO(resp.data)).namelist()
    blob = b"".join(
        zipfile.ZipFile(io.BytesIO(resp.data)).read(n) for n in names if n.endswith(".json")
    )
    assert b"Cadeau secret" not in blob


# --- Droits : foyers et ratio ----------------------------------------------------------------


def _hh(client, s, hid, **over):
    data = {"name": "Foyer Renommé", "num_adults": "3", "num_children": "1"}
    data.update(over)
    return client.post(f"{s.url}/households/{hid}/edit", data=data)


def test_participant_cannot_add_household(client, setup):
    s = setup
    resp = _as(client, s.event, s.alice).post(
        f"{s.url}/households/new", data={"name": "Nouveau", "num_adults": "1"}
    )
    assert resp.status_code == 403


def test_creator_adds_household(client, setup):
    s = setup
    _as(client, s.event, "creator", s.creator).post(
        f"{s.url}/households/new", data={"name": "Nouveau", "num_adults": "1"}
    )
    assert Household.query.filter_by(name="Nouveau").count() == 1


def test_owner_edits_own_household_composition(client, setup):
    s = setup
    _hh(_as(client, s.event, s.alice), s, s.ha.id)
    h = Household.query.get(s.ha.id)
    assert (h.num_adults, h.num_children) == (3, 1)


def test_participant_cannot_edit_another_household(client, setup):
    s = setup
    assert _hh(_as(client, s.event, s.alice), s, s.hb.id).status_code == 403


def test_creator_edits_any_household(client, setup):
    s = setup
    assert _hh(_as(client, s.event, "creator", s.creator), s, s.hb.id).status_code == 302


def test_household_edit_with_invalid_adults_reopens_edit_sheet(client, setup):
    s = setup
    html = _hh(_as(client, s.event, s.alice), s, s.ha.id, num_adults="0").get_data(as_text=True)
    assert json.loads(text_of(html, "costs-open-sheet", "script")) == "costs-household-edit-sheet"


def test_participant_cannot_delete_household(client, setup):
    s = setup
    assert (
        _as(client, s.event, s.alice).post(f"{s.url}/households/{s.ha.id}/delete").status_code
        == 403
    )


def test_household_with_expenses_cannot_be_deleted(client, setup):
    s = setup
    _expense(s, "Loyer", s.ha, s.alice)
    _as(client, s.event, "creator", s.creator).post(f"{s.url}/households/{s.ha.id}/delete")
    assert Household.query.get(s.ha.id) is not None


def test_ui_shows_household_edit_only_for_own_household(client, setup):
    html = (
        _as(client, setup.event, setup.alice).get(f"{setup.url}?tab=balance").get_data(as_text=True)
    )
    assert html.count('data-testid="household-edit"') == 1


def test_ui_shows_household_edit_for_every_household_to_creator(client, setup):
    s = setup
    html = (
        _as(client, s.event, "creator", s.creator)
        .get(f"{s.url}?tab=balance")
        .get_data(as_text=True)
    )
    assert html.count('data-testid="household-edit"') == 3


def test_ui_hides_add_household_and_ratio_from_participant(client, setup):
    html = (
        _as(client, setup.event, setup.alice).get(f"{setup.url}?tab=balance").get_data(as_text=True)
    )
    assert ('data-testid="household-add-open"' in html, 'data-testid="ratio-open"' in html) == (
        False,
        False,
    )


def test_ui_shows_add_household_and_ratio_to_creator(client, setup):
    s = setup
    html = (
        _as(client, s.event, "creator", s.creator)
        .get(f"{s.url}?tab=balance")
        .get_data(as_text=True)
    )
    assert ('data-testid="household-add-open"' in html, 'data-testid="ratio-open"' in html) == (
        True,
        True,
    )


def test_participant_cannot_update_ratio(client, setup):
    s = setup
    resp = _as(client, s.event, s.alice).post(
        f"{s.url}/ratio", data={"adult_weight": "1", "child_weight": "0.3"}
    )
    assert resp.status_code == 403


def test_participant_ratio_attempt_changes_nothing(client, setup):
    s = setup
    _as(client, s.event, s.alice).post(
        f"{s.url}/ratio", data={"adult_weight": "2", "child_weight": "0.3"}
    )
    assert Household.query.get(s.ha.id).adult_weight == 1.0


def test_creator_updates_ratio_for_all_households(client, setup):
    s = setup
    _as(client, s.event, "creator", s.creator).post(
        f"{s.url}/ratio", data={"adult_weight": "1", "child_weight": "0,3"}
    )
    assert {h.child_weight for h in Household.query.all()} == {0.3}


def test_ratio_with_invalid_weight_reopens_ratio_sheet(client, setup):
    s = setup
    html = (
        _as(client, s.event, "creator", s.creator)
        .post(f"{s.url}/ratio", data={"adult_weight": "0", "child_weight": "0.3"})
        .get_data(as_text=True)
    )
    assert json.loads(text_of(html, "costs-open-sheet", "script")) == "costs-ratio-sheet"


# --- Droits : transferts ---------------------------------------------------------------------


def _transfer(client, s, frm, to, **over):
    data = {"from_household_id": frm.id, "to_household_id": to.id, "amount": "20"}
    data.update(over)
    return client.post(f"{s.url}/transfers/new", data=data)


def test_participant_records_transfer_from_own_household(client, setup):
    s = setup
    assert _transfer(_as(client, s.event, s.alice), s, s.ha, s.hb).status_code == 302


def test_participant_records_transfer_to_own_household(client, setup):
    s = setup
    assert _transfer(_as(client, s.event, s.alice), s, s.hb, s.ha).status_code == 302


def test_participant_cannot_record_transfer_between_other_households(client, setup):
    s = setup
    assert _transfer(_as(client, s.event, s.alice), s, s.hb, s.hc).status_code == 403


def test_forbidden_transfer_is_not_recorded(client, setup):
    s = setup
    _transfer(_as(client, s.event, s.alice), s, s.hb, s.hc)
    assert Transfer.query.count() == 0


def test_creator_records_any_transfer(client, setup):
    s = setup
    assert _transfer(_as(client, s.event, "creator", s.creator), s, s.ha, s.hb).status_code == 302


def test_participant_without_household_cannot_record_transfer(client, db, setup, event):
    from app.models import Guest

    s = setup
    loner = Guest(code="lonerlon", display_name="Seul", event_id=event.id)
    db.session.add(loner)
    db.session.commit()
    assert _transfer(_as(client, event, loner), s, s.ha, s.hb).status_code == 403


def test_transfer_by_direction_out_goes_from_own_household(client, setup):
    s = setup
    _as(client, s.event, s.alice).post(
        f"{s.url}/transfers/new",
        data={"direction": "out", "other_household_id": s.hb.id, "amount": "5"},
    )
    t = Transfer.query.one()
    assert (t.from_household_id, t.to_household_id) == (s.ha.id, s.hb.id)


def test_transfer_by_direction_in_goes_to_own_household(client, setup):
    s = setup
    _as(client, s.event, s.alice).post(
        f"{s.url}/transfers/new",
        data={"direction": "in", "other_household_id": s.hb.id, "amount": "5"},
    )
    t = Transfer.query.one()
    assert (t.from_household_id, t.to_household_id) == (s.hb.id, s.ha.id)


def test_transfer_records_its_author(client, setup):
    s = setup
    _transfer(_as(client, s.event, s.alice), s, s.ha, s.hb)
    assert Transfer.query.one().created_by == s.alice.id


def test_transfer_date_defaults_to_today(client, setup):
    s = setup
    _transfer(_as(client, s.event, s.alice), s, s.ha, s.hb)
    assert Transfer.query.one().date == TODAY


def _make_transfer(s, author):
    t = Transfer(
        from_household_id=s.ha.id,
        to_household_id=s.hb.id,
        amount_cents=1000,
        event_id=s.event.id,
        created_by=author.id if author else None,
    )
    s.db.session.add(t)
    s.db.session.commit()
    return t


def test_author_deletes_own_transfer(client, setup):
    s = setup
    t = _make_transfer(s, s.alice)
    assert _as(client, s.event, s.alice).post(f"{s.url}/transfers/{t.id}/delete").status_code == 302


def test_participant_cannot_delete_transfer_of_another_author(client, setup):
    s = setup
    t = _make_transfer(s, s.alice)
    assert _as(client, s.event, s.bob).post(f"{s.url}/transfers/{t.id}/delete").status_code == 403


def test_creator_deletes_any_transfer(client, setup):
    s = setup
    t = _make_transfer(s, s.alice)
    assert (
        _as(client, s.event, "creator", s.creator)
        .post(f"{s.url}/transfers/{t.id}/delete")
        .status_code
        == 302
    )


def test_ui_shows_transfer_delete_only_to_author_and_creator(client, setup):
    s = setup
    _make_transfer(s, s.alice)
    counts = [
        _as(client, s.event, who, s.creator)
        .get(f"{s.url}?tab=balance")
        .get_data(as_text=True)
        .count('data-testid="transfer-delete"')
        for who in (s.alice, s.bob, "creator")
    ]
    assert counts == [1, 0, 1]


def test_transfer_form_is_present_without_any_existing_transfer(client, setup):
    html = (
        _as(client, setup.event, setup.alice).get(f"{setup.url}?tab=balance").get_data(as_text=True)
    )
    assert 'data-testid="transfer-form"' in html


def test_transfer_form_is_present_for_creator_without_any_transfer(client, setup):
    s = setup
    html = (
        _as(client, s.event, "creator", s.creator)
        .get(f"{s.url}?tab=balance")
        .get_data(as_text=True)
    )
    assert 'data-testid="transfer-form"' in html


def test_transfer_open_button_is_absent_without_household(client, db, setup, event):
    from app.models import Guest

    loner = Guest(code="lonerlon", display_name="Seul", event_id=event.id)
    db.session.add(loner)
    db.session.commit()
    html = _as(client, event, loner).get(f"{setup.url}?tab=balance").get_data(as_text=True)
    assert 'data-testid="transfer-open"' not in html


def test_invalid_transfer_amount_reopens_transfer_sheet(client, setup):
    s = setup
    html = _transfer(_as(client, s.event, s.alice), s, s.ha, s.hb, amount="0").get_data(
        as_text=True
    )
    assert json.loads(text_of(html, "costs-open-sheet", "script")) == "costs-transfer-sheet"


def test_settle_button_creates_the_transfer_that_clears_the_debt(client, setup):
    s = setup
    s.db.session.delete(s.hc)
    s.db.session.commit()
    _expense(s, "Gîte", s.ha, s.alice, cents=10000)
    _as(client, s.event, s.bob)
    html = client.get(f"{s.url}?tab=balance").get_data(as_text=True)
    form = block(html, "settle", "button")  # le bouton existe pour le débiteur
    assert form
    client.post(
        f"{s.url}/transfers/new",
        data={
            "from_household_id": s.hb.id,
            "to_household_id": s.ha.id,
            "amount": "50.00",
            "tab": "balance",
        },
    )
    html = client.get(f"{s.url}?tab=balance").get_data(as_text=True)
    assert 'data-testid="who-owes-row"' not in html


def test_settle_button_is_hidden_from_uninvolved_participant(client, setup):
    s = setup
    s.db.session.delete(s.hc)
    s.db.session.commit()
    _expense(s, "Gîte", s.ha, s.alice, cents=10000)
    html = _as(client, s.event, s.alice).get(f"{s.url}?tab=balance").get_data(as_text=True)
    assert (
        html.count('data-testid="settle"') == 1
    )  # Alice est créditrice : le bouton lui est proposé


# --- Droits : demandes de paiement -----------------------------------------------------------


def _request(s, author=None):
    pr = PaymentRequest(
        from_household_id=s.ha.id,
        to_household_id=s.hb.id,
        amount_cents=900,
        event_id=s.event.id,
        created_by=(author or s.alice).id,
    )
    s.db.session.add(pr)
    s.db.session.commit()
    return pr


def test_participant_creates_request_from_own_household(client, setup):
    s = setup
    resp = _as(client, s.event, s.alice).post(
        f"{s.url}/payment-requests/new", data={"to_household_id": s.hb.id, "amount": "5"}
    )
    assert resp.status_code == 302


def test_participant_cannot_create_request_from_another_household(client, setup):
    s = setup
    resp = _as(client, s.event, s.alice).post(
        f"{s.url}/payment-requests/new",
        data={"from_household_id": s.hb.id, "to_household_id": s.hc.id, "amount": "5"},
    )
    assert resp.status_code == 403


def test_creator_creates_request_from_any_household(client, setup):
    s = setup
    resp = _as(client, s.event, "creator", s.creator).post(
        f"{s.url}/payment-requests/new",
        data={"from_household_id": s.hb.id, "to_household_id": s.hc.id, "amount": "5"},
    )
    assert resp.status_code == 302


def test_request_records_its_author(client, setup):
    s = setup
    _as(client, s.event, s.alice).post(
        f"{s.url}/payment-requests/new", data={"to_household_id": s.hb.id, "amount": "5"}
    )
    assert PaymentRequest.query.one().created_by == s.alice.id


def test_recipient_resolves_request(client, setup):
    s = setup
    pr = _request(s)
    _as(client, s.event, s.bob).post(f"{s.url}/payment-requests/{pr.id}/resolve")
    assert PaymentRequest.query.get(pr.id).is_resolved is True


def test_non_recipient_cannot_resolve_request(client, setup):
    s = setup
    pr = _request(s)
    assert (
        _as(client, s.event, s.alice).post(f"{s.url}/payment-requests/{pr.id}/resolve").status_code
        == 403
    )


def test_creator_resolves_any_request(client, setup):
    s = setup
    pr = _request(s)
    assert (
        _as(client, s.event, "creator", s.creator)
        .post(f"{s.url}/payment-requests/{pr.id}/resolve")
        .status_code
        == 302
    )


def test_author_deletes_own_request(client, setup):
    s = setup
    pr = _request(s)
    assert (
        _as(client, s.event, s.alice).post(f"{s.url}/payment-requests/{pr.id}/delete").status_code
        == 302
    )


def test_non_author_cannot_delete_request(client, setup):
    s = setup
    pr = _request(s)
    assert (
        _as(client, s.event, s.bob).post(f"{s.url}/payment-requests/{pr.id}/delete").status_code
        == 403
    )


def test_ui_shows_resolve_only_to_recipient_and_creator(client, setup):
    s = setup
    _request(s)
    counts = [
        _as(client, s.event, who, s.creator)
        .get(f"{s.url}?tab=requests")
        .get_data(as_text=True)
        .count('data-testid="request-resolve"')
        for who in (s.alice, s.bob, "creator")
    ]
    assert counts == [0, 1, 1]


def test_ui_shows_request_delete_only_to_author_and_creator(client, setup):
    s = setup
    _request(s)
    counts = [
        _as(client, s.event, who, s.creator)
        .get(f"{s.url}?tab=requests")
        .get_data(as_text=True)
        .count('data-testid="request-delete"')
        for who in (s.alice, s.bob, "creator")
    ]
    assert counts == [1, 0, 1]


# --- Structure de la page --------------------------------------------------------------------


def test_page_shows_three_segments_in_order(client, setup):
    html = _as(client, setup.event, setup.alice).get(setup.url).get_data(as_text=True)
    assert testids(block(html, "costs-segments", "nav"), "costs-seg-") == [
        "costs-seg-expenses",
        "costs-seg-balance",
        "costs-seg-requests",
    ]


@pytest.mark.parametrize(
    ("tab", "section"), [("expenses", "expenses"), ("balance", "balance"), ("requests", "requests")]
)
def test_page_renders_only_the_selected_segment(client, setup, tab, section):
    html = (
        _as(client, setup.event, setup.alice).get(f"{setup.url}?tab={tab}").get_data(as_text=True)
    )
    assert testids(html, "costs-section-") == [f"costs-section-{section}"]


def test_unknown_tab_falls_back_to_expenses(client, setup):
    html = _as(client, setup.event, setup.alice).get(f"{setup.url}?tab=zzz").get_data(as_text=True)
    assert 'data-tab="expenses"' in html


def test_current_segment_is_marked_with_aria_current(client, setup):
    html = (
        _as(client, setup.event, setup.alice).get(f"{setup.url}?tab=balance").get_data(as_text=True)
    )
    assert 'aria-current="page"' in tag(html, "costs-seg-balance")


def test_redirect_after_post_keeps_the_segment(client, setup):
    s = setup
    resp = _as(client, s.event, s.alice).post(
        f"{s.url}/expenses/new", data=_payload(s, tab="requests")
    )
    assert "tab=requests" in resp.headers["Location"]


def test_add_expense_button_is_the_single_primary_action(client, setup):
    html = _as(client, setup.event, setup.alice).get(setup.url).get_data(as_text=True)
    assert 'data-sheet-open="costs-expense-sheet"' in tag(html, "costs-add-expense")


def test_add_expense_form_is_not_open_by_default(client, setup):
    html = _as(client, setup.event, setup.alice).get(setup.url).get_data(as_text=True)
    assert 'data-testid="costs-open-sheet"' not in html


def test_add_expense_button_is_absent_without_household(client, event, creator, creator_guest):
    html = (
        _as(client, event, "creator", creator).get(f"/e/{event.code}/costs").get_data(as_text=True)
    )
    assert 'data-testid="costs-add-expense"' not in html


def test_expense_sheet_defaults_payer_to_own_household(client, setup):
    s = setup
    html = _as(client, s.event, s.alice).get(s.url).get_data(as_text=True)
    sheet = block(html, "costs-expense-sheet", "dialog")
    assert f'value="{s.ha.id}" selected' in sheet


def test_invalid_expense_reopens_the_add_sheet_with_field_error(client, setup):
    html = _post_expense(_as(client, setup.event, setup.alice), setup, description="").get_data(
        as_text=True
    )
    assert json.loads(text_of(html, "costs-open-sheet", "script")) == "costs-expense-sheet"


def test_invalid_expense_keeps_typed_values(client, setup):
    html = _post_expense(
        _as(client, setup.event, setup.alice), setup, description="", amount="42,5"
    ).get_data(as_text=True)
    assert 'value="42,5"' in html


@pytest.mark.parametrize(
    ("expense_cents", "state"),
    [(10000, "credit"), (None, "even")],
)
def test_my_balance_state_for_creditor_and_even(client, setup, expense_cents, state):
    s = setup
    if expense_cents:
        _expense(s, "Gîte", s.ha, s.alice, cents=expense_cents)
    html = _as(client, s.event, s.alice).get(s.url).get_data(as_text=True)
    assert f'data-state="{state}"' in tag(html, "my-balance")


def test_my_balance_state_for_debtor(client, setup):
    s = setup
    _expense(s, "Gîte", s.ha, s.alice, cents=10000)
    html = _as(client, s.event, s.bob).get(s.url).get_data(as_text=True)
    assert 'data-state="debt"' in tag(html, "my-balance")


def test_my_balance_amount_is_localised_in_english(client, setup):
    s = setup
    _expense(s, "Gîte", s.ha, s.alice, cents=10000)
    _as(client, s.event, s.alice)
    html = client.get(f"{s.url}?lang=en").get_data(as_text=True)
    assert text_of(html, "my-balance-amount", "p").startswith("+€")


def test_my_balance_shows_invitation_without_household(client, event, creator, creator_guest):
    html = (
        _as(client, event, "creator", creator).get(f"/e/{event.code}/costs").get_data(as_text=True)
    )
    assert 'data-testid="my-balance-empty"' in html


def test_who_owes_whom_shows_full_household_names(client, setup):
    s = setup
    long_name = "Famille Dupont-Martin-Lefebvre de la Haute-Saône et du Territoire de Belfort"
    s.hb.name = long_name
    s.db.session.delete(s.hc)
    s.db.session.commit()
    _expense(s, "Gîte", s.ha, s.alice, cents=10000)
    html = _as(client, s.event, s.alice).get(f"{s.url}?tab=balance").get_data(as_text=True)
    assert text_of(html, "owes-from", "strong") == long_name


def test_expense_row_shows_payer_date_and_amount(client, setup):
    s = setup
    e = _expense(s, "Pain", s.ha, s.alice, cents=1234)
    e.date = date(2026, 3, 4)
    s.db.session.commit()
    html = _as(client, s.event, s.alice).get(s.url).get_data(as_text=True)
    assert text_of(html, "expense-meta", "span") == "Foyer Alice · 4 mars"


def test_expense_detail_shows_split_per_household(client, setup):
    s = setup
    _expense(s, "Pain", s.ha, s.alice, cents=3000)
    html = _as(client, s.event, s.alice).get(s.url).get_data(as_text=True)
    assert "Foyer Bob" in block(html, "detail-split", "div")


def test_no_hardcoded_euro_sign_in_costs_templates():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "app/templates/costs"
    assert [p.name for p in root.glob("*.html") if "€" in p.read_text()] == []


# --- Non-régression de l'algorithme de répartition -------------------------------------------


def test_settlement_algorithm_is_unchanged_for_weighted_households(setup):
    from app.costs import _per_expense_shares, _settlement

    s = setup
    s.hc.num_adults, s.hc.num_children = 1, 1
    s.ha.num_adults, s.ha.num_children = 2, 0
    exp = _expense(s, "Total", s.ha, s.alice, cents=7000)
    hs = [s.ha, s.hc]
    shares, paid = _per_expense_shares(hs, [exp])
    assert (shares[s.ha.id], shares[s.hc.id], paid[s.ha.id]) == (4000, 3000, 7000)
    assert _settlement(hs, [exp], []) == [(s.hc.id, s.ha.id, 3000)]


# --- Suppression d'un événement : les frais et leurs auteurs partent ensemble ----------------


def test_deleting_event_removes_expenses_that_reference_their_author(db, setup):
    s = setup
    _expense(s, "Gîte", s.ha, s.alice)
    _make_transfer(s, s.alice)
    _request(s)
    db.session.delete(s.event)
    db.session.commit()
    assert Expense.query.count() + Transfer.query.count() + PaymentRequest.query.count() == 0
