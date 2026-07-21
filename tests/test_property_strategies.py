"""Property-based tests for search strategies (Hypothesis).

Covers the pure-function contract that every strategy must uphold:
- params() never throws (returns dict or None)
- Positional shims return identical results to context-form
- Params dicts contain only valid FaG URL keys
- When ctx lacks required fields, strategy returns None gracefully
"""
from __future__ import annotations

import pytest
from hypothesis import assume, given, strategies as st, settings, HealthCheck

from scripts.search.context import SearchContext
from scripts.search.strategies import (
    # Context-form (canonical)
    b1_exact,
    b2_middle_initial,
    b3_first_initial_fuzzy,
    b4_fuzzy_last,
    b5_apostrophe_variants,
    c1_cw_context,
    with_birth_year,
    with_death_year,
    year_sniper,
    with_year_window,
    # Positional shims (legacy)
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

# ── Strategy generators ──────────────────────────────────────

# All 10 context-form strategies (name, function)
ALL_STRATEGIES = [
    ("b1_exact", b1_exact),
    ("b2_middle_initial", b2_middle_initial),
    ("b3_first_initial_fuzzy", b3_first_initial_fuzzy),
    ("b4_fuzzy_last", b4_fuzzy_last),
    ("b5_apostrophe_variants", b5_apostrophe_variants),
    ("c1_cw_context", c1_cw_context),
    ("with_birth_year", with_birth_year),
    ("with_death_year", with_death_year),
    ("year_sniper", year_sniper),
    ("with_year_window", with_year_window),
]

# Pairs of (canonical, positional) for the contract test
CANONICAL_POSITIONAL_PAIRS = [
    (b1_exact, strategy_b1_exact),
    (b2_middle_initial, strategy_b2_middle_initial),
    (b3_first_initial_fuzzy, strategy_b3_first_initial_fuzzy),
    (b4_fuzzy_last, strategy_b4_fuzzy_last),
    (b5_apostrophe_variants, strategy_b5_apostrophe_variants),
    (c1_cw_context, strategy_c1_cw_context),
    (with_birth_year, strategy_with_birth_year),
    (with_death_year, strategy_with_death_year),
    (year_sniper, strategy_year_sniper),
    (with_year_window, strategy_with_year_window),
]


# ── Generators ──────────────────────────────────────────────

# Valid FaG URL parameter keys
_VALID_FAG_PARAM_KEYS = {
    "firstname", "middlename", "lastname",
    "exactspelling", "fuzzyNames",
    "birthyear", "birthyearfilter",
    "deathyear", "deathyearfilter",
    "yearfilter", "isVeteran", "bio",
    "locationId",
}


@st.composite
def search_contexts(draw) -> SearchContext:
    """Generate arbitrary SearchContext values."""
    first = draw(st.text(min_size=0, max_size=30))
    middle = draw(st.text(min_size=0, max_size=30))
    last = draw(st.text(min_size=0, max_size=30))
    birth = draw(st.text(min_size=0, max_size=10))
    death = draw(st.text(min_size=0, max_size=10))

    return SearchContext(
        first=first.strip() or "",
        middle=middle.strip() or "",
        last=last.strip() or "",
        birth_year=birth.strip() or "",
        death_year=death.strip() or "",
        state="OK",
    )


@st.composite
def search_contexts_with_names(draw) -> SearchContext:
    """Generate SearchContext with guaranteed first + last name."""
    first = draw(st.text(min_size=1, max_size=20, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"))
    last = draw(st.text(min_size=1, max_size=20, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"))
    middle = draw(st.text(min_size=0, max_size=20, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"))
    birth = draw(st.text(min_size=0, max_size=8, alphabet="0123456789"))
    death = draw(st.text(min_size=0, max_size=8, alphabet="0123456789"))

    return SearchContext(
        first=first.strip(),
        last=last.strip(),
        middle=middle.strip() or "",
        birth_year=birth.strip() or "",
        death_year=death.strip() or "",
        state="OK",
    )


# ── Property 1: strategies never throw ──────────────────────


@given(ctx=search_contexts())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_all_strategies_never_throw(ctx: SearchContext):
    """Every strategy must return dict|None; never raise an exception.

    This is the fundamental contract — the runner iterates the
    ladder and assumes strategies are safe to call on any context.
    """
    for name, strat_fn in ALL_STRATEGIES:
        result = strat_fn(ctx)
        assert result is None or isinstance(result, dict), (
            f"{name} returned {type(result).__name__}, expected dict|None"
        )


# ── Property 2: params dicts have valid keys ────────────────


@given(ctx=search_contexts_with_names())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_params_dict_keys_are_valid(ctx: SearchContext):
    """Every returned params dict must only contain valid FaG URL keys.

    If a strategy invents a key, FaG ignores it or errors.
    """
    for name, strat_fn in ALL_STRATEGIES:
        result = strat_fn(ctx)
        if result is None:
            continue
        unknown = set(result.keys()) - _VALID_FAG_PARAM_KEYS
        assert not unknown, (
            f"{name} returned unknown keys: {unknown}"
        )


# ── Property 3: required fields → non-None result ───────────


@given(ctx=search_contexts_with_names())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_b1_exact_returns_dict_when_names_present(ctx: SearchContext):
    """B1-exact must return a dict when first+last are present."""
    result = b1_exact(ctx)
    assert isinstance(result, dict), (
        f"B1-exact returned None despite first={ctx.first!r} last={ctx.last!r}"
    )
    assert "firstname" in result
    assert "lastname" in result
    assert result.get("exactspelling") == "true"


# ── Property 4: no names → None for name-requiring strategies ─


@given(first=st.text(max_size=0), last=st.text(max_size=0))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_name_requiring_strategies_return_none_without_names(
    first: str, last: str
):
    """Strategies that require names must return None when names are empty."""
    ctx = SearchContext(first=first, last=last, state="OK")
    name_required = [
        b1_exact, b2_middle_initial, b3_first_initial_fuzzy,
        c1_cw_context, with_birth_year, year_sniper,
    ]
    for fn in name_required:
        result = fn(ctx)
        assert result is None, (
            f"{fn.__name__} returned {result!r} despite empty names"
        )


# ── Property 5: canonical == positional shim ────────────────


@given(ctx=search_contexts_with_names())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_positional_shims_match_canonical(ctx: SearchContext):
    """Every positional shim must return the same result as its
    canonical context-form counterpart.

    This pins the dual-form contract added in the 2026-07-20
    refactor. If they diverge, the test suite and scripts/fag/filters.py
    will break.
    """
    for canonical, positional in CANONICAL_POSITIONAL_PAIRS:
        canonical_result = canonical(ctx)

        # Positional shims take (first, middle, last, birth, death)
        pos_result = positional(
            ctx.first, ctx.middle, ctx.last, ctx.birth_year, ctx.death_year
        )
        assert canonical_result == pos_result, (
            f"{canonical.__name__} vs {positional.__name__} mismatch:\n"
            f"  canonical: {canonical_result}\n"
            f"  positional: {pos_result}\n"
            f"  ctx: first={ctx.first!r} middle={ctx.middle!r} "
            f"last={ctx.last!r} birth={ctx.birth_year!r} death={ctx.death_year!r}"
        )


# ── Property 6: apostrophe strategy only fires with apostrophe ─


@given(ctx=search_contexts_with_names())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_apostrophe_strategy_only_fires_with_apostrophe(ctx: SearchContext):
    """B5 must return None when last name has no apostrophe."""
    result = b5_apostrophe_variants(ctx)
    if "'" in ctx.last:
        # May or may not fire (needs first name too), but when it does
        # the result must NOT contain an apostrophe
        if result is not None:
            assert "'" not in str(result.get("lastname", "")), (
                f"B5 returned lastname with apostrophe: {result['lastname']}"
            )
    # If no apostrophe and first name present, should not fire
    elif ctx.first:
        assert result is None, (
            f"B5 fired despite no apostrophe in last={ctx.last!r}"
        )


# ── Property 7: middle-initial only fires on single-char middle ──


@given(ctx=search_contexts_with_names())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_middle_initial_only_fires_on_single_char(ctx: SearchContext):
    """B2 must return None when middle is not exactly one character."""
    result = b2_middle_initial(ctx)
    if result is not None:
        assert len(ctx.middle) == 1, (
            f"B2 fired with middle={ctx.middle!r} (len={len(ctx.middle)})"
        )


# ── Property 8: year sniper requires both years ─────────────


@given(ctx=search_contexts_with_names())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_year_sniper_requires_both_years(ctx: SearchContext):
    """F1c must return None unless both birth and death years present."""
    result = year_sniper(ctx)
    if result is not None:
        assert ctx.birth_year, "F1c fired without birth_year"
        assert ctx.death_year, "F1c fired without death_year"


# ── Property 9: veteran filter doesn't include bio ──────────


@given(ctx=search_contexts_with_names())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_c1_no_bio_param(ctx: SearchContext):
    """C1 (veteran filter) must never include a bio param.

    Regression guard for #69 research: old CSA bio had 0% hit rate.
    """
    result = c1_cw_context(ctx)
    if result is not None:
        assert "bio" not in result, (
            f"C1 included bio param: {result.get('bio')}"
        )
        assert result.get("isVeteran") == "true"
