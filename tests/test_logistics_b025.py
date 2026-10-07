"""Infos pratiques refondues (B025b, 25.2) : cartes, ordre logique, copie, feuille HTMX."""

import re
from datetime import date, datetime, timedelta

import pytest
from tests.ui_helpers import block, tag, testids

from app.infos import linkify
from app.models import Event, LogisticsItem

HX = {"HX-Request": "true"}


def _add(db, event, title, category="general", content="c", order=0, age=0):
    item = LogisticsItem(
        title=title,
        content=content,
        category=category,
        order=order,
        event_id=event.id,
        created_at=datetime(2026, 10, 1) + timedelta(minutes=age),  # noqa: DTZ001
    )
    db.session.add(item)
    db.session.commit()
    return item


def _index(client, event):
    return client.get(f"/e/{event.code}/logistics").data.decode()


def _titles(html):
    return re.findall(r'data-testid="info-title"[^>]*>([^<]*)<', html)


@pytest.fixture
def other_event(db, creator):
    e = Event(
        code="OTHER1",
        title="Autre",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 2),
        creator_id=creator.id,
        verified_at=datetime.utcnow(),
    )
    db.session.add(e)
    db.session.commit()
    return e


# --- Ordre -------------------------------------------------------------------


def test_index_orders_categories_in_registry_order(db, creator_client, event):
    for cat in ("general", "notes", "docs", "timing", "access", "address"):
        _add(db, event, cat, cat)
    html = _index(creator_client, event)
    got = re.findall(r'data-testid="info-category" data-category="([a-z]+)"', html)
    assert got == ["address", "access", "timing", "docs", "notes", "general"]


def test_index_orders_unknown_category_last(db, creator_client, event):
    _add(db, event, "Zed", "zzz")
    _add(db, event, "Gen", "general")
    assert _titles(_index(creator_client, event)) == ["Gen", "Zed"]


def test_index_orders_items_in_category_by_order_then_age(db, creator_client, event):
    _add(db, event, "Ancien", "notes", order=0, age=1)
    _add(db, event, "Recent", "notes", order=0, age=5)
    _add(db, event, "Premier", "notes", order=-1, age=9)
    assert _titles(_index(creator_client, event)) == ["Premier", "Ancien", "Recent"]


# --- Champ « ordre » ---------------------------------------------------------


@pytest.mark.parametrize("suffix", ["", "/new"])
def test_pages_have_no_order_field(db, creator_client, event, suffix):
    html = creator_client.get(f"/e/{event.code}/logistics{suffix}").data.decode()
    assert 'name="order"' not in html


def test_edit_page_has_no_order_field(db, creator_client, event):
    item = _add(db, event, "A")
    html = creator_client.get(f"/e/{event.code}/logistics/{item.id}/edit").data.decode()
    assert 'name="order"' not in html


def test_create_ignores_posted_order(db, creator_client, event):
    creator_client.post(
        f"/e/{event.code}/logistics/new", data={"title": "Parking", "content": "x", "order": "7"}
    )
    assert LogisticsItem.query.filter_by(title="Parking").one().order == 0


def test_edit_keeps_existing_order(db, creator_client, event):
    item = _add(db, event, "A", order=4)
    creator_client.post(
        f"/e/{event.code}/logistics/{item.id}/edit",
        data={"title": "AA", "content": "x", "category": "notes", "order": "9"},
    )
    db.session.refresh(item)
    assert item.order == 4


# --- Cartes ------------------------------------------------------------------


def test_card_copy_button_carries_content(db, creator_client, event):
    _add(db, event, "Code", content="A1B2")
    assert 'data-copy="A1B2"' in tag(_index(creator_client, event), "info-copy")


def test_card_preserves_line_breaks_in_content(db, creator_client, event):
    _add(db, event, "Adresse", content="12 rue\n67000 Strasbourg")
    body = block(_index(creator_client, event), "info-content", "p")
    assert "12 rue\n67000 Strasbourg" in body


def test_card_links_http_urls_in_content(db, creator_client, event):
    _add(db, event, "Site", content="Voir https://example.org/a?b=1&c=2.")
    body = block(_index(creator_client, event), "info-content", "p")
    assert 'href="https://example.org/a?b=1&amp;c=2"' in body


def test_card_link_opens_safely(db, creator_client, event):
    _add(db, event, "Site", content="https://example.org")
    assert 'rel="noopener noreferrer"' in block(_index(creator_client, event), "info-content", "p")


def test_card_does_not_link_javascript_scheme(db, creator_client, event):
    _add(db, event, "X", content="javascript:alert(1) et ftp://x.org")
    assert "<a " not in block(_index(creator_client, event), "info-content", "p")


def test_card_escapes_html_in_title(db, creator_client, event):
    _add(db, event, "<script>alert(1)</script>")
    assert "<script>alert(1)" not in _index(creator_client, event)


def test_card_escapes_html_in_content(db, creator_client, event):
    _add(db, event, "T", content="<img src=x onerror=alert(1)>")
    assert "<img src=x" not in _index(creator_client, event)


