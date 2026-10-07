"""Journal lisible (B020, 20.5) : phrases traduites, filtres, pagination, confidentialité."""

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.ui_helpers import testids

from app.i18n import (
    ACTION_LABELS,
    ACTION_MODULES,
    ACTION_SENTENCES,
    ACTION_VARIANTS,
    describe_action,
)
from app.models import ActivityLog, Event


def _dt(day, hour=10):
    """Date naïve (colonnes UTC naïves du modèle) sans appel DTZ001."""
    return datetime(2026, 12, day, hour, tzinfo=UTC).replace(tzinfo=None)


ROOT = Path(__file__).resolve().parent.parent
LOG_FUNCS = {"log_event", "_log_expense", "log_action"}


def _in_lang(app, lang, code, actor="Zed", target=None, full=False):
    # Contexte applicatif neuf : Flask-Babel met la locale en cache sur ``g``.
    with app.app_context(), app.test_request_context(f"/?lang={lang}"):
        out = describe_action(code, actor, target, "done")
    return out if full else out["sentence"]


def _add(db, event, action, actor="Antoine", target=None, details=None, when=None):
    row = ActivityLog(
        event_id=event.id,
        actor_name=actor,
        actor_type="guest",
        action=action,
        target=target,
        details=details,
        created_at=when or _dt(2),
    )
    db.session.add(row)
    db.session.commit()
    return row


def _log(client, event, query=""):
    return client.get(f"/e/{event.code}/log{query}").get_data(as_text=True)


# --- garde statique -------------------------------------------------------------


def _codes_in_source() -> set[str]:
    """Codes d'action littéraux passés à log_event/_log_expense/log_action (AST, tous les .py)."""
    used: set[str] = set()
    for path in (ROOT / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if name not in LOG_FUNCS:
                continue
            for arg in node.args:
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and "." in arg.value
                ):
                    used.add(arg.value)
                if isinstance(arg, ast.JoinedStr):  # list.{kind}_covered : codes générés
                    used |= {
                        f"list.{k}_{s}"
                        for k in ("meal", "activity")
                        for s in ("covered", "uncovered")
                    }
    return used


def test_every_action_code_used_in_code_has_a_short_label():
    assert _codes_in_source() - set(ACTION_LABELS) == set()


def test_every_action_code_used_in_code_has_a_sentence():
    assert _codes_in_source() - set(ACTION_SENTENCES) == set()


def test_every_action_code_has_a_module():
    assert [c for c in ACTION_LABELS if c.partition(".")[0] not in ACTION_MODULES] == []


def test_sentences_and_labels_cover_the_same_codes():
    assert set(ACTION_SENTENCES) == set(ACTION_LABELS)


# --- phrases ---------------------------------------------------------------------


def test_describe_action_with_target_builds_a_full_sentence(app):
    out = describe_action("activity.created", "Antoine", "Randonnée")
    assert out["sentence"] == "Antoine a ajouté une activité : Randonnée"


def test_describe_action_in_english_translates_the_sentence(app):
    out = _in_lang(app, "en", "activity.created", "Antoine", "Hiking", full=True)
    assert out["sentence"] == "Antoine added an activity: Hiking"


def test_describe_action_toggled_done_says_checked(app):
    assert describe_action("list_item.toggled", "Zoé", "Pain", "done")["sentence"].startswith(
        "Zoé a coché un article"
    )


def test_describe_action_rsvp_inlines_the_translated_status(app):
    assert describe_action("rsvp.updated", "Zoé", "Rando", "maybe")["sentence"] == (
        "Zoé a répondu « Peut-être » à une activité : Rando"
    )


def test_describe_action_hides_technical_details(app):
    assert describe_action("media.uploaded", "Zoé", "a.jpg", "12 KB, geo=0")["detail"] == ""


def test_describe_action_unknown_code_never_shows_the_code(app):
    assert "weird.code" not in describe_action("weird.code", "Zoé")["sentence"]


@pytest.mark.parametrize("code", sorted(set(ACTION_SENTENCES) | {c for c, _ in ACTION_VARIANTS}))
def test_describe_action_every_code_has_an_english_sentence(app, code):
    fr = _in_lang(app, "fr", code)
    en = _in_lang(app, "en", code)
    assert en != fr


# --- page -------------------------------------------------------------------------


def test_log_page_shows_readable_sentence_not_technical_code(creator_client, db, event):
    _add(db, event, "activity.created", target="Randonnée")
    html = _log(creator_client, event)
    assert ("Antoine a ajouté une activité : Randonnée" in html, "activity.created" in html) == (
        True,
        False,
    )


