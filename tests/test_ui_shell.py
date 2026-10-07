"""B017 — responsive shell, navigation, shared JS hooks (spec §4, §7, §11.2)."""

import json
import re
from datetime import date, datetime
from pathlib import Path

import pytest

from app.extensions import db as _db
from app.models import Creator, Event, Guest, generate_event_code
from ui_helpers import block, tag, testids, text_of

REPO = Path(__file__).resolve().parents[1]


def _html(resp) -> str:
    return resp.data.decode()


def _json_script(html: str, attrs_regex: str) -> dict:
    match = re.search(rf"<script[^>]*{attrs_regex}[^>]*>(.*?)</script>", html, re.S)
    if match is None:
        raise AssertionError(f"script {attrs_regex} absent")
    return json.loads(match.group(1))


def _creator_with_verified_event(application):
    creator = Creator(email="b017@test.com", email_verified=True, display_name="Camille")
    _db.session.add(creator)
    _db.session.commit()
    event = Event(
        code=generate_event_code(),
        title="Gated",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 7),
        creator_id=creator.id,
        verified_at=datetime.utcnow(),
    )
    _db.session.add(event)
    _db.session.commit()
    client = application.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = creator.id
        s["_fresh"] = True
    return client, event


# --- <head> -----------------------------------------------------------------


def test_base_stylesheet_uses_fingerprinted_app_css(client):
    html = _html(client.get("/"))
    assert re.search(r'href="/static/css/app\.css\?v=[0-9a-f]{10}"', html)


def test_base_does_not_reference_legacy_main_css(client):
    html = _html(client.get("/"))
    assert "main.css" not in html


def test_base_viewport_meta_has_viewport_fit_cover(client):
    html = _html(client.get("/"))
    assert "viewport-fit=cover" in html


def test_theme_script_precedes_stylesheet_in_head(client):
    html = _html(client.get("/"))
    assert 0 <= html.find("setAttribute('data-theme'") < html.index("css/app.css")


def test_base_has_single_module_script(client):
    html = _html(client.get("/"))
    assert html.count('type="module"') == 1


def test_importmap_lists_every_ui_module(client):
    html = _html(client.get("/"))
    imports = _json_script(html, r'type="importmap"')["imports"]
    expected = {"ui/" + p.stem for p in (REPO / "app/static/js/ui").glob("*.js")}
    assert set(imports) == expected


def test_base_has_importmap_and_no_inline_event_handlers(client):
    html = _html(client.get("/"))
    assert 'type="importmap"' in html
    assert not re.search(r'\son[a-z]+="', html)


def test_htmx_script_is_deferred_and_fingerprinted(client):
    html = _html(client.get("/"))
    assert re.search(r'<script src="/static/js/htmx\.min\.js\?v=[0-9a-f]{10}" defer>', html)


# --- Navigation contexts -----------------------------------------------------


def test_landing_bottom_nav_has_global_context(client):
    html = _html(client.get("/"))
    assert 'data-context="global"' in tag(html, "nav-bottom")


def test_landing_bottom_nav_has_no_event_tabs(client):
    html = _html(client.get("/"))
    assert testids(block(html, "nav-bottom", "nav"), "tab-") == ["tab-landing", "tab-create"]


def test_global_nav_shows_events_tab_for_authenticated_creator(creator_client):
    html = _html(creator_client.get("/"))
    assert testids(block(html, "nav-bottom", "nav"), "tab-") == [
        "tab-landing",
        "tab-create",
        "tab-events",
    ]


def test_event_page_bottom_nav_has_event_context_for_creator(creator_client, event):
    html = _html(creator_client.get(f"/e/{event.code}"))
    assert 'data-context="event"' in tag(html, "nav-bottom")


def test_event_page_bottom_nav_has_event_context_for_guest(guest_client, event):
    html = _html(guest_client.get(f"/e/{event.code}"))
    assert 'data-context="event"' in tag(html, "nav-bottom")


def test_join_page_uses_global_nav_for_anonymous(client, event):
    html = _html(client.get(f"/e/{event.code}/join"))
    assert 'data-context="global"' in tag(html, "nav-bottom")


