"""scripts.fag.scoring: FaG candidate scoring + _found_by tagging.

Extracted from scripts.fag.search.py (T008). Pure functions (no
Playwright/browser dependencies).

Public surface:
  - score_candidate(local, candidate) -> (score, breakdown)
  - tag_candidates_with_found_by(candidates) -> None (in-place)
"""
import re
from typing import Any
from scripts.fag.filters import (
    parse_slug,
    normalise,
    soundex,
    ACW_BIRTH_YEAR_MIN,
    ACW_BIRTH_YEAR_MAX,
    ACW_DEATH_YEAR_MIN,
    ACW_DEATH_YEAR_MAX,
)

# Issue #108: detect maiden-name inclusion in candidate name.
# A widow candidate like "Lucy Ann Ham Gwinn" has 3+ name tokens
# (first Ann Ham + last Gwinn). The extra token (Ham) is the
# maiden name - strong evidence of a widow match.
_DATE_PATTERN_RE = re.compile(r'\b\d{4}\b')
# Month names and ordinal days that appear in FaG name strings.
_MONTH_NAMES = frozenset([
    'jan', 'feb', 'mar', 'apr', 'may', 'jun',
    'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
])
_NOISE_TOKENS = frozenset([
    'no', 'grave', 'photo', 'honoring', 'memory',
    'v', 'veteran', 'sgt', 'pvt', 'cpl', 'capt', 'sr', 'jr',
])


def _count_name_tokens(name: str) -> int:
    """Count significant name tokens in a candidate name string.

    Strips date runs, VETERAN markers, rank prefixes, month/day
    words, and photo-caption noise before counting. A widow with
    a maiden name like "Lucy Ann Ham Gwinn" should have >= 3
    tokens (Lucy + Ham + Gwinn, with Ann as middle that may or
    may not count).
    """
    if not name:
        return 0
    lower = name.lower()
    # Remove four-digit years
    cleaned = _DATE_PATTERN_RE.sub(' ', lower)
    # Remove standalone 1-2 digit day numbers (but not initials)
    cleaned = re.sub(r'\b\d{1,2}\b', ' ', cleaned)
    # Remove special chars
    cleaned = cleaned.replace('-', ' ').replace(chr(0x2013), ' ')
    cleaned = cleaned.replace('.', ' ')
    # Tokenize
    tokens = cleaned.split()
    # Filter noise
    name_tokens = [
        t for t in tokens
        if len(t) > 1
        and t not in _MONTH_NAMES
        and t not in _NOISE_TOKENS
    ]
    return len(name_tokens)


