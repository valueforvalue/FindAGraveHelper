"""FaG search-strategy ladder (T017 split + 2026-07-20 refactor).

The 10 strategy functions extracted verbatim from search_fag.py.
Each takes a SearchContext and returns either:

  - a dict of FaG search-URL params, OR
  - None when the strategy is not applicable for the given context.

The ladder is `STRATEGIES` — an ordered list of Strategy objects.
The runner calls `params()` on each; the first to return a dict
is used (or all, in mode='all').

These are pure functions with no shared state.

============================================================
DUAL-FORM LAYER (refactor 2026-07-20)
============================================================
Every strategy is exposed in two equivalent forms:

  1. **Context form** (canonical) — takes a SearchContext, returns
     dict | None. New code should use this. Names: `b1_exact`,
     `b3_first_initial_fuzzy`, etc. (Pythonic; the module
     name `strategies` provides the namespace.)

  2. **Positional form** (legacy shim) — takes the original
     primitives (first, middle, last, birth_year, death_year).
     Names: `strategy_b1_exact`, etc. (legacy names kept for
     back-compat with the original test suite and
     scripts/fag/filters.py imports). Will be deprecated in
     a future release.

The two forms MUST return identical results for identical
inputs. Tests pin this.

F2-regiment-bio and F3-nickname remain positional-only because
they need pensioner fields that don't fit the SearchContext
core (regiment, nickname). They read from `ctx.extras`. The
positional shims accept the extra args.
"""
from __future__ import annotations

__all__ = [
    # Context-form (canonical) — new code uses these
    "b1_exact",
    "b2_middle_initial",
    "b3_first_initial_fuzzy",
    "b4_fuzzy_last",
    "b5_apostrophe_variants",
    "c1_cw_context",
    "with_birth_year",
    "with_death_year",
    "year_sniper",
    "with_year_window",
    # Positional shims (legacy) — kept for back-compat
    "strategy_b1_exact",
    "strategy_b2_middle_initial",
    "strategy_b3_first_initial_fuzzy",
    "strategy_b4_fuzzy_last",
    "strategy_b5_apostrophe_variants",
    "strategy_c1_cw_context",
    "strategy_with_birth_year",
    "strategy_with_death_year",
    "strategy_year_sniper",
    "strategy_with_year_window",
    # Ladder
    "STRATEGIES",
]


# ============================================================
# Context-form strategies (canonical)
# ============================================================


def b1_exact(ctx):
    """B1: exact sniper. first + middlename + last + exactspelling."""
    if not ctx.first or not ctx.last:
        return None
    p = {"firstname": ctx.first, "lastname": ctx.last, "exactspelling": "true"}
    if ctx.middle:
        p["middlename"] = ctx.middle
    if ctx.birth_year:
        p["birthyear"] = ctx.birth_year
        p["birthyearfilter"] = "1"
    return p


def b2_middle_initial(ctx):
    """B2: middlename-initial. Only if middle is a single letter."""
    if not ctx.middle or len(ctx.middle) > 1 or not ctx.first or not ctx.last:
        return None
    return {
        "firstname": ctx.first,
        "middlename": ctx.middle,
        "lastname": ctx.last,
        "exactspelling": "true",
    }


def b3_first_initial_fuzzy(ctx):
    """B3: first-initial + fuzzy last + middlename."""
    if not ctx.first or not ctx.last:
        return None
    first_initial = ctx.first[0]
    return {
        "firstname": f"{first_initial}*",
        "lastname": ctx.last,
        "fuzzyNames": "true",
        "birthyearfilter": "5",
    }


def b4_fuzzy_last(ctx):
    """B4: fuzzy last only + middlename."""
    if not ctx.last:
        return None
    p = {"lastname": ctx.last, "fuzzyNames": "true", "birthyearfilter": "5"}
    if ctx.middle:
        p["middlename"] = ctx.middle
    return p