def test_bottom_nav_order_with_all_modules_enabled(guest_client, event):
    html = _html(guest_client.get(f"/e/{event.code}"))
    assert testids(block(html, "nav-bottom", "nav"), "tab-") == [
        "tab-home",
        "tab-planning",
        "tab-meals",
        "tab-lists",
        "tab-costs",
        "tab-more",
    ]


def test_bottom_nav_promotes_secondary_modules_when_primary_disabled(app_factory):
    application = app_factory({"ENABLED_MODULES": "planning,voting,chat"})
    client, event = _creator_with_verified_event(application)
    html = _html(client.get(f"/e/{event.code}/planning"))
    assert testids(block(html, "nav-bottom", "nav"), "tab-") == [
        "tab-home",
        "tab-planning",
        "tab-voting",
        "tab-chat",
        "tab-more",
    ]


def test_bottom_nav_keeps_more_tab_when_no_module_enabled(app_factory):
    application = app_factory({"ENABLED_MODULES": ""})
    client, event = _creator_with_verified_event(application)
    html = _html(client.get(f"/e/{event.code}/members"))
    assert testids(block(html, "nav-bottom", "nav"), "tab-") == ["tab-home", "tab-more"]


# --- "Plus" sheet ------------------------------------------------------------


def test_more_sheet_lists_remaining_modules_in_order(guest_client, event):
    from app.ui import PRIMARY_ORDER

    sheet = block(_html(guest_client.get(f"/e/{event.code}")), "more-sheet", "dialog")
    assert [
        t for t in testids(sheet, "more-item-") if t.removeprefix("more-item-") in PRIMARY_ORDER
    ] == ["more-item-voting", "more-item-logistics", "more-item-chat", "more-item-media"]


def test_more_sheet_event_group_is_log_only_for_guest(guest_client, event):
    sheet = block(_html(guest_client.get(f"/e/{event.code}")), "more-sheet", "dialog")
    group = ("more-item-participants", "more-item-invite", "more-item-log")
    assert [t for t in testids(sheet, "more-item-") if t in group] == ["more-item-log"]


def test_more_sheet_hides_invite_for_guest(guest_client, event):
    sheet = block(_html(guest_client.get(f"/e/{event.code}")), "more-sheet", "dialog")
    assert "more-item-invite" not in testids(sheet, "more-item-")


def test_more_sheet_shows_participants_and_invite_for_creator(creator_client, event):
    sheet = block(_html(creator_client.get(f"/e/{event.code}")), "more-sheet", "dialog")
    assert {"more-item-participants", "more-item-invite"} <= set(testids(sheet, "more-item-"))


def test_more_sheet_hides_account_items_for_guest(guest_client, event):
    sheet = block(_html(guest_client.get(f"/e/{event.code}")), "more-sheet", "dialog")
    assert "more-item-logout" not in testids(sheet, "more-item-")


# --- Active state ------------------------------------------------------------


def test_active_tab_has_aria_current_on_planning_page(guest_client, event):
    html = _html(guest_client.get(f"/e/{event.code}/planning"))
    assert 'aria-current="page"' in tag(html, "tab-planning")


def test_more_tab_marked_active_on_chat_page(guest_client, event):
    html = _html(guest_client.get(f"/e/{event.code}/chat"))
    assert 'data-active="true"' in tag(html, "tab-more")


def test_more_item_has_aria_current_on_chat_page(guest_client, event):
    html = _html(guest_client.get(f"/e/{event.code}/chat"))
    assert 'aria-current="page"' in tag(html, "more-item-chat")


def test_more_tab_not_active_on_planning_page(guest_client, event):
    html = _html(guest_client.get(f"/e/{event.code}/planning"))
    assert 'data-active="true"' not in tag(html, "tab-more")


# --- Desktop navigation and header -------------------------------------------


