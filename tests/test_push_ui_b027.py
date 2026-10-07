"""B027 — section Notifications de Mon profil, invitation de l'accueil, module push.js."""

import re
from pathlib import Path

import pytest

from app.models import ChatMessage, PushSubscription

JS = Path(__file__).resolve().parents[1] / "app/static/js/ui/push.js"


@pytest.fixture
def with_keys(app):
    app.config["VAPID_PUBLIC_KEY"] = "BPUBLICKEY"
    app.config["VAPID_PRIVATE_KEY"] = "private"


def me(client, event) -> str:
    return client.get(f"/e/{event.code}/me").data.decode()


def home(client, event) -> str:
    return client.get(f"/e/{event.code}").data.decode()


def tid(name: str) -> str:
    return f'data-testid="{name}"'


# --- Section Notifications ---------------------------------------------------------------


def test_me_page_without_vapid_keys_says_notifications_are_unavailable(app, guest_client, event):
    app.config["VAPID_PUBLIC_KEY"] = app.config["VAPID_PRIVATE_KEY"] = ""
    assert tid("push-state-unavailable") in me(guest_client, event)


def test_me_page_without_vapid_keys_has_no_toggle(app, guest_client, event):
    app.config["VAPID_PUBLIC_KEY"] = app.config["VAPID_PRIVATE_KEY"] = ""
    assert tid("push-toggle") not in me(guest_client, event)


def test_me_page_with_vapid_keys_renders_the_toggle(with_keys, guest_client, event):
    assert tid("push-toggle") in me(guest_client, event)


def test_me_page_exposes_public_vapid_key_in_data_attribute(with_keys, guest_client, event):
    assert 'data-vapid-key="BPUBLICKEY"' in me(guest_client, event)


def test_me_page_never_exposes_the_private_vapid_key(with_keys, guest_client, event):
    assert (
        "private"
        not in me(guest_client, event).split('data-testid="push-card"')[1].split("</section>")[0]
    )


def test_me_page_renders_a_csrf_token_for_push_requests(with_keys, guest_client, event):
    assert re.search(
        r'data-testid="push-card"[^>]*data-csrf="[^"]+"', me(guest_client, event).replace("\n", " ")
    )


@pytest.mark.parametrize("state", ["unsupported", "install", "denied"])
def test_me_page_renders_explicit_state_messages_hidden_by_default(
    with_keys, guest_client, event, state
):
    html = me(guest_client, event)
    assert re.search(
        rf'data-push-state="{state}"[^>]*data-testid="push-state-{state}" hidden', html
    )


@pytest.mark.parametrize("name", ["chat", "polls", "requests", "preview"])
def test_me_page_renders_each_preference_checkbox(with_keys, guest_client, event, name):
    assert tid(f"push-pref-{name}") in me(guest_client, event)


def test_me_page_renders_disable_all_button(with_keys, guest_client, event):
    assert tid("push-disable-all") in me(guest_client, event)


def test_me_page_install_hint_mentions_home_screen(with_keys, guest_client, event):
    html = me(guest_client, event)
    assert "« Sur l'écran d'accueil »" in html


def test_me_page_loads_the_push_module(with_keys, guest_client, event):
    assert "import { initPush } from 'ui/push'" in me(guest_client, event)


def test_importmap_lists_the_push_module(with_keys, guest_client, event):
    assert '"ui/push"' in me(guest_client, event)


# --- Invitation de l'accueil -------------------------------------------------------------


def _act(db, event, guest):
    db.session.add(
        ChatMessage(
            content="Salut",
            guest_id=guest.id,
            author_name="G",
            author_type="guest",
            event_id=event.id,
        )
    )
    db.session.commit()


def test_home_invite_is_rendered_hidden_after_a_first_useful_gesture(
    with_keys, db, guest_client, event, guest
):
    _act(db, event, guest)
    assert re.search(
        r'data-push-invite data-testid="push-invite"[^>]* hidden', home(guest_client, event)
    )


def test_home_invite_is_absent_before_any_gesture(with_keys, guest_client, event):
    assert tid("push-invite") not in home(guest_client, event)


def test_home_invite_is_absent_without_vapid_keys(app, db, guest_client, event, guest):
    app.config["VAPID_PUBLIC_KEY"] = app.config["VAPID_PRIVATE_KEY"] = ""
    _act(db, event, guest)
    assert tid("push-invite") not in home(guest_client, event)


def test_home_invite_is_absent_when_a_device_is_already_subscribed(
    with_keys, db, guest_client, event, guest
):
    _act(db, event, guest)
    db.session.add(
        PushSubscription(
            event_id=event.id,
            guest_id=guest.id,
            endpoint="https://p.example.com/a",
            p256dh="k",
            auth="a",
        )
    )
    db.session.commit()
    assert tid("push-invite") not in home(guest_client, event)


def test_home_invite_is_dismissible(with_keys, db, guest_client, event, guest):
    _act(db, event, guest)
    assert tid("push-invite-dismiss") in home(guest_client, event)


def test_home_invite_links_to_the_notifications_section(with_keys, db, guest_client, event, guest):
    _act(db, event, guest)
    assert f"/e/{event.code}/me#h-notifications" in home(guest_client, event)


def test_home_invite_has_no_primary_button(with_keys, db, guest_client, event, guest):
    _act(db, event, guest)
    invite = home(guest_client, event).split('data-testid="push-invite"')[1].split("</section>")[0]
    assert "ui-btn--primary" not in invite


# --- Module push.js (analyse statique) ---------------------------------------------------


def test_push_module_requests_permission_only_inside_enable():
    source = JS.read_text(encoding="utf-8")
    assert source.count("requestPermission") == 1


def test_push_module_requests_permission_from_the_toggle_handler_only():
    source = JS.read_text(encoding="utf-8")
    enable = source.split("async function enable")[1].split("async function disable")[0]
    assert "requestPermission" in enable


def test_push_module_init_does_not_call_enable_directly():
    source = JS.read_text(encoding="utf-8")
    init = source.split("export function initPush")[1]
    assert "enable(" not in init


def test_push_module_detects_installed_pwa_with_display_mode():
    assert "(display-mode: standalone)" in JS.read_text(encoding="utf-8")


def test_push_module_detects_installed_pwa_on_ios():
    assert "navigator.standalone" in JS.read_text(encoding="utf-8")


def test_push_module_wraps_local_storage_in_try_catch():
    source = JS.read_text(encoding="utf-8")
    assert re.search(r"try \{\s*return localStorage", source)


def test_push_module_sends_csrf_header():
    assert "X-CSRFToken" in JS.read_text(encoding="utf-8")


def test_push_module_uses_only_registered_string_keys():
    from app.ui import JS_STRINGS

    used = set(re.findall(r"\bt\('([a-z_]+)'\)", JS.read_text(encoding="utf-8")))
    assert used - set(JS_STRINGS) == set()


# --- Vie privée --------------------------------------------------------------------------


def test_privacy_sheet_mentions_push_notifications(guest_client, event):
    assert "service de notification de votre navigateur" in home(guest_client, event)
