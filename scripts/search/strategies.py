"""FaG search-strategy ladder (T017 split).

The 10 strategy functions extracted verbatim from search_fag.py.
Each takes primitives (first/middle/last/birth_year/death_year)
and returns either:

  - a dict of FaG search-URL params, OR
  - None when the strategy is not applicable for these inputs.

The ladder is `STRATEGIES` — an ordered list of (label, fn)
tuples. The runner tries each in order; the first to return
a dict is used.

These are pure functions with no shared state.
"""
from __future__ import annotations

__all__ = [
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
    "STRATEGIES",
]


def strategy_b1_exact(first, middle, last, birth_year, death_year=None):
    """B1: exact sniper. first + middlename + last + exactspelling."""
    if not first or not last:
        return None
    p = {"firstname": first, "lastname": last, "exactspelling": "true"}
    if middle:
        p["middlename"] = middle
    if birth_year:
        p["birthyear"] = str(birth_year)
        p["birthyearfilter"] = "1"
    return p


def strategy_b2_middle_initial(first, middle, last, birth_year, death_year=None):
    """B2: middlename-initial. Only if middle is a single letter."""
    if not middle or len(middle) > 1 or not first or not last:
        return None
    return {
        "firstname": first,
        "middlename": middle,
        "lastname": last,
        "exactspelling": "true",
    }


def strategy_b3_first_initial_fuzzy(first, middle, last, birth_year, death_year=None):
    """B3: first-initial + fuzzy last + middlename."""
    if not first or not last:
        return None
    first_initial = first[0]
    return {
        "firstname": f"{first_initial}*",
        "lastname": last,
        "fuzzyNames": "true",
        "birthyearfilter": "5",
    }


def strategy_b4_fuzzy_last(first, middle, last, birth_year, death_year=None):
    """B4: fuzzy last only + middlename."""
    if not last:
        return None
    p = {"lastname": last, "fuzzyNames": "true", "birthyearfilter": "5"}
    if middle:
        p["middlename"] = middle
    return p


def strategy_b5_apostrophe_variants(first, middle, last, birth_year, death_year=None):
    """B5: apostrophe variants. Only if last contains apostrophe."""
    if not last or "'" not in last:
        return None
    if not first:
        return None
    # Drop the apostrophe
    return {
        "firstname": first,
        "lastname": last.replace("'", ""),
        "fuzzyNames": "true",
    }


def strategy_c1_cw_context(first, middle, last, birth_year, death_year=None):
    """C1: civil war bio context catch-all.

    Uses the narrowest bio term first ("Confederate States America"
    or "United States Army") because the broader terms (Civil War,
    Confederate) return hundreds of thousands of results.
    """
    if not first or not last:
        return None
    # Try Confederate-specific first; the regex would be ideal but
    # bio is full-text only. We pick the narrowest CSA-specific term.
    return {
        "firstname": first,
        "lastname": last,
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


def strategy_with_birth_year(first, middle, last, birth_year, exact=False):
    """F1a: B1-style exact with birth year filter.

    When the pensioner has a birth year, this strategy combines it
    with the name search. birthyearfilter=5 gives a 5-year window;
    use exact=True for tighter (exact birth year required).
    """
    by = _year_str(birth_year)
    if not first or not last or not by:
        return None
    params = {
        "firstname": first,
        "lastname": last,
        "exactspelling": "true",
        "birthyear": by,
        "birthyearfilter": "exact" if exact else "5",
    }
    if middle:
        params["middlename"] = middle
    return params


def strategy_with_death_year(first, middle, last, birth_year, death_year):
    """F1b: Death year filter strategy.

    Uses deathyearfilter. Default window is 5y; for veterans who
    died pre-1930 (poor records) widen to 10y.
    """
    dy = _year_str(death_year)
    if not first or not last or not dy:
        return None
    try:
        dy_int = int(dy)
    except ValueError:
        return None
    window = "10" if dy_int < 1930 else "5"
    return {
        "firstname": first,
        "lastname": last,
        "deathyear": dy,
        "deathyearfilter": window,
        "exactspelling": "true",
    }


def strategy_year_sniper(first, middle, last, birth_year, death_year):
    """F1c: Name + birth year + death year triple-filter.

    Most precise strategy: requires both years to match.
    Highly selective — only fires when we know both years.
    """
    by = _year_str(birth_year)
    dy = _year_str(death_year)
    if not first or not last or not by or not dy:
        return None
    p = {
        "firstname": first,
        "lastname": last,
        "exactspelling": "true",
        "birthyear": by,
        "birthyearfilter": "5",
        "deathyear": dy,
        "deathyearfilter": "5",
    }
    if middle:
        p["middlename"] = middle
    return p


def strategy_with_year_window(first, middle, last, birth_year, death_year):
    """F1d: Widened year window (or-accept).

    Uses both birthyearfilter and deathyearfilter at 5y. Returns
    None if neither year is available.
    """
    by = _year_str(birth_year)
    dy = _year_str(death_year)
    if not first or not last or (not by and not dy):
        return None
    p = {
        "firstname": first,
        "lastname": last,
        "fuzzyNames": "true",
    }
    if by:
        p["birthyear"] = by
        p["birthyearfilter"] = "5"
    if dy:
        p["deathyear"] = dy
        p["deathyearfilter"] = "5"
    if middle:
        p["middlename"] = middle
    return p


STRATEGIES = [
    ("B1-exact",              strategy_b1_exact),
    ("B2-middle-initial",     strategy_b2_middle_initial),
    ("B3-first-initial-fuzzy", strategy_b3_first_initial_fuzzy),
    ("B4-fuzzy-last",         strategy_b4_fuzzy_last),
    ("B5-apostrophe",         strategy_b5_apostrophe_variants),
    ("C1-cw-context",         strategy_c1_cw_context),
    ("F1a-birthyear-exact",   strategy_with_birth_year),
    ("F1b-deathyear",         strategy_with_death_year),
    ("F1c-year-sniper",       strategy_year_sniper),
    ("F1d-year-window",       strategy_with_year_window),
]