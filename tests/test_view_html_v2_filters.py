"""Playwright behavior tests for view.html v2 Commit 2 controls."""
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent.parent
VIEW_V2 = ROOT / "scripts" / "view" / "v2.html"


RECORDS = [
    {
        "pensioner_id": 101,
        "pensioner_name": "Five Candidate Pensioner",
        "fag_status": "ambiguous",
        "fag_records": [
            {
                "memorial_id": f"fag-{rank}",
                "name": f"Find a Grave Candidate {rank}",
                "score": 1 - rank / 10,
                "score_breakdown": {"last": 1, "first": 0.8, "death": 0.5},
                "details": {"birth_year": "1840", "death_year": f"190{rank}"},
            }
            for rank in range(1, 6)
        ],
    },
    {
        "pensioner_id": 102,
        "pensioner_name": "Two Candidate Pensioner",
        "fag_status": "auto_accept",
        "fag_records": [
            {"memorial_id": "two-a", "name": "Two Candidate A", "score": 0.9},
            {"memorial_id": "two-b", "name": "Two Candidate B", "score": 0.8},
        ],
    },
    {
        "pensioner_id": 103,
        "pensioner_name": "Newspaper Pensioner",
        "engine": "newspapers_com",
        "fag_status": "needs_review",
        "fag_records": [
            {"memorial_id": "news-1", "name": "Newspaper Candidate", "score": 0.7},
        ],
    },
    {
        "pensioner_id": 104,
        "pensioner_name": "Follow-up Pensioner",
        "fag_status": "needs_review",
        "fag_records": [],
    },
]


@pytest.fixture(scope="module")
def browser():
    """Launch one Chromium process for Commit 2 interaction tests."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def filters_page(browser):
    """Load fresh Commit 2 fixture state for each behavior."""
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(VIEW_V2.as_uri())
    page.evaluate(
        "records => window.ViewV2.loadRecords(records, 'commit-2-results.jsonl')",
        RECORDS,
    )
    page.locator(".record-card").first.wait_for()
    yield page
    page.close()


def test_record_collapse_removes_expensive_rows_and_restores_them(filters_page):
    """Record toggle keeps compact summary while removing expanded DOM."""
    card = filters_page.locator('.record-card[data-record-id="101"]')
    toggle = card.locator('[data-action="toggle-record"]')

    assert toggle.get_attribute("aria-expanded") == "true"
    assert card.locator(".record-status").count() == 1
    assert card.locator(".candidate-row").count() == 3

    toggle.click()
    # Alpine x-if removes/attaches elements asynchronously.
    # Wait for expanded sections to disappear.
    card.locator(".record-status").wait_for(state="detached")

    assert toggle.get_attribute("aria-expanded") == "false"
    assert card.locator(".collapsed-summary").count() == 1
    assert card.locator(".record-status").count() == 0
    assert card.locator(".candidate-row").count() == 0

    toggle.click()
    assert card.locator(".record-status").count() == 1


def test_collapse_all_and_expand_all_control_every_visible_card(filters_page):
    """Header controls collapse and restore whole result set."""
    filters_page.locator("#collapseAll").click()

    assert filters_page.locator('.record-card [aria-expanded="false"]').count() == 4
    assert filters_page.locator(".record-status").count() == 0

    filters_page.locator("#expandAll").click()

    assert filters_page.locator('.record-card [aria-expanded="true"]').count() == 4
    assert filters_page.locator(".record-status").count() == 4


def test_engine_filter_options_come_from_loaded_records(filters_page):
    """Engine facet is populated from data and filters record cards."""
    options = filters_page.locator("#engineFilter option")
    assert options.evaluate_all("els => els.map(el => [el.value, el.textContent])") == [
        ["all", "All engines"],
        ["findagrave", "findagrave"],
        ["newspapers_com", "newspapers_com"],
    ]

    filters_page.locator("#engineFilter").select_option("newspapers_com")

    assert filters_page.locator(".record-card").count() == 1
    assert filters_page.locator(".engine-badge").inner_text() == "newspapers_com"


def test_decision_filter_covers_picked_none_match_and_follow_up(filters_page):
    """Decision facet reflects reviewer state without separate pages."""
    first_card = filters_page.locator('.record-card[data-record-id="101"]')
    first_card.locator('[data-action="pick"]').first.click()
    filters_page.locator("#decisionFilter").select_option("picked")
    assert filters_page.locator(".record-card").count() == 1
    assert filters_page.locator(".record-card").get_attribute("data-record-id") == "101"

    filters_page.locator("#decisionFilter").select_option("all")
    second_card = filters_page.locator('.record-card[data-record-id="102"]')
    second_card.locator('[data-action="none-match"]').click()
    filters_page.locator("#decisionFilter").select_option("none_match")
    assert filters_page.locator(".record-card").get_attribute("data-record-id") == "102"

    filters_page.evaluate(
        "window.ViewV2.getDecisions()['104'] = {decision_type: 'follow_up'}"
    )
    filters_page.locator("#decisionFilter").select_option("follow_up")
    assert filters_page.locator(".record-card").get_attribute("data-record-id") == "104"

    filters_page.locator("#decisionFilter").select_option("undecided")
    visible_ids = filters_page.locator(".record-card").evaluate_all(
        "cards => cards.map(card => card.dataset.recordId)"
    )
    assert visible_ids == ["103"]


def test_pick_hides_other_candidates_until_show_all(filters_page):
    """Picking keeps chosen candidate visible and collapses its siblings."""
    card = filters_page.locator('.record-card[data-record-id="101"]')
    card.locator('[data-action="show-all-candidates"]').click()
    assert card.locator(".candidate-row").count() == 5

    card.locator('[data-candidate-id="fag-2"] [data-action="pick"]').click()

    assert card.locator(".candidate-row").count() == 1
    assert card.locator(".candidate-row").get_attribute("data-candidate-id") == "fag-2"
    assert card.locator(".picked-badge").count() == 1
    assert card.locator('[data-action="show-all-candidates"]').inner_text() == "Show all candidates"

    card.locator('[data-action="show-all-candidates"]').click()
    assert card.locator(".candidate-row").count() == 5


def test_none_match_does_not_hide_candidates(filters_page):
    """No-match decision leaves candidate evidence visible for review."""
    card = filters_page.locator('.record-card[data-record-id="102"]')
    assert card.locator(".candidate-row").count() == 2

    card.locator('[data-action="none-match"]').click()

    assert card.locator(".decision-pill").inner_text() == "none_match"
    assert card.locator(".candidate-row").count() == 2
