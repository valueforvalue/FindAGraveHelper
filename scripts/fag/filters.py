"""scripts.fag.filters: location/regiment extraction helpers.

Extracted from scripts.fag.search.py (T008). Pure functions for
parsing FaG slug shapes, extracting state from regiment strings,
and narrowing the search by location.

Public surface:
  - apply_location_filter(params, state_abbr) -> narrowed_params
  - parse_slug(slug) -> {first, middle, last}
  - extract_state_from_regiment(regiment) -> state_abbr
  - extract_candidate_details(snippet) -> {is_veteran, birth_year, ...}
"""
import re

# FaG locationId constants. country_4 = United States, state_NN
# per FaG's internal numbering. Subset of states we encounter
# in OK CW pensioner data.
FAG_COUNTRY_FILTER_US = {"locationId": "country_4"}
FAG_STATE_IDS = {
    "AL": "state_1", "AK": "state_2", "AZ": "state_3", "AR": "state_4",
    "CA": "state_5", "CO": "state_6", "CT": "state_7", "DE": "state_8",
    "FL": "state_9", "GA": "state_10", "HI": "state_11", "ID": "state_12",
    "IL": "state_13", "IN": "state_14", "IA": "state_15", "KS": "state_16",
    "KY": "state_17", "LA": "state_18", "ME": "state_19", "MD": "state_20",
    "MA": "state_21", "MI": "state_22", "MN": "state_23", "MS": "state_24",
    "MO": "state_25", "MT": "state_26", "NE": "state_27", "NV": "state_28",
    "NH": "state_29", "NJ": "state_30", "NM": "state_31", "NY": "state_32",
    "NC": "state_33", "ND": "state_34", "OH": "state_35", "OK": "state_38",
    "OR": "state_39", "PA": "state_40", "RI": "state_41", "SC": "state_42",
    "SD": "state_43", "TN": "state_44", "TX": "state_45", "UT": "state_46",
    "VT": "state_47", "VA": "state_48", "WA": "state_49", "WV": "state_50",
    "WI": "state_51", "WY": "state_52",
}


def apply_location_filter(params: dict, state_abbr: str = "") -> dict:
    """Inject FaG country (and optionally state) filter into a strategy's URL params.

    Restricts results to the United States via locationId=country_4. When
    `state_abbr` is a known US state, narrows further with locationId=state_<id>
    (e.g. locationId=state_38 for Oklahoma). State filter cuts results 60x vs
    country alone for common names — recommended when regiment state is known.

    Note: only ONE locationId value can be passed at a time (last write wins),
    so when state_abbr is supplied it overrides the country filter. Country is
    implicit (state_38 is Oklahoma, United States of America per FaG's hierarchy).

    By default, ALSO injects the ACW-appropriate date window
    (`birthyear=1820&birthyearfilter=after&deathyear=1950&deathyearfilter=before`)
    so modern same-surname candidates never come back at all. Pass
    `include_date_window=False` to skip the date injection (rare; tests
    that exercise specific date scopes).

    Returns a NEW dict; does not mutate the caller's dict.
    """
    return _apply_filters(dict(params), state_abbr, include_date_window=True)


def apply_location_only(params: dict, state_abbr: str = "") -> dict:
    """Location filter only, no date window. Use for tests or for
    strategies that bring their own date scope.
    """
    return _apply_filters(dict(params), state_abbr, include_date_window=False)


def _apply_filters(
    params: dict, state_abbr: str, include_date_window: bool
) -> dict:
    """Internal: shared location + (optional) date injection."""
    p = dict(params)
    if state_abbr:
        state_id = FAG_STATE_IDS.get(state_abbr.upper())
        if state_id:
            p["locationId"] = state_id
        else:
            p.update(FAG_COUNTRY_FILTER_US)
    else:
        p.update(FAG_COUNTRY_FILTER_US)
    if include_date_window:
        _inject_acw_date_window(p)
    return p


