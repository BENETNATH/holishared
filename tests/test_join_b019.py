"""B019 — rejoindre (/join) et saisie du code (/mycode)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _join(client, event, **overrides):
    data = {"display_name": "Zoé", "code": "zoe12345", **overrides}
    return client.post(f"/e/{event.code}/join", data=data)


def _html(resp):
    return resp.get_data(as_text=True)


def _has_error(resp, field):
    return f'data-testid="err-{field}"' in _html(resp)


# --- /join -------------------------------------------------------------------


def test_join_page_prefills_a_server_suggested_code(client, event):
    html = _html(client.get(f"/e/{event.code}/join"))
    assert re.search(r'name="code"[^>]*value="[a-z0-9]{8}"', html) is not None


def test_join_page_has_no_generate_button(client, event):
    assert "Générer" not in _html(client.get(f"/e/{event.code}/join"))


def test_join_page_has_no_client_side_random_generation(client, event):
    assert "Math.random" not in _html(client.get(f"/e/{event.code}/join"))


def test_no_served_script_generates_secrets_with_math_random():
    scripts = [*(ROOT / "app/static/js/ui").glob("*.js"), *(ROOT / "app/templates").rglob("*.js")]
    assert [p.name for p in scripts if "Math.random" in p.read_text(encoding="utf-8")] == []


def test_no_template_generates_secrets_with_math_random():
    templates = (ROOT / "app/templates").rglob("*.html")
    assert [p.name for p in templates if "Math.random" in p.read_text(encoding="utf-8")] == []


def test_join_page_explains_how_the_code_is_used(client, event):
    assert "depuis un autre appareil" in _html(client.get(f"/e/{event.code}/join"))


def test_join_page_keeps_household_folded(client, event):
    html = _html(client.get(f"/e/{event.code}/join"))
    assert re.search(r'<details[^>]*data-testid="join-options"[^>]*open', html) is None


def test_join_page_has_single_submit_button(client, event):
    assert _html(client.get(f"/e/{event.code}/join")).count('data-testid="join-submit"') == 1


def test_join_page_links_to_code_entry(client, event):
    html = _html(client.get(f"/e/{event.code}/join"))
    assert f'href="/e/{event.code}/mycode"' in html


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"display_name": ""}, "display_name"),
        ({"display_name": "Z"}, "display_name"),
        ({"code": ""}, "code"),
        ({"code": "abc"}, "code"),
        ({"code": "abcdefghi"}, "code"),
        ({"code": "ab cd!"}, "code"),
        ({"email": "pas-un-email"}, "email"),
        ({"email": "x@mailinator.com"}, "email"),
    ],
)
def test_join_error_is_attached_to_its_field(client, event, overrides, field):
    assert _has_error(_join(client, event, **overrides), field)


def test_join_taken_code_error_is_attached_to_code_field(client, event, guest):
    assert _has_error(_join(client, event, code=guest.code), "code")


def test_join_error_keeps_nickname(client, event):
    assert 'value="Zoé"' in _html(_join(client, event, code="abc"))


def test_join_email_error_opens_the_options_section(client, event):
    html = _html(_join(client, event, email="pas-un-email"))
    assert re.search(r'<details[^>]*data-testid="join-options"[^>]*open', html) is not None


def test_join_success_lands_on_event_home(client, event):
    assert _join(client, event).headers["Location"] == f"/e/{event.code}"


def test_join_success_event_home_is_reachable(client, event):
    _join(client, event)
    assert client.get(f"/e/{event.code}").status_code == 200


# --- /mycode -----------------------------------------------------------------


def test_mycode_help_points_to_join_when_no_code_yet(client, event):
    html = _html(client.get(f"/e/{event.code}/mycode"))
    assert "Vous n'avez pas encore de code ?" in html


def test_mycode_help_link_goes_to_join(client, event):
    html = _html(client.get(f"/e/{event.code}/mycode"))
    assert f'href="/e/{event.code}/join"' in html


def test_mycode_has_no_client_side_random_generation(client, event):
    assert "Math.random" not in _html(client.get(f"/e/{event.code}/mycode"))


def test_mycode_wrong_code_shows_inline_field_error(client, event):
    assert _has_error(
        client.post(f"/e/{event.code}/mycode", data={"guest_code": "zzzz9999"}), "guest_code"
    )


def test_mycode_wrong_code_keeps_typed_value(client, event):
    html = _html(client.post(f"/e/{event.code}/mycode", data={"guest_code": "zzzz9999"}))
    assert 'value="zzzz9999"' in html


def test_mycode_guest_code_lands_on_event_home(client, event, guest):
    resp = client.post(f"/e/{event.code}/mycode", data={"guest_code": guest.code})
    assert resp.headers["Location"] == f"/e/{event.code}"


def test_mycode_has_single_submit_button(client, event):
    assert _html(client.get(f"/e/{event.code}/mycode")).count('data-testid="mycode-submit"') == 1
