"""Tests for _found_by tracking in candidate records.

Each candidate returned from a FaG search should carry a
`_found_by` field telling us which strategy + URL params
surfaced it. This is what we show in the HTML viewer next to
each backlink.

The `_found_by` structure is:
  {
    "strategy": "B1-exact",
    "params": {"firstname": "John", "lastname": "Smith", "birthyear": "1842"},
  }

This is set by tag_candidates_with_found_by() in scripts/search_fag.py,
called per-strategy after parse_results_page().
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.search_fag import tag_candidates_with_found_by


def test_tag_candidates_with_found_by_adds_field():
    """Each candidate gets a _found_by dict after tagging."""
    cands = [
        {"memorial_id": "1", "slug": "a", "name": "John Smith"},
        {"memorial_id": "2", "slug": "b", "name": "John Smith Jr"},
    ]
    tagged = tag_candidates_with_found_by(
        cands, strategy="B1-exact", params={"firstname": "John", "lastname": "Smith"}
    )
    assert len(tagged) == 2
    assert all("_found_by" in c for c in tagged)


def test_tag_preserves_strategy_name():
    """_found_by.strategy is set to the strategy we passed in."""
    cands = [{"memorial_id": "1", "slug": "a", "name": "X"}]
    tagged = tag_candidates_with_found_by(cands, "B3-first-initial-fuzzy", {})
    assert tagged[0]["_found_by"]["strategy"] == "B3-first-initial-fuzzy"


def test_tag_preserves_params():
    """_found_by.params is set to the params dict we passed in."""
    cands = [{"memorial_id": "1", "slug": "a", "name": "X"}]
    params = {"firstname": "John", "middlename": "W", "lastname": "Smith"}
    tagged = tag_candidates_with_found_by(cands, "B1-exact", params)
    assert tagged[0]["_found_by"]["params"] == params


def test_tag_does_not_mutate_input():
    """tag_candidates returns new list; doesn't mutate originals."""
    cands = [{"memorial_id": "1", "slug": "a", "name": "X"}]
    tagged = tag_candidates_with_found_by(cands, "B1-exact", {})
    assert tagged[0] is not cands[0]  # new dict
    assert "_found_by" not in cands[0]  # original untouched


def test_tag_handles_empty_list():
    """Empty candidate list returns empty list, no crash."""
    tagged = tag_candidates_with_found_by([], "B1-exact", {})
    assert tagged == []


def test_tag_with_params_having_birthyear():
    """B1-exact params include birthyear when provided."""
    cands = [{"memorial_id": "1", "slug": "a", "name": "X"}]
    params = {"firstname": "John", "lastname": "Smith", "birthyear": "1842"}
    tagged = tag_candidates_with_found_by(cands, "B1-exact", params)
    assert tagged[0]["_found_by"]["params"]["birthyear"] == "1842"


def test_tag_handles_none_params():
    """Some strategies return None (skip). Tagging should still work with {}."""
    cands = [{"memorial_id": "1", "slug": "a", "name": "X"}]
    # In practice, search_one_pensioner filters out None params, so we
    # only call tag with non-None params. But the helper should handle {}.
    tagged = tag_candidates_with_found_by(cands, "B1-exact", {})
    assert tagged[0]["_found_by"]["params"] == {}