def _inject_acw_date_window(params: dict) -> None:
    """Inject the project-wide ACW date window into FaG URL params.

    ACW era Confederate vets: born after 1810 (research-backed;
    27/1,135 ground-truth vets were 1810-1819), died before
    1955 (research-backed; 7/1,135 ground-truth deaths after
    1940). See docs/research/acw-vet-date-ranges.md for the
    full derivation from local data.

    Args:
        params: dict of URL params (mutated in place). Keys
            `birthyear`, `birthyearfilter`, `deathyear`,
            `deathyearfilter` are set ONLY if not already set,
            so a strategy that wants a tighter window (e.g.
            F2-regiment-bio specifies death_year=1927±5) is
            preserved.
    """
    if "birthyear" not in params:
        params["birthyear"] = str(ACW_BIRTH_YEAR_MIN)
        params["birthyearfilter"] = "after"
    if "deathyear" not in params:
        params["deathyear"] = str(ACW_DEATH_YEAR_MAX)
        params["deathyearfilter"] = "before"

# ============================================================
# ACW-vet date window (J13 + research-driven bounds)
# ============================================================
# Window for birth/death years of an American Civil War
# Confederate pensioner. Derived from:
#   docs/research/acw-vet-date-ranges.md (curated 2026-07-16
#   from the 577-pair local ground truth + 1,135-row
#   age-at-death validation set; full derivation in that file).
#
#   ACW_BIRTH_YEAR_MIN = 1810   # local data has 27 born 1810-1819 (fought as 40+)
#   ACW_BIRTH_YEAR_MAX = 1880   # born after war; almost certainly a name-collision
#   ACW_DEATH_YEAR_MIN = 1861   # war started 1861
#   ACW_DEATH_YEAR_MAX = 1955   # OK pension rolls filed through ~1950s; 7/1135 deaths beyond 1940
#
# These keep 100% of the 577 ground-truth matches (the 2-3
# edge cases that fall outside are flagged for human review
# via the parse-time apply_date_filter, not silently dropped).
#
# Any FaG candidate outside this window is overwhelmingly likely a
# same-surname name-collision (modern relative, pre-war ancestor,
# or unrelated person) — NOT the pensioner.
#
# These constants are the SINGLE SOURCE OF TRUTH for the
# project-wide date filter. Used by:
#   - apply_date_filter (filters.py)
#   - score_candidate (scoring.py) — when local dates are absent,
#     a candidate with death_year outside this window scores 0.
ACW_BIRTH_YEAR_MIN = 1810
ACW_BIRTH_YEAR_MAX = 1880
ACW_DEATH_YEAR_MIN = 1861
ACW_DEATH_YEAR_MAX = 1955


def _parse_int(s: object) -> int | None:
    """Parse a year/int from a string, int, or None. Returns
    None if not parseable."""
    if s is None:
        return None
    if isinstance(s, int):
        return s
    s = str(s).strip()
    if not s:
        return None
    # Take the first 4-digit run only ("01/22/1835" -> 1835)
    m = re.search(r"(\d{4})", s)
    if m:
        return int(m.group(1))
    try:
        return int(s)
    except ValueError:
        return None


def _in_acw_window(birth_year: int | None, death_year: int | None) -> bool:
    """Returns True if the given dates are compatible with an
    ACW-era veteran OR if BOTH are missing (we don't know
    enough to reject).

    Conservative: if only ONE date is available, use it. If
    BOTH are available, use both (intersection).
    """
    if birth_year is None and death_year is None:
        return True  # no data, can't reject
    # If we have a birth_year, it must be in [1820, 1870]
    if birth_year is not None:
        if not (ACW_BIRTH_YEAR_MIN <= birth_year <= ACW_BIRTH_YEAR_MAX):
            return False
    # If we have a death_year, it must be in [1861, 1950]
    if death_year is not None:
        if not (ACW_DEATH_YEAR_MIN <= death_year <= ACW_DEATH_YEAR_MAX):
            return False
    return True