def test_log_page_is_available_to_a_guest(guest_client, db, event):
    _add(db, event, "meal.created", target="Pâtes")
    assert "Antoine a ajouté un repas : Pâtes" in _log(guest_client, event)


def test_log_page_in_english_shows_english_sentence(creator_client, db, event):
    _add(db, event, "activity.created", target="Hiking")
    assert "Antoine added an activity: Hiking" in _log(creator_client, event, "?lang=en")


def test_log_page_groups_entries_by_day(creator_client, db, event):
    _add(db, event, "meal.created", when=_dt(2, 9))
    _add(db, event, "meal.deleted", when=_dt(3, 9))
    assert len(testids(_log(creator_client, event), "log-day")) == 2


def test_log_page_lists_most_recent_first(creator_client, db, event):
    _add(db, event, "meal.created", target="Ancien", when=_dt(2, 9))
    _add(db, event, "meal.created", target="Récent", when=_dt(3, 9))
    html = _log(creator_client, event)
    assert html.index("Récent") < html.index("Ancien")


def test_log_page_empty_state_when_nothing_logged(creator_client, event):
    assert "log-empty" in _log(creator_client, event)


def test_log_page_escapes_target_and_actor(creator_client, db, event):
    _add(db, event, "activity.created", actor="<b>x</b>", target="<script>alert(1)</script>")
    html = _log(creator_client, event)
    assert ("<script>alert(1)</script>" in html, "&lt;script&gt;" in html) == (False, True)


def test_log_page_hides_personal_expense_description_and_amount(creator_client, db, event):
    _add(db, event, "expense.created")  # B024 : une dépense personnelle n'enregistre rien
    html = _log(creator_client, event)
    assert "Antoine a ajouté une dépense" in html
    assert ": " not in html.split('data-testid="log-sentence">')[1].split("</p>")[0]


def test_log_page_ignores_entries_of_other_events(creator_client, db, event, creator):
    other = Event(
        code="OTHER1",
        title="Autre",
        start_date=event.start_date,
        end_date=event.end_date,
        creator_id=creator.id,
        verified_at=datetime.utcnow(),
    )
    db.session.add(other)
    db.session.commit()
    _add(db, other, "activity.created", target="SecretAilleurs")
    assert "SecretAilleurs" not in _log(creator_client, event)


# --- filtres et pagination --------------------------------------------------------


def test_log_filter_by_module_keeps_only_that_module(creator_client, db, event):
    _add(db, event, "meal.created", target="Pâtes")
    _add(db, event, "activity.created", target="Rando")
    html = _log(creator_client, event, "?type=meals")
    assert ("Pâtes" in html, "Rando" in html) == (True, False)


def test_log_filter_by_person_keeps_only_that_person(creator_client, db, event):
    _add(db, event, "meal.created", actor="Zoé", target="Pâtes")
    _add(db, event, "meal.created", actor="Max", target="Riz")
    html = _log(creator_client, event, "?who=Zoé")
    assert ("Pâtes" in html, "Riz" in html) == (True, False)


def test_log_filter_unknown_module_is_ignored(creator_client, db, event):
    _add(db, event, "meal.created", target="Pâtes")
    assert "Pâtes" in _log(creator_client, event, "?type=bogus")


def test_log_filter_without_match_shows_empty_state(creator_client, db, event):
    _add(db, event, "meal.created")
    assert "log-empty" in _log(creator_client, event, "?type=chat")


def test_log_paginates_fifty_per_page(creator_client, db, event):
    base = _dt(2, 8)
    for i in range(55):
        _add(db, event, "meal.created", target=f"R{i:02d}", when=base + timedelta(minutes=i))
    assert len(testids(_log(creator_client, event), "log-entry")) == 50


def test_log_second_page_has_the_oldest_entries(creator_client, db, event):
    base = _dt(2, 8)
    for i in range(55):
        _add(db, event, "meal.created", target=f"R{i:02d}", when=base + timedelta(minutes=i))
    html = _log(creator_client, event, "?page=2")
    assert (len(testids(html, "log-entry")), "R00" in html) == (5, True)


def test_log_older_link_keeps_the_filters(creator_client, db, event):
    base = _dt(2, 8)
    for i in range(51):
        _add(db, event, "meal.created", when=base + timedelta(minutes=i))
    html = _log(creator_client, event, "?type=meals")
    assert "type=meals" in html.split('data-testid="log-older"')[0].rsplit("<a", 1)[1]


def test_log_no_older_link_on_last_page(creator_client, db, event):
    _add(db, event, "meal.created")
    assert "log-older" not in _log(creator_client, event)


def test_log_invalid_page_falls_back_to_first(creator_client, db, event):
    _add(db, event, "meal.created", target="Pâtes")
    assert "Pâtes" in _log(creator_client, event, "?page=abc")
