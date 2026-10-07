"""B019 — les scènes de la garde UI couvrent les parcours d'entrée."""

import json
from pathlib import Path

SCENES = json.loads(
    (Path(__file__).resolve().parent.parent / "scripts/ui/scenes.json").read_text(encoding="utf-8")
)["scenes"]
BY_ID = {s["id"]: s for s in SCENES}

REQUIRED = [
    "landing",
    "landing-code-error",
    "landing-device",
    "events-index-guest",
    "create",
    "create-error",
    "verify",
    "verify-sent",
    "recover",
    "join",
    "join-error",
    "mycode",
    "mycode-error",
    "admin-login",
    "error-404",
    "error-404-event",
    "error-403-event",
]


def test_every_entry_journey_has_a_scene():
    assert [i for i in REQUIRED if i not in BY_ID] == []


def test_guest_events_scene_runs_as_a_guest():
    assert BY_ID["events-index-guest"]["role"].startswith("guest_")


def test_error_scenes_declare_the_expected_status():
    assert [
        BY_ID[i].get("expectStatus") for i in ("error-404", "error-404-event", "error-403-event")
    ] == [404, 404, 403]


def test_entry_scenes_are_checked_on_the_whole_page():
    assert [i for i in REQUIRED if BY_ID[i]["scope"] != "page"] == []


def test_scenes_cover_mobile_and_desktop():
    widths = set(
        json.loads((Path(__file__).resolve().parent.parent / "scripts/ui/scenes.json").read_text())[
            "defaults"
        ]["viewports"]
    )
    assert {390, 1280} <= widths
