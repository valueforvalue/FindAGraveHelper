"""Tests for the phonetic blocking index.

A blocking index is a pre-computed lookup table that, given
a query (pensioner's name), returns only the CGR veteran IDs
that share a block key with the query.

Why: instead of 7,758 search_by_name() calls against CGR (each
a network roundtrip), we make 0 CGR API calls and just look
up in the index (which is built once from a previous scrape).

Blocking strategies (we use all of them in parallel):
  - Surname Metaphone code
  - Surname NYSIIS code
  - Soundex code
  - First 2 chars of surname (literal prefix)
  - First 2 chars of first name (literal prefix)

For each query, we return the union of CGR IDs in any matching
block. Duplicates are removed.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.blocking import (
    build_blocking_index,
    build_blocking_index_from_scrape,
    lookup_block,
    metaphone_code,
    nysiis_code,
)


# ============================================================
# Phonetic code tests
# ============================================================
def test_metaphone_code_looney():
    assert metaphone_code("Looney") == "LN"


def test_metaphone_code_loney():
    """Looney and Loney both encode to LN."""
    assert metaphone_code("Loney") == "LN"


def test_metaphone_code_handles_empty():
    assert metaphone_code("") == ""


def test_nysiis_code_looney():
    assert nysiis_code("Looney") == "LANY"


def test_nysiis_code_william_williams():
    """William and Williams share NYSIIS code WALAN."""
    assert nysiis_code("William") == "WALAN"
    assert nysiis_code("Williams") == "WALAN"


def test_nysiis_code_handles_empty():
    assert nysiis_code("") == ""


# ============================================================
# Index building
# ============================================================
def _sample_cgr_vets():
    """Small fixture: 3 vets in our index."""
    return [
        {"id": 1, "name": "William G Looney", "unit": "34 TX", "born": "May 24 1840"},
        {"id": 2, "name": "John Smith", "unit": "5 AL", "born": "1842"},
        {"id": 3, "name": "William Roberts", "unit": "10 TN", "born": "1845"},
    ]


def test_build_index_returns_dict():
    """The index is a dict (or dict-like) keyed by block code."""
    index = build_blocking_index(_sample_cgr_vets())
    assert isinstance(index, dict)


def test_build_index_has_phonetic_keys():
    """Index includes metaphone and NYSIIS keyed blocks."""
    index = build_blocking_index(_sample_cgr_vets())
    # Looney -> LN metaphone, LANY nysiis
    assert "surname_metaphone:LN" in index
    assert "surname_nysiis:LANY" in index


def test_build_index_groups_by_block():
    """Same block contains the same vet ID."""
    index = build_blocking_index(_sample_cgr_vets())
    # William (vet 1) and William (vet 3) share firstname_metaphone block
    wlm = index.get("firstname_metaphone:WLM", set())
    assert 1 in wlm
    assert 3 in wlm


def test_build_index_includes_first_name_blocks():
    """Index includes first-name metaphone blocks."""
    index = build_blocking_index(_sample_cgr_vets())
    # William -> WLM (jellyfish metaphone)
    assert "firstname_metaphone:WLM" in index


def test_build_index_includes_surname_prefix_blocks():
    """Index includes surname prefix blocks (first 2 chars)."""
    index = build_blocking_index(_sample_cgr_vets())
    # Looney -> "Lo"
    assert "surname_prefix:lo" in index


def test_build_index_handles_empty_list():
    """Empty input returns empty index."""
    index = build_blocking_index([])
    # Even an empty index has the structural keys (but empty values)
    for v in index.values():
        assert len(v) == 0


def test_build_index_handles_malformed_names():
    """Names with only first or last still get indexed."""
    vets = [
        {"id": 99, "name": "Cher", "unit": "1 OK", "born": "1840"},  # only first
    ]
    index = build_blocking_index(vets)
    # Should still be indexable by first-name metaphone
    assert "firstname_metaphone:X" in index or len(index) > 0


# ============================================================
# Lookup
# ============================================================
def test_lookup_returns_matching_vet_ids():
    """Lookup for William Looney should return his CGR ID."""
    index = build_blocking_index(_sample_cgr_vets())
    matches = lookup_block(index, first_name="William", last_name="Looney")
    assert 1 in matches  # William G Looney


def test_lookup_returns_union_of_matching_blocks():
    """If two blocks both contain the same ID, return once."""
    index = build_blocking_index(_sample_cgr_vets())
    matches = lookup_block(index, first_name="William", last_name="Looney")
    # Should be a set (no duplicates)
    assert isinstance(matches, set)


def test_lookup_returns_empty_for_no_match():
    """A query that doesn't match anything returns empty set."""
    index = build_blocking_index(_sample_cgr_vets())
    matches = lookup_block(index, first_name="Zebra", last_name="Elephant")
    assert matches == set()