def score_candidate(local: dict, candidate: dict) -> tuple[float, dict]:
    """Score how likely a FaG candidate matches the local record.

    Returns (score, breakdown) where breakdown is a dict of feature scores.
    """
    local_first = local.get("first_name", "")
    local_middle = local.get("middle_name", "")
    local_last = local.get("last_name", "")
    local_state = (local.get("_state_abbr") or "").upper()
    is_widow = bool(local.get("_is_widow", False))

    slug_parts = parse_slug(candidate.get("slug", ""))

    # Last name match (highest weight — most reliable in FaG)
    local_last_n = normalise(local_last)
    slug_last_n = normalise(slug_parts["last"])
    last_eq = local_last_n == slug_last_n
    last_phon = soundex(local_last) == soundex(slug_parts["last"]) if slug_last_n else False
    last_partial = bool(local_last_n) and bool(slug_last_n) and (
        local_last_n.startswith(slug_last_n) or slug_last_n.startswith(local_last_n)
    )
    if last_eq:
        last_score = 1.0
    elif last_partial:
        last_score = 0.7
    elif last_phon:
        last_score = 0.5
    else:
        last_score = 0.0

    # First name match
    local_first_n = normalise(local_first)
    slug_first_n = normalise(slug_parts["first"])
    first_eq = local_first_n == slug_first_n
    first_phon = soundex(local_first) == soundex(slug_parts["first"]) if slug_first_n else False
    first_initial_match = bool(local_first_n) and bool(slug_first_n) and local_first_n[0] == slug_first_n[0]
    if first_eq:
        first_score = 1.0
    elif first_initial_match:
        first_score = 0.6
        # Issue: initial match V↔Virginia or B↔Mary is too
        # generous when candidate is clearly male and pensioner
        # is a widow (female). Halve first_score for cross-gender
        # initial matches.
        from scripts.fag.filters import _MALE_VETERAN_FIRST_NAMES
        if is_widow and slug_first_n in _MALE_VETERAN_FIRST_NAMES:
            first_score = 0.3
    elif first_phon:
        first_score = 0.4
    else:
        first_score = 0.0

    # Middle name match
    middle_score = 0.0
    local_middle_n = normalise(local_middle)
    slug_middle_n = normalise(slug_parts["middle"])
    if local_middle_n and slug_middle_n:
        if local_middle_n == slug_middle_n:
            middle_score = 1.0
        elif local_middle_n[0] == slug_middle_n[0]:
            middle_score = 0.5
    elif not local_middle_n:
        # No middle on local — we don't penalize
        middle_score = 0.5

    # OK burial boost — informational, NOT required.
    # All pensioners in this index lived in OK (proof of residency
    # required). But burial state could be anywhere — many veterans
    # were buried where they died, which may or may not be OK.
    # We don't REQUIRE OK burial to declare a match; it's just a
    # tiebreaker when names collide (e.g. "Robert Goad" in OK vs
    # "Robert Goad" in MD). Gives a small bonus; not penalizing
    # non-OK burial because the project cares about OK connection,
    # not specifically OK burial.
    ok_burial_score = 0.0
    cand_state = candidate.get("details", {}).get("state")
    if cand_state and cand_state.upper() == "OK":
        ok_burial_score = 0.3  # smaller bonus; was 0.5

    # State match — tiebreaker when local regiment state's abbreviation
    # matches the candidate's burial state (rare, but useful).
    state_score = 0.0
    if local_state and cand_state and local_state.upper() == cand_state.upper():
        state_score = 0.1  # smaller bonus; was 0.2

    # Veteran flag (CW pensioners were veterans — strong signal!)
    # Widows: the veteran connection is implicit in the pension record
    # itself. Give a moderate bonus that the candidate belongs to a CW
    # pensioner family, lower than veteran because the candidate IS the
    # widow, not the vet (issue #105).
    widow_pension_score = 0.0
    if is_widow:
        # Scale by first-name confidence — a widow candidate
        # with wrong first name (e.g. Victor for Virginia)
        # should not get full pension-family credit.
        widow_pension_score = 0.5 * first_score
        veteran_score = 0.0  # widow's memorial won't have veteran flag
    else:
        is_vet = candidate.get("details", {}).get("is_veteran", False)
        veteran_score = 0.8 if is_vet else 0.0

    # Death-year match (strong signal when local death_year is known)
    death_score = 0.0
    local_dy = str(local.get("_death_year", "")).strip()
    cand_dy = candidate.get("details", {}).get("death_year", "")
    cand_by = candidate.get("details", {}).get("birth_year", "")

    # J13 / issue #104 / issue #105: impossible-date soft gate.
    # A candidate whose dates are outside the ACW window (born after
    # 1880 or died after 1955) is overwhelmingly a same-surname modern
    # person. Instead of hard-scoring 0.0 (which crowded real
    # low-signal matches), apply a heavy penalty to the name-match
    # score so the candidate still sorts meaningfully below in-window
    # entries but above true parser noise.
    # Issue #105: for widows, the window widens (birth up to 1920,
    # death up to 1980) because the candidate IS the widow, not the
    # veteran.
    from scripts.fag.filters import _in_acw_window, _parse_int
    cand_by_i = _parse_int(cand_by)
    cand_dy_i = _parse_int(cand_dy)
    date_penalty = 0.0
    if not _in_acw_window(cand_by_i, cand_dy_i, is_widow=is_widow):
        date_penalty = 1.0

    if local_dy and cand_dy:
        try:
            d_local = int(local_dy)
            d_cand = int(cand_dy)
            diff = abs(d_local - d_cand)
            if diff == 0:
                death_score = 0.5
            elif diff <= 2:
                death_score = 0.4
            elif diff <= 5:
                death_score = 0.2
        except (ValueError, TypeError):
            pass
    elif is_widow and cand_dy:
        # Issue #105: widow pensioner has no death_year on
        # record (alive when she applied), but the candidate
        # does. If the candidate's death_year falls in the
        # CW-widow era, give a moderate "plausible era" signal.
        # This is NOT as strong as an exact death_year match;
        # it just says "this person lived in the right timeframe
        # to be a Confederate veteran's widow."
        dy_i = _parse_int(cand_dy)
        if dy_i is not None:
            from scripts.fag.filters import (
                ACW_DEATH_YEAR_MIN,
                WIDOW_DEATH_YEAR_MAX,
            )
            if ACW_DEATH_YEAR_MIN <= dy_i <= WIDOW_DEATH_YEAR_MAX:
                death_score = 0.3

    # Issue #108: maiden-name pattern for widow candidates.
    # When a widow's FaG memorial includes her maiden name
    # (e.g. "Lucy Ann Ham Gwinn" where Ham is maiden, Gwinn is
    # married), the candidate has 3+ name tokens and the last
    # name matches the pensioner's married name. This is strong
    # evidence of a correct widow match — the widow kept her
    # married name on her headstone and the memorial includes
    # her birth family name.
    maiden_name_score = 0.0
    if is_widow and last_score > 0 and first_score >= 0.6:
        name_tokens = _count_name_tokens(candidate.get("name", ""))
        if name_tokens >= 3:
            maiden_name_score = 1.0  # binary: name structure suggests maiden name

    # Weights (rebalanced for "OK-connected, burial-agnostic" search):
    # - last/first/middle: name match dominates (0.62 max)
    # - death year: confirms correct person (0.5 max) — bumped up
    # - veteran: strong tiebreaker (0.4 max)
    # - widow_pension: moderate pension-family signal (0.25 max, issue #105)
    # - OK burial: smaller bonus (0.3 max, was 0.5)
    # - state match: minor (0.1 max, was 0.2)
    #
    # A perfect name+veteran+death match = 1.00 (the right person)
    # Without death year (some records lack it): 0.62 name + 0.4 vet = 1.02 → 0.78
    # Without veteran flag: name + death = 0.92 → still strong
    # Widow with name+death(pension-era)+widow_pension = 0.77 → strong widow match
    # With OK burial bonus: +0.10, helps break ties among same-name people
    score = (
        0.22 * last_score +
        0.17 * first_score +
        0.11 * middle_score +
        0.10 * ok_burial_score +
        0.05 * state_score +
        0.18 * (veteran_score if not is_widow else 0.0) +
        0.18 * widow_pension_score +
        0.22 * death_score +
        0.12 * maiden_name_score
    )

    # Issue #104: soft date gate. When candidate dates are outside
    # the ACW window, multiply the score by a heavy penalty instead
    # of returning 0.0, so the candidate still appears in order
    # below real matches but above parser noise (caption entries
    # with score 0).
    _DATE_PENALTY_FACTOR = 0.3
    if date_penalty:
        score *= _DATE_PENALTY_FACTOR

    breakdown: dict[str, Any] = {
        "last": round(last_score, 2),
        "first": round(first_score, 2),
        "middle": round(middle_score, 2),
        "ok_burial": round(ok_burial_score, 2),
        "state": round(state_score, 2),
        "veteran": round(veteran_score, 2),
        "death": round(death_score, 2),
    }
    if is_widow:
        breakdown["widow_pension"] = round(widow_pension_score, 2)
    if maiden_name_score:
        breakdown["maiden_name"] = 1.0
    if date_penalty:
        breakdown["_date_penalty"] = 1.0  # sentinel: score reduced by soft gate
    return score, breakdown


