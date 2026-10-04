"""Extract translatable strings from Python + Jinja2 templates.

Babel 2.18 dropped the built-in jinja2 extractor, so we extract the
template ``_("...")`` / ``_('...')`` calls with a regex and merge them
into the Babel-generated .pot (which already has the Python strings).
"""
import re
import sys
from pathlib import Path

APP = Path("app")
POT = Path("translations/messages.pot")

# Match _("...") or _('...') with a literal string argument.
RE = re.compile(r"_\(\s*[\"']([^\"']+)[\"']\s*\)")


def extract_templates():
    """Return {string: [locations]} for all template _() calls."""
    found = {}
    for html in sorted(APP.glob("templates/**/*.html")):
        rel = str(html)
        for i, line in enumerate(html.read_text(encoding="utf-8").splitlines(), 1):
            for m in RE.finditer(line):
                s = m.group(1)
                found.setdefault(s, []).append(f"{rel}:{i}")
    return found


def main():
    # Read the existing .pot (Python strings) and collect msgids.
    pot_text = POT.read_text(encoding="utf-8")
    existing = set(re.findall(r'^msgid "(.*)"$', pot_text, re.M))

    templates = extract_templates()
    new_strings = [s for s in templates if s not in existing and s]

    # Build the header (reuse the first 19 lines of the existing .pot).
    header_lines = pot_text.splitlines()[:19]
    # Drop the trailing blank line if present.
    while header_lines and header_lines[-1] == "":
        header_lines.pop()

    out = "\n".join(header_lines) + "\n\n"

    # Append template entries (sorted for stability).
    for s in sorted(new_strings):
        locs = "\n".join(f"#: {loc}" for loc in templates[s])
        out += f"{locs}\nmsgid \"{s}\"\nmsgstr \"\"\n\n"

    POT.write_text(out, encoding="utf-8")
    print(f"Added {len(new_strings)} template strings "
          f"({len(existing)} Python strings already present).")


if __name__ == "__main__":
    main()
