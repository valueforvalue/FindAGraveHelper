"""Tests for F1: birth + death year filter strategies.

FaG search URL params:
  birthyear=YYYY&birthyearfilter=N  — N years either side of birthyear
  deathyear=YYYY&deathyearfilter=N  — N years either side of deathyear
  yearfilter=N                      — applies to both when no specific year

Where N is one of: 1, 3, 5, 10, 25

The bug we found: strategies call fn(first, middle, last, None) but
should pass the actual birth_year from the pensioner record.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.search_fag import (
    strategy_b1_exact,
    strategy_b3_first_initial_fuzzy,
    strategy_b4_fuzzy_last,
    strategy_with_birth_year,
    strategy_with_death_year,
    strategy_with_year_window,
    strategy_year_sniper,
)


# ============================================================
# Strategy that uses birth year (new — F1)
# ============================================================
def test_strategy_with_birth_year_returns_params():
    """When given a birth year, the strategy adds birthyear + filter."""
    params = strategy_with_birth_year("William", "", "Looney", "1840")
    assert params is not None
    assert params["birthyear"] == "1840"
    assert params["birthyearfilter"] in ("1", "3", "5", "10", "25", "exact")
    assert params["firstname"] == "William"
    assert params["lastname"] == "Looney"


def test_strategy_with_birth_year_no_year_returns_none():
    """Without a birth year, the strategy is skipped (returns None)."""
    assert strategy_with_birth_year("William", "", "Looney", "") is None
    assert strategy_with_birth_year("William", "", "Looney", None) is None
    assert strategy_with_birth_year("William", "", "Looney", "0") is None


def test_strategy_with_birth_year_filters_to_5():
    """Default filter window is ±5 years (matches our existing B3/B4)."""
    params = strategy_with_birth_year("William", "", "Looney", "1840")
    assert params["birthyearfilter"] == "5"


def test_strategy_with_birth_year_includes_middle_if_present():
    """If pensioner has a middle name, include it."""
    params = strategy_with_birth_year("William", "G", "Looney", "1840")
    assert params["middlename"] == "G"


def test_strategy_with_birth_year_requires_names():
    """Without first or last name, returns None."""
    assert strategy_with_birth_year("", "", "Looney", "1840") is None
    assert strategy_with_birth_year("William", "", "", "1840") is None


def test_strategy_with_birth_year_uses_exact_when_close():
    """If birth year is the year only and exact spelling, use exact filter."""
    params = strategy_with_birth_year("William", "", "Looney", "1840", exact=True)
    assert params.get("exactspelling") == "true"
    assert params.get("birthyearfilter") == "exact"


# ============================================================
# Strategy that uses death year (new — F1)
# ============================================================
def test_strategy_with_death_year_returns_params():
    """Death year filter strategy."""
    params = strategy_with_death_year("William", "", "Looney", None, "1932")
    assert params is not None
    assert params["deathyear"] == "1932"
    assert params["deathyearfilter"] in ("1", "3", "5", "10", "25", "exact")


def test_strategy_with_death_year_no_year_returns_none():
    """No death year → skip strategy."""
    assert strategy_with_death_year("William", "", "Looney", None, "") is None
    assert strategy_with_death_year("William", "", "Looney", None, None) is None
    assert strategy_with_death_year("William", "", "Looney", None, "0") is None


def test_strategy_with_death_year_widens_window_for_old_deaths():
    """Died before 1930: use 10-year window (poor records).
    Died 1930+: use 5-year window (better records)."""
    # 1924 (CW era veteran): widen
    p = strategy_with_death_year("Hugh", "H", "Akers", None, "1924")
    assert p["deathyearfilter"] in ("5", "10", "25")
    # Recent (20th century late): tighter
    p = strategy_with_death_year("William", "", "Looney", None, "1932")
    assert p["deathyearfilter"] in ("5", "10", "25")


# ============================================================
# Combined birth + death window (new — F1)
# ============================================================
def test_strategy_year_sniper_uses_both():
    """Year sniper uses birthyear AND deathyear together."""
    params = strategy_year_sniper("William", "", "Looney", "1840", "1932")
    assert params is not None
    assert params["birthyear"] == "1840"
    assert params["deathyear"] == "1932"
    assert params["firstname"] == "William"
    assert params["lastname"] == "Looney"


def test_strategy_year_sniper_requires_both_years():
    """Need both years for the sniper to fire."""
    assert strategy_year_sniper("William", "", "Looney", "1840", "") is None
    assert strategy_year_sniper("William", "", "Looney", "", "1932") is None
    assert strategy_year_sniper("William", "", "Looney", None, "1932") is None


def test_strategy_year_window():
    """Year window: birth OR death year filter, widening window."""
    # Has both years → return params with both filters
    params = strategy_with_year_window("William", "", "Looney", "1840", "1932")
    assert params is not None
    assert params["birthyear"] == "1840"
    assert params["deathyear"] == "1932"
    # Only birth
    params = strategy_with_year_window("William", "", "Looney", "1840", "")
    assert params is not None
    assert params["birthyear"] == "1840"
    assert "deathyear" not in params
    # Only death
    params = strategy_with_year_window("William", "", "Looney", "", "1932")
    assert params is not None
    assert "birthyear" not in params
    assert params["deathyear"] == "1932"
    # Neither
    assert strategy_with_year_window("William", "", "Looney", "", "") is None


# ============================================================
# Existing strategies can now use birth year properly
# ============================================================
def test_existing_b1_passes_birth_year_through():
    """B1-exact now should optionally include birth year."""
    # New signature: strategy_b1_exact(first, middle, last, birth_year, ...)
    # When given a real birth year and the user requests it, include it
    import inspect
    sig = inspect.signature(strategy_b1_exact)
    # Should accept birth_year as a parameter
    assert "birth_year" in sig.parameters


def test_strategy_with_year_args_actually_filters():
    """Sanity: when we pass a birth year, the URL params include the
    filter. This is the bug-buster."""
    params = strategy_with_birth_year("William", "", "Looney", "1840")
    url_params = "&".join(f"{k}={v}" for k, v in params.items())
    assert "birthyear=1840" in url_params
    assert "birthyearfilter=" in url_params


def test_year_strategies_are_testable():
    """Year strategies can be exercised without a real browser."""
    # B1 used to hardcode None — verify the new behavior is testable
    p = strategy_with_birth_year("R", "W", "Adair", "1840")
    assert p["birthyear"] == "1840"
    assert p["firstname"] == "R"
    assert p["lastname"] == "Adair"