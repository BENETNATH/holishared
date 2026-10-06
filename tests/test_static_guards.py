"""Gardes statiques B029 : plus de helpers dupliqués ni de variables héritées."""

import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"


def _python_sources() -> list[tuple[Path, str]]:
    return [(p, p.read_text(encoding="utf-8")) for p in sorted(APP.rglob("*.py"))]


def test_no_duplicated_access_helpers_in_app():
    pattern = re.compile(
        r"def (_resolve_actor|_get_event_or_404|_actor_name|_actor\(|_can_modify"
        r"|_is_event_creator|_get_current_guest)"
    )
    found = [str(p) for p, text in _python_sources() if pattern.search(text)]
    assert found == []


def test_templates_do_not_use_guest_or_is_creator_variables():
    block = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
    literal = re.compile(r'"[^"]*"|\'[^\']*\'')
    forbidden = [
        re.compile(r"""(?<!["'.])\bguest\b(?!["'])"""),
        re.compile(r"(?<!ctx\.)\bis_creator\b"),
        re.compile(r"current_user\.id == event\.creator_id"),
    ]
    offenders = []
    for path in sorted((APP / "templates").rglob("*.html")):
        for match in block.finditer(path.read_text(encoding="utf-8")):
            code = literal.sub('""', match.group(0))
            if any(rx.search(code) for rx in forbidden):
                offenders.append(f"{path.name}: {match.group(0)[:60]}")
    assert offenders == []


def test_no_raw_error_strings_in_views():
    pattern = re.compile(
        r'return "Not found"|"Pas autorisé\.", 403|_\("Pas autorisé\."\), 403|flash\("Pas autorisé\.'
    )
    found = [str(p) for p, text in _python_sources() if pattern.search(text)]
    assert found == []


def test_no_creator_literal_outside_context():
    pattern = re.compile(r'["\'](Créateur|Système)["\']')
    allowed = {"context.py", "models.py"}
    found = [
        str(p) for p, text in _python_sources() if p.name not in allowed and pattern.search(text)
    ]
    assert found == []