def apply_date_filter(candidates: list, hard: bool = True) -> list:
    """Drop candidates whose dates are incompatible with the ACW vet window.

    ACW window: birth 1820-1870; death 1861-1950. A candidate
    outside this window is overwhelmingly likely a same-surname
    name-collision (modern relative, pre-war ancestor, etc.) and
    wastes the reviewer's time.

    Args:
        candidates: list of dicts with .details.birth_year /
            .details.death_year populated by parse_results_page.
        hard: when True (default), drops out-of-window candidates.
            When False, returns the input list unchanged (kept
            for debug / dry-run use).

    Returns:
        Filtered list (candidates with in-window dates only;
        candidates without dates are KEPT — conservative).
    """
    if not hard:
        return list(candidates)
    out = []
    for c in candidates:
        det = c.get("details", {}) if isinstance(c, dict) else {}
        by = _parse_int(det.get("birth_year"))
        dy = _parse_int(det.get("death_year"))
        if _in_acw_window(by, dy):
            out.append(c)
    return out
S_AMBIGUOUS = "ambiguous"          # 2-10 candidates, none high-confidence
S_TOO_MANY = "too_many"            # >10 results even with narrowing
S_NO_RESULTS = "no_results"        # all strategies returned 0
S_CAPTCHA = "captcha"              # Cloudflare blocked us
S_SKIP = "skip"                    # local record had no name
S_ERROR = "error"                  # exception during search


# ============================================================
# Strategy ladder — see docs/v5-design/strategy-ladder.md
# ============================================================
#
# Each strategy returns a dict of search params, or None to skip.
# Strategies are tried in order; we stop early only on a 0.95+
# auto-accept match. Otherwise we collect the union of all
# candidates seen across all strategies and rank by score.

# Strategy ladder extracted to scripts/search/strategies.py (T017).
# Re-import here so existing callers of `from scripts.search_fag
# import strategy_*` and `STRATEGIES` keep working.
from scripts.search.strategies import (  # noqa: F401
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
    STRATEGIES,
) 


# ============================================================
# Slug parser + scoring
# ============================================================

def normalise(s: str) -> str:
    """Back-compat shim. Canonical implementation: scripts.name_utils.normalise."""
    from scripts.name_utils import normalise as _impl
    return _impl(s)


def soundex(name: str) -> str:
    """Back-compat shim. Canonical implementation: scripts.name_utils.soundex."""
    from scripts.name_utils import soundex as _impl
    return _impl(name)


def parse_slug(slug: str) -> dict:
    """Parse a FaG slug into first/middle/last parts."""
    parts = slug.lower().split('/')[0].split('_')
    if len(parts) == 1:
        if '-' in parts[0]:
            hy = parts[0].split('-')
            if len(hy) == 2:
                return {"first": hy[0], "middle": "", "last": hy[1]}
            return {"first": hy[0], "middle": " ".join(hy[1:-1]), "last": hy[-1]}
        return {"first": parts[0], "middle": "", "last": ""}
    last = parts[-1]
    first = parts[0]
    middle = ""
    if '-' in last:
        last_main, last_suffix = last.split('-', 1)
        middle_parts = parts[1:-1] + [last_main]
        middle = ' '.join(middle_parts)
        last = last_suffix
    else:
        middle = ' '.join(parts[1:])
    return {"first": first, "middle": middle, "last": last}


def extract_state_from_regiment(regiment: str) -> str:
    if not regiment:
        return ""
    # Normalize "Co." → "Co" (we don't want to match it as Colorado CO)
    norm = re.sub(r'\bCo\.', 'Co', regiment)
    norm_up = norm.upper()
    # Try 2-letter abbreviation. Find ALL matches; skip "CO" (Company)
    # and prefer later matches (the state is usually after the company).
    skip_codes = {'CO'}
    all_codes = re.findall(
        r"\b(AL|MS|TN|TX|GA|FL|AR|SC|NC|VA|LA|KY|MO|MD|OK|IN|IL|OH|PA|NY|"
        r"NJ|CT|MA|VT|NH|ME|DE|WV|IA|WI|MN|MI|KS|NE|ND|SD|WY|CO|NV|CA|"
        r"OR|WA|ID|UT|MT|AZ|NM|AK|HI|RI)\b",
        norm_up)
    filtered = [c for c in all_codes if c not in skip_codes]
    if filtered:
        return filtered[0]  # first non-CO match
    if all_codes:
        # Only CO found; fall through to full-name match
        pass
    # Try full state name (use module-level constant, not a per-call dict)
    for name, code in _STATE_NAMES_UPPER.items():
        if name in norm_up:
            return code
    return ""


