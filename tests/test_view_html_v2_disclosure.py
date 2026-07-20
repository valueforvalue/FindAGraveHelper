"""Playwright tests for view.html v2 Commit 4 engine disclosure scaffolding."""
import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent.parent
VIEW_V2 = ROOT / "scripts" / "view" / "v2.html"

RECORDS = [
    {
        "pensioner_id": 401,
        "pensioner_name": "FaG Disclosure Pensioner",
        "fag_status": "auto_accept",
        "fag_records": [
            {
                "memorial_id": "fag-disclose-401",
                "slug": "fag-disclosure-slug",
                "name": "FaG Disclosure Candidate",
                "backlink": "https://www.findagrave.com/memorial/fag-disclose-401/fag-disclosure-slug",
                "iiif_url": "https://www.findagrave.com/iiif/2/memorial:fag-disclose-401",
                "score": 0.88,
                "score_breakdown": {
                    "last": 1.0, "first": 1.0, "middle": 0.5,
                    "ok_burial": 0.3, "state": 0.1, "veteran": 0.8, "death": 0.5,
                },
                "details": {
                    "birth_year": "1844", "death_year": "1932",
                    "state": "Oklahoma", "is_veteran": True,
                },
                "_found_by": {"strategy": "B1-exact", "params": {"firstname": "John", "lastname": "Smith"}},
                "via_strategies": ["B1-exact"],
            },
        ],
    },
    {
        "pensioner_id": 402,
        "pensioner_name": "Newspapers Stub Pensioner",
        "engine": "newspapers_com",
        "fag_status": "needs_review",
        "fag_records": [
            {
                "memorial_id": "news-disclose-402",
                "name": "Newspapers Stub Candidate",
                "score": 0.72,
                "details": {},
            },
        ],
    },
]


@pytest.fixture(scope="module")
def disclosure_page():
    """Load FaG and Newspapers records for engine-disclosure tests."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(VIEW_V2.as_uri())
        page.evaluate(
            "records => window.ViewV2.loadRecords(records, 'commit-4-results.jsonl')",
            RECORDS,
        )
        page.locator(".record-card").first.wait_for()
        yield page
        browser.close()


def test_dispatcher_renders_fag_details_for_findagrave_record(disclosure_page):
    """FaG-specific details appear behind disclosure when engine is findagrave."""
    card = disclosure_page.locator('.record-card[data-record-id="401"]')
    details = card.locator(".engine-disclosure")
    assert details.count() == 1
    assert "findagrave details" in details.locator("summary").inner_text()


def test_fag_disclosure_exposes_all_seven_score_features(disclosure_page):
    """Full 7-feature breakdown lives inside engine disclosure."""
    details = disclosure_page.locator(
        '.record-card[data-record-id="401"] .engine-disclosure'
    )
    details.evaluate("el => el.open = true")
    body = details.inner_text()
    assert "last name" in body
    assert "first name" in body
    assert "middle name" in body
    assert "OK burial" in body
    assert "served state" in body
    assert "VETERAN" in body
    assert "death year" in body


def test_fag_disclosure_exposes_paged_memorial_image(disclosure_page):
    """IIIF image link appears alongside feature breakdown."""
    details = disclosure_page.locator(
        '.record-card[data-record-id="401"] .engine-disclosure'
    )
    details.evaluate("el => el.open = true")
    body = details.inner_text()
    assert "image" in body


def test_fag_disclosure_exposes_found_by_provenance(disclosure_page):
    """Found-by strategy and params live inside disclosure."""
    details = disclosure_page.locator(
        '.record-card[data-record-id="401"] .engine-disclosure'
    )
    details.evaluate("el => el.open = true")
    body = details.inner_text()
    assert "B1-exact" in body
    assert "John" in body


def test_dispatcher_renders_newspapers_stub_for_newspapers_com_record(disclosure_page):
    """Non-FaG engine shows placeholder disclosure without FaG feature labels."""
    card = disclosure_page.locator('.record-card[data-record-id="402"]')
    details = card.locator(".engine-disclosure")
    assert details.count() == 1
    details.locator("summary").click()
    body = details.inner_text()
    assert "No evidence details available" in body
    assert "last name" not in body
