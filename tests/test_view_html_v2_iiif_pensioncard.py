"""Regression test for the v2 pension card IIIF link (issue #62).

The v2 view had a confused href template that built
`/iiif/2/pensioncard:{id}/full//0/default.jpg` (note the
double slash) which the IIIF server at digitalprairie.ok.gov
rejected with `404 Not Found / No route for path`. The fix
replaces the inline concat with the canonical IIIF full-size
URL `/iiif/2/pensioncard:{id}/full/full/0/default.jpg`.
"""

from __future__ import annotations

import re
from pathlib import Path


V2_PATH = (
    Path(__file__).parent.parent
    / "scripts"
    / "view"
    / "v2.html"
)


def _iiif_link_strings() -> list[str]:
    """Return the v2.html source strings that contain an IIIF
    pensioncard link. The href is split across Alpine JS
    string concat (`:href="'...pensioncard:' + pageId + '/full/...'"`)
    so we return the full source string between the nearest
    HTML attribute quotes.
    """
    with V2_PATH.open(encoding="utf-8") as f:
        text = f.read()
    matches = []
    for m in re.finditer(r'iiif/2/pensioncard', text):
        # The href is inside :href="'...'" or :src="'...'"
        # Walk back to find the attribute open and forward
        # to find its close.
        i = m.start()
        # Find the attribute opener going back: look for `=` or `"`
        quote_start = text.rfind('"', 0, i)
        if quote_start < 0:
            continue
        # The attribute value closes at the next `"` after the
        # href/src's open quote. But Alpine uses single-quoted
        # JS strings inside double-quoted attributes, so the
        # actual close is `"` after the second single-quote.
        # We just grab until the next `>` since attributes end
        # at `>`.
        close = text.find('>', i)
        if close < 0:
            continue
        matches.append(text[quote_start:close])
    return matches


def test_pension_card_href_uses_iiif_full_full_size():
    """The href template must use the IIIF `full/full/` size
    segment so the digitalprairie.ok.gov server returns 200
    (not 404). Issue #62 regression.
    """
    matches = _iiif_link_strings()
    assert matches, "v2.html has no pensioncard IIIF link"
    for href in matches:
        # Skip the thumb URL (uses /full/300,/)
        if "/full/300," in href:
            continue
        # Full-size must use /full/full/0/default.jpg
        assert "/full/full/0/default.jpg" in href, (
            f"v2 pension card full-size href missing the "
            f"/full/full/0/default.jpg pattern: {href!r}"
        )
        # Must NOT contain the buggy double-slash
        assert "/full//0/" not in href, (
            f"v2 pension card href has the buggy double-slash "
            f"pattern: {href!r}"
        )


def test_pension_card_thumb_uses_iiif_300_width():
    """The thumb URL must use the 300px-wide IIIF size segment."""
    matches = _iiif_link_strings()
    assert matches
    thumb = [h for h in matches if "/full/300" in h]
    assert thumb, "v2.html has no /full/300,/0 thumb link"
    for href in thumb:
        assert "/full/300,/0/default.jpg" in href, (
            f"v2 pension card thumb href malformed: {href!r}"
        )


def test_pension_card_thumb_and_full_are_distinct_size_segments():
    """Thumb (300px) and full (max) URLs must differ in the
    size segment only.
    """
    matches = _iiif_link_strings()
    assert matches
    full = next((h for h in matches if "/full/full/0" in h), None)
    thumb = next((h for h in matches if "/full/300,/0" in h), None)
    assert full is not None, "no full-size href found"
    assert thumb is not None, "no thumb href found"
    assert full != thumb, "full and thumb hrefs are identical"