def test_desktop_nav_lists_all_destinations_for_creator(creator_client, event):
    nav = block(_html(creator_client.get(f"/e/{event.code}")), "nav-desktop", "nav")
    assert testids(nav, "navlink-") == [
        "navlink-home",
        "navlink-planning",
        "navlink-meals",
        "navlink-lists",
        "navlink-costs",
        "navlink-voting",
        "navlink-logistics",
        "navlink-chat",
        "navlink-media",
        "navlink-participants",
        "navlink-invite",
        "navlink-share",
        "navlink-log",
        "navlink-me",
        "navlink-manage",
        "navlink-privacy",
        "navlink-events",
        "navlink-logout",
    ]


def test_desktop_nav_does_not_repeat_event_title(creator_client, event):
    nav = block(_html(creator_client.get(f"/e/{event.code}")), "nav-desktop", "nav")
    assert event.title not in nav


def test_header_renders_full_long_event_title(creator_client, event, db):
    event.title = "Réveillon " + "x" * 110
    db.session.commit()
    html = _html(creator_client.get(f"/e/{event.code}"))
    assert text_of(html, "header-event-title", "a") == event.title


def test_header_event_title_is_marked_translate_no(creator_client, event):
    html = _html(creator_client.get(f"/e/{event.code}"))
    assert 'translate="no"' in tag(html, "header-event-title")


def test_identity_chip_has_guest_role_for_guest(guest_client, event):
    html = _html(guest_client.get(f"/e/{event.code}"))
    assert 'data-role="guest"' in tag(html, "identity-chip")


def test_identity_chip_has_creator_role_for_creator(creator_client, event):
    html = _html(creator_client.get(f"/e/{event.code}"))
    assert 'data-role="creator"' in tag(html, "identity-chip")


def test_identity_chip_absent_for_anonymous_visitor(client):
    html = _html(client.get("/"))
    assert 'data-testid="app-header"' in html
    assert 'data-testid="identity-chip"' not in html


# --- Toasts, footer, privacy, headings ---------------------------------------


def test_flash_message_rendered_as_danger_toast(client):
    html = _html(client.get("/e/verify/jeton-inconnu", follow_redirects=True))
    assert 'data-tone="danger"' in tag(html, "toast")


def test_footer_rendered_outside_event(client):
    html = _html(client.get("/"))
    assert 'data-testid="site-footer"' in html


def test_footer_absent_inside_event(creator_client, event):
    html = _html(creator_client.get(f"/e/{event.code}"))
    assert 'data-testid="nav-bottom"' in html
    assert 'data-testid="site-footer"' not in html


def test_privacy_sheet_is_dialog_without_emoji(client):
    sheet = block(_html(client.get("/")), "privacy-sheet", "dialog")
    assert not any(e in sheet for e in ("🛡", "🚫", "🍪", "🔐"))


def test_landing_has_exactly_one_h1_with_new_shell(client):
    html = _html(client.get("/"))
    assert 'data-testid="main-content"' in html
    assert html.count("<h1") == 1


# --- i18n ---------------------------------------------------------------------

NEW_SHELL_MSGIDS = [
    "Événement",
    "Participants",
    "Préférences",
    "Compte",
    "Aller au contenu",
    "Thème sombre",
    "Retirer %(name)s ?",
    "Accueil holishared",
    "Notifications",
    "Annuler",
    "Confirmer",
    "Confirmer l'action",
    "Copié",
    "Copie impossible",
    "Nouvelle version disponible",
    "Recharger",
    "Hors ligne",
    "Vous êtes hors ligne",
    "Vérifiez votre connexion puis réessayez.",
    "Réessayer",
    "facultatif",
    "Catalogue de composants",
]

