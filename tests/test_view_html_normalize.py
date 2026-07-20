"""Behavior tests for view.html v2's FaG-to-common normalization seam."""
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent.parent
VIEW_V2 = ROOT / "scripts" / "view" / "v2.html"


@pytest.fixture(scope="module")
def normalization_page():
    """Open v2 review UI and expose its public normalization helpers."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(VIEW_V2.as_uri())
        page.wait_for_function("window.ViewV2 !== undefined")
        yield page
        browser.close()


def test_fag_evidence_maps_to_common_feature_names(normalization_page):
    """FaG feature keys map once at boundary; renderer gets common keys."""
    mapped = normalization_page.evaluate(
        "breakdown => window.ViewV2.fagEvidenceToCommon(breakdown)",
        {
            "last": 1.0,
            "first": 0.8,
            "middle": 0.5,
            "death": 0.4,
            "state": 0.1,
            "ok_burial": 0.3,
            "veteran": 0.8,
        },
    )

    assert mapped == {
        "last_name": 1.0,
        "first_name": 0.8,
        "middle_name": 0.5,
        "year_window": 0.4,
        "state": 0.1,
        "ok_burial": 0.3,
        "veteran": 0.8,
    }


def test_empty_fag_evidence_stays_empty(normalization_page):
    """Missing score evidence stays absent instead of fabricating bars."""
    assert normalization_page.evaluate(
        "window.ViewV2.fagEvidenceToCommon(null)"
    ) == {}


def test_fag_record_normalizes_to_engine_agnostic_shape(normalization_page):
    """Existing state.jsonl fields become common record and candidate fields."""
    record = {
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
        "pensioncard_pages": ["500", "501"],
        "fag_status": "auto_accept",
        "best_score": 0.644,
        "fag_records": [
            {
                "memorial_id": "26716384",
                "slug": "hugh-h-akers",
                "name": "Rev Hugh H Akers",
                "backlink": "https://www.findagrave.com/memorial/26716384/hugh-h-akers",
                "iiif_url": "https://www.findagrave.com/iiif/2/memorial:26716384",
                "score": 0.644,
                "score_breakdown": {"last": 1, "first": 1, "death": 0.5},
                "details": {
                    "birth_year": "1846",
                    "death_year": "1924",
                    "state": "Oklahoma",
                    "is_veteran": True,
                },
                "_found_by": {"strategy": "B1-exact"},
            }
        ],
        "cgr_records": [{"cgr_id": "cgr-5"}],
        "dd_match": {"dd_memorial_id": "26716384"},
        "spouse_match": {"match_strength": "strong"},
        "both_match": {"method": "corroboration"},
    }

    normalized = normalization_page.evaluate(
        "record => window.ViewV2.normalizeRecord(record)", record
    )

    assert normalized == {
        "id": 5,
        "title": "Hugh H. Akers",
        "engine": "findagrave",
        "attributes": {
            "first": "Hugh",
            "middle": "H.",
            "last": "Akers",
            "application_number": "A-5",
            "birth_year": "1846",
            "death_year": "1924",
            "regiment": "Co. A, 1st AR Infantry",
            "company": "A",
            "pensioncard_url": "https://digitalprairie.example/card/5",
            "source_url": "https://digitalprairie.example/application/5",
            "pensioncard_pages": ["500", "501"],
            "spouse": {"first": "", "middle": "", "last": ""},
            "both_match": {"method": "corroboration"},
        },
        "status": "auto_accept",
        "best_score": 0.644,
        "candidates": [
            {
                "id": "26716384",
                "title": "Rev Hugh H Akers",
                "url": "https://www.findagrave.com/memorial/26716384/hugh-h-akers",
                "score": 0.644,
                "attributes": {
                    "birth_year": "1846",
                    "death_year": "1924",
                    "state": "Oklahoma",
                },
                "media": {
                    "image_url": "https://www.findagrave.com/iiif/2/memorial:26716384",
                },
                "evidence": {
                    "score_breakdown": {
                        "last_name": 1,
                        "first_name": 1,
                        "middle_name": 0,
                        "year_window": 0.5,
                        "state": 0,
                        "ok_burial": 0,
                        "veteran": 0,
                    },
                    "raw": record["fag_records"][0],
                },
            }
        ],
        "corroboration": {
            "cgr": [{"cgr_id": "cgr-5"}],
            "dd_match": {"dd_memorial_id": "26716384"},
            "spouse_match": {"match_strength": "strong"},
        },
    }


def test_normalize_record_defaults_missing_engine_and_collections(normalization_page):
    """Sparse current records still produce complete common collections."""
    normalized = normalization_page.evaluate(
        "record => window.ViewV2.normalizeRecord(record)",
        {"pensioner_id": "8", "pensioner_name": "Sparse Pensioner"},
    )

    assert normalized["engine"] == "findagrave"
    assert normalized["status"] == "unknown"
    assert normalized["best_score"] == 0
    assert normalized["candidates"] == []
    assert normalized["corroboration"] == {
        "cgr": [],
        "dd_match": None,
        "spouse_match": None,
    }


def test_normalize_v2_reads_common_key_when_present(normalization_page):
    """When record has common key, normalizeRecordV2 uses it directly."""
    record = {
        "pensioner_id": 42,
        "pensioner_name": "Test Pensioner",
        "pensioner_first": "Test",
        "pensioner_last": "Pensioner",
        "fag_status": "auto_accept",
        "common": {
            "id": 42,
            "title": "Test Pensioner (from common)",
            "engine": "newspapers_com",
            "status": "needs_review",
            "best_score": 0.75,
            "candidates": [
                {
                    "id": "999",
                    "title": "News Article",
                    "url": "https://example.com/999",
                    "score": 0.75,
                    "attributes": {"date": "1896-01-01"},
                    "evidence": {"score_breakdown": {}, "raw": {}},
                }
            ],
            "corroboration": {
                "cgr": [{"cgr_id": "cgr-1"}],
                "dd_match": None,
                "spouse_match": None,
            },
        },
    }
    result = normalization_page.evaluate(
        "record => window.ViewV2.normalizeRecordV2(record)", record
    )
    # Common fields win when present
    assert result["title"] == "Test Pensioner (from common)"
    assert result["engine"] == "newspapers_com"
    assert result["status"] == "needs_review"
    assert result["best_score"] == 0.75
    assert result["candidates"][0]["id"] == "999"
    assert result["candidates"][0]["title"] == "News Article"
    # Legacy attributes still merged
    assert result["attributes"]["first"] == "Test"
    assert result["attributes"]["last"] == "Pensioner"
    # Corroboration from common
    assert result["corroboration"]["cgr"] == [{"cgr_id": "cgr-1"}]


def test_normalize_v2_falls_back_when_no_common_key(normalization_page):
    """Without common key, normalizeRecordV2 delegates to normalizeRecord."""
    result = normalization_page.evaluate(
        "record => window.ViewV2.normalizeRecordV2(record)",
        {
            "pensioner_id": "8",
            "pensioner_name": "Legacy Pensioner",
            "fag_records": [],
        },
    )
    assert result["title"] == "Legacy Pensioner"
    assert result["engine"] == "findagrave"
    assert result["candidates"] == []