def b5_apostrophe_variants(ctx):
    """B5: apostrophe variants. Only if last contains apostrophe."""
    if not ctx.last or "'" not in ctx.last:
        return None
    if not ctx.first:
        return None
    # Drop the apostrophe
    return {
        "firstname": ctx.first,
        "lastname": ctx.last.replace("'", ""),
        "fuzzyNames": "true",
    }


def c1_cw_context(ctx):
    """C1: civil war bio context catch-all.

    Uses the narrowest bio term first ("Confederate States America"
    or "United States Army") because the broader terms (Civil War,
    Confederate) return hundreds of thousands of results.
    """
    if not ctx.first or not ctx.last:
        return None
    # Try Confederate-specific first; the regex would be ideal but
    # bio is full-text only. We pick the narrowest CSA-specific term.
    return {
        "firstname": ctx.first,
        "lastname": ctx.last,
        "isVeteran": "true",
        "bio": "Confederate States America",
    }


# ============================================================
# Year-filter strategies (F1: birth + death year support)
# ============================================================
# FaG search URL params:
#   birthyear=YYYY&birthyearfilter=N — N years either side
#   deathyear=YYYY&deathyearfilter=N — N years either side
#   yearfilter=N                     — applies to both when no specific year
# Where N is one of: 1, 3, 5, 10, 25 (or "exact" for exact match)


def _year_str(year) -> str:
    """Return year as a clean string, or '' if missing/zero."""
    s = str(year or "").strip()
    if not s or s == "0":
        return ""
    return s


def with_birth_year(ctx):
    """F1a: B1-style exact with birth year filter.

    When the pensioner has a birth year, this strategy combines it
    with the name search. birthyearfilter=5 gives a 5-year window.
    Reads `exact` from ctx.extras (bool, default False); when True,
    uses `birthyearfilter="exact"` for a tighter (exact-year) match.
    """
    by = _year_str(ctx.birth_year)
    if not ctx.first or not ctx.last or not by:
        return None
    exact = bool(ctx.extra("exact", False))
    params = {
        "firstname": ctx.first,
        "lastname": ctx.last,
        "exactspelling": "true",
        "birthyear": by,
        "birthyearfilter": "exact" if exact else "5",
    }
    if ctx.middle:
        params["middlename"] = ctx.middle
    return params


def with_death_year(ctx):
    """F1b: Death year filter strategy.

    Uses deathyearfilter. Default window is 5y; for veterans who
    died pre-1930 (poor records) widen to 10y.
    """
    dy = _year_str(ctx.death_year)
    if not ctx.first or not ctx.last or not dy:
        return None
    try:
        dy_int = int(dy)
    except ValueError:
        return None
    window = "10" if dy_int < 1930 else "5"
    return {
        "firstname": ctx.first,
        "lastname": ctx.last,
        "deathyear": dy,
        "deathyearfilter": window,
        "exactspelling": "true",
    }


def year_sniper(ctx):
    """F1c: Name + birth year + death year triple-filter.

    Most precise strategy: requires both years to match.
    Highly selective — only fires when we know both years.
    """
    by = _year_str(ctx.birth_year)
    dy = _year_str(ctx.death_year)
    if not ctx.first or not ctx.last or not by or not dy:
        return None
    p = {
        "firstname": ctx.first,
        "lastname": ctx.last,
        "exactspelling": "true",
        "birthyear": by,
        "birthyearfilter": "5",
        "deathyear": dy,
        "deathyearfilter": "5",
    }
    if ctx.middle:
        p["middlename"] = ctx.middle
    return p


def with_year_window(ctx):
    """F1d: Widened year window (or-accept).

    Uses both birthyearfilter and deathyearfilter at 5y. Returns
    None if neither year is available.
    """
    by = _year_str(ctx.birth_year)
    dy = _year_str(ctx.death_year)
    if not ctx.first or not ctx.last or (not by and not dy):
        return None
    p = {
        "firstname": ctx.first,
        "lastname": ctx.last,
        "fuzzyNames": "true",
    }
    if by:
        p["birthyear"] = by
        p["birthyearfilter"] = "5"
    if dy:
        p["deathyear"] = dy
        p["deathyearfilter"] = "5"
    if ctx.middle:
        p["middlename"] = ctx.middle
    return p


