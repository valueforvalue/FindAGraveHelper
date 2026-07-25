"""Tests for #123: burial state extraction from FaG search result cards.

Commit a4a8ad6 replaced ancestor DOM read with link.inner_text()
which drops cemetery/location text, causing candidate_state to
always be None. The fix restores location text via a lightweight
evaluate() call.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from scripts.fag.parser import parse_results_page


# FaG-like card text with location in ancestor element
FAG_CARD_LINK_TEXT = "John Smith\n1840 – 1920"
FAG_CARD_LOCATION_TEXT = "Battle Creek Cemetery\nEolian, Stephens County, Texas"
FAG_CARD_FULL = FAG_CARD_LINK_TEXT + "\n" + FAG_CARD_LOCATION_TEXT

# What link.inner_text() returns (no location)
FAG_LINK_INNER = "John Smith V Veteran\n1840 – 1920"

# FaG card with no location data
FAG_CARD_NO_LOCATION = "Unknown Person\nunknown – unknown"


class _FakeLink:
    """Simulates a Playwright locator element."""

    def __init__(self, href: str, inner_text: str, ancestor_text: str) -> None:
        self._href = href
        self._inner_text = inner_text
        self._ancestor_text = ancestor_text

    def get_attribute(self, name: str) -> str:
        return self._href

    def inner_text(self, timeout: float = 2000) -> str:
        return self._inner_text

    def evaluate(self, js: str) -> str:
        # Simulate el.parentElement?.parentElement?.innerText
        return self._ancestor_text


class _FakeLocator:
    """Simulates Playwright page.locator()."""

    def __init__(self, links: list[_FakeLink]) -> None:
        self._links = links

    def count(self) -> int:
        return len(self._links)

    def nth(self, i: int) -> _FakeLink:
        return self._links[i]


def _make_fake_page(links: list[_FakeLink], total: int = 1) -> MagicMock:
    """Create a mock Playwright Page that returns the given links."""
    page = MagicMock()
    page.locator.return_value = _FakeLocator(links)
    page.evaluate.return_value = f"{total} matching records"
    page.wait_for_selector.return_value = MagicMock()
    page.wait_for_selector.return_value.dispose = MagicMock()
    return page


def test_parser_extracts_state_from_location_text():
    """Card text with location in ancestor should yield candidate_state."""
    link = _FakeLink(
        href='/memorial/50923719/john-smith"',
        inner_text=FAG_LINK_INNER,
        ancestor_text=FAG_CARD_LOCATION_TEXT,
    )
    page = _make_fake_page([link], total=1)
    total, candidates = parse_results_page(page)
    assert total == 1
    assert len(candidates) == 1
    assert candidates[0]["details"]["state"] == "TX"


def test_parser_extracts_state_from_full_card():
    """State abbreviation in ancestor location text should be found."""
    link = _FakeLink(
        href='/memorial/12345/jane-doe"',
        inner_text="Jane Doe\n1900 – 1950",
        ancestor_text="Oakwood Cemetery\nTulsa, Tulsa County, OK",
    )
    page = _make_fake_page([link], total=1)
    total, candidates = parse_results_page(page)
    assert len(candidates) == 1
    assert candidates[0]["details"]["state"] == "OK"


def test_parser_returns_none_when_no_location():
    """Card with no location should return None for state (not crash)."""
    link = _FakeLink(
        href='/memorial/99999/unknown"',
        inner_text=FAG_CARD_NO_LOCATION,
        ancestor_text="",  # No ancestor text
    )
    page = _make_fake_page([link], total=1)
    total, candidates = parse_results_page(page)
    assert len(candidates) == 1
    assert candidates[0]["details"]["state"] is None


def test_parser_extracts_cemetery_from_location():
    """Cemetery name should be extracted from location text."""
    link = _FakeLink(
        href='/memorial/11111/test-person"',
        inner_text="Test Person\n1865 – 1920",
        ancestor_text="Arlington National Cemetery\nArlington, Arlington County, Virginia",
    )
    page = _make_fake_page([link], total=1)
    total, candidates = parse_results_page(page)
    assert len(candidates) == 1
    assert candidates[0]["details"]["state"] == "VA"
    assert "Arlington National Cemetery" in candidates[0]["details"]["cemetery"]


def test_parser_state_not_from_link_text():
    """Ensure state is NOT extracted from link text alone.
    The link text 'John Smith V Veteran 1840-1920' has no state.
    Before the fix, card_text was just link text → always None.
    """
    link = _FakeLink(
        href='/memorial/22222/test"',
        inner_text="John Smith V Veteran\n1840 – 1920",
        ancestor_text="",  # Empty ancestor → no location
    )
    page = _make_fake_page([link], total=1)
    total, candidates = parse_results_page(page)
    assert len(candidates) == 1
    assert candidates[0]["details"]["state"] is None


def test_parser_handles_multiple_candidates():
    """Multiple candidates with mixed location data."""
    links = [
        _FakeLink(
            href=f'/memorial/{i}/person"',
            inner_text=f"Person {i}\n1900 – 1950",
            ancestor_text=f"Cemetery {i}\nCity{i}, County{i}, OK" if i % 2 == 0 else "",
        )
        for i in range(5)
    ]
    page = _make_fake_page(links, total=5)
    total, candidates = parse_results_page(page)
    assert len(candidates) == 5
    # Even-indexed candidates have state OK
    for i, c in enumerate(candidates):
        if i % 2 == 0:
            assert c["details"]["state"] == "OK", f"Candidate {i} should have state OK"
        else:
            assert c["details"]["state"] is None, f"Candidate {i} should have no state"
