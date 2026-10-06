"""Menu « Événement », « Mon code » et « Gérer l'événement » (B020a, 20.2)."""

import pytest
from tests.ui_helpers import block, tag, testids, text_of

from app.models import Event


def _html(resp):
    return resp.data.decode()


def _sheet(client, event):
    return block(_html(client.get(f"/e/{event.code}")), "more-sheet", "dialog")


# --- Menu ---------------------------------------------------------------------


def test_event_menu_guest_has_share_log_and_my_code(guest_client, event):
    group = ("more-item-share", "more-item-log", "more-item-me", "more-item-manage")
    ids = testids(_sheet(guest_client, event), "more-item-")
    assert [i for i in ids if i in group] == ["more-item-share", "more-item-log", "more-item-me"]


def test_event_menu_creator_has_manage_entry(creator_client, event):
    assert "more-item-manage" in testids(_sheet(creator_client, event), "more-item-")


def test_event_menu_share_entry_copies_join_url(app, guest_client, event):
    app.config["APP_URL"] = "https://holi.example"
    html = _html(guest_client.get(f"/e/{event.code}"))
    assert f'data-copy="https://holi.example/e/{event.code}/join"' in tag(html, "more-item-share")


def test_event_menu_my_code_item_is_active_on_my_code_page(guest_client, event):
    html = _html(guest_client.get(f"/e/{event.code}/me"))
    assert 'aria-current="page"' in tag(html, "more-item-me")


def test_event_menu_manage_item_is_active_on_manage_page(creator_client, event):
    html = _html(creator_client.get(f"/e/{event.code}/manage"))
    assert 'aria-current="page"' in tag(html, "more-item-manage")


@pytest.mark.parametrize(
    ("endpoint", "expected"), [("events.me", "me"), ("events.manage", "manage")]
)
def test_nav_section_maps_new_event_pages(endpoint, expected):
    from app.ui import nav_section

    assert nav_section(endpoint) == expected


# --- Mon code -------------------------------------------------------------------


def test_my_code_page_shows_guest_code_masked(guest_client, event, guest):
    html = _html(guest_client.get(f"/e/{event.code}/me"))
    assert (guest.code in html, 'data-masked="true"' in tag(html, "my-code")) == (True, True)


def test_my_code_page_for_creator_shows_personal_code(db, creator_client, event, creator):
    creator.personal_code = "crea2345"
    db.session.commit()
    assert "crea2345" in text_of(
        _html(creator_client.get(f"/e/{event.code}/me")), "my-code", "code"
    )


def test_my_code_page_creator_without_code_explains(creator_client, event):
    html = _html(creator_client.get(f"/e/{event.code}/me"))
    assert "my-code-none" in html


def test_my_code_page_for_visitor_redirects_to_code_entry(client, event):
    assert client.get(f"/e/{event.code}/me").status_code == 302


# --- Gérer l'événement -------------------------------------------------------------


def test_manage_page_guest_gets_403(guest_client, event):
    assert guest_client.get(f"/e/{event.code}/manage").status_code == 403


def test_manage_page_visitor_is_redirected(client, event):
    assert client.get(f"/e/{event.code}/manage").status_code == 302


def test_manage_page_creator_gets_200(creator_client, event):
    assert creator_client.get(f"/e/{event.code}/manage").status_code == 200


def test_manage_page_links_to_zip_export(creator_client, event):
    html = _html(creator_client.get(f"/e/{event.code}/manage"))
    assert f'href="/e/{event.code}/export"' in tag(html, "export-zip")


def test_manage_export_link_downloads_zip(creator_client, event):
    resp = creator_client.get(f"/e/{event.code}/export")
    assert resp.mimetype == "application/zip"


def test_manage_pdf_status_free_tier_mentions_vacances_plus(creator_client, event):
    html = _html(creator_client.get(f"/e/{event.code}/manage"))
    assert "Vacances+" in text_of(html, "export-pdf-status", "div")


def test_manage_pdf_status_has_no_action_button(creator_client, event):
    html = _html(creator_client.get(f"/e/{event.code}/manage"))
    assert "<a" not in block(html, "export-pdf-status", "div")


def test_manage_pdf_status_pro_tier_is_honest_not_available(db, creator_client, event, creator):
    creator.tier = "pro"
    db.session.commit()
    html = _html(creator_client.get(f"/e/{event.code}/manage"))
    assert "pas encore disponible" in text_of(html, "export-pdf-status", "div")


def test_manage_delete_form_requires_strong_confirmation(creator_client, event):
    html = _html(creator_client.get(f"/e/{event.code}/manage"))
    form = block(html, "manage-danger", "section")
    assert "data-confirm=" in form


def test_manage_delete_confirmation_names_the_event(creator_client, event):
    html = _html(creator_client.get(f"/e/{event.code}/manage"))
    assert "Test Vacation" in tag(html, "delete-form")


def test_manage_delete_form_posts_to_delete_route(creator_client, event):
    html = _html(creator_client.get(f"/e/{event.code}/manage"))
    assert f'action="/e/{event.code}/delete"' in html


def test_manage_mentions_purge_after_thirty_days(creator_client, event):
    html = _html(creator_client.get(f"/e/{event.code}/manage"))
    assert "30 jours" in text_of(html, "manage-danger", "section")


def test_manage_delete_post_removes_event(db, creator_client, event):
    code = event.code
    creator_client.post(f"/e/{code}/delete")
    assert Event.query.filter_by(code=code).first() is None


def test_manage_delete_post_by_guest_is_forbidden(guest_client, event):
    assert guest_client.post(f"/e/{event.code}/delete").status_code == 403