# ============================================================
# Positional shims (legacy)
# ============================================================
# Each takes the OLD positional signature and builds a SearchContext
# to call the new form. Kept so the old test suite and
# scripts/fag/filters.py imports keep working unchanged.


def _ctx_from_pos(first, middle, last, birth_year, death_year, **extras):
    """Build a SearchContext from positional args + extras."""
    from scripts.search.context import SearchContext
    return SearchContext(
        first=str(first or ""),
        middle=str(middle or ""),
        last=str(last or ""),
        birth_year=_year_str(birth_year),
        death_year=_year_str(death_year),
        extras=extras,
    )


def strategy_b1_exact(first, middle, last, birth_year, death_year=None):
    return b1_exact(_ctx_from_pos(first, middle, last, birth_year, death_year))


def strategy_b2_middle_initial(first, middle, last, birth_year, death_year=None):
    return b2_middle_initial(_ctx_from_pos(first, middle, last, birth_year, death_year))


def strategy_b3_first_initial_fuzzy(first, middle, last, birth_year, death_year=None):
    return b3_first_initial_fuzzy(_ctx_from_pos(first, middle, last, birth_year, death_year))


def strategy_b4_fuzzy_last(first, middle, last, birth_year, death_year=None):
    return b4_fuzzy_last(_ctx_from_pos(first, middle, last, birth_year, death_year))


def strategy_b5_apostrophe_variants(first, middle, last, birth_year, death_year=None):
    return b5_apostrophe_variants(_ctx_from_pos(first, middle, last, birth_year, death_year))


def strategy_c1_cw_context(first, middle, last, birth_year, death_year=None):
    return c1_cw_context(_ctx_from_pos(first, middle, last, birth_year, death_year))


def strategy_with_birth_year(first, middle, last, birth_year, death_year=None, exact=False):
    # The `exact` kwarg is accepted for legacy callers; we pass
    # it through to the canonical form via the context extras.
    return with_birth_year(_ctx_from_pos(
        first, middle, last, birth_year, death_year, exact=bool(exact),
    ))


def strategy_with_death_year(first, middle, last, birth_year, death_year):
    return with_death_year(_ctx_from_pos(first, middle, last, birth_year, death_year))


def strategy_year_sniper(first, middle, last, birth_year, death_year):
    return year_sniper(_ctx_from_pos(first, middle, last, birth_year, death_year))


def strategy_with_year_window(first, middle, last, birth_year, death_year):
    return with_year_window(_ctx_from_pos(first, middle, last, birth_year, death_year))


# ============================================================
# Ladder
# ============================================================
# Each entry is a FunctionStrategy wrapping the context-form
# function. External code (e.g. scripts/fag/filters.py back-compat
# shim) imports the positional functions separately.

from scripts.search.strategy import FunctionStrategy  # noqa: E402

STRATEGIES = [
    FunctionStrategy("B1-exact",               b1_exact),
    FunctionStrategy("B2-middle-initial",      b2_middle_initial),
    FunctionStrategy("B3-first-initial-fuzzy", b3_first_initial_fuzzy),
    FunctionStrategy("B4-fuzzy-last",          b4_fuzzy_last),
    FunctionStrategy("B5-apostrophe",          b5_apostrophe_variants),
    FunctionStrategy("C1-cw-context",          c1_cw_context),
    FunctionStrategy("F1a-birthyear-exact",    with_birth_year),
    FunctionStrategy("F1b-deathyear",          with_death_year),
    FunctionStrategy("F1c-year-sniper",        year_sniper),
    FunctionStrategy("F1d-year-window",        with_year_window),
]
