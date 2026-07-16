"""scripts.fag.scoring: FaG candidate scoring + _found_by tagging.

Extracted from scripts.fag.search.py (T008). Pure functions (no
Playwright/browser dependencies).

Public surface:
  - score_candidate(local, candidate) -> (score, breakdown)
  - tag_candidates_with_found_by(candidates) -> None (in-place)
"""
import re
from scripts.fag.filters import parse_slug


def score_candidate(local: dict, candidate: dict) -> tuple[float, dict]:
    """Score how likely a FaG candidate matches the local record.

    Returns (score, breakdown) where breakdown is a dict of feature scores.
    """
    local_first = local.get("first_name", "")
    local_middle = local.get("middle_name", "")
    local_last = local.get("last_name", "")
    local_state = (local.get("_state_abbr") or "").upper()

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
    is_veteran = candidate.get("details", {}).get("is_veteran", False)
    # When veteran flag fires AND we have CW context, this is very
    # strong evidence. Higher score than "any random vet" would get.
    veteran_score = 0.8 if is_veteran else 0.0

    # Death-year match (strong signal when local death_year is known)
    death_score = 0.0
    local_dy = str(local.get("_death_year", "")).strip()
    cand_dy = candidate.get("details", {}).get("death_year", "")
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

    # Weights (rebalanced for "OK-connected, burial-agnostic" search):
    # - last/first/middle: name match dominates (0.62 max)
    # - death year: confirms correct person (0.5 max) — bumped up
    # - veteran: strong tiebreaker (0.4 max)
    # - OK burial: smaller bonus (0.3 max, was 0.5)
    # - state match: minor (0.1 max, was 0.2)
    #
    # A perfect name+veteran+death match = 1.00 (the right person)
    # Without death year (some records lack it): 0.62 name + 0.4 vet = 1.02 → 0.78
    # Without veteran flag: name + death = 0.92 → still strong
    # With OK burial bonus: +0.06, helps break ties among same-name people
    score = (
        0.22 * last_score +
        0.17 * first_score +
        0.11 * middle_score +
        0.10 * ok_burial_score +
        0.05 * state_score +
        0.18 * veteran_score +
        0.22 * death_score
    )

    breakdown = {
        "last": round(last_score, 2),
        "first": round(first_score, 2),
        "middle": round(middle_score, 2),
        "ok_burial": round(ok_burial_score, 2),
        "state": round(state_score, 2),
        "veteran": round(veteran_score, 2),
        "death": round(death_score, 2),
    }
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