def test_linkify_escapes_quotes_in_url():
    assert '"onmouseover' not in str(linkify('https://a.org/"onmouseover=1'))


def test_linkify_keeps_text_without_url_escaped():
    assert str(linkify("a < b & c")) == "a &lt; b &amp; c"


def test_index_empty_state_shows_add_action(creator_client, event):
    assert "info-add" in testids(_index(creator_client, event), "info-add")


def test_index_has_single_primary_add_button(db, creator_client, event):
    html = _index(creator_client, event)
    assert len(re.findall(r'data-testid="info-add"[^>]*>', html)) == 1


# --- Droits ------------------------------------------------------------------


def test_guest_sees_edit_but_no_delete_on_card(db, guest_client, event):
    _add(db, event, "A")
    ids = testids(_index(guest_client, event), "info-")
    assert ("info-edit" in ids, "info-delete" in ids) == (True, False)


def test_creator_sees_delete_on_card(db, creator_client, event):
    _add(db, event, "A")
    assert "info-delete" in testids(_index(creator_client, event), "info-")


def test_guest_delete_is_forbidden(db, guest_client, event):
    item = _add(db, event, "A")
    assert guest_client.post(f"/e/{event.code}/logistics/{item.id}/delete").status_code == 403


def test_edit_info_of_other_event_is_404(db, creator_client, event, other_event):
    item = _add(db, other_event, "Autre")
    assert (
        creator_client.post(
            f"/e/{event.code}/logistics/{item.id}/edit", data={"title": "ZZ", "content": "x"}
        ).status_code
        == 404
    )


def test_delete_info_of_other_event_is_404(db, creator_client, event, other_event):
    item = _add(db, other_event, "Autre")
    assert creator_client.post(f"/e/{event.code}/logistics/{item.id}/delete").status_code == 404


# --- HTMX / feuille ----------------------------------------------------------


def test_index_contains_bottom_sheet_form(db, creator_client, event):
    assert 'data-testid="info-sheet"' in _index(creator_client, event)


def test_htmx_create_returns_list_fragment(db, creator_client, event):
    r = creator_client.post(
        f"/e/{event.code}/logistics/new", data={"title": "Wifi", "content": "pwd"}, headers=HX
    )
    assert (r.status_code, 'data-testid="infos-list"' in r.text, "Wifi" in r.text) == (
        200,
        True,
        True,
    )


def test_htmx_create_sends_toast_trigger(db, creator_client, event):
    r = creator_client.post(
        f"/e/{event.code}/logistics/new", data={"title": "Wifi", "content": "pwd"}, headers=HX
    )
    assert "ui:toast" in r.headers["HX-Trigger"]


def test_htmx_create_error_retargets_form_with_field_error(db, creator_client, event):
    r = creator_client.post(
        f"/e/{event.code}/logistics/new", data={"title": "W", "content": ""}, headers=HX
    )
    assert (r.headers["HX-Retarget"], 'data-testid="err-title"' in r.text) == (
        "#info-sheet-form",
        True,
    )


def test_htmx_create_error_does_not_create(db, creator_client, event):
    creator_client.post(f"/e/{event.code}/logistics/new", data={"title": "W"}, headers=HX)
    assert LogisticsItem.query.count() == 0


def test_plain_create_redirects(db, creator_client, event):
    r = creator_client.post(
        f"/e/{event.code}/logistics/new", data={"title": "Wifi", "content": "p"}
    )
    assert r.status_code == 302


def test_htmx_edit_returns_list_fragment_with_new_title(db, creator_client, event):
    item = _add(db, event, "Ancien")
    r = creator_client.post(
        f"/e/{event.code}/logistics/{item.id}/edit",
        data={"title": "Nouveau", "content": "x", "category": "notes"},
        headers=HX,
    )
    assert (r.status_code, "Nouveau" in r.text, "Ancien" in r.text) == (200, True, False)


def test_htmx_delete_returns_list_fragment_without_item(db, creator_client, event):
    item = _add(db, event, "Bye")
    _add(db, event, "Reste")
    r = creator_client.post(f"/e/{event.code}/logistics/{item.id}/delete", headers=HX)
    assert ("Bye" in r.text, "Reste" in r.text) == (False, True)


def test_delete_form_asks_confirmation(db, creator_client, event):
    _add(db, event, "A")
    assert "data-confirm=" in tag(_index(creator_client, event), "info-delete-form")


def test_new_page_is_sectioned_form_without_js(creator_client, event):
    assert 'data-testid="info-form"' in creator_client.get(f"/e/{event.code}/logistics/new").text


# --- Accueil -----------------------------------------------------------------


def test_home_shows_first_three_infos_in_logical_order(db, creator_client, event):
    for cat in ("general", "notes", "timing", "address"):
        _add(db, event, f"I-{cat}", cat)
    html = creator_client.get(f"/e/{event.code}").data.decode()
    got = re.findall(r'data-testid="info-item".*?<p[^>]*>([^<]*)</p>', html, re.S)
    assert got == ["I-address", "I-timing", "I-notes"]