# ============================================================
# FaG result-page parser
# ============================================================
#
# FaG renders the result list client-side. The HTML uses relative
# URLs (`/memorial/<id>/<slug>`), not absolute. We pull the parsed
# text of each link via the DOM (Playwright locator), which gives us
# the name + flags + dates all in one text blob.

# Match both absolute and relative URL forms
RESULT_LINK_RE = re.compile(
    r'href=["\'](?:https?://www\.findagrave\.com)?/memorial/(\d+)/([^/?\"\'#]+)',
    re.I
)


# ============================================================
# State name lookup tables (module-level constants)
# ============================================================
# Previously these dicts were recreated on every call to
# extract_state_from_regiment() (50 names x ~2000 calls = 100K
# transient dicts) and parse_results_page() (50 names x ~10K
# calls = 500K transient dicts). Allocating+throwing away that
# many dicts leaked MB of Python heap per minute: CPython's pymalloc
# freelist never returned the pages to the OS. Hoisting both
# lookups to module level fixes that path.

# A simpler compiled regex used inside parse_results_page where the
# href attribute is the relative /memorial/<id>/<slug> form (we strip
# the `href=...` prefix in get_attribute). The full RESULT_LINK_RE
# above expects an `href="..."` wrapper which we don't get here.
_MEMORIAL_PATH_RE = re.compile(
    r'(?:^|[\"\'])'  # leading boundary or quote char
    r'((?:https?://www\.findagrave\.com)?/memorial/(\d+)/([^/?\"\'#]+))',
    re.I,
)

# Death-year pattern (en dash or hyphen): "1890 – 9 Apr 1917" or "1890 - 1917"
DATE_RANGE_RE = re.compile(r"(\d{4})\s*[–\-]\s*(\d{4})")
SINGLE_DATE_RE = re.compile(r"\b(\d{4})\b")
# Cemetery / location pattern
CEMETERY_RE = re.compile(
    r"([A-Z][^<>\n]{2,40}?\s+(?:Cemetery|Memorial Cemetery|Burying Ground|"
    r"Cemetery|Church Cemetery|Memorial Park|National Cemetery|"
    r"City Cemetery|Memorial Gardens|Mausoleum))\s*[,]?\s*"
    r"([A-Z][^<>\n,]{2,40})?",
    re.I
)


def tag_candidates_with_found_by(
    candidates: list[dict], strategy: str, params: dict
) -> list[dict]:
    """Add a _found_by field to each candidate.

    Returns a NEW list of new dicts (does not mutate inputs). Each
    output dict has the original fields plus:
      _found_by: {strategy: str, params: dict}

    The _found_by field is what the HTML viewer renders next to each
    backlink so the reviewer can see "this candidate was found by
    strategy B1-exact with params {firstname=John&lastname=Smith}".
    """
    out = []
    for c in candidates:
        new_c = dict(c)
        new_c["_found_by"] = {"strategy": strategy, "params": dict(params or {})}
        out.append(new_c)
    return out
