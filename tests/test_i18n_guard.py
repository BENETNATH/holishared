"""B018 — garde i18n : aucune page rendue dans une langue ne contient la chaîne de l'autre.

Les données utilisateur du jeu d'essai sont des jetons neutres (``Zorgblat``…) : tout
msgid français traduit différemment en anglais qui apparaît dans le HTML visible d'une
page ``?lang=en`` est une chaîne non traduite (et inversement pour ``?lang=fr``).
"""

import re
from datetime import date
from html import unescape
from pathlib import Path

import pytest
from babel.messages.pofile import read_po

from app.models import ActivityLog, ChatMessage, Household, ListItem, Meal, SharedList

ROOT = Path(__file__).resolve().parent.parent
# Mots courts / noms propres légitimes dans les deux langues ou issus du jeu d'essai.
ALLOW = {"holishared", "Vacances+"}


def _catalog():
    with (ROOT / "translations/en/LC_MESSAGES/messages.po").open("rb") as fh:
        cat = read_po(fh, locale="en")
    pairs = {}
    for m in cat:
        if m.id and isinstance(m.id, str) and isinstance(m.string, str) and m.string:
            if m.id != m.string and "%(" not in m.id and "\n" not in m.id:
                pairs[m.id] = m.string
    return pairs


PAIRS = _catalog()


def _visible(html: str) -> str:
    """Texte visible + attributs d'interface, sans scripts, styles ni commentaires."""
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    attrs = re.findall(r'\b(?:aria-label|title|placeholder|alt|data-confirm)="([^"]*)"', html)
    text = re.sub(r"<[^>]+>", " ", html)
    return unescape(" ".join([text, *attrs]))


def _find(text: str, needles: dict[str, str], pick: int) -> list[str]:
    """Msgids dont la forme source (pick=0) ou traduite (pick=1) figure dans ``text``."""
    out = []
    for fr, en in needles.items():
        needle = (fr, en)[pick]
        if len(needle) < 5 or needle in ALLOW:
            continue
        if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", text):
            out.append(needle)
    return out


@pytest.fixture
def rich(creator_client, db, event, creator, creator_guest, guest):
    """Un événement qui exerce toutes les pages, avec des données utilisateur neutres."""
    event.title = "Zorgblat"
    creator.display_name = creator_guest.display_name = "Zorgcreator"
    guest.display_name = "Zorgguest"
    event.location = "Qwertyville"
    h = Household(name="Zorgfam", event_id=event.id, guest_id=creator_guest.id)
    other = Household(name="Blargfam", event_id=event.id, guest_id=guest.id)
    db.session.add_all([h, other])
    lst = SharedList(title="Zorglist", event_id=event.id)
    db.session.add(lst)
    db.session.flush()
    db.session.add(ListItem(name="Zorgitem", list_id=lst.id))
    db.session.add(Meal(title="Zorgmeal", date=date(2026, 12, 2), slot="dinner", event_id=event.id))
    db.session.add(
        ChatMessage(
            content="Zorgchat", author_name="Zorgnick", author_type="guest", event_id=event.id
        )
    )
    db.session.commit()
    c = creator_client
    code = event.code
    post = lambda path, **data: c.post(f"/e/{code}/{path}?lang=en", data=data)  # noqa: E731
    post("planning/new", title="Zorgrando", date="2026-12-02", start_time="10:00")
    post("logistics/new", title="Zorginfo", content="Zorgcontent", category="timing")
    post("voting/new", question="Zorgquestion", options="Aaaa\nBbbb")
    post(
        "costs/expenses/new",
        description="Zorgdepense",
        amount="12.5",
        household_id=h.id,
        category="food",
        is_shared="on",
    )
    post("costs/transfers/new", from_household_id=h.id, to_household_id=other.id, amount="3")
    post(
        "costs/payment-requests/new",
        from_household_id=other.id,
        to_household_id=h.id,
        amount="4",
    )
    c.get(f"/e/{code}?lang=en")  # consomme les messages flash des POST ci-dessus
    return event


