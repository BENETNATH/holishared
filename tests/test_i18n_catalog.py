"""B018 — le catalogue (.pot/.po/.mo) est complet et à jour."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _tool():
    spec = importlib.util.spec_from_file_location("i18n_tool", ROOT / "scripts" / "i18n.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_catalog_has_no_empty_fuzzy_obsolete_or_stale_entry():
    assert _tool().check() == []


def test_check_detects_empty_english_entry(tmp_path, monkeypatch):
    tool = _tool()
    tr = tmp_path / "translations"
    (tr / "en" / "LC_MESSAGES").mkdir(parents=True)
    (tr / "fr" / "LC_MESSAGES").mkdir(parents=True)
    pot = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n\nmsgid "Bonjour"\nmsgstr ""\n'
    (tr / "messages.pot").write_text(pot)
    for loc in ("en", "fr"):
        (tr / loc / "LC_MESSAGES" / "messages.po").write_text(pot)
    monkeypatch.setattr(tool, "TRANS", tr)
    monkeypatch.setattr(tool, "POT", tr / "messages.pot")
    monkeypatch.setattr(tool, "_extract", lambda out: out.write_text(pot))
    problems = tool.check()
    assert "en: vide 'Bonjour'" in problems
    assert not any(p.startswith("fr: vide") for p in problems)
