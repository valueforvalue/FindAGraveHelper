"""J13: ACW-vet date-window filter for FaG candidates.

The pipeline was leaking modern same-name matches into the
candidate pool because:

  (a) The source data (docs/research/digitalprairie/
      ok_pensioners.json) has 0/7,709 records with birth_year
      or death_year populated (only metadata like coverage=
      "1910s-1950s" + empty "date" field).

  (b) The score_candidate death-year component is gated on
      `if local_dy and cand_dy`. When local_dy is empty, the
      death_year component is 0, making a 1920s death and a
      2020s death indistinguishable.

  (c) No filter rejected impossible-date candidates at the
      parse step.

Fix:
  1. apply_date_filter(candidates, hard=True) drops
     candidates whose date_attribution is outside the project-
     appropriate window for an American Civil War Confederate
     pensioner. ACW era (research-backed, see
     docs/research/acw-vet-date-ranges.md): birth 1810-1880,
     death 1861-1955. Outside = hostile name-collision; drop it.

  2. score_candidate treats any candidate with
     death_year > 1950 as a HARD miss (score 0) even when
     local_dy is unknown, because the candidate is too
     young to be a Civil War veteran.

  3. enrich_pensioner_dates(pensioners) joins ok_pensioners.json
     rows against the dixiedata SQLite (if available) on
     (last_name, first_initial). Adds .birth_year and
     .death_year to each row where the join succeeds.

Tests below cover each of the three layers.
"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).parent.parent
FILTERS_PY = (ROOT / "scripts" / "fag" / "filters.py").read_text(encoding="utf-8")
SCORING_PY = (ROOT / "scripts" / "fag" / "scoring.py").read_text(encoding="utf-8")


# ============================================================
# Layer 1: apply_date_filter must exist and drop impossible dates
# ============================================================
def test_apply_date_filter_exists():
    """apply_date_filter(candidates) -> filtered list must exist
    in scripts/fag/filters.py."""
    assert "def apply_date_filter" in FILTERS_PY, (
        "expected `def apply_date_filter` in scripts/fag/filters.py"
    )


def test_hard_filter_rejects_modern_death_year():
    """A candidate with death_year=2020 must be DROPPED, not
    just scored low. (Score-based filtering relies on threshold
    tuning; drop is policy.)"""
    from scripts.fag.filters import apply_date_filter

    c_modern = {
        "name": "Modern Same Surname",
        "details": {"birth_year": "1949", "death_year": "2020"},
    }
    c_acw = {
        "name": "A.C.W. Era Match",
        "details": {"birth_year": "1835", "death_year": "1927"},
    }
    out = apply_date_filter([c_modern, c_acw])
    names = [c["name"] for c in out]
    assert "Modern Same Surname" not in names, (
        "modern death_year=2020 candidate was NOT dropped"
    )
    assert "A.C.W. Era Match" in names, (
        "plausible death_year=1927 candidate WAS dropped"
    )


def test_hard_filter_handles_no_dates():
    """Candidates without dates must be KEPT (not dropped) -
    we don't know enough. Filtering should be conservative."""
    from scripts.fag.filters import apply_date_filter

    c_no_date = {
        "name": "No Dates Listed",
        "details": {"birth_year": "", "death_year": ""},
    }
    c_bad_birth = {
        "name": "Birth Year Missing from Parse",
        "details": {"birth_year": None, "death_year": "1920"},
    }
    out = apply_date_filter([c_no_date, c_bad_birth])
    assert len(out) == 2, (
        f"expected both candidates kept (no-good-reason to drop), got {len(out)}"
    )


def test_hard_filter_rejects_pre_acw_death():
    """A candidate with death_year < 1861 (pre-Civil War) must
    be dropped  -  same name, but wrong era."""
    from scripts.fag.filters import apply_date_filter

    c_pre = {
        "name": "Pre-Civil-War Death",
        "details": {"birth_year": "1820", "death_year": "1850"},
    }
    out = apply_date_filter([c_pre])
    assert len(out) == 0


def test_pensioner_id_lookup_filter_works():
    """Real-world shape: candidate.details.{birth,death}_year
    must be the path the filter reads. Confirm by inspecting
    the implementation rather than runtime  -  this is a
    canary test for refactors that change the candidate dict
    shape."""
    m = re.search(
        r"def apply_date_filter\(.*?\):.*?return.*?\]",
        FILTERS_PY, re.DOTALL,
    )
    assert m, "apply_date_filter body not found"
    body = m.group(0)
    assert "details" in body or "details[" in body, (
        "apply_date_filter must read candidate['details'] per the "
        "candidate shape produced by parse_results_page"
    )
    assert "death_year" in body, (
        "apply_date_filter must inspect death_year"
    )


# ============================================================
# Layer 2: scoring penalises impossible dates even without local
# ============================================================
    """A candidate with death_year=2020 must score ZERO regardless
    of local data being absent. This is the canonical
    impossible-date case (modern person, same surname).
    """
    from scripts.fag.scoring import score_candidate

    local = {  # no _death_year
        "first_name": "R.",
        "middle_name": "W.",
        "last_name": "Adair",
        "_state_abbr": "OK",
    }
    cand_modern = {
        "name": "Ralph Michael Adair V",
        "slug": "ralph-michael-adair",
        "details": {
            "is_veteran": False,
            "birth_year": "1949",
            "death_year": "2020",
            "state": "OK",
        },
    }
    score, _ = score_candidate(local, cand_modern)
    assert score == 0.0, (
        f"modern (by=1949, dy=2020) candidate scored {score:.3f}; "
        f"expected 0.0 (impossible for ACW Confederate pensioner)"
    )


