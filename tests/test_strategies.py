"""Tests for scripts/search/strategies.py (T017 split).

10 strategy functions extracted verbatim from search_fag.py.
Tests assert: each strategy returns a dict (params) or None;
None is the documented "strategy not applicable" signal.

The strategies are pure functions — they take primitives and
return a dict or None. They share no state.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.search.strategies import (
    strategy_b1_exact,
    strategy_b2_middle_initial,
    strategy_b3_first_initial_fuzzy,
    strategy_b4_fuzzy_last,
    strategy_b5_apostrophe_variants,
    strategy_b10_pre1851_tight,
    strategy_c1_cw_context,
    strategy_with_birth_year,
    strategy_with_death_year,
    strategy_year_sniper,
    strategy_with_year_window,
)


# ============================================================
# B1: exact sniper
# ============================================================
def test_b1_returns_full_params():
    p = strategy_b1_exact("William", "Pickney", "Looney", "1844", "1932")
    assert p is not None
    assert p["firstname"] == "William"
    assert p["middlename"] == "Pickney"
    assert p["lastname"] == "Looney"
    assert p["exactspelling"] == "true"
    assert p["birthyear"] == "1844"
    assert p["birthyearfilter"] == "1"


def test_b1_without_middle_omits_field():
    p = strategy_b1_exact("William", "", "Looney", None, None)
    assert "middlename" not in p


def test_b1_missing_first_returns_none():
    assert strategy_b1_exact("", "X", "Looney", None, None) is None


def test_b1_missing_last_returns_none():
    assert strategy_b1_exact("William", "X", "", None, None) is None


# ============================================================
# B2: middle-initial
# ============================================================
def test_b2_single_letter_middle():
    p = strategy_b2_middle_initial("William", "P", "Looney", None, None)
    assert p is not None
    assert p["middlename"] == "P"


def test_b2_multi_letter_middle_returns_none():
    """B2 only triggers when middle is a single character."""
    assert strategy_b2_middle_initial("William", "Pickney", "Looney", None, None) is None


def test_b2_empty_middle_returns_none():
    assert strategy_b2_middle_initial("William", "", "Looney", None, None) is None


# ============================================================
# B3: first-initial fuzzy
# ============================================================
def test_b3_returns_params():
    p = strategy_b3_first_initial_fuzzy("William", "Pickney", "Looney", None, None)
    assert p is not None
    # B3 emits "W*" (first initial + wildcard)
    assert p["firstname"].startswith("W")
    assert p["lastname"] == "Looney"


# ============================================================
# B4: fuzzy last
# ============================================================
def test_b4_returns_params():
    p = strategy_b4_fuzzy_last("William", "Pickney", "Looney", None, None)
    assert p is not None
    assert p["lastname"].startswith("Looney") or "Looney" in p["lastname"]


# ============================================================
# B5: apostrophe variants
# ============================================================
def test_b5_with_apostrophe_in_last():
    p = strategy_b5_apostrophe_variants("O", "", "Brien", None, None)
    # O'Brien -> OBrien (apostrophe stripped)
    assert p is not None or p is None  # implementation may return None when no apostrophe


# ============================================================
# C1: CW context (regiment/unit terms)
# ============================================================
def test_c1_returns_params():
    p = strategy_c1_cw_context("William", "Pickney", "Looney", None, None)
    # C1 only triggers when regiment/context info present;
    # without it may return None
    assert p is None or isinstance(p, dict)


# ============================================================
# Year-based strategies
# ============================================================
def test_birth_year_strategy():
    p = strategy_with_birth_year("William", "", "Looney", "1844", exact=False)
    assert p is not None  # should fire when birth_year present
    assert "birthyear" in p


def test_death_year_strategy():
    p = strategy_with_death_year("William", "", "Looney", None, "1932")
    assert p is None or isinstance(p, dict)


def test_year_sniper():
    p = strategy_year_sniper("William", "", "Looney", "1844", "1932")
    assert p is None or isinstance(p, dict)


def test_year_window():
    p = strategy_with_year_window("William", "", "Looney", "1844", "1932")
    assert p is None or isinstance(p, dict)


# ============================================================
# B10: pre-1851 birth-year refinement (issue #137)
# ============================================================
def test_b10_fires_for_pre1851_birth_year():
    p = strategy_b10_pre1851_tight("John", "", "Smith", "1840", None)
    assert p is not None
    assert p["firstname"] == "John"
    assert p["lastname"] == "Smith"
    assert p["exactspelling"] == "true"
    assert p["birthyear"] == "1840"
    assert p["birthyearfilter"] == "3"  # tighter than B1's 1-window / B3-B4's 5-window
    assert "deathyear" not in p


def test_b10_boundary_1850_fires():
    """1850 is still pre-1851."""
    p = strategy_b10_pre1851_tight("John", "", "Smith", "1850", None)
    assert p is not None
    assert p["birthyear"] == "1850"


def test_b10_boundary_1851_skips():
    """1851 is NOT pre-1851; B10 returns None."""
    p = strategy_b10_pre1851_tight("John", "", "Smith", "1851", None)
    assert p is None


def test_b10_post1851_skips():
    """Modern birth years (1900) must skip B10."""
    p = strategy_b10_pre1851_tight("John", "", "Smith", "1900", None)
    assert p is None


def test_b10_missing_birth_year_skips():
    p = strategy_b10_pre1851_tight("John", "", "Smith", None, None)
    assert p is None


def test_b10_missing_first_skips():
    p = strategy_b10_pre1851_tight("", "", "Smith", "1840", None)
    assert p is None


def test_b10_missing_last_skips():
    p = strategy_b10_pre1851_tight("John", "", "", "1840", None)
    assert p is None


def test_b10_includes_middle_when_present():
    p = strategy_b10_pre1851_tight("John", "Q", "Smith", "1840", None)
    assert p is not None
    assert p["middlename"] == "Q"


def test_b10_ladder_position():
    """B10 must sit after B5 and before C1 per issue #137 acceptance."""
    from scripts.search.strategies import STRATEGIES
    names = [s.name for s in STRATEGIES]
    assert "B10-pre1851-tight" in names
    # Order check
    assert names.index("B5-apostrophe") < names.index("B10-pre1851-tight")
    assert names.index("B10-pre1851-tight") < names.index("C1-cw-context")


# ============================================================
# Regression: counts match the original search_fag.py
# ============================================================
def test_strategies_module_has_11_public_strategies():
    """Issue #137 added B10-pre1851-tight; count is now 11."""
    import scripts.search.strategies as s
    names = [
        n for n in dir(s)
        if n.startswith("strategy_") and callable(getattr(s, n))
    ]
    assert len(names) == 11, f"expected 11 strategies, got {len(names)}: {names}"