"""Tests for backlink field carrying through the state.jsonl pipeline.

The pensions-application digitalprairie URL is stored in ok_pensioners.json
as `backlink` (distinct from `pensioncard_backlink` which is the
pension card URL). State.jsonl must carry both so view.html and
report.md can render both source links per pensioner.

Backwards compatibility: existing state.jsonl files without the
`backlink` field must still load cleanly (default to "").
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.state_normalize import normalize_state_record, is_unified


# ============================================================
# Fixtures
# ============================================================
def _make_unified_record(**overrides) -> dict:
    """A canonical unified record with pensioncard_backlink + backlink."""
    base = {
        "pensioner_id": 42,
        "pensioner_name": "Adair, R. W.",
        "pensioner_first": "R.",
        "pensioner_middle": "W.",
        "pensioner_last": "Adair",
        "pensioner_app_number": "A4",
        "regiment": "2nd Mississippi",
        "company": "A & C",
        "pensioncard_backlink": "https://digitalprairie.ok.gov/digital/singleitem/collection/pensioncard/id/98",
        "backlink": "https://digitalprairie.ok.gov/digital/singleitem/collection/pensions/id/3",
        "fag_records": [],
        "fag_status": "no_results",
        "cgr_records": [],
        "cgr_status": "",
        "both_match": None,
    }
    base.update(overrides)
    return base


# ============================================================
# state_normalize.to_unified carries backlink
# ============================================================
def test_normalize_carries_backlink():
    """normalize_state_record preserves backlink from input record."""
    rec = _make_unified_record()
    out = normalize_state_record(rec)
    assert out["backlink"] == "https://digitalprairie.ok.gov/digital/singleitem/collection/pensions/id/3"


def test_normalize_carries_pensioncard_backlink():
    """Regression: pensioncard_backlink still carried."""
    rec = _make_unified_record()
    out = normalize_state_record(rec)
    assert out["pensioncard_backlink"] == "https://digitalprairie.ok.gov/digital/singleitem/collection/pensioncard/id/98"


def test_normalize_missing_backlink_defaults_to_empty():
    """Backwards compat: legacy records without backlink → ''."""
    rec = _make_unified_record()
    del rec["backlink"]
    out = normalize_state_record(rec)
    assert out["backlink"] == ""


def test_normalize_legacy_format_passes_backlink_through():
    """Legacy FaG-only records can also carry backlink (rare but allowed)."""
    legacy = {
        "pensioner_id": 7,
        "name": "Test",
        "backlink": "https://digitalprairie.ok.gov/digital/singleitem/collection/pensions/id/77",
        "ranked_candidates": [],
    }
    out = normalize_state_record(legacy)
    assert out.get("backlink") == "https://digitalprairie.ok.gov/digital/singleitem/collection/pensions/id/77"


# ============================================================
# is_unified still detects unified records (regression)
# ============================================================
def test_is_unified_still_true_for_unified_record():
    """Adding backlink to schema must not break unified detection."""
    rec = _make_unified_record()
    assert is_unified(rec) is True


# ============================================================
# Round-trip: write + read
# ============================================================
def test_roundtrip_preserves_both_links(tmp_path):
    """Write unified record to state.jsonl, read back, both links survive."""
    from scripts.run_unified import write_unified_line

    state_path = tmp_path / "state.jsonl"
    rec = _make_unified_record()
    write_unified_line(state_path, rec)

    lines = state_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["pensioncard_backlink"].endswith("/pensioncard/id/98")
    assert parsed["backlink"].endswith("/pensions/id/3")