def _urls(event, db):
    code = event.code
    lst = SharedList.query.filter_by(event_id=event.id).first()
    item = LogisticsItemFirst(event)
    from app.models import Activity, Poll

    act = Activity.query.filter_by(event_id=event.id).first()
    poll = Poll.query.filter_by(event_id=event.id).first()
    urls = [
        "/",
        "/offline",
        "/admin/login",
        "/e/",
        "/e/new",
        "/e/recover",
        "/e/access",
        f"/e/{code}",
        f"/e/{code}/chat",
        f"/e/{code}/costs",
        f"/e/{code}/costs/households/new",
        f"/e/{code}/export/pdf",
        f"/e/{code}/invite",
        f"/e/{code}/join",
        f"/e/{code}/lists",
        f"/e/{code}/lists/{lst.id}",
        f"/e/{code}/lists/new",
        f"/e/{code}/log",
        f"/e/{code}/logistics",
        f"/e/{code}/logistics/{item.id}/edit",
        f"/e/{code}/logistics/new",
        f"/e/{code}/meals",
        f"/e/{code}/media",
        f"/e/{code}/members",
        f"/e/{code}/mycode",
        f"/e/{code}/planning",
        f"/e/{code}/planning/{act.id}/edit",
        f"/e/{code}/planning/new",
        f"/e/{code}/voting",
        f"/e/{code}/voting/{poll.id}",
        f"/e/{code}/voting/new",
    ]
    return urls


def LogisticsItemFirst(event):  # noqa: N802
    from app.models import LogisticsItem

    return LogisticsItem.query.filter_by(event_id=event.id).first()


def _render_all(client, event, db, lang):
    pages = {}
    for url in _urls(event, db):
        resp = client.get(f"{url}?lang={lang}", follow_redirects=True)
        assert resp.status_code < 500, (url, resp.status_code)
        if resp.status_code == 200:
            pages[url] = _visible(resp.get_data(as_text=True))
    return pages


def test_english_pages_contain_no_translated_french_msgid(creator_client, rich, db):
    pages = _render_all(creator_client, rich, db, "en")
    assert len(pages) >= 25
    leaks = {url: found for url, text in pages.items() if (found := _find(text, PAIRS, 0))}
    assert leaks == {}


def test_french_pages_contain_no_english_translation(creator_client, rich, db):
    pages = _render_all(creator_client, rich, db, "fr")
    leaks = {url: found for url, text in pages.items() if (found := _find(text, PAIRS, 1))}
    assert leaks == {}


def test_guard_has_teeth():
    assert len(PAIRS) > 300
    assert "Ajouter une dépense" in _find("Ajouter une dépense ici", PAIRS, 0)
    assert "Add an expense" in _find("Add an expense here", PAIRS, 1)
    assert "Ajouter une dépense" not in _find("Ajouter une dépenses", PAIRS, 0)


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_guest_pages_contain_no_foreign_msgid(client, rich, guest, db, lang):
    with client.session_transaction() as s:
        s[f"guest_{rich.code}"] = guest.id
    pages = _render_all(client, rich, db, lang)
    assert len(pages) >= 15
    pick = 0 if lang == "en" else 1
    leaks = {url: found for url, text in pages.items() if (found := _find(text, PAIRS, pick))}
    assert leaks == {}


def test_flashes_follow_the_request_language(creator_client, event, creator_guest):
    data = {"title": "", "date": "2026-12-02", "slot": "lunch"}
    en = creator_client.post(
        f"/e/{event.code}/meals/create?lang=en", data=data, follow_redirects=True
    ).get_data(as_text=True)
    assert "Name required (min. 2 characters)." in en
    fr = creator_client.post(
        f"/e/{event.code}/meals/create?lang=fr", data=data, follow_redirects=True
    ).get_data(as_text=True)
    assert "Nom requis (min 2 caractères)." in fr


def test_every_action_code_used_by_the_code_has_a_label():
    from app.i18n import ACTION_LABELS

    used = set()
    for path in (ROOT / "app").rglob("*.py"):
        used |= set(re.findall(r'log_event\(\s*\w+,\s*"([a-z_]+\.[a-z_]+)"', path.read_text()))
    assert used
    assert used <= set(ACTION_LABELS)


def test_log_page_shows_translated_action_labels(creator_client, db, event, creator_guest):
    db.session.add(
        ActivityLog(
            event_id=event.id, actor_name="Zorgnick", actor_type="guest", action="expense.created"
        )
    )
    db.session.commit()
    html = creator_client.get(f"/e/{event.code}/log?lang=en").get_data(as_text=True)
    assert "Expense added" in html
    assert "expense.created" not in html