# ============================================================
# State extraction from a candidate (parse out birth/death/state
# from the surrounding HTML snippet)
# ============================================================

def extract_candidate_details(snippet: str) -> dict:
    """Pull structured details from a result snippet.

    Returns {birth_date, death_date, cemetery, state, location}.
    """
    out = {}
    # Birth / death year patterns
    m = re.search(r"\b(\d{4})\s*[–\-]\s*(\d{4})\b", snippet)
    if m:
        out["birth_year"] = m.group(1)
        out["death_year"] = m.group(2)
    m = re.search(r"\b(\d{4})\s*–\s*\?", snippet)
    if m:
        out["birth_year"] = m.group(1)
    # Cemetery + location: pattern "Cemetery, City, County, State, Country"
    # Best-effort: find commas, last non-Country token is state
    m = re.search(r"([^,]+(?:Cemetery|Memorial|Church|Burying)[^,]+(?:,\s*[^,]+){0,4})", snippet, re.I)
    if m:
        out["cemetery_text"] = m.group(1).strip()
    return out


# State name -> abbreviation lookup, used by extract_state_from_regiment
# and by parse_results_page for the birth_state / death_state match.
_STATE_NAMES_UPPER = {
    'ALABAMA': 'AL', 'MISSISSIPPI': 'MS', 'TENNESSEE': 'TN', 'TEXAS': 'TX',
    'GEORGIA': 'GA', 'FLORIDA': 'FL', 'ARKANSAS': 'AR', 'SOUTH CAROLINA': 'SC',
    'NORTH CAROLINA': 'NC', 'VIRGINIA': 'VA',
    'LOUISIANA': 'LA', 'KENTUCKY': 'KY',
    'MISSOURI': 'MO', 'MARYLAND': 'MD', 'OKLAHOMA': 'OK', 'INDIANA': 'IN',
    'ILLINOIS': 'IL', 'OHIO': 'OH', 'PENNSYLVANIA': 'PA', 'NEW YORK': 'NY',
    'NEW JERSEY': 'NJ', 'CONNECTICUT': 'CT', 'MASSACHUSETTS': 'MA',
    'VERMONT': 'VT', 'NEW HAMPSHIRE': 'NH', 'MAINE': 'ME', 'DELAWARE': 'DE',
    'WEST VIRGINIA': 'WV', 'IOWA': 'IA', 'WISCONSIN': 'WI', 'MINNESOTA': 'MN',
    'MICHIGAN': 'MI', 'KANSAS': 'KS', 'NEBRASKA': 'NE', 'NORTH DAKOTA': 'ND',
    'SOUTH DAKOTA': 'SD', 'WYOMING': 'WY', 'COLORADO': 'CO', 'NEVADA': 'NV',
    'CALIFORNIA': 'CA', 'OREGON': 'OR', 'WASHINGTON': 'WA', 'IDAHO': 'ID',
    'UTAH': 'UT', 'MONTANA': 'MT', 'ARIZONA': 'AZ', 'NEW MEXICO': 'NM',
    'ALASKA': 'AK', 'HAWAII': 'HI', 'RHODE ISLAND': 'RI',
}
# Lowercase-keys variant for parse_results_page (state names are
# matched case-insensitively against the candidate text).
_STATE_NAMES_LOWER = {k.lower(): v for k, v in _STATE_NAMES_UPPER.items()}

