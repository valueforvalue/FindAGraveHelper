"""Playwright tests for view.html v2 Commit 3 sidecar persistence."""
import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent.parent
VIEW_V2 = ROOT / "scripts" / "view" / "v2.html"


@pytest.fixture(scope="module")
def sidecar_page():
    """Loaded v2 with record for persistence reload tests."""
    records = [
        {
            "pensioner_id": 301,
            "pensioner_name": "Sidecar Test Pensioner",
            "fag_status": "ambiguous",
            "fag_records": [
                {
                    "memorial_id": "sidecar-301",
                    "slug": "sidecar-slug",
                    "name": "Sidecar Candidate",
                    "backlink": "https://www.findagrave.com/memorial/sidecar-301/sidecar-slug",
                    "score": 0.85,
                    "score_breakdown": {"last": 1, "first": 1, "death": 0.5},
                    "details": {"birth_year": "1845", "death_year": "1910"},
                    "_found_by": {"strategy": "B1-exact"},
                },
            ],
        },
    ]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(VIEW_V2.as_uri())
        page.evaluate(
            "records => window.ViewV2.loadRecords(records, 'test-sidecar-results.jsonl')",
            records,
        )
        page.locator(".record-card").first.wait_for()
        yield page
        browser.close()


def test_auto_loads_decisions_from_sidecar_json(sidecar_page, tmp_path):
    """Decisions placed alongside results.jsonl restore picks on open."""
    sidecar = tmp_path / "decisions_test-sidecar-results.jsonl.json"
    sidecar.write_text(json.dumps({
        "version": 1,
        "exported_at": "2026-07-20T01:00:00Z",
        "source_file": "results.jsonl",
        "stats": {"total_pensioners": 1, "decided": 1, "by_status": {}, "by_cgr_dedup": {}},
        "decisions": {
            "301": {
                "decision": {
                    "memorial_id": "sidecar-301",
                    "slug": "sidecar-slug",
                    "by": "user",
                    "at": "2026-07-20T01:00:00Z",
                    "notes": "looks correct",
                    "removed_candidates": [],
                    "candidate_notes": {},
                },
            },
        },
    }), encoding="utf-8")

    sidecar_page.evaluate(
        "decisionsText => window.ViewV2.applyDecisionsSidecar(decisionsText, 'decisions.json')",
        sidecar.read_text(encoding="utf-8"),
    )

    assert sidecar_page.locator(".record-card .picked-badge").count() == 1
    assert sidecar_page.locator(".record-card .decision-pill.picked").count() == 1


def test_import_button_loads_export_json(sidecar_page, tmp_path):
    """Import path accepts decisions.json shape."""
    export_file = tmp_path / "decisions.json"
    export_file.write_text(json.dumps({
        "version": 1,
        "exported_at": "2026-07-20T01:00:00Z",
        "source_file": "results.jsonl",
        "stats": {"total_pensioners": 1, "decided": 0, "by_status": {}, "by_cgr_dedup": {}},
        "decisions": {
            "301": {
                "decision": {
                    "memorial_id": "sidecar-301",
                    "slug": "sidecar-slug",
                    "by": "user",
                    "at": "2026-07-20T01:00:00Z",
                    "notes": "",
                    "removed_candidates": [],
                    "candidate_notes": {},
                },
            },
        },
    }), encoding="utf-8")

    sidecar_page.locator("#importFile").set_input_files(export_file)

    assert sidecar_page.locator(".record-card .picked-badge").count() == 1
    assert sidecar_page.locator(".record-card .decision-pill.picked").count() == 1


def test_load_status_banner_shows_loaded_count(sidecar_page, tmp_path):
    """After sidecar loads, status banner reflects decision count."""
    sidecar = tmp_path / "decisions.json"
    sidecar.write_text(json.dumps({
        "version": 1,
        "exported_at": "2026-07-20T01:00:00Z",
        "source_file": "results.jsonl",
        "stats": {"total_pensioners": 1, "decided": 1, "by_status": {}, "by_cgr_dedup": {}},
        "decisions": {
            "301": {
                "decision": {
                    "memorial_id": "sidecar-301",
                    "slug": "sidecar-slug",
                    "by": "user",
                    "at": "2026-07-20T01:00:00Z",
                    "notes": "",
                    "removed_candidates": [],
                    "candidate_notes": {},
                },
            },
        },
    }), encoding="utf-8")

    sidecar_page.evaluate(
        "text => window.ViewV2.applyDecisionsSidecar(text, 'decisions.json')",
        sidecar.read_text(encoding="utf-8"),
    )
    text = sidecar_page.locator("#loadStatus").inner_text()
    assert "Loaded 1 decision" in text
