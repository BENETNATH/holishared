"""B018 — messages serveur traduits, erreurs par champ, vouvoiement."""

import re


def _post_create(client, lang, **over):
    data = {
        "title": "Fête",
        "start_date": "2026-12-01",
        "end_date": "2026-12-03",
        "email": "alice@example.com",
    }
    data.update(over)
    return client.post(f"/e/new?lang={lang}", data=data)


def test_create_errors_attach_to_their_field_not_to_a_french_substring(client):
    # En anglais, plus aucun mot français ne peut servir d'indice : seul le champ compte.
    html = _post_create(client, "en", title="", end_date="").get_data(as_text=True)
    assert 'id="f-title-error"' in html
    assert 'id="f-end_date-error"' in html
    assert 'id="f-email-error"' not in html
    assert re.search(r'id="title"[^>]*aria-invalid="true"', html)
    assert "Title required." in html
    assert "End date required." in html


def test_create_errors_are_translated(client):
    html = _post_create(client, "fr", email="nope").get_data(as_text=True)
    assert "Format d&#39;email invalide." in html or "Format d'email invalide." in html
    html = _post_create(client, "en", email="nope").get_data(as_text=True)
    assert "Invalid email format." in html


def test_create_invalid_start_date_is_reported_on_start_date_only(client):
    html = _post_create(client, "en", start_date="31/12/2026").get_data(as_text=True)
    assert 'id="f-start_date-error"' in html
    assert 'id="f-end_date-error"' not in html


def test_duration_error_uses_plural_forms(client):
    html = _post_create(client, "en", end_date="2030-01-01").get_data(as_text=True)
    assert re.search(r"Max\. duration: \d+ days\.", html)


def test_planning_form_errors_are_per_field(creator_client, event):
    resp = creator_client.post(
        f"/e/{event.code}/planning/new?lang=en",
        data={"title": "x", "date": "2030-01-01", "start_time": "10:00", "end_time": "09:00"},
    )
    html = resp.get_data(as_text=True)
    assert 'id="f-title-error"' in html
    assert 'id="f-date-error"' in html
    assert 'id="f-end_time-error"' in html
    assert "Date outside the event period." in html
    assert "Missing" not in html


def test_planning_missing_date_has_its_own_message(creator_client, event):
    html = creator_client.post(
        f"/e/{event.code}/planning/new?lang=fr", data={"title": "Rando"}
    ).get_data(as_text=True)
    assert "Date requise." in html
    assert "Date hors de la période" not in html


def test_join_errors_render_inline_per_field(client, event, creator):
    html = client.post(
        f"/e/{event.code}/join?lang=en", data={"display_name": "", "code": "ab"}
    ).get_data(as_text=True)
    assert 'id="f-display_name-error"' in html
    assert 'id="f-code-error"' in html


def test_flashes_are_translated(creator_client, db, event, creator_guest):
    resp = creator_client.post(
        f"/e/{event.code}/costs/households/new?lang=en", data={"name": "x"}, follow_redirects=True
    )
    assert "Household name required (min. 2 characters)." in resp.get_data(as_text=True)
    resp = creator_client.post(
        f"/e/{event.code}/costs/households/new?lang=fr", data={"name": "x"}, follow_redirects=True
    )
    assert "Nom du foyer requis (min 2 caractères)." in resp.get_data(as_text=True)


def test_household_default_name_follows_request_language(app):
    from app.i18n import household_default_name

    with app.app_context(), app.test_request_context("/?lang=en"):
        assert household_default_name("Alice") == "Alice household"
    assert household_default_name("Alice") == "Foyer Alice"


def test_expense_errors_are_flashed_and_translated(creator_client, event):
    resp = creator_client.post(
        f"/e/{event.code}/costs/expenses/new?lang=en", data={}, follow_redirects=True
    )
    html = resp.get_data(as_text=True)
    assert "Description required." in html
    assert "Invalid amount." in html


def test_source_catalog_uses_formal_address():
    """Aucun tutoiement dans le catalogue source (msgids)."""
    from pathlib import Path

    pot = (Path(__file__).resolve().parent.parent / "translations" / "messages.pot").read_text()
    ids = re.findall(r'^msgid "(.*)"$', pot, re.M)
    informal = re.compile(
        r"\b(ton|ta|tes|toi|tu|te|t')\b|\b(clique|saisis|indique|choisis|ajoute|crée)\b",
        re.I,
    )
    offenders = [i for i in ids if informal.search(i)]
    assert offenders == []


def test_paywall_feature_labels_and_js_strings_are_translated(app):
    from app.freemium import FALLBACK_FEATURE_LABEL, FEATURE_LABELS
    from app.ui import ui_strings

    with app.app_context(), app.test_request_context("/?lang=en"):
        assert str(FEATURE_LABELS["pdf_export"]) == "Certified accountancy PDF export"
        assert str(FALLBACK_FEATURE_LABEL) == "Advanced feature"
        assert ui_strings()["lists_noted"] == "Noted"
    with app.app_context(), app.test_request_context("/?lang=fr"):
        assert ui_strings()["lists_noted"] == "C'est noté"


def test_list_claim_script_has_no_hardcoded_french():
    from pathlib import Path

    html = (Path(__file__).resolve().parent.parent / "app/templates/lists/detail.html").read_text()
    assert "not\\u00e9" not in html
    assert "ui-strings" in html
