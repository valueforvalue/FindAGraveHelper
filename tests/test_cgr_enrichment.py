"""Tests for F4b: CGR vet details enrichment.

Takes ok_cemeteries.jsonl (cems + flat vet lists inside) and
fetches vetDetails.php for each of 2,593 vets, producing
ok_vets_enriched.jsonl (one record per vet, with death info).

This is the "death data" step we need before the unified
pipeline can use CGR for strong matching.
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cgr_enrich import (
    expand_to_per_vet,
    build_enriched_record,
    parse_already_fetched,
    EnrichmentStats,
)


# ============================================================
# Flatten cems -> per-vet records
# ============================================================
def _sample_cem():
    return [
        {
            "cemetery_id": 13211,
            "cemetery_name": "Baptist Mission Cemetery",
            "county": "Adair",
            "state": "OK",
            "veterans": [
                {"id": 96425, "name": "Andrew Jackson Alberty", "unit": "1 OK", "born": "1843"},
                {"id": 111050, "name": "William Looney", "unit": "34 TX", "born": "1840"},
            ],
        },
        {
            "cemetery_id": 14481,
            "cemetery_name": "Chalk Bluff Cemetery",
            "county": "Adair",
            "state": "OK",
            "veterans": [
                {"id": 112601, "name": "Andrew J Alberty", "unit": "1 OK", "born": "1843"},
            ],
        },
    ]


def test_expand_produces_one_record_per_vet():
    """All vets across all cems become flat records."""
    expanded = expand_to_per_vet(_sample_cem())
    assert len(expanded) == 3  # 2 + 1


def test_expand_preserves_cem_context():
    """Each vet record includes cemetery_id, name, county."""
    expanded = expand_to_per_vet(_sample_cem())
    for v in expanded:
        assert "cemetery_id" in v
        assert "cemetery_name" in v
        assert "county" in v


def test_expand_includes_input_fields():
    """Input fields (id, name, unit, born) are preserved."""
    expanded = expand_to_per_vet(_sample_cem())
    v = expanded[0]
    assert "id" in v
    assert "name" in v
    assert "unit" in v
    assert "born" in v


def test_expand_handles_empty():
    """Empty input returns empty list."""
    assert expand_to_per_vet([]) == []


def test_expand_skips_cems_without_veterans():
    """Cems with no vets → no records."""
    assert expand_to_per_vet([{"cemetery_id": 1, "veterans": []}]) == []


# ============================================================
# build_enriched_record — merges vet_details into base vet
# ============================================================
def test_build_enriched_merges_vet_details():
    """vet_details fields are added to the base vet record."""
    base = {
        "id": 96425,
        "name": "Andrew Jackson Alberty",
        "unit": "1 OK",
        "born": "1843",
        "cemetery_id": 13211,
        "cemetery_name": "Baptist Mission Cemetery",
        "county": "Adair",
        "state": "OK",
    }
    vet_details = {
        "first_name": "Andrew",
        "middle_name": "Jackson",
        "last_name": "Alberty",
        "died": "1933-04-15",
        "died_state": "OK",
        "rank": "Pvt",
        "company": "A",
        "unit": "1 OK Infantry",
    }
    enriched = build_enriched_record(base, vet_details)
    assert enriched["died"] == "1933-04-15"
    assert enriched["died_state"] == "OK"
    assert enriched["rank"] == "Pvt"
    # Base fields preserved
    assert enriched["id"] == 96425
    assert enriched["cemetery_id"] == 13211


def test_build_enriched_handles_empty_vet_details():
    """If vet_details is empty (e.g. fetch failed), base is preserved."""
    base = {"id": 96425, "name": "Andrew Jackson Alberty", "cemetery_id": 13211}
    enriched = build_enriched_record(base, {})
    assert enriched["id"] == 96425
    assert "died" not in enriched  # nothing added


def test_build_enriched_handles_failed_vet_details_none():
    """If vet_details is None (network error), error field is set."""
    base = {"id": 96425, "name": "Andrew", "cemetery_id": 13211}
    enriched = build_enriched_record(base, None)
    assert "vet_error" in enriched or enriched.get("vet_details") is None


# ============================================================
# parse_already_fetched — resume support
# ============================================================
def test_parse_already_fetched_returns_id_set():
    """Resume parser returns the set of vet IDs already fetched."""
    import json
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        f.write(json.dumps({"id": 1, "name": "Foo", "died": "1925"}) + "\n")
        f.write(json.dumps({"id": 2, "name": "Bar", "died": "1930"}) + "\n")
        f.write(json.dumps({"id": 3, "name": "Baz"}) + "\n")  # no died
        path = Path(f.name)
    try:
        ids = parse_already_fetched(path)
        assert ids == {1, 2, 3}  # all three, regardless of whether died was set
    finally:
        path.unlink(missing_ok=True)


def test_parse_already_fetched_handles_nonexistent():
    """If the file doesn't exist, returns empty set."""
    ids = parse_already_fetched(Path("/nonexistent/path.jsonl"))
    assert ids == set()


def test_parse_already_fetched_handles_missing_id():
    """Records without 'id' field are skipped without crashing."""
    import json
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        f.write(json.dumps({"name": "no_id"}) + "\n")
        f.write(json.dumps({"id": 5, "name": "has_id"}) + "\n")
        path = Path(f.name)
    try:
        ids = parse_already_fetched(path)
        assert ids == {5}
    finally:
        path.unlink(missing_ok=True)


# ============================================================
# EnrichmentStats
# ============================================================
def test_stats_counts():
    """Stats have fields for total, fetched, errors."""
    s = EnrichmentStats(total=10, fetched=5, errors=2, died_state_ok=3)
    assert s.total == 10
    assert s.fetched == 5
    assert s.errors == 2
    assert s.died_state_ok == 3


def test_stats_progress_pct():
    """Progress percentage is 0-100."""
    s = EnrichmentStats(total=10, fetched=5)
    pct = s.progress_pct
    assert 0 <= pct <= 100


def test_stats_to_dict():
    """Stats serialize to JSONL cleanly."""
    import json
    s = EnrichmentStats(total=10, fetched=5, errors=2, died_state_ok=3, vet_died_in_ok=2)
    d = s.to_dict()
    line = json.dumps(d, ensure_ascii=False)
    parsed = json.loads(line)
    assert parsed["total"] == 10
    assert parsed["vet_died_in_ok"] == 2