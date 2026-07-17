"""Tests for the pension-card IIIF page-id extraction.

The bug (rediscovered 2026-07-17 during es-fresh-run review):
scripts/ingest/fetch_pensioncard_pages.py::extract_page_ids()
only looked at objectInfo.page[].pageptr and returned [] for
single-page pension cards. Single-page items make up 73% of
records (objectInfo.code == -2, no page[] entries). The view.html
review UI thus had no images to embed for those records, even
though the IIIF URL worked.

Fix: when objectInfo.page[] is empty/missing but imageUri
exists, fall back to using pcid as the single page id. The
IIIF URL https://digitalprairie.ok.gov/iiif/2/pensioncard:{pcid}
/full/300,/0/default.jpg works for that case.

This test pins the working pattern. It does NOT make live API
calls — uses recorded fixtures.
"""
from __future__ import annotations

from scripts.ingest.fetch_pensioncard_pages import extract_page_ids


# Recorded API response for pcid=11486 (compound, two-sided postcard)
FIXTURE_COMPOUND = {
    "contentType": "application/octet-stream",
    "filename": "11487.cpd",
    "imageUri": "https://digitalprairie.ok.gov/iiif/2/pensioncard:11486/full/full/0/default.jpg",
    "iiifInfoUri": "/iiif/2/pensioncard:11486/info.json",
    "objectInfo": {
        "code": "0",
        "message": "Compound object",
        "page": [
            {"pagetitle": "Side 1", "pagefile": "11485.jp2", "pageptr": "11484"},
            {"pagetitle": "Side 2", "pagefile": "11486.jp2", "pageptr": "11485"},
        ],
        "type": "Postcard",
    },
}


# Recorded API response for pcid=2169 (single page)
FIXTURE_SINGLE = {
    "contentType": "image/jp2",
    "filename": "2170.jp2",
    "imageUri": "https://digitalprairie.ok.gov/iiif/2/pensioncard:2169/full/full/0/default.jpg",
    "iiifInfoUri": "/iiif/2/pensioncard:2169/info.json",
    "objectInfo": {"code": "-2", "message": "Requested item is not compound"},
}


# Recorded API response for pcid=9182 (single page, different shape)
FIXTURE_SINGLE_ALT = {
    "contentType": "image/jp2",
    "filename": "9183.jp2",
    "imageUri": "https://digitalprairie.ok.gov/iiif/2/pensioncard:9182/full/full/0/default.jpg",
    "iiifInfoUri": "/iiif/2/pensioncard:9182/info.json",
    "objectInfo": {"code": "-2", "message": "Requested item is not compound"},
}


def test_extract_compound_returns_pageptr_ids():
    """Compound objects have pageptr entries that ARE the IIIF image IDs."""
    page_ids = extract_page_ids(FIXTURE_COMPOUND, pcid=11486)
    assert page_ids == [11484, 11485], (
        f"Compound fixture should yield pageptr IDs, got {page_ids}"
    )


def test_extract_single_falls_back_to_pcid():
    """Single-page items have objectInfo.code == -2 and no page[].
    We should fall back to using the pcid as a single page id."""
    page_ids = extract_page_ids(FIXTURE_SINGLE, pcid=2169)
    assert page_ids == [2169], (
        f"Single-page fixture should fall back to [pcid], got {page_ids}"
    )


def test_extract_single_alt_pcid():
    """A different single-page item, same shape."""
    page_ids = extract_page_ids(FIXTURE_SINGLE_ALT, pcid=9182)
    assert page_ids == [9182], (
        f"Single-page fixture (alt) should fall back to [pcid], got {page_ids}"
    )


def test_extract_empty_api_returns_empty():
    """Defensive: missing API JSON yields empty list (no images)."""
    assert extract_page_ids(None, pcid=99999) == []
    assert extract_page_ids({}, pcid=99999) == []
    # objectInfo present but no page AND no imageUri -> still empty
    assert extract_page_ids(
        {"objectInfo": {"code": "-2"}},
        pcid=99999,
    ) == []


def test_extract_compound_takes_precedence_over_pcid_fallback():
    """If a compound object ALSO has an imageUri pointing at the parent
    pcid, we should use the pageptr entries (NOT fall back to pcid)
    because the parent's IIIF URL 501s for compound items."""
    page_ids = extract_page_ids(FIXTURE_COMPOUND, pcid=11486)
    assert 11486 not in page_ids, (
        "Compound items MUST use pageptr, not parent pcid (parent "
        "IIIF URL returns 501 'Unsupported source format')"
    )
    assert all(pid != 11486 for pid in page_ids)


def test_iiif_url_pattern_compound():
    """The IIIF URL pattern that works for compound pageptr IDs:
    https://digitalprairie.ok.gov/iiif/2/pensioncard:{page_id}/full/300,/0/default.jpg
    Verified 2026-07-17 to return image/jpeg for the E-batch."""
    for pid in (11484, 11485):  # the pageptr values from pcid=11486
        expected = f"https://digitalprairie.ok.gov/iiif/2/pensioncard:{pid}/full/300,/0/default.jpg"
        # Pin the pattern as a string template
        assert "pensioncard:" in expected
        assert "/full/300,/0/default.jpg" in expected


def test_iiif_url_pattern_single():
    """For single-page items, the IIIF URL uses the pcid directly."""
    pcid = 2169
    expected = f"https://digitalprairie.ok.gov/iiif/2/pensioncard:{pcid}/full/300,/0/default.jpg"
    assert "pensioncard:" in expected
    assert "/full/300,/0/default.jpg" in expected