def test_lookup_handles_phonetic_variants():
    """Query with phonetic variant (Loney vs Looney) still finds the
    original because the index has Looney under multiple keys."""
    index = build_blocking_index(_sample_cgr_vets())
    # The original is "William G Looney" (metaphone LN, nysiis LANY)
    # Query with "Loney" produces same codes
    matches = lookup_block(index, first_name="William", last_name="Loney")
    assert 1 in matches  # finds William G Looney via phonetic block


def test_lookup_first_name_only():
    """Lookup with only first name returns all Williams."""
    index = build_blocking_index(_sample_cgr_vets())
    matches = lookup_block(index, first_name="William", last_name="")
    # Both vet 1 and vet 3 are Williams
    assert 1 in matches
    assert 3 in matches


def test_lookup_last_name_only():
    """Lookup with only last name works too."""
    index = build_blocking_index(_sample_cgr_vets())
    matches = lookup_block(index, first_name="", last_name="Smith")
    assert 2 in matches  # John Smith


def test_lookup_is_case_insensitive():
    """Case doesn't matter."""
    index = build_blocking_index(_sample_cgr_vets())
    matches_lower = lookup_block(index, first_name="william", last_name="looney")
    matches_upper = lookup_block(index, first_name="WILLIAM", last_name="LOONEY")
    assert matches_lower == matches_upper


def test_lookup_handles_empty_query():
    """Empty query returns empty set."""
    index = build_blocking_index(_sample_cgr_vets())
    assert lookup_block(index, first_name="", last_name="") == set()


def test_lookup_pruning_reduces_candidate_set():
    """The whole point of blocking: a query that would return 1000
    candidates via full-table search returns a small set."""
    vets = [
        {"id": i, "name": f"Person {i}", "unit": "5 AL", "born": "1840"}
        for i in range(1, 1001)
    ]
    # Also add one Looney
    vets.append({"id": 9999, "name": "William Looney", "unit": "34 TX", "born": "1840"})
    index = build_blocking_index(vets)
    matches = lookup_block(index, first_name="William", last_name="Looney")
    # Should return just the Looney (and maybe a few same-prefix matches)
    # The 1000 "Person N" are all different names, so they shouldn't match
    assert 9999 in matches
    # The blocking drastically reduced the candidate set
    assert len(matches) < 50  # way less than 1001


# ============================================================
# Index size
# ============================================================
def test_index_is_smaller_than_input():
    """For real data, the index should be a small fraction of the
    input size (most blocks have very few entries)."""
    vets = [
        {"id": i, "name": f"Person {i}", "unit": "5 AL", "born": "1840"}
        for i in range(1, 1001)
    ]
    index = build_blocking_index(vets)
    # How many distinct blocks?
    n_blocks = len(index)
    # Each block is one of: surname_metaphone, surname_nysiis,
    # firstname_metaphone, surname_prefix
    # For 1000 unique names, expect ~1000+ blocks (each name maps
    # to its own metaphone code, mostly)
    # We just verify the index is structured; not making claims
    # about exact size
    assert n_blocks > 100  # lots of distinct phonetic codes
    # Average block size should be small
    avg_block_size = sum(len(v) for v in index.values()) / max(1, n_blocks)
    assert avg_block_size < 5  # most blocks have 1-3 entries


def test_index_can_be_serialized():
    """The index can be saved and loaded (for caching across runs)."""
    import json
    index = build_blocking_index(_sample_cgr_vets())
    # Serialize sets as lists
    serializable = {
        k: sorted(v) for k, v in index.items()
    }
    round_trip = json.loads(json.dumps(serializable))
    assert isinstance(round_trip, dict)
    assert "surname_metaphone:LN" in round_trip


# ============================================================
# Integration with CGR scrape
# ============================================================
def test_build_index_from_cgr_scrape_records():
    """Build the index from actual CGR scrape records (cgr_records)."""
    # CGR scrape records have nested 'veterans' list
    scrape = [
        {
            "state": "OK",
            "cemetery_id": 12754,
            "cemetery_name": "Rose Hill Cemetery",
            "veterans": [
                {"id": 1, "name": "William Looney", "unit": "34 TX", "born": "1840"},
                {"id": 2, "name": "John Smith", "unit": "5 AL", "born": "1842"},
            ],
        },
    ]
    index = build_blocking_index_from_scrape(scrape)
    assert isinstance(index, dict)
    # Vet 1 (Looney) should be findable
    matches = lookup_block(index, first_name="William", last_name="Looney")
    assert 1 in matches


def test_build_index_from_scrape_flattens_veterans():
    """The index flattens nested veterans into one global set."""
    scrape = [
        {"veterans": [{"id": 1, "name": "William Looney"}]},
        {"veterans": [{"id": 2, "name": "William Roberts"}]},
    ]
    index = build_blocking_index_from_scrape(scrape)
    matches = lookup_block(index, first_name="William", last_name="")
    assert 1 in matches
    assert 2 in matches


def test_build_index_from_scrape_handles_empty_records():
    """Empty scrape records produce empty index."""
    index = build_blocking_index_from_scrape([])
    assert all(len(v) == 0 for v in index.values())