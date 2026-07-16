"""Tests for scripts/state/schema.py (T018).

Typed dataclasses for the state.jsonl wire format. The cross-layer
contract (docs/agents/cross-layer-contract.md) defines what fields
each record carries; this module makes those fields typed so we
catch drift at parse time instead of at view.html render time.

Three record shapes:
  - PensionerRecord (one row in state.jsonl)
  - CandidateRecord (one FaG result inside fag_records)
  - BothMatchRecord (the corroboration verdict)

Schema version: 1 (T018 introduces the dataclasses; schema_version
in the meta file will bump if breaking changes ship).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.state.schema import (
    PensionerRecord,
    CandidateRecord,
    BothMatchRecord,
    from_dict_pensioner,
    from_dict_candidate,
    from_dict_both_match,
)


# ============================================================
# CandidateRecord
# ============================================================
def test_candidate_from_dict_minimal():
    """Only memorial_id is required."""
    c = from_dict_candidate({"memorial_id": "12345"})
    assert c.memorial_id == "12345"
    assert c.slug == ""
    assert c.name == ""
    assert c.score == 0.0
    assert c.backlink == ""


def test_candidate_from_dict_full():
    c = from_dict_candidate({
        "memorial_id": "50923719",
        "slug": "william_pickney-looney",
        "name": "William Pickney Looney",
        "score": 0.92,
        "backlink": "https://www.findagrave.com/memorial/50923719",
    })
    assert c.memorial_id == "50923719"
    assert c.slug == "william_pickney-looney"
    assert c.score == 0.92


def test_candidate_roundtrip():
    """to_dict then from_dict round-trips losslessly."""
    src = {
        "memorial_id": "12345",
        "slug": "john-doe",
        "name": "John Doe",
        "score": 0.85,
        "backlink": "https://example.com/12345",
        "iiif_url": "https://example.com/iiif/12345",
    }
    c = from_dict_candidate(src)
    out = c.to_dict()
    # All keys from src must be preserved
    for k, v in src.items():
        assert out[k] == v


def test_candidate_unknown_fields_passed_through():
    """Unknown fields in the source dict stay in to_dict output.

    The dataclass is the typed front; the wire format may carry
    extra fields (e.g. details, _found_by) that some readers need.
    Stripping them silently would break downstream consumers.
    """
    src = {"memorial_id": "1", "details": {"birth_year": "1844"}, "_found_by": {"strategy": "B1"}}
    c = from_dict_candidate(src)
    assert c.to_dict()["details"] == {"birth_year": "1844"}
    assert c.to_dict()["_found_by"] == {"strategy": "B1"}


def test_candidate_missing_memorial_id_defaults_empty():
    """Defensive: legacy records without memorial_id don't crash."""
    c = from_dict_candidate({})
    assert c.memorial_id == ""


# ============================================================
# BothMatchRecord
# ============================================================
def test_both_match_from_dict_minimal():
    bm = from_dict_both_match({"method": "direct_link"})
    assert bm.method == "direct_link"
    assert bm.confidence == 0.0
    assert bm.fag_memorial_id == ""


def test_both_match_from_dict_full():
    bm = from_dict_both_match({
        "method": "corroboration",
        "confidence": 0.95,
        "reason": "name + death year + burial state agree",
        "fag_memorial_id": "50923719",
    })
    assert bm.method == "corroboration"
    assert bm.confidence == 0.95


def test_both_match_roundtrip():
    src = {"method": "direct_link", "confidence": 1.0, "fag_memorial_id": "12345"}
    bm = from_dict_both_match(src)
    out = bm.to_dict()
    for k, v in src.items():
        assert out[k] == v


# ============================================================
# PensionerRecord
# ============================================================
def test_pensioner_from_dict_minimal():
    """Empty record is allowed."""
    p = from_dict_pensioner({})
    assert p.pensioner_id is None
    assert p.cgr_records == []
    assert p.fag_records == []
    assert p.pensioncard_backlink == ""
    assert p.backlink == ""
    assert p.both_match is None


def test_pensioner_from_dict_full():
    p = from_dict_pensioner({
        "pensioner_id": 3,
        "pensioner_name": "Adair, R. W.",
        "pensioner_first": "R.",
        "pensioner_last": "Adair",
        "pensioncard_backlink": "https://dp/card/98",
        "backlink": "https://dp/pensions/3",
        "fag_records": [{"memorial_id": "1"}, {"memorial_id": "2"}],
        "cgr_records": [{"cgr_id": "999"}],
        "fag_status": "auto_accept",
        "cgr_status": "cgr_found",
        "both_match": {"method": "direct_link", "fag_memorial_id": "1"},
    })
    assert p.pensioner_id == 3
    assert len(p.fag_records) == 2
    assert all(isinstance(c, CandidateRecord) for c in p.fag_records)
    assert p.both_match is not None
    assert p.both_match.method == "direct_link"


def test_pensioner_roundtrip():
    """A canonical state.jsonl row round-trips losslessly."""
    src = {
        "pensioner_id": 1,
        "pensioner_name": "William Looney",
        "pensioner_first": "William",
        "pensioner_middle": "Pickney",
        "pensioner_last": "Looney",
        "pensioner_app_number": "A4",
        "regiment": "34 TX",
        "company": "A",
        "pensioncard_backlink": "https://dp/card/100",
        "backlink": "https://dp/pensions/5",
        "fag_records": [
            {"memorial_id": "50923719", "slug": "william-looney",
             "score": 0.85, "backlink": "https://fg/50923719"}
        ],
        "fag_status": "auto_accept",
        "cgr_records": [{"cgr_id": "999", "match_strength": "strong"}],
        "cgr_status": "cgr_found",
        "both_match": {"method": "corroboration", "confidence": 0.95,
                       "fag_memorial_id": "50923719"},
        "timestamp": "2026-07-16T12:34:56",
    }
    p = from_dict_pensioner(src)
    out = p.to_dict()
    # Required + known fields preserved
    assert out["pensioner_id"] == src["pensioner_id"]
    assert out["pensioner_name"] == src["pensioner_name"]
    assert out["pensioncard_backlink"] == src["pensioncard_backlink"]
    assert out["backlink"] == src["backlink"]
    assert len(out["fag_records"]) == 1
    assert out["fag_records"][0]["memorial_id"] == "50923719"
    assert out["both_match"]["method"] == "corroboration"


def test_pensioner_unknown_root_fields_passed_through():
    """Extra root-level fields stay in to_dict (e.g. dd_in_local)."""
    p = from_dict_pensioner({
        "pensioner_id": 1,
        "dd_in_local": True,
        "leftover_pass": {"disposition": "found_conclusive"},
    })
    out = p.to_dict()
    assert out["dd_in_local"] is True
    assert out["leftover_pass"] == {"disposition": "found_conclusive"}


def test_pensioner_to_jsonl_then_parse():
    """The wire format is JSONL; ensure to_dict output is JSON-serialisable."""
    p = from_dict_pensioner({
        "pensioner_id": 1,
        "fag_records": [{"memorial_id": "x", "score": 0.5}],
    })
    line = json.dumps(p.to_dict(), ensure_ascii=False)
    parsed = json.loads(line)
    assert parsed["pensioner_id"] == 1
    assert parsed["fag_records"][0]["score"] == 0.5


# ============================================================
# Schema version constant
# ============================================================
def test_schema_version_is_1():
    """If you bump this, bump CHANGELOG and the *_meta.json files too."""
    from scripts.state.schema import SCHEMA_VERSION
    assert SCHEMA_VERSION == 1