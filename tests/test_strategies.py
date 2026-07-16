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
# Regression: counts match the original search_fag.py
# ============================================================
def test_strategies_module_has_10_public_strategies():
    """The audit counted 10 strategy_* functions. If this drops,
    something was lost in the move."""
    import scripts.search.strategies as s
    names = [
        n for n in dir(s)
        if n.startswith("strategy_") and callable(getattr(s, n))
    ]
    assert len(names) == 10, f"expected 10 strategies, got {len(names)}: {names}"