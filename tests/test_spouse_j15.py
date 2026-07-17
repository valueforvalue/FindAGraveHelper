"""J15: Spouse capture + boost scoring.

The user wants to leverage the spouse data already in
ok_pensioners.json (49% of records have both first+last
spouse names). The plan:

  S1 (this file): Inject spouse into FaG search URL params.
      ok_pensioners has 'spouse_first_name' + 'spouse_last_name'.
      FaG supports `linkedToName=...` (Spouse, Parent, Child or
      Sibling name). When present, FaG returns only candidates
      that share that family-link. Captures via the search URL
      (no extra page hits).

  S2 (next slice): Scrape spouse from the top-1 FaG memorial
      page and compare to ok_pensioners spouse. Boost scoring
      when they agree (a spouse name agreement is very strong
      evidence the candidate is the right person).

  S3 (final slice): view.html badge + filter for spouse match.

Tests in this file pin the S1 URL-param injection. S2 and S3
have their own files once those land.
"""
from __future__ import annotations

from pathlib import Path


def test_apply_spouse_filter_injects_linked_to_name():
    """When given first + last spouse names, the resulting URL params
    must include linkedToName=... so FaG returns only candidates
    linked to that family member."""
    from scripts.fag.filters import apply_spouse_filter
    out = apply_spouse_filter(
        {"firstname": "Sarah", "lastname": "Adams"},
        spouse_first="Garnett",
        spouse_last="Adams",
    )
    # FaG uses 'linkedToName' for the spouse/parent/child/sibling
    # name filter (verified 2026-07 from data/probe/search_page_advanced.html).
    assert "linkedToName" in out
    # The value should be the spouse's full name (first+last) so
    # FaG can match either order. Spaces are kept.
    assert out["linkedToName"] == "Garnett Adams"


def test_apply_spouse_filter_skips_when_data_missing():
    """When first OR last is empty, no linkedToName is set
    (FaG would return zero results with a half-name)."""
    from scripts.fag.filters import apply_spouse_filter

    out_empty_first = apply_spouse_filter(
        {"firstname": "John"}, spouse_first="", spouse_last="Doe"
    )
    assert "linkedToName" not in out_empty_first

    out_empty_last = apply_spouse_filter(
        {"firstname": "John"}, spouse_first="Jane", spouse_last=""
    )
    assert "linkedToName" not in out_empty_last

    out_both_empty = apply_spouse_filter(
        {"firstname": "John"}, spouse_first="", spouse_last=""
    )
    assert "linkedToName" not in out_both_empty


def test_apply_spouse_filter_normalizes_whitespace():
    """The combined spouse name must be normalized (trim + single
    spaces) so ' Garnett   Adams ' -> 'Garnett Adams'."""
    from scripts.fag.filters import apply_spouse_filter
    out = apply_spouse_filter(
        {"firstname": "Sarah"},
        spouse_first="  Garnett  A.  ",
        spouse_last="  Adams  ",
    )
    assert out["linkedToName"] == "Garnett A. Adams"


def test_apply_spouse_filter_handles_middle_initial():
    """Spouse first names like 'Garnett A.' should pass through
    (don't strip the initial). FaG does a partial match on
    the family-link name."""
    from scripts.fag.filters import apply_spouse_filter
    out = apply_spouse_filter(
        {"firstname": "Sarah"},
        spouse_first="Garnett A.",
        spouse_last="Adams",
    )
    assert out["linkedToName"] == "Garnett A. Adams"


def test_apply_spouse_filter_does_not_overwrite_existing():
    """If the caller already set linkedToName (rare; future expansion),
    we don't clobber it."""
    from scripts.fag.filters import apply_spouse_filter
    out = apply_spouse_filter(
        {"linkedToName": "preset"},
        spouse_first="Garnett", spouse_last="Adams",
    )
    assert out["linkedToName"] == "preset"


def test_apply_spouse_filter_does_not_mutate_input():
    """Defensive: input dict must not be modified (the caller
    loops through 10 strategies; if one mutates, the next
    would start from a partially-modified dict)."""
    from scripts.fag.filters import apply_spouse_filter
    original = {"firstname": "John", "lastname": "Smith"}
    snapshot = dict(original)
    apply_spouse_filter(
        original, spouse_first="Jane", spouse_last="Smith"
    )
    assert original == snapshot


def test_apply_location_filter_forwards_spouse():
    """apply_location_filter is the function called from
    search_one_pensioner per strategy. It must accept and
    forward spouse_first + spouse_last down to apply_spouse_filter.
    Default is no spouse (skips injection)."""
    from scripts.fag.filters import apply_location_filter

    # No spouse
    out_no = apply_location_filter(
        {"firstname": "Sarah"}, "OK"
    )
    assert "linkedToName" not in out_no

    # With spouse
    out_with = apply_location_filter(
        {"firstname": "Sarah"},
        "OK",
        spouse_first="Garnett", spouse_last="Adams",
    )
    assert out_with["linkedToName"] == "Garnett Adams"
    # Existing injections preserved
    assert out_with["locationId"] == "state_38"
    assert out_with["birthyearfilter"] == "after"


def test_apply_location_filter_signature_with_spouse_kwargs():
    """Backward-compatible call sites must still work. The
    apply_location_filter signature uses keyword-only args for
    spouse (no positional breaking)."""
    from scripts.fag.filters import apply_location_filter
    # Legacy 2-arg call
    out = apply_location_filter({"k": "v"}, "OK")
    assert "linkedToName" not in out


def test_spouse_filter_combined_with_location_and_date():
    """Full integration: spouse + location + ACW date window all
    coexist in the returned URL params."""
    from scripts.fag.filters import apply_location_filter
    out = apply_location_filter(
        {"firstname": "Sarah", "exactspelling": "true"},
        "OK",
        spouse_first="Garnett", spouse_last="Adams",
    )
    # All three filters applied
    assert out["linkedToName"] == "Garnett Adams"
    assert out["locationId"] == "state_38"
    assert out["birthyearfilter"] == "after"
    assert out["deathyearfilter"] == "before"
    # Original param preserved
    assert out["exactspelling"] == "true"


# ============================================================
# search_one_pensioner calls apply_location_filter with spouse
# ============================================================
def test_search_one_pensioner_threads_spouse_to_filter():
    """The strategy-ladder runner in scripts/fag/search.py must
    pass the pensioner's spouse fields into apply_location_filter.
    Verify by reading the source for the call shape (the actual
    URL hit is too expensive for unit tests; covered by
    integration tests + manual run).

    Pattern assertion: search.py imports apply_location_filter
    and calls it with `spouse_first=` and `spouse_last=` keyword
    args sourced from the pensioner dict."""
    search_src = (Path(__file__).parent.parent
                  / "scripts" / "fag" / "search.py").read_text(
                      encoding="utf-8"
                  )
    # Must reference spouse_first in the call to apply_location_filter
    assert "spouse_first" in search_src, (
        "scripts/fag/search.py must thread spouse_first into the "
        "apply_location_filter call"
    )
    assert "spouse_last" in search_src, (
        "scripts/fag/search.py must thread spouse_last into the "
        "apply_location_filter call"
    )
    # Must read from pensioner.get(...) not hardcoded
    assert "pensioner.get(\"spouse_first_name\"" in search_src, (
        "must read spouse_first_name from the pensioner dict"
    )
    assert "pensioner.get(\"spouse_last_name\"" in search_src, (
        "must read spouse_last_name from the pensioner dict"
    )
