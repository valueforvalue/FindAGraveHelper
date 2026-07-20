"""Playwright tests for view.html v2 Commit 3 export download shapes."""
import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent.parent
VIEW_V2 = ROOT / "scripts" / "view" / "v2.html"

RECORDS = [
    {
        "pensioner_id": 201,
        "pensioner_name": "Pickable Pensioner",
        "fag_status": "auto_accept",
        "fag_records": [
            {
                "memorial_id": "mem-201-a",
                "slug": "pickable-candidate-a",
                "name": "Pickable Candidate A",
                "backlink": "https://www.findagrave.com/memorial/mem-201-a/pickable-candidate-a",
                "score": 0.95,
                "score_breakdown": {"last": 1, "first": 1, "death": 0.5},
                "details": {"birth_year": "1840", "death_year": "1901", "state": "Oklahoma"},
                "_found_by": {"strategy": "B1-exact"},
            },
            {
                "memorial_id": "mem-201-b",
                "slug": "pickable-candidate-b",
                "name": "Pickable Candidate B",
                "backlink": "https://www.findagrave.com/memorial/mem-201-b/pickable-candidate-b",
                "score": 0.61,
                "score_breakdown": {"last": 1, "first": 0.8},
                "details": {"birth_year": "1842", "death_year": "1905"},
            },
        ],
    },
    {
        "pensioner_id": 202,
        "pensioner_name": "No-Match Pensioner",
        "fag_status": "ambiguous",
        "fag_records": [
            {
                "memorial_id": "mem-202-a",
                "slug": "nomatch-candidate-a",
                "name": "No-Match Candidate A",
                "backlink": "https://www.findagrave.com/memorial/mem-202-a/nomatch-candidate-a",
                "score": 0.44,
                "score_breakdown": {"last": 1},
                "details": {},
            },
        ],
        "cgr_records": [{"cgr_id": "cgr-202"}],
    },
]


@pytest.fixture(scope="module")
def exports_page():
    """Load fixture plus pick and no-match decisions, then expose helpers."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(VIEW_V2.as_uri())
        page.evaluate(
            "records => window.ViewV2.loadRecords(records, 'test-export-results.jsonl')",
            RECORDS,
        )
        page.locator(".record-card").first.wait_for()
        # Pick candidate A in record 201
        card = page.locator('.record-card[data-record-id="201"]')
        card.locator('[data-action="pick"]').first.click()
        # No-match record 202
        page.locator('.record-card[data-record-id="202"] [data-action="none-match"]').click()
        yield page
        browser.close()


def test_candidate_to_scraper_record_populates_memorial_id_name_url(exports_page):
    """FaG candidate fields map into memorials_archive shape once."""
    record = exports_page.evaluate(
        "window.ViewV2.candidateToScraperRecord("
        + "window.ViewV2.getRecords()[0].candidates[0], "
        + "window.ViewV2.getRecords()[0])"
    )
    assert record["memorial_id"] == "mem-201-a"
    assert record["name"] == "Pickable Candidate A"
    assert record["url"] == "https://www.findagrave.com/memorial/mem-201-a/pickable-candidate-a"


def test_candidate_to_scraper_record_attaches_reviewer_extensions(exports_page):
    """Reviewer extensions prefixed with _ land alongside scraper fields."""
    record = exports_page.evaluate(
        "window.ViewV2.candidateToScraperRecord("
        + "window.ViewV2.getRecords()[0].candidates[0], "
        + "window.ViewV2.getRecords()[0])"
    )
    assert record["_source_pensioner_id"] == 201
    assert record["_source_pensioner_name"] == "Pickable Pensioner"
    assert record["_reviewer_decided_at"] is not None


def test_pensioners_to_scraper_export_excludes_undecided_records(exports_page):
    """Only picked and none_match decisions reach scraper export."""
    export = exports_page.evaluate(
        "window.ViewV2.pensionersToScraperExport("
        + "window.ViewV2.getRecords(), window.ViewV2.getDecisions())"
    )
    assert len(export) == 2
    ids = {item["_source_pensioner_id"] for item in export}
    assert ids == {201, 202}


def test_save_decisions_button_downloads_v1_export_shape(exports_page):
    """Save decisions Blob matches today's decisions.json schema."""
    blob_json = exports_page.evaluate("async () => {"
        "  const blob = await window.ViewV2.buildDecisionsBlob();"
        "  return await blob.text();"
        "}")
    payload = json.loads(blob_json)
    assert payload["version"] == 1
    assert "exported_at" in payload
    assert "decisions" in payload
    assert "201" in payload["decisions"]
    assert "202" in payload["decisions"]
    assert payload["decisions"]["201"]["decision"]["memorial_id"] == "mem-201-a"
    assert payload["decisions"]["202"]["decision"]["memorial_id"] is None


def test_export_picks_button_downloads_scraper_shape(exports_page):
    """Scraper export is flat list with expected metadata."""
    blob_json = exports_page.evaluate("async () => {"
        "  const blob = await window.ViewV2.buildScraperExportBlob();"
        "  return await blob.text();"
        "}")
    export = json.loads(blob_json)
    assert isinstance(export, list)
    assert len(export) == 2
    assert export[0]["memorial_id"] == "mem-201-a"
    assert export[0]["_source_pensioner_id"] == 201
    assert export[1]["memorial_id"] == ""
    assert export[1]["_reviewer_decision"] == "no_match"
