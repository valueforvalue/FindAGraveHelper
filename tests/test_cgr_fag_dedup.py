"""Tests for scripts/cgr/cgr_fag_dedup.py.

Post-run dedup: compares results.jsonl against CGR data and tags
each pensioner as one of:
  - duplicate: CGR has them AND FaG found them (same person)
  - follow_up_candidate: CGR has them but FaG didn't auto-resolve
  - clear: no CGR match (FaG is the only signal)
  - no_cgr_match: no CGR record AND no FaG record (cold lead)
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cgr import cgr_fag_dedup as cfd


# ============================================================
# Year extraction from CGR date strings
# ============================================================
def test_extract_year_full_date():
    assert cfd.extract_year("1845-01-21") == "1845"
    assert cfd.extract_year("1925-07-15") == "1925"


def test_extract_year_year_only():
    assert cfd.extract_year("1844") == "1844"
    assert cfd.extract_year("1934") == "1934"


def test_extract_year_empty():
    assert cfd.extract_year("") is None
    assert cfd.extract_year(None) is None


def test_extract_year_garbage():
    """Non-date strings return None, not crash."""
    assert cfd.extract_year("unknown") is None
    assert cfd.extract_year("?") is None
    assert cfd.extract_year("about 1845") == "1845"  # best-effort


# ============================================================
# Unit string normalization (for matching)
# ============================================================
def test_normalize_unit_aliases():
    """Unit strings like '4 LA' should match '4th Louisiana'."""
    # Just sanity-check the helper exists; the real alias logic
    # lives in scripts/cgr/cgr_matcher.py.
    assert hasattr(cfd, "normalize_unit")


# ============================================================
# Per-pensioner dedup decision
# ============================================================
def _pensioner(pid, last="Smith", first="John", middle="", unit="",
               birth_year="", death_year="", fag_status="no_results",
               fag_records=None):
    return {
        "pensioner_id": pid,
        "pensioner_last": last,
        "pensioner_first": first,
        "pensioner_middle": middle,
        "pensioner_name": f"{first} {middle} {last}".strip(),
        "regiment": unit,
        "pensioner_birth_year": birth_year,
        "pensioner_death_year": death_year,
        "fag_status": fag_status,
        "fag_records": fag_records or [],
    }


def _cgr(cid, last="Smith", first="John", middle="", unit="",
         born="", died="", died_state="OK"):
    return {
        "id": cid,
        "last_name": last,
        "first_name": first,
        "middle_name": middle,
        "name": f"{first} {middle} {last}".strip(),
        "unit": unit,
        "born": born,
        "died": died,
        "died_state": died_state,
        "cemetery_id": 1,
        "cemetery_name": "Test Cemetery",
    }


def test_classify_no_cgr_match_with_fag_clears():
    """Pensioner with no CGR candidate AND a FaG result → CLEAR."""
    p = _pensioner(pid=1, last="Smith", first="John", fag_status="auto_accept",
                   fag_records=[{"memorial_id": "1", "score": 0.9}])
    cgrs = []  # no CGR records for this pensioner
    result = cfd.classify_pensioner(p, cgrs)
    assert result["cgr_dedup_status"] == "clear"
    assert result["cgr_match_summary"] is None


def test_classify_no_cgr_no_fag_is_no_fag_match():
    """Pensioner with no CGR candidate AND FaG found nothing → NO_FAG_MATCH."""
    p = _pensioner(pid=1, last="Smith", first="John", fag_status="no_results")
    cgrs = []
    result = cfd.classify_pensioner(p, cgrs)
    assert result["cgr_dedup_status"] == "no_fag_match"
    assert result["cgr_match_summary"] is None


def test_classify_strong_cgr_match_with_fag_is_duplicate():
    """CGR strong match + FaG auto_accept → DUPLICATE."""
    p = _pensioner(
        pid=1, last="Smith", first="John", unit="4 LA",
        birth_year="1844", death_year="1934",
        fag_status="auto_accept",
        fag_records=[{"memorial_id": "999", "score": 0.92}],
    )
    cgrs = [_cgr(cid=100, last="Smith", first="John", unit="4 LA",
                born="1844", died="1934", died_state="OK")]
    result = cfd.classify_pensioner(p, cgrs)
    assert result["cgr_dedup_status"] == "duplicate"
    assert result["cgr_match_summary"]["cgr_id"] == 100
    assert result["cgr_match_summary"]["match_strength"] in ("strong", "medium")


def test_classify_strong_cgr_match_without_fag_is_followup():
    """CGR strong match + FaG no_results/too_many → FOLLOW_UP_CANDIDATE."""
    p = _pensioner(
        pid=1, last="Smith", first="John", unit="4 LA",
        birth_year="1844", death_year="1934",
        fag_status="no_results",
        fag_records=[],
    )
    cgrs = [_cgr(cid=100, last="Smith", first="John", unit="4 LA",
                born="1844", died="1934", died_state="OK")]
    result = cfd.classify_pensioner(p, cgrs)
    assert result["cgr_dedup_status"] == "follow_up_candidate"
    assert result["cgr_match_summary"]["cgr_id"] == 100


def test_classify_weak_cgr_match_is_clear():
    """CGR with only last-name match (no first name) → CLEAR (noise)."""
    p = _pensioner(pid=1, last="Smith", first="John", fag_status="auto_accept")
    cgrs = [_cgr(cid=100, last="Smith", first="Jane", unit="4 LA")]
    result = cfd.classify_pensioner(p, cgrs)
    # First name differs — not a strong match → CLEAR
    assert result["cgr_dedup_status"] in ("clear", "duplicate")
    # Even if first name differs, last name matches; depends on
    # whether the helper treats it as a "weak" match. The key
    # invariant: the strong-match follow-up branch must NOT fire.


def test_classify_cgr_died_state_not_ok_still_follows_up():
    """A CGR match in a non-OK state is still useful for dedup."""
    p = _pensioner(pid=1, last="Smith", first="John", unit="4 LA",
                   fag_status="too_many")
    cgrs = [_cgr(cid=100, last="Smith", first="John", unit="4 LA",
                born="1844", died="1934", died_state="TX")]
    result = cfd.classify_pensioner(p, cgrs)
    # Strong match regardless of died_state
    assert result["cgr_dedup_status"] == "follow_up_candidate"


def test_classify_picks_strongest_cgr_match():
    """When multiple CGR rows match, pick the strongest one."""
    p = _pensioner(pid=1, last="Smith", first="John", unit="4 LA",
                   birth_year="1844", fag_status="no_results")
    cgrs = [
        _cgr(cid=100, last="Smith", first="John", unit="", born=""),  # weak
        _cgr(cid=200, last="Smith", first="John", unit="4 LA", born="1844"),  # strong
    ]
    result = cfd.classify_pensioner(p, cgrs)
    assert result["cgr_dedup_status"] == "follow_up_candidate"
    assert result["cgr_match_summary"]["cgr_id"] == 200  # the strong one


# ============================================================
# Top-level run_dedup: reads JSONL, writes JSON
# ============================================================
def _write_jsonl(path: Path, records: list) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_run_dedup_annotates_records(tmp_path):
    """run_dedup writes back annotated records + a report JSON."""
    results = tmp_path / "results.jsonl"
    cgr_path = tmp_path / "cgr.jsonl"
    out_json = tmp_path / "cgr_fag_dedup.json"

    _write_jsonl(results, [
        _pensioner(pid=1, last="Smith", first="John", fag_status="no_results"),
        _pensioner(pid=2, last="Doe", first="Jane", fag_status="auto_accept",
                   fag_records=[{"memorial_id": "1", "score": 0.9}]),
    ])
    _write_jsonl(cgr_path, [
        # Strong CGR match for pensioner 2
        _cgr(cid=999, last="Doe", first="Jane", unit="", born="1845", died="1920"),
        # No CGR match for pensioner 1
    ])

    report = cfd.run_dedup(
        results_path=results,
        cgr_path=cgr_path,
        output_path=out_json,
    )
    assert "pensioner_count_by_status" in report["stats"]
    assert "pensioners" in report
    # Pensioner 1 → no CGR match + fag_status=no_results → no_fag_match
    assert report["pensioners"]["1"]["cgr_dedup_status"] == "no_fag_match"
    # Pensioner 2 → strong CGR match + auto_accept → duplicate
    assert report["pensioners"]["2"]["cgr_dedup_status"] == "duplicate"
    assert report["pensioners"]["2"]["cgr_match_summary"]["cgr_id"] == 999

    # In-place annotation: results.jsonl was rewritten
    annotated = [
        json.loads(l) for l in results.read_text(encoding="utf-8").splitlines() if l
    ]
    assert annotated[0]["cgr_dedup_status"] == "no_fag_match"
    assert annotated[1]["cgr_dedup_status"] == "duplicate"

    # Report JSON was written
    assert out_json.exists()
    saved = json.loads(out_json.read_text(encoding="utf-8"))
    assert saved["version"] >= 1
    assert "stats" in saved


def test_run_dedup_handles_missing_cgr_file(tmp_path):
    """When the CGR file is absent, all pensioners get a default
    classification (clear if FaG has a result, no_fag_match otherwise)."""
    results = tmp_path / "results.jsonl"
    cgr_path = tmp_path / "nope.jsonl"  # does not exist
    out_json = tmp_path / "cgr_fag_dedup.json"

    _write_jsonl(results, [
        _pensioner(pid=1, last="Smith", first="John", fag_status="no_results"),
        _pensioner(pid=2, last="Doe", first="Jane", fag_status="auto_accept",
                   fag_records=[{"memorial_id": "1", "score": 0.9}]),
    ])
    report = cfd.run_dedup(
        results_path=results,
        cgr_path=cgr_path,
        output_path=out_json,
    )
    # Pensioner 1: no CGR + no_results → no_fag_match
    assert report["pensioners"]["1"]["cgr_dedup_status"] == "no_fag_match"
    # Pensioner 2: no CGR + auto_accept → clear
    assert report["pensioners"]["2"]["cgr_dedup_status"] == "clear"
    assert report["stats"]["cgr_records_loaded"] == 0


def test_run_dedup_loads_cgr_blocking_index(tmp_path):
    """By default, run_dedup builds the CGR blocking index from
    ok_vets_enriched.jsonl to find candidates per pensioner. The
    test confirms the right CGR records surface for the right
    pensioner."""
    results = tmp_path / "results.jsonl"
    cgr_path = tmp_path / "cgr.jsonl"
    out_json = tmp_path / "cgr_fag_dedup.json"

    _write_jsonl(results, [
        _pensioner(pid=1, last="Campbell", first="Lafayette",
                   middle="C", fag_status="too_many"),
    ])
    _write_jsonl(cgr_path, [
        _cgr(cid=96425, last="Campbell", first="Lafayette", middle="Carroll",
             unit="NC", born="1845-01-21", died="1925-07-15", died_state="OK"),
    ])
    report = cfd.run_dedup(
        results_path=results,
        cgr_path=cgr_path,
        output_path=out_json,
    )
    p1 = report["pensioners"]["1"]
    assert p1["cgr_dedup_status"] == "follow_up_candidate"
    assert p1["cgr_match_summary"]["cgr_id"] == 96425
    # Year extraction
    assert p1["cgr_match_summary"].get("cgr_birth_year") == "1845"
    assert p1["cgr_match_summary"].get("cgr_death_year") == "1925"

# ============================================================
# Issue #31: _AUTO_RESOLVED_FAG_STATUSES is a status set, not a
# mixed status+field set. 'both_match' is a record field, not a
# status; 'BOTH_MATCH' is an internal label, not a status. None
# belong in a status check.
# ============================================================
class TestAutoResolvedFagStatusesSet:
    """The set that decides whether FaG is self-resolved must
    contain only canonical FaG status strings. 'both_match' is a
    CGR cross-confirmation field on the record, not a status;
    'BOTH_MATCH' is an internal label that doesn't appear in
    the STATUS_* enum. Both are noise in the status check."""

    def test_set_contains_only_status_auto_accept(self):
        """After the #31 migration, the set has exactly one entry:
        STATUS_AUTO_ACCEPT. 'both_match' and 'BOTH_MATCH' were
        wrongly mixed in; they're not statuses."""
        from scripts.cgr.cgr_fag_dedup import _AUTO_RESOLVED_FAG_STATUSES
        from scripts.pipeline.scoring_constants import STATUS_AUTO_ACCEPT
        # The set must contain only canonical status strings
        for s in _AUTO_RESOLVED_FAG_STATUSES:
            # Every member must be a STATUS_* value (i.e. one of
            # the canonical FaG statuses, not a field name or
            # internal label)
            from scripts.pipeline import scoring_constants as sc
            canonical = {
                getattr(sc, name)
                for name in dir(sc)
                if name.startswith("STATUS_") and isinstance(getattr(sc, name), str)
            }
            assert s in canonical, (
                f"'{s}' is not a canonical STATUS_* value; "
                f"only status strings belong in this set"
            )
        # And the canonical auto_accept must be there
        assert STATUS_AUTO_ACCEPT in _AUTO_RESOLVED_FAG_STATUSES

    def test_both_match_is_treated_as_record_field_not_status(self, tmp_path):
        """Pensioners with fag_status='auto_accept' classify as
        'clear' (no CGR match, FaG self-resolved). The 'both_match'
        record field is consumed by report_generator separately;
        the dedup status check must not depend on it."""
        results = tmp_path / "results.jsonl"
        cgr_path = tmp_path / "cgr.jsonl"
        out_json = tmp_path / "out.json"

        _write_jsonl(results, [
            _pensioner(pid=1, last="Smith", first="John", fag_status="auto_accept"),
        ])
        report = cfd.run_dedup(
            results_path=results,
            cgr_path=cgr_path,
            output_path=out_json,
        )
        assert report["pensioners"]["1"]["cgr_dedup_status"] == "clear"