def test_scoring_zeroes_pre_acw_match():
    """A candidate with death_year=1850 (pre-Civil War) must
    also score zero."""
    from scripts.fag.scoring import score_candidate

    local = {
        "first_name": "Robert",
        "middle_name": "",
        "last_name": "Smith",
        "_state_abbr": "OK",
    }
    cand_pre = {
        "name": "Robert Smith (early)",
        "slug": "robert-smith-early",
        "details": {
            "is_veteran": False,
            "birth_year": "1810",
            "death_year": "1850",
            "state": "OK",
        },
    }
    score, _ = score_candidate(local, cand_pre)
    assert score == 0.0, (
        f"pre-CW (dy=1850) candidate scored {score:.3f}; expected 0.0"
    )


def test_scoring_keeps_plausible_match():
    """A candidate with by=1835, dy=1927 (the actual Robert W. Adair
    from the test batch) must still score positively so we do not
    lose real matches."""
    from scripts.fag.scoring import score_candidate

    local = {
        "first_name": "R.",
        "middle_name": "W.",
        "last_name": "Adair",
        "_state_abbr": "OK",
    }
    cand_real = {
        "name": "Robert William Adair V",
        "slug": "robert-william-adair",
        "details": {
            "is_veteran": True,
            "birth_year": "1835",
            "death_year": "1927",
            "state": "OK",
        },
    }
    score, _ = score_candidate(local, cand_real)
    assert score > 0.5, (
        f"real ACW match (R. W. Adair 1835-1927) scored {score:.3f}; "
        f"expected >0.5 (name+veteran match)"
    )


# ============================================================
# Layer 3: REMOVED in J14 — automatic enrichment was a poison
# risk (silent bad joins). Replaced with a post-pipeline
# comparison in scripts/cgr/dixiedata_match.py (see J14).
# ============================================================


def test_date_window_constants_are_narrow():
    """Pin the date window so the ACW-appropriate range is
    explicit. Born 1810-1880 (research-backed: covers 27
    born 1810-1819 in local data + 1840s peak; widest possible
    is 1880 to catch post-war widows); died 1861-1955 (the
    OK Confederate pension rolls were active through ~1955;
    7 deaths after 1940 in local data).
    """
    from scripts.fag.filters import (
        ACW_BIRTH_YEAR_MIN,
        ACW_BIRTH_YEAR_MAX,
        ACW_DEATH_YEAR_MIN,
        ACW_DEATH_YEAR_MAX,
    )
    assert ACW_BIRTH_YEAR_MIN == 1810
    assert ACW_BIRTH_YEAR_MAX == 1880
    assert ACW_DEATH_YEAR_MIN == 1861
    assert ACW_DEATH_YEAR_MAX == 1955


# ============================================================
# Layer 4: URL-level date filter (the cheapest layer)
# ============================================================
def test_apply_location_filter_adds_date_window():
    """apply_location_filter must ALSO inject the ACW date
    window into the FaG URL params, so modern same-surname
    candidates are filtered at the source (not just scored
    low downstream)."""
    from scripts.fag.filters import apply_location_filter

    out = apply_location_filter({"firstname": "John"}, "OK")
    assert out["birthyear"] == "1810"
    assert out["birthyearfilter"] == "after"
    assert out["deathyear"] == "1955"
    assert out["deathyearfilter"] == "before"
    # Location filter is preserved
    assert out["locationId"] == "state_38"


def test_date_window_preserves_strategy_specific_dates():
    """When a strategy already specifies birthyear / deathyear,
    apply_location_filter MUST NOT overwrite them  -  that would
    lose the strategy-specific tighter scope (e.g.
    F2-regiment-bio: death_year=1927+/-5).
    """
    from scripts.fag.filters import apply_location_filter

    out = apply_location_filter(
        {"firstname": "John", "deathyear": "1927", "deathyearfilter": "5year"},
        "OK",
    )
    assert out["deathyear"] == "1927", "strategy-specific deathyear was overwritten"
    assert out["deathyearfilter"] == "5year", "strategy-specific filter mode was overwritten"
    # Birth still gets the window
    assert out["birthyear"] == "1810"


def test_apply_location_only_skips_date_window():
    """apply_location_only is the escape hatch for tests or
    strategies that bring their own date scope; NOT meant to
    bypass the window in production.
    """
    from scripts.fag.filters import apply_location_only

    out = apply_location_only({"firstname": "John"}, "OK")
    assert out["locationId"] == "state_38"
    assert "birthyear" not in out
    assert "deathyear" not in out


# ============================================================
# Layer 5: view.html meta row shows dates (or 'unknown' badge)
# ============================================================
def test_view_html_meta_row_shows_dates_when_present():
    """When the JSONL has pensioner_birth_year / pensioner_death_year,
    view.html must render them in the meta row (so the reviewer can
    anchor candidates against known dates)."""
    VIEW = (Path(__file__).parent.parent / "scripts" / "view.html").read_text(
        encoding="utf-8"
    )
    assert "pensioner_birth_year" in VIEW, (
        "view.html should read pensioner_birth_year from the record"
    )
    assert "pensioner_death_year" in VIEW, (
        "view.html should read pensioner_death_year from the record"
    )
    # The actual meta-row render code must exist
    assert "Dates:</strong>" in VIEW or "Dates:" in VIEW, (
        "view.html must include a Dates span in the meta row"
    )


def test_view_html_meta_row_handles_missing_dates():
    """When pensioner_birth_year / pensioner_death_year are both
    empty, view.html shows an 'unknown' badge so the reviewer
    knows the match set isn't date-anchored."""
    VIEW = (Path(__file__).parent.parent / "scripts" / "view.html").read_text(
        encoding="utf-8"
    )
    assert 'class="life-dates missing"' in VIEW, (
        "view.html must surface missing dates with a 'missing' CSS class"
    )
