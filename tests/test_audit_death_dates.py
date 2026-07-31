"""Tests for the death-date audit logic.

The audit cross-references the enriched pensioner sidecar with
the OCR results to flag suspicious extractions. Issue #139
follow-up (2026-07-31): `near_death_keyword` is stored INSIDE
`death_date` (matching `process_image`'s schema) but the audit
was reading it at the TOP level of the OCR record. These tests
pin the corrected read.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).parent
_ROOT = _TESTS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.audit import audit_death_dates as audit  



def test_no_keyword_check_reads_from_death_date_subfield(tmp_path):
    """The audit must read `near_death_keyword` from the
    `death_date` sub-dict of OCR records (where the re-enrich
    driver writes it), NOT from the top level (where it was
    never written).

    Before the fix, the audit always saw `near_death_keyword`
    as None/False and false-positived on every record where
    the death keyword was only in easy_text."""
    
    enriched = [{
        "id": 109,
        "pensioncard_id": 7525,
        "name_raw": "Brown, Young K.",
        "death_year": "1928",
        "death_date_iso": "1928-03-13",
        "spouse_name_raw": "",
        "first_name": "Young",
        "last_name": "Brown",
        "mentions_soldier_name": False,
    }]
    
    ocr = [{
        "image": "7525__7523.jpg",
        "pensioncard_id": 7525,
        "death_date": {
            "kind": "date",
            "year": 1928,
            "month": 3,
            "day": 13,
            "iso": "1928-03-13",
            "near_death_keyword": True,
            "mentions_soldier_name": True,
        },
        "source_pass": "easyocr",
        "red_text": "",
        "full_text": "",
        "easy_text": "DECEASED 3-13-1928",
        "red_text_len": 0,
        "full_text_len": 0,
    }]
    
    enriched_path = tmp_path / "enriched.json"
    ocr_path = tmp_path / "ocr.json"
    enrichment_path = tmp_path / "enrichment.json"
    enriched_path.write_text(json.dumps(enriched), encoding="utf-8")
    ocr_path.write_text(json.dumps(ocr), encoding="utf-8")
    enrichment_path.write_text(json.dumps(enriched), encoding="utf-8")
    
    audit.main([
        "--enriched", str(enriched_path),
        "--enrichment", str(enrichment_path),
        "--ocr", str(ocr_path),
        "--out-json", str(tmp_path / "out.json"),
        "--out-md", str(tmp_path / "out.md"),
    ])
    
    findings = json.loads(
        (tmp_path / "out.json").read_text(encoding="utf-8")
    )["findings"]
    
    no_kw_findings = [
        f for f in findings
        if f["tag"] == "NO_KEYWORD_BUT_DATE"
        and f["pensioner_id"] == 109
    ]
    assert not no_kw_findings, (
        f"audit false-positived NO_KEYWORD_BUT_DATE for Brown "
        f"despite DECEASED in easy_text and near_death_keyword=True "
        f"in death_date. Findings: {no_kw_findings}"
    )


def test_audit_also_reads_legacy_top_level_near_death_keyword(tmp_path):
    """Backward compat: older OCR records (pre-L3 re-enrich)
    may have near_death_keyword at the top level. The audit
    should still accept those."""
    enriched = [{
        "id": 200,
        "pensioncard_id": 9999,
        "name_raw": "Legacy, Test",
        "death_year": "1920",
        "death_date_iso": "1920",
        "spouse_name_raw": "",
        "first_name": "Test",
        "last_name": "Legacy",
    }]
    ocr = [{
        "image": "9999__1.jpg",
        "pensioncard_id": 9999,
        "near_death_keyword": True,  
        "source_pass": "red",
        "death_date": {"year": 1920},
        "red_text": "DECEASED 1920",
        "full_text": "",
        "easy_text": "",
        "red_text_len": 10,
        "full_text_len": 0,
    }]
    enriched_path = tmp_path / "enriched.json"
    ocr_path = tmp_path / "ocr.json"
    enrichment_path = tmp_path / "enrichment.json"
    enriched_path.write_text(json.dumps(enriched), encoding="utf-8")
    ocr_path.write_text(json.dumps(ocr), encoding="utf-8")
    enrichment_path.write_text(json.dumps(enriched), encoding="utf-8")
    audit.main([
        "--enriched", str(enriched_path),
        "--enrichment", str(enrichment_path),
        "--ocr", str(ocr_path),
        "--out-json", str(tmp_path / "out.json"),
        "--out-md", str(tmp_path / "out.md"),
    ])
    findings = json.loads(
        (tmp_path / "out.json").read_text(encoding="utf-8")
    )["findings"]
    no_kw_findings = [
        f for f in findings
        if f["tag"] == "NO_KEYWORD_BUT_DATE"
        and f["pensioner_id"] == 200
    ]
    assert not no_kw_findings