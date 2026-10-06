"""Catalogue i18n (B018) : ``extract``, ``compile``, ``check``.

    python scripts/i18n.py extract   # .pot depuis le code, puis mise à jour des .po (sans fuzzy ni obsolètes)
    python scripts/i18n.py compile   # .po -> .mo
    python scripts/i18n.py check     # échoue sur vide/fuzzy/obsolète/.pot ou .mo périmé/placeholders

Le français est la langue source (msgstr FR vide) ; l'anglais est édité dans son .po.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import sys
import tempfile
from pathlib import Path

from babel.messages.frontend import CommandLineInterface
from babel.messages.mofile import read_mo
from babel.messages.pofile import read_po

ROOT = Path(__file__).resolve().parent.parent
TRANS = ROOT / "translations"
POT = TRANS / "messages.pot"
LOCALES = ("fr", "en")
KEYWORDS = ("-k", "_l", "-k", "lazy_gettext", "-k", "N_")
PLACEHOLDER = re.compile(r"%\((\w+)\)[sd]")


def _pybabel(*args: str) -> None:
    os.chdir(ROOT)  # les motifs de babel.cfg sont relatifs à la racine
    with contextlib.redirect_stderr(io.StringIO()) as err:  # babel journalise chaque fichier
        code = CommandLineInterface().run(["pybabel", *args])
    if code:
        sys.stderr.write(err.getvalue())
    if code:
        raise SystemExit(code)


def _extract(out: Path) -> None:
    _pybabel(
        "extract", "-F", str(ROOT / "babel.cfg"), *KEYWORDS, "--add-location=file",
        "--project=holishared", "--version=1", "--copyright-holder=holishared",
        "-o", str(out), "app", "app/templates/_components",  # babel saute les dossiers en « _ »
    )  # fmt: skip


def extract() -> None:
    _extract(POT)
    _pybabel("update", "-i", str(POT), "-d", str(TRANS), "--ignore-obsolete", "--no-fuzzy-matching")


def compile_() -> None:
    _pybabel("compile", "-d", str(TRANS))


def _ids(catalog: object) -> set[str]:
    return {m.id if isinstance(m.id, str) else m.id[0] for m in catalog if m.id}  # type: ignore[attr-defined]


def check() -> list[str]:
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp) / "messages.pot"
        _extract(fresh)
        code_ids = _ids(read_po(fresh.open("rb")))
    pot_ids = _ids(read_po(POT.open("rb")))
    for msgid in sorted(code_ids ^ pot_ids):
        problems.append(f".pot périmé : {msgid!r}")
    for loc in LOCALES:
        po_path = TRANS / loc / "LC_MESSAGES" / "messages.po"
        mo_path = po_path.with_suffix(".mo")
        cat = read_po(po_path.open("rb"), locale=loc)
        if cat.obsolete:
            problems.append(f"{loc}: {len(cat.obsolete)} entrée(s) obsolète(s)")
        if _ids(cat) != pot_ids:
            problems.append(f"{loc}: .po désynchronisé du .pot")
        for msg in cat:
            if not msg.id:
                continue
            if msg.fuzzy:
                problems.append(f"{loc}: fuzzy {msg.id!r}")
            strings = [msg.string] if isinstance(msg.string, str) else list(msg.string)
            if loc != "fr" and not all(strings):
                problems.append(f"{loc}: vide {msg.id!r}")
            if loc != "fr":
                src = msg.id if isinstance(msg.id, str) else msg.id[0]
                for s in filter(None, strings):
                    if set(PLACEHOLDER.findall(src)) != set(PLACEHOLDER.findall(s)):
                        problems.append(f"{loc}: placeholders {src!r}")
        if not mo_path.exists():
            problems.append(f"{loc}: .mo absent")
            continue
        mo = read_mo(mo_path.open("rb"))

        def norm(x: object) -> object:
            return tuple(x) if isinstance(x, (list, tuple)) else x

        expected = {}
        for m in cat:
            if not m.id or m.fuzzy:
                continue
            if any([m.string] if isinstance(m.string, str) else m.string):
                expected[norm(m.id)] = norm(m.string)
            elif isinstance(m.id, tuple):  # babel recopie le pluriel source dans le .mo
                expected[norm(m.id)] = norm(m.id)
        actual = {norm(m.id): norm(m.string) for m in mo if m.id}
        if expected != actual:
            problems.append(f"{loc}: .mo périmé (lancer compile)")
    return problems


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "extract":
        extract()
    elif cmd == "compile":
        compile_()
    elif cmd == "check":
        problems = check()
        for p in problems:
            print(p)
        return 1 if problems else 0
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
