"""Playwright coverage for view.html v2's four-row review layout."""
import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent.parent
VIEW_V2 = ROOT / "scripts" / "view" / "v2.html"


@pytest.fixture(scope="module")
def layout_page():
    """Load v2 with representative existing state.jsonl records."""
    records = [
        {
            "pensioner_id": 5,
            "pensioner_name": "Hugh H. Akers",
            "pensioner_first": "Hugh",
            "pensioner_middle": "H.",
            "pensioner_last": "Akers",
            "pensioner_app_number": "A-5",
            "pensioner_birth_year": "1846",
            "pensioner_death_year": "1924",
            "regiment": "Co. A, 1st AR Infantry",
            "company": "A",
            "pensioncard_backlink": "https://digitalprairie.example/card/5",
            "backlink": "https://digitalprairie.example/application/5",
            "fag_status": "auto_accept",
            "best_score": 0.91,
            "fag_records": [
                {
                    "memorial_id": "26716384",
                    "slug": "hugh-h-akers",
                    "name": "Rev Hugh H Akers",
                    "backlink": "https://www.findagrave.com/memorial/26716384/hugh-h-akers",
                    "iiif_url": "https://www.findagrave.com/iiif/2/memorial:26716384",
                    "score": 0.91,
                    "score_breakdown": {
                        "last": 1.0,
                        "first": 1.0,
                        "middle": 1.0,
                        "death": 0.5,
                    },
                    "details": {
                        "birth_year": "1846",
                        "death_year": "1924",
                        "state": "Oklahoma",
                        "is_veteran": True,
                    },
                    "_found_by": {"strategy": "B1-exact"},
                },
                {
                    "memorial_id": "999",
                    "slug": "hugh-akers",
                    "name": "Hugh Akers",
                    "backlink": "https://www.findagrave.com/memorial/999/hugh-akers",
                    "score": 0.61,
                    "score_breakdown": {"last": 1.0, "first": 1.0},
                    "details": {"birth_year": "1848", "death_year": "1915"},
                },
            ],
            "cgr_records": [{"cgr_id": "cgr-5"}],
            "dd_match": {"dd_memorial_id": "26716384"},
            "pensioner_spouse_first": "Jane",
            "pensioner_spouse_last": "Akers",
        },
        {
            "pensioner_id": 8,
            "pensioner_name": "No Candidate Pensioner",
            "fag_status": "no_results",
            "fag_records": [],
            "cgr_records": [],
        },
    ]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(VIEW_V2.as_uri())
        page.evaluate(
            "records => window.ViewV2.loadRecords(records, 'fixture-results.jsonl')",
            records,
        )
        page.locator(".record-card").first.wait_for()
        yield page
        browser.close()


def test_renders_record_card_per_existing_state_record(layout_page):
    """Current state.jsonl records render without wire-format changes."""
    assert layout_page.locator(".record-card").count() == 2
    assert "2 records" in layout_page.locator("#runTitle").inner_text()


def test_card_uses_four_row_review_structure(layout_page):
    """Identity, status, candidates, and reviewer notes remain scannable."""
    card = layout_page.locator('.record-card[data-record-id="5"]')

    assert card.get_attribute("aria-labelledby") == "record-1h-heading"
    assert card.locator(".record-identity").count() == 1
    assert card.locator(".record-status").count() == 1
    assert card.locator(".record-candidates").count() == 1
    assert card.locator(".record-notes").count() == 1
    assert card.locator("textarea[aria-label='Reviewer notes for Hugh H. Akers']").count() == 1


def test_header_shows_engine_and_source_identity(layout_page):
    """Reviewer sees engine, pensioner name, ID, source links, and lifespan."""
    card = layout_page.locator('.record-card[data-record-id="5"]')

    assert card.locator(".engine-badge").inner_text() == "findagrave"
    assert card.locator("h2").inner_text() == "Hugh H. Akers"
    assert card.locator(".record-id").inner_text() == "#5"
    assert "1846–1924" in card.locator(".record-meta").inner_text()
    assert card.locator("a", has_text="source card").count() == 1
    assert card.locator("a", has_text="View source").count() == 1


def test_renderer_accepts_normalized_shape_without_fag_fields(layout_page):
    """Common renderer works without memorial_id, backlink, or score_breakdown."""
    rendered = layout_page.evaluate(
        """() => window.ViewV2.renderRecord({
            id: 'future-1',
            title: 'Future source record',
            engine: 'future_engine',
            attributes: {},
            status: 'needs_review',
            best_score: 0.75,
            candidates: [{
                id: 'future-candidate',
                title: 'Normalized future candidate',
                url: 'https://example.com/candidate',
                score: 0.75,
                attributes: {birth_year: '1840', death_year: '1900'},
                media: {},
                evidence: {
                    score_breakdown: {
                        last_name: 1,
                        first_name: 0.5,
                        year_window: 0.4,
                    },
                    raw: {},
                },
            }],
            corroboration: {cgr: [], dd_match: null, spouse_match: null},
        })"""
    )

    assert "future_engine" in rendered
    assert "Normalized future candidate" in rendered
    assert "1840–1900" in rendered