REUSED_SHELL_MSGIDS = [
    "Créateur",
    "Accueil",
    "Planning",
    "Repas",
    "Listes",
    "Frais",
    "Plus",
    "Sondages",
    "Infos",
    "Chat",
    "Media",
    "Inviter",
    "Journal",
    "Mes événements",
    "Créer",
    "Créer un événement",
    "Se déconnecter",
    "Fermer",
    "Navigation principale",
    "Confidentialité",
    "Confidentialité garantie",
    "Voir",
    "Masquer",
    "Copier",
    "Chargement…",
    "Holishared respecte votre vie privée : 0 cookie tiers, 0 pistage, 0 revente de données.",
    "Aucun compte forcé",
    "Les invités rejoignent avec un code, sans e-mail ni inscription.",
    "Aucun cookie tiers, aucun pistage",
    "Aucun script tiers, aucune analyse publicitaire, aucune revente de données.",
    "Vos données restent vos données",
    "Export complet en 1 clic, et effacement définitif (base + photos) quand vous voulez.",
]


def test_shell_msgids_have_english_translation():
    from babel.messages.pofile import read_po

    from app.ui import JS_STRINGS

    with (REPO / "translations/en/LC_MESSAGES/messages.po").open("rb") as fh:
        catalog = read_po(fh)

    def translated(msgid: str) -> bool:
        entry = catalog.get(msgid)
        return entry is not None and bool(entry.string) and not entry.fuzzy

    shell_msgids = NEW_SHELL_MSGIDS + REUSED_SHELL_MSGIDS + list(JS_STRINGS.values())
    assert [m for m in shell_msgids if not translated(m)] == []


def test_templates_contain_no_native_confirm_call():
    offenders = [
        str(p)
        for p in (REPO / "app/templates").rglob("*.html")
        if "confirm(" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_templates_contain_no_direct_clipboard_api():
    offenders = [
        str(p)
        for p in (REPO / "app/templates").rglob("*.html")
        if "navigator.clipboard" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_ui_strings_json_is_translated_in_english(client):
    data = _json_script(_html(client.get("/?lang=en")), r'id="ui-strings"')
    assert data["copied"] == "Copied"


def test_ui_strings_json_matches_registry(client):
    from app.ui import JS_STRINGS

    data = _json_script(_html(client.get("/")), r'id="ui-strings"')
    assert set(data) == set(JS_STRINGS)


def test_js_strings_registry_keys_follow_convention():
    from app.ui import JS_STRINGS

    required = {
        "copied",
        "copy_failed",
        "close",
        "cancel",
        "confirm",
        "confirm_title",
        "new_version",
        "reload",
        "show",
        "hide",
        "loading",
    }
    assert [k for k in JS_STRINGS if not re.fullmatch(r"[a-z][a-z0-9_]*", k)] == []
    assert required <= set(JS_STRINGS)


# --- Migrated templates (§7.12) -----------------------------------------------


def test_guest_my_code_page_has_copy_hook_for_code(guest_client, event, guest):
    html = _html(guest_client.get(f"/e/{event.code}/me"))
    assert f'data-copy="{guest.code}"' in html


def test_guest_my_code_page_code_is_masked_by_default(guest_client, event):
    html = _html(guest_client.get(f"/e/{event.code}/me"))
    assert 'data-masked="true"' in html


def test_members_remove_button_uses_data_confirm(creator_client, event, guest):
    html = _html(creator_client.get(f"/e/{event.code}/members"))
    assert "data-confirm=" in html


def test_members_page_hides_other_participant_codes_for_guest(guest_client, event, db):
    db.session.add(Guest(code="autre123", display_name="Autre", event_id=event.id))
    db.session.commit()
    resp = guest_client.get(f"/e/{event.code}/members")
    assert resp.status_code == 200
    assert "autre123" not in _html(resp)


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        (None, None),
        ("main.index", "landing"),
        ("events.create", "create"),
        ("events.verify_sent", "create"),
        ("events.index", "events"),
        ("events.dashboard", "home"),
        ("events.members", "participants"),
        ("events.invite", "invite"),
        ("events.invite_qr", "invite"),
        ("events.log", "log"),
        ("planning.index", "planning"),
        ("meals.index", "meals"),
        ("media.gallery", "media"),
        ("costs.index", "costs"),
        ("events.guest_access", None),
        ("auth.login", None),
    ],
)
def test_nav_section_maps_endpoint_to_key(endpoint, expected):
    from app.ui import nav_section

    assert nav_section(endpoint) == expected
