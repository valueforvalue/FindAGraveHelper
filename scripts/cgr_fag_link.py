"""CGR -> FaG backlink extractor.

Some CGR veteran records include a direct link to a Find a
Grave memorial in their 'Source' or 'Notes' field. When
present, this is the strongest possible match evidence — we
call it a "direct link" in the BOTH MATCH detector.

Patterns we detect:
  - URL: http(s)://(www.)?findagrave.com/memorial/<id>[/<slug>]
  - Text: "Find a Grave Memorial <id>"
  - Text: "FaG: <id>"

The memorial ID is extracted from the URL or text. The link
is returned for view.html to display as "matched via direct
link".
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# Pattern: findagrave.com/memorial/<digits>[/<anything>]
_FAG_URL_RE = re.compile(
    r"(?:https?:)?//(?:www\.)?findagrave\.com/memorial/(\d+)(?:[^\s]*)?",
    re.I,
)

# Pattern: "Find a Grave Memorial 12345" or "FaG: 12345"
_FAG_TEXT_RE = re.compile(
    r"(?:Find\s+a\s+Grave(?:\s+Memorial)?|FaG[:\s]+)\s*[:\s]*\s*(\d+)",
    re.I,
)

# Generic "memorial NNN" pattern (when not in URL form)
_FAG_BARE_RE = re.compile(
    r"memorial[:#\s]+\s*(\d+)",
    re.I,
)


@dataclass
class FagLink:
    """An FaG backlink discovered in a CGR record."""
    memorial_id: str
    url: str
    source_field: str = ""  # which field it came from

    def to_dict(self) -> dict:
        return {
            "memorial_id": self.memorial_id,
            "url": self.url,
            "source_field": self.source_field,
            "match_method": "direct_link",
        }


def find_fag_url(text: str) -> str | None:
    """Find the first FaG URL in text, or None."""
    if not text:
        return None
    m = _FAG_URL_RE.search(text)
    if m:
        return f"https://www.findagrave.com/memorial/{m.group(1)}"
    return None


def has_fag_link(text: str) -> bool:
    """Heuristic: does the text mention FaG?"""
    return extract_fag_memorial_id(text) is not None


def extract_fag_memorial_id(text: str) -> FagLink | None:
    """Extract an FaG memorial reference from text.

    Tries URL first, then text patterns.
    Returns FagLink or None.
    """
    if not text:
        return None
    # 1. Try URL pattern
    m = _FAG_URL_RE.search(text)
    if m:
        return FagLink(
            memorial_id=m.group(1),
            url=f"https://www.findagrave.com/memorial/{m.group(1)}",
        )
    # 2. Try text patterns
    m = _FAG_TEXT_RE.search(text)
    if m:
        return FagLink(memorial_id=m.group(1), url="")
    # 3. Try "memorial 12345"
    m = _FAG_BARE_RE.search(text)
    if m:
        return FagLink(memorial_id=m.group(1), url="")
    return None


def extract_fag_source_fields(record: dict) -> FagLink | None:
    """Scan a vet record's text fields for FaG references."""
    SEARCH_FIELDS = ("source", "notes", "submitted_by", "spouse")
    for fld in SEARCH_FIELDS:
        val = record.get(fld)
        if not val or not isinstance(val, str):
            continue
        link = extract_fag_memorial_id(val)
        if link:
            link.source_field = fld
            return link
    return None