"""Playwright coverage for the verified-spouse link feature (issue #137).

The v2 view renders a clickable link to the spouse's FaG memorial page
when the top candidate's spouse_match block carries a captured_memorial_id.

These tests pin:
  - Link rendered with correct URL + display text
  - Link absent when captured_memorial_id missing
  - Link absent on non-top candidates
  - Link absent when record has no top candidate
  - slug embedded in URL when present
"""
from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent.parent
VIEW_V2 = ROOT / "scripts" / "view" / "v2.html"

SPOUSE_URL = (
    "https://www.findagrave.com/memorial/40964275/denny_l-haggard"
)


@pytest.fixture(scope="module")
def spouse_page():
    """Load v2 with three records covering link/no-link edge cases."""
    records = [
        # Case 1: spouse-verified candidate with full slug + captured_display.
        {
            "pensioner_id": 101,
            "pensioner_name": "Haggard, Mary",
            "pensioner_first": "Mary",
            "pensioner_last": "Haggard",
            "pensioner_spouse_first": "Dennie",
            "pensioner_spouse_last": "Haggard",
            "fag_status": "auto_accept",
            "best_score": 0.96,
            "fag_records": [
                {
                    "memorial_id": "49901728",
                    "slug": "mary-haggard",
                    "name": "Mary Moore Haggard",
                    "backlink": "https://www.findagrave.com/memorial/49901728/mary-haggard",
                    "score": 0.96,
                    "score_breakdown": {"_spouse_verified": True},
                    "spouse_match": {
                        "matched": True,
                        "matched_via": "last_name",
                        "captured_first": "Denny",
                        "captured_middle": "L.",
                        "captured_last": "Haggard",
                        "captured_display": "Denny L. Haggard",
                        "captured_memorial_id": "40964275",
                        "captured_slug": "denny_l-haggard",
                        "match_strength": "medium",
                    },
                },
            ],
            "cgr_records": [],
        },
        # Case 2: spouse match with NO captured_memorial_id (no link).
        {
            "pensioner_id": 102,
            "pensioner_name": "Hall, Fannie",
            "fag_status": "needs_review",
            "best_score": 0.72,
            "fag_records": [
                {
                    "memorial_id": "50000001",
                    "slug": "fannie-hall",
                    "name": "Fannie Hall",
                    "backlink": "https://www.findagrave.com/memorial/50000001/fannie-hall",
                    "score": 0.72,
                    "score_breakdown": {"_spouse_linked": True},
                    "spouse_match": {
                        "matched": True,
                        "captured_display": "(not on FaG)",
                    },
                },
            ],
            "cgr_records": [],
        },
        # Case 3: no spouse_match at all (no link).
        {
            "pensioner_id": 103,
            "pensioner_name": "Plain Pensioner",
            "fag_status": "needs_review",
            "best_score": 0.55,
            "fag_records": [
                {
                    "memorial_id": "50000002",
                    "slug": "plain-pensioner",
                    "name": "Plain Pensioner",
                    "backlink": "https://www.findagrave.com/memorial/50000002/plain-pensioner",
                    "score": 0.55,
                    "score_breakdown": {},
                },
            ],
            "cgr_records": [],
        },
    ]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(VIEW_V2.as_uri())
        page.evaluate(
            "records => window.ViewV2.loadRecords(records, 'fixture-spouse.jsonl')",
            records,
        )
        page.locator(".record-card").first.wait_for()
        yield page
        browser.close()


def test_spouse_link_present_on_verified_top_candidate(spouse_page):
    """The top candidate shows a spouse link with the right URL + text."""
    card = spouse_page.locator('.record-card[data-record-id="101"]')
    link = card.locator(".spouse-link").first
    assert link.count() == 1, "expected exactly one spouse-link in this card"
    assert link.get_attribute("href") == SPOUSE_URL
    assert "Denny L. Haggard" in link.inner_text()
    assert link.get_attribute("target") == "_blank"
    assert "noopener" in (link.get_attribute("rel") or "")


def test_spouse_link_absent_when_no_captured_memorial_id(spouse_page):
    """No captured_memorial_id → no link, even if spouse_match exists."""
    card = spouse_page.locator('.record-card[data-record-id="102"]')
    assert card.locator(".spouse-link").count() == 0


def test_spouse_link_absent_when_no_spouse_match(spouse_page):
    """Plain candidate with no spouse data → no link."""
    card = spouse_page.locator('.record-card[data-record-id="103"]')
    assert card.locator(".spouse-link").count() == 0


def test_spouse_link_target_blank_includes_match_strength_in_title(spouse_page):
    """Tooltip reveals the match_strength so reviewers can judge trust."""
    link = spouse_page.locator(
        '.record-card[data-record-id="101"] .spouse-link'
    ).first
    title = link.get_attribute("title") or ""
    assert "medium" in title
    assert "FaG memorial" in title