def test_status_and_corroboration_are_grouped(layout_page):
    """Engine status and reviewer decision sit above grouped corroboration."""
    card = layout_page.locator('.record-card[data-record-id="5"]')
    status_row = card.locator(".record-status")

    assert status_row.locator(".status-pill").inner_text() == "auto_accept"
    assert status_row.locator(".decision-pill").inner_text() == "undecided"
    corroboration = status_row.locator(".corroboration-summary").inner_text()
    assert "CGR 1 match" in corroboration
    assert "DD tracked ✓" in corroboration
    assert "Spouse known ✓" in corroboration
    assert "CGR 0 matches" in layout_page.locator(
        '.record-card[data-record-id="8"] .corroboration-summary'
    ).inner_text()


def test_candidate_row_exposes_common_content_and_prominent_actions(layout_page):
    """Candidate name, score evidence, links, notes, Pick, and remove are visible."""
    candidate = layout_page.locator('[data-record-id="5"] .candidate-row').first

    assert "Rev Hugh H Akers" in candidate.inner_text()
    assert "1846–1924" in candidate.inner_text()
    assert "Oklahoma" in candidate.inner_text()
    assert candidate.locator(".candidate-score").inner_text() == "0.91"
    assert candidate.locator('[data-feature="last_name"]').count() == 1
    assert candidate.locator('[data-feature="first_name"]').count() == 1
    assert candidate.locator('[data-feature="year_window"]').count() == 1
    assert candidate.locator("a", has_text="open").count() == 1
    assert candidate.locator("a", has_text="image").count() == 1
    assert candidate.locator("input[aria-label='Notes for candidate Rev Hugh H Akers']").count() == 1
    assert candidate.locator("button", has_text="Pick").count() == 1
    assert candidate.locator("button[aria-label='Remove Rev Hugh H Akers']").count() == 1


def test_candidate_actions_change_visible_review_state(layout_page):
    """Commit 1 layout keeps v1 Pick, remove, and note behavior usable."""
    card = layout_page.locator('.record-card[data-record-id="5"]')
    first = card.locator(".candidate-row").first

    first.locator("button", has_text="Pick").click()
    assert card.locator(".decision-pill").inner_text() == "picked"
    assert first.locator(".picked-badge").count() == 1

    first.locator("button[aria-label='Remove Rev Hugh H Akers']").click()
    assert "removed" in first.get_attribute("class").split()

    note = first.locator("input[aria-label='Notes for candidate Rev Hugh H Akers']")
    note.fill("same regiment")
    note.blur()
    decision = layout_page.evaluate("window.ViewV2.getDecisions()['5']")
    assert decision["candidate_notes"]["26716384"] == "same regiment"


def test_empty_candidate_state_stays_actionable(layout_page):
    """No-result records show empty state plus pensioner-level review controls."""
    card = layout_page.locator('.record-card[data-record-id="8"]')

    assert "No candidates found" in card.locator(".candidate-empty").inner_text()
    assert card.locator("button", has_text="No match").count() == 1
    assert card.locator("textarea").count() == 1


def test_real_past_run_renders_unchanged_state_jsonl(layout_page):
    """Committed past-run fixture renders without wire-format changes."""
    raw_records = [
        json.loads(line)
        for line in (ROOT / "tests" / "fixtures" / "view_v2" / "results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    layout_page.evaluate(
        "records => window.ViewV2.loadRecords(records, 'test-batch-25/results.jsonl')",
        raw_records,
    )

    assert layout_page.locator(".record-card").count() == 2
    assert layout_page.locator(".candidate-row").count() == 2
    assert layout_page.locator(".record-card .engine-badge").first.inner_text() == "findagrave"
    assert layout_page.locator('[data-record-id="15"] .candidate-empty').count() == 1


def test_same_filename_runs_do_not_share_browser_decisions(layout_page):
    """Distinct results content gets distinct localStorage crash-recovery state."""
    first_run = [{
        "pensioner_id": "run-a",
        "pensioner_name": "First run",
        "fag_records": [{
            "memorial_id": "candidate-a",
            "name": "Candidate A",
            "score": 0.8,
        }],
    }]
    second_run = [{
        "pensioner_id": "run-b",
        "pensioner_name": "Second run",
        "fag_records": [{
            "memorial_id": "candidate-b",
            "name": "Candidate B",
            "score": 0.7,
        }],
    }]

    layout_page.evaluate(
        "records => window.ViewV2.loadRecords(records, 'results.jsonl')", first_run
    )
    layout_page.locator("button", has_text="Pick").click()
    layout_page.evaluate(
        "records => window.ViewV2.loadRecords(records, 'results.jsonl')", second_run
    )

    assert layout_page.evaluate("window.ViewV2.getDecisions()") == {}
    assert layout_page.locator(".decision-pill").inner_text() == "undecided"


def test_file_picker_allows_same_file_retry_after_parse_error(layout_page, tmp_path):
    """Malformed JSONL can be fixed and re-selected at same path."""
    results_file = tmp_path / "results.jsonl"
    results_file.write_text("not json\n", encoding="utf-8")

    file_input = layout_page.locator("#resultsFile")
    file_input.set_input_files(results_file)
    layout_page.wait_for_function(
        "document.getElementById('loadStatus').textContent.includes('Could not load results')"
    )

    results_file.write_text(
        json.dumps({
            "pensioner_id": "fixed",
            "pensioner_name": "Fixed record",
            "fag_records": [],
        }) + "\n",
        encoding="utf-8",
    )
    file_input.set_input_files(results_file)
    fixed_card = layout_page.locator('.record-card[data-record-id="fixed"]')
    fixed_card.wait_for()

    assert fixed_card.count() == 1
