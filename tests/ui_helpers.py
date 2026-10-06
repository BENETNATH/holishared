"""HTML extraction helpers for the UI tests (B017). No test here."""

import html as _html
import re


def tag(html: str, testid: str) -> str:
    """Opening tag of the first element carrying ``data-testid="<testid>"``."""
    match = re.search(rf'<[^>]*\bdata-testid="{re.escape(testid)}"[^>]*>', html)
    if match is None:
        raise AssertionError(f'data-testid="{testid}" absent')
    return match.group(0)


def block(html: str, testid: str, element: str) -> str:
    """From ``<element … data-testid="<testid>"`` to the first ``</element>`` after it."""
    match = re.search(
        rf'<{element}\b[^>]*\bdata-testid="{re.escape(testid)}"[^>]*>.*?</{element}>',
        html,
        re.S,
    )
    if match is None:
        raise AssertionError(f'<{element} data-testid="{testid}"> absent')
    return match.group(0)


def testids(fragment: str, prefix: str) -> list[str]:
    """``data-testid`` values starting with ``prefix``, in document order."""
    return [t for t in re.findall(r'data-testid="([^"]+)"', fragment) if t.startswith(prefix)]


def text_of(html: str, testid: str, element: str) -> str:
    """Text content of ``block(html, testid, element)`` (tags removed, spaces normalised)."""
    text = re.sub(r"<[^>]+>", " ", block(html, testid, element))
    return " ".join(_html.unescape(text).split())
