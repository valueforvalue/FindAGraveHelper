#!/usr/bin/env python3
"""Batch Find a Grave searcher for OK Confederate pensioners.

Loads the unified OK Confederate pensioner list, iterates each
record, applies the v5 strategy ladder, parses FaG search results,
scores candidates, and writes a state file (one JSON line per
pensioner). The output state is designed to be reviewed in the
companion HTML viewer (scripts/view.html).

Each output record contains:
  - pensioner_id, name, regiment
  - status: auto_accept | ambiguous | no_results | too_many | captcha | skip | error
  - ranked_candidates: top 20 FaG candidates seen, each with
      memorial_id, slug, name, score, score_breakdown,
      details (is_veteran, birth_year, death_year),
      backlink, iiif_url
  - decision: null (filled in by human via view.html)
  - ground_truth: optional, set when --ground-truth-csv is used.
    Records whether the expected memorial_id/slug was found in the
    candidate list, and at what rank.

Prerequisites:
  pip install playwright playwright-stealth
  playwright install chromium

Usage:
  # First time: from local file
  python scripts/search_fag.py \\
      --input docs/research/digitalprairie/unified.json \\
      --state out/search_state.jsonl

  # From raw GitHub
  python scripts/search_fag.py \\
      --input-url https://raw.githubusercontent.com/valueforvalue/FindAGraveHelper/master/docs/research/digitalprairie/unified.json \\
      --state out/search_state.jsonl

  # Test on a few records first
  python scripts/search_fag.py \\
      --input docs/research/digitalprairie/unified.json \\
      --state out/test_state.jsonl --limit 20

Notes:
  - Must be run with a VISIBLE browser window (headless=False) on
    Windows because Cloudflare Turnstile blocks headless Chromium.
  - 1.5s throttle between requests; 30s backoff on CAPTCHA.
  - Resume-safe: re-running skips already-processed pensioners.
  - State file is one JSON record per line (JSONL). Easy to grep,
    version-control, parse.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# Allow imports from this script's directory when run as a script.
sys.path.insert(0, str(Path(__file__).parent))
from checkpoint import write_checkpoint, read_checkpoint, record_failure  # noqa: E402
from urllib.parse import urlencode
from regiment_keyword import strategy_regiment_bio, extract_regiment_phrases  # noqa: E402
from nickname_match import strategy_with_nickname, nickname_candidates  # noqa: E402

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from playwright.sync_api import TimeoutError as PWTimeout

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("search")

# ============================================================
# Tunables
# ============================================================
# Auto-accept when score is high. With our scoring function, exact
# last+first+middle + veteran + death + state all match → 0.80.
# When local state is known AND candidate state matches, we get
# 0.80; when it doesn't, we cap at 0.735. So 0.75 is a reasonable
# threshold: at or above this, we're confident the top candidate
# is the right person.
AUTO_ACCEPT_THRESHOLD = 0.70  # name+veteran+death match is sufficient
# When local has no death year, the max achievable score is lower
# (~0.64 = name match + veteran flag). Use a lower threshold for those.
AUTO_ACCEPT_THRESHOLD_NO_DEATH = 0.60
AUTO_ACCEPT_GAP = 0.10  # top must beat #2 by this much for auto-accept
PROMPT_THRESHOLD = 0.60
THROTTLE_SECONDS = 1.5
CAPTCHA_BACKOFF_SECONDS = 30.0
MAX_CANDIDATES_PER_PENSIONER = 20
MAX_FAG_RESULTS_TO_PARSE = 20  # per strategy

BASE_URL = "https://www.findagrave.com/memorial/search"

# Status values
S_AUTO_ACCEPT = "auto_accept"
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


# ============================================================
# Slug parser + scoring
# ============================================================

def normalise(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def soundex(name: str) -> str:
    name = normalise(name)
    if not name:
        return ""
    code = name[0].upper()
    mapping = {"BFPV": "1", "CGJKQSXZ": "2", "DT": "3", "L": "4", "MN": "5", "R": "6"}
    for c in name[1:]:
        for k, v in mapping.items():
            if c in k:
                if code[-1] != v:
                    code += v
                break
    code = code[0] + ''.join(c for c in code[1:] if not c.isalpha())
    return code.ljust(4, '0')[:4]


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
    # Try full state name
    state_names = {
        'ALABAMA': 'AL', 'MISSISSIPPI': 'MS', 'TENNESSEE': 'TN', 'TEXAS': 'TX',
        'GEORGIA': 'GA', 'FLORIDA': 'FL', 'ARKANSAS': 'AR', 'SOUTH CAROLINA': 'SC',
        'NORTH CAROLINA': 'NC', 'VIRGINIA': 'VA', 'LOUISIANA': 'LA', 'KENTUCKY': 'KY',
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
    for name, code in state_names.items():
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


def parse_results_page(page: Page) -> tuple[int, list[dict]]:
    """Parse the search results page.

    Returns (total_count, list_of_candidate_dicts).
    Each candidate has: memorial_id, slug, name, snippet, details,
    is_veteran, dates, cemetery.
    """
    # Wait for at least one result link to appear (the result list is
    # client-rendered after a few hundred ms).
    try:
        page.wait_for_selector('a[href*="/memorial/"]', timeout=15000)
    except PWTimeout:
        pass

    body = page.inner_text("body", timeout=10000)
    m = re.search(r"(\d[\d,]*)\s+matching records?", body)
    total = int(m.group(1).replace(",", "")) if m else 0

    # Pull per-result details from the DOM (richer than HTML regex)
    candidates = []
    seen = set()
    try:
        link_locators = page.locator('a[href*="/memorial/"]').all()
    except Exception as e:
        log.warning("Locator query failed: %s", e)
        link_locators = []

    for link in link_locators:
        try:
            href = link.get_attribute("href") or ""
        except Exception:
            continue
        m = re.search(r'/memorial/(\d+)/([^/?\#]+)', href)
        if not m:
            continue
        mem_id, slug = m.group(1), m.group(2)
        if mem_id in seen:
            continue
        seen.add(mem_id)

        try:
            text = link.inner_text(timeout=2000)
        except Exception:
            text = ""
        text = re.sub(r'\s+', ' ', text).strip()

        # Parse out name (first line of text), dates, veteran flag
        lines = [l.strip() for l in text.split('\n') if l.strip()] if text else []
        # If inner_text gave us one long string, split heuristically
        if not lines and text:
            lines = [text]

        # The name is the first line; subsequent lines are flags/dates
        name_display = lines[0] if lines else slug.replace('-', ' ').title()
        # Strip the "V Veteran" marker from the name
        name_display = re.sub(r'\s*V\s*Veteran\s*$', '', name_display, flags=re.I)
        name_display = name_display.strip()
        if not name_display:
            name_display = slug.replace('-', ' ').title()

        is_veteran = bool(
            'VETERAN' in text
            or 'CSA' in text
            or 'C.S.A.' in text
            or 'Civil War' in text
            or 'Confederate' in text
            or 'United States Army' in text
        )
        # Birth / death year. Patterns we see:
        #   "1922 – 1922"           (years only, both)
        #   "1890 – 9 Apr 1917"      (year, then full date)
        #   "21 Oct 1900 – 21 Dec 1956"  (full date, full date)
        #   "unknown – 9 Apr 1917"   (unknown year, then date)
        #   "unknown – unknown"      (both unknown)
        birth_year = None
        death_year = None
        # First, find the date range (whatever's between the en/em dash and a year)
        dm = DATE_RANGE_RE.search(text)
        if dm:
            # The pattern only captures \d{4} on each side; the left one is
            # always the birth year (or the year before the dash)
            birth_year = dm.group(1)
            death_year = dm.group(2)
        else:
            # Single date after a dash
            sm = re.search(r'[–\-]\s*(?:\d{1,2}\s+\w+\s+)?(\d{4})', text)
            if sm:
                death_year = sm.group(1)
            sm2 = re.search(r'(\d{4})\s*[–\-]', text)
            if sm2 and not birth_year:
                birth_year = sm2.group(1)

        # Grab the full result card (2 levels up — enough for cemetery +
        # location, not so far that we capture other results on the page).
        try:
            card_text = link.evaluate('''el => {
                let cur = el;
                for (let i = 0; i < 2; i++) {
                    if (cur.parentElement) cur = cur.parentElement;
                }
                return cur.innerText;
            }''')
        except Exception:
            card_text = ""
        card_text = re.sub(r'\s+', ' ', card_text).strip()

        # Extract state from the card text. Location is rendered like:
        #   "Eolian, Stephens County, Texas"  (one entry)
        #   or "Battle Creek Cemetery Eolian, Stephens County, Texas"
        # After whitespace normalization, commas may or may not be present
        # between city and county. Use a state-name lookup that works in
        # both cases: find a state name or 2-letter code anywhere in the
        # card text, prioritizing the LAST match (state is always last).
        cand_state = None
        state_names = {
            'alabama': 'AL', 'mississippi': 'MS', 'tennessee': 'TN', 'texas': 'TX',
            'georgia': 'GA', 'florida': 'FL', 'arkansas': 'AR', 'south carolina': 'SC',
            'north carolina': 'NC', 'virginia': 'VA', 'louisiana': 'LA', 'kentucky': 'KY',
            'missouri': 'MO', 'maryland': 'MD', 'oklahoma': 'OK', 'indiana': 'IN',
            'illinois': 'IL', 'ohio': 'OH', 'pennsylvania': 'PA', 'new york': 'NY',
            'new jersey': 'NJ', 'connecticut': 'CT', 'massachusetts': 'MA',
            'vermont': 'VT', 'new hampshire': 'NH', 'maine': 'ME', 'delaware': 'DE',
            'west virginia': 'WV', 'iowa': 'IA', 'wisconsin': 'WI', 'minnesota': 'MN',
            'michigan': 'MI', 'kansas': 'KS', 'nebraska': 'NE', 'north dakota': 'ND',
            'south dakota': 'SD', 'wyoming': 'WY', 'colorado': 'CO', 'nevada': 'NV',
            'california': 'CA', 'oregon': 'OR', 'washington': 'WA', 'idaho': 'ID',
            'utah': 'UT', 'montana': 'MT', 'arizona': 'AZ', 'new mexico': 'NM',
            'alaska': 'AK', 'hawaii': 'HI', 'rhode island': 'RI',
        }
        # First try comma-separated tokens (works for "City, County, State")
        for tok in reversed(re.split(r',\s*', card_text)):
            tok_clean = tok.strip().rstrip('.').lower()
            if tok_clean in state_names:
                cand_state = state_names[tok_clean]
                break
            if re.fullmatch(r'[A-Z]{2}', tok.strip()) and len(tok.strip()) == 2:
                cand_state = tok.strip()
                break
        # Fallback: scan the whole text for state names (handles
        # whitespace-collapsed "Stephens County Texas")
        if not cand_state:
            lower = card_text.lower()
            # Find the rightmost state-name match
            best_idx = -1
            for name, code in state_names.items():
                idx = lower.rfind(name)
                if idx > best_idx:
                    best_idx = idx
                    cand_state = code
            # Also check for 2-letter codes as standalone words
            if not cand_state:
                for m in re.finditer(r'\b([A-Z]{2})\b', card_text):
                    code = m.group(1)
                    # Skip obvious false positives (the company letters in
                    # company codes like "A B" — but state codes are valid
                    # too, so just include all)
                    cand_state = code
                    break

        # Extract cemetery name (line before the city/county/state line)
        cemetery = None
        cm = re.search(r'([A-Z][A-Za-z\.\s]+?(?:Cemetery|Memorial Cemetery|Burying Ground|'
                       r'Cemetery|Church Cemetery|National Cemetery|Memorial Park|'
                       r'City Cemetery|Memorial Gardens|Mausoleum))\s*[,\n]',
                       card_text)
        if cm:
            cemetery = cm.group(1).strip()

        # Cemetery + location: parse the surrounding card if accessible.
        # Fall back to the snippet text.
        # The full result card may have cemetery/location as additional
        # sibling elements. Try to grab the parent <li> or <div> text.
        snippet = text[:300]

        candidates.append({
            "memorial_id": mem_id,
            "slug": slug,
            "name": name_display,
            "backlink": f"https://www.findagrave.com/memorial/{mem_id}/{slug}",
            "iiif_url": f"https://www.findagrave.com/iiif/2/memorial:{mem_id}/full/full/0/default.jpg",
            "details": {
                "is_veteran": is_veteran,
                "birth_year": birth_year,
                "death_year": death_year,
                "state": cand_state,
                "cemetery": cemetery,
            },
        })
        if len(candidates) >= MAX_FAG_RESULTS_TO_PARSE:
            break

    return total, candidates


# ============================================================
# Result-merging across strategies
# ============================================================

def merge_candidates(strategy_runs: list[tuple[str, list[dict]]]) -> list[dict]:
    """Combine candidates from multiple strategy runs.

    For each unique memorial_id, keep the highest-scoring occurrence
    (or — for pre-scoring — just the first occurrence, since we score
    after merging using the local context).
    """
    seen: dict[str, dict] = {}
    for strat_name, cands in strategy_runs:
        for c in cands:
            mid = c["memorial_id"]
            if mid in seen:
                # Track which strategies surfaced this candidate
                if strat_name not in seen[mid].get("via_strategies", []):
                    seen[mid]["via_strategies"].append(strat_name)
            else:
                c2 = dict(c)
                c2["via_strategies"] = [strat_name]
                seen[mid] = c2
    return list(seen.values())


# ============================================================
# State persistence
# ============================================================

def load_processed_ids(state_path: Path) -> set[int]:
    if not state_path.exists():
        return set()
    seen = set()
    with state_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                pid = rec.get("pensioner_id")
                if pid is not None:
                    seen.add(pid)
            except json.JSONDecodeError:
                pass
    return seen


def load_skipped_ids(skipped_path: Path) -> set[int]:
    if not skipped_path.exists():
        return set()
    seen = set()
    with skipped_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                pid = rec.get("pensioner_id")
                if pid is not None:
                    seen.add(pid)
            except json.JSONDecodeError:
                pass
    return seen


def append_state(state_path: Path, record: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with state_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def write_skipped(path: Path, skipped: list[dict]) -> None:
    """Write skipped pensioners to a JSONL sidecar file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in skipped:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ============================================================
# Input loading
# ============================================================

def load_unified_from_url(url: str) -> list[dict]:
    import urllib.request
    log.info("Fetching %s ...", url)
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = json.loads(resp.read())
    log.info("Loaded %d records", len(data))
    return data


def load_unified_from_file(path: Path) -> list[dict]:
    log.info("Loading %s ...", path)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    log.info("Loaded %d records", len(data))
    return data


def load_local_csv(path: Path) -> list[dict]:
    """Load a generic CSV (e.g. from local dixiedata export).

    Expected columns (case-insensitive, some optional):
      id, first_name, middle_name, last_name,
      unit, pension_state, application_number, slug, memorial_id
    """
    import csv
    log.info("Loading %s ...", path)
    out = []
    with path.open(encoding='utf-8', errors='replace', newline='') as f:
        rdr = csv.DictReader(f)
        for i, row in enumerate(rdr, start=1):
            # Normalise column names
            lc = {k.lower().strip(): (v or '').strip() for k, v in row.items() if k}
            out.append({
                'id': int(lc.get('id') or i),
                'first_name': lc.get('first_name', ''),
                'middle_name': lc.get('middle_name', ''),
                'last_name': lc.get('last_name', ''),
                'application_number': lc.get('application_number', ''),
                'regiment': lc.get('unit', ''),
                'company': lc.get('company', ''),
                'birth_year': lc.get('birth_year', ''),
                'death_year': lc.get('death_year', ''),
                'pensioncard_backlink': '',
                # For ground-truth testing:
                '_expected_memorial_id': lc.get('memorial_id', ''),
                '_expected_slug': lc.get('slug', ''),
            })
    log.info("Loaded %d records", len(out))
    return out


def load_input(args, pensioners_list_holder: list) -> None:
    """Resolve which input loader to use based on args.

    Mutates pensioners_list_holder[0] to be the loaded list.
    """
    if args.input_url:
        pensioners_list_holder.append(load_unified_from_url(args.input_url))
    elif args.input_csv:
        pensioners_list_holder.append(load_local_csv(args.input_csv))
    else:
        pensioners_list_holder.append(load_unified_from_file(args.input))


def load_ground_truth(path: Path) -> dict[int, dict]:
    """Load expected {memorial_id, slug} per row, keyed by row id.

    The CSV must have columns: id, memorial_id, slug
    (or: id, app_number for matching by application number)
    """
    import csv
    gt = {}
    with path.open(encoding='utf-8', errors='replace', newline='') as f:
        for row in csv.DictReader(f):
            try:
                rid = int(row.get('id') or 0)
            except (ValueError, TypeError):
                continue
            gt[rid] = {
                'memorial_id': (row.get('memorial_id') or '').strip(),
                'slug': (row.get('slug') or '').strip(),
            }
    log.info("Loaded %d ground-truth records from %s", len(gt), path)
    return gt


# ============================================================
# Setup Playwright with stealth
# ============================================================

def setup_browser(p):
    from playwright_stealth import Stealth
    b = p.chromium.launch(
        headless=False,
        args=['--disable-blink-features=AutomationControlled', '--no-sandbox'],
    )
    ctx = b.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        viewport={'width': 1280, 'height': 720},
        locale='en-US',
        timezone_id='America/Chicago',
    )
    page = ctx.new_page()
    Stealth().apply_stealth_sync(page)
    return b, ctx, page


def warmup_session(page: Page, log_) -> bool:
    """Visit FaG homepage to establish a Cloudflare session.

    Without this warmup, the very first /memorial/search request
    triggers a Turnstile challenge because the browser context has
    no CF cookies. Visiting the homepage first primes the session.

    Returns True if homepage loaded without challenge.
    """
    try:
        page.goto('https://www.findagrave.com/', wait_until='domcontentloaded', timeout=30000)
        time.sleep(3)
        t = page.title()
        if 'Just a moment' in t:
            log_.warning('Warmup: still on challenge page after homepage')
            return False
        log_.info('Warmup: homepage loaded, title=%r', t)
        return True
    except Exception as e:
        log_.warning('Warmup failed: %s', e)
        return False


# ============================================================
# Per-pensioner search
# ============================================================

def search_one_pensioner(page: Page, pensioner: dict) -> dict:
    """Run the strategy ladder for one pensioner. Return a state record."""
    first = pensioner.get("first_name", "")
    middle = pensioner.get("middle_name", "")
    last = pensioner.get("last_name", "")
    state_abbr = extract_state_from_regiment(pensioner.get("regiment", ""))
    pensioner_id = pensioner.get("id", -1)
    record = {
        "pensioner_id": pensioner_id,
        "pensioner_app_number": pensioner.get("application_number", ""),
        "pensioner_name": f"{first} {middle} {last}".strip().replace("  ", " "),
        "pensioner_first": first,
        "pensioner_middle": middle,
        "pensioner_last": last,
        "pensioner_birth_year": pensioner.get("birth_year", ""),
        "pensioner_death_year": pensioner.get("death_year", ""),
        "regiment": pensioner.get("regiment", ""),
        "company": pensioner.get("company", ""),
        "pensioncard_backlink": pensioner.get("pensioncard_backlink", ""),
        "ranked_candidates": [],
        "status": S_NO_RESULTS,
        "best_score": 0.0,
        "best_candidate": None,
        "strategies_run": [],
        "decision": None,  # {memorial_id, slug, by, at, notes}
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    if not last:
        record["status"] = S_SKIP
        record["error"] = "no last name"
        return record

    local = {
        "first_name": first,
        "middle_name": middle,
        "last_name": last,
        "_state_abbr": state_abbr,
        "_death_year": pensioner.get("death_year", ""),
        "_birth_year": pensioner.get("birth_year", ""),
    }

    strategy_runs = []  # (strategy_name, [candidates])
    captcha_seen = False
    any_error = False

    for name, fn in STRATEGIES:
        # Build per-strategy closure for F2/F3 which need pensioner
        if name == "F2-regiment-bio":
            params = strategy_regiment_bio(first, middle, last, pensioner.get("regiment", ""), pensioner.get("death_year"))
        elif name == "F3-nickname":
            params = strategy_with_nickname(first, middle, last, pensioner.get("birth_year"), pensioner.get("death_year"), pensioner)
        else:
            params = fn(first, middle, last, pensioner.get("birth_year"), pensioner.get("death_year"))
        if params is None:
            continue
        url = BASE_URL + "?" + urlencode(params)
        record["strategies_run"].append(name)

        try:
            page.goto(url, wait_until='domcontentloaded', timeout=20000)
        except PWTimeout:
            log.warning("Nav timeout: %s %s [%s]", first, last, name)
            any_error = True
            time.sleep(CAPTCHA_BACKOFF_SECONDS)
            continue

        title = page.title()
        if "Just a moment" in title or "Attention Required" in title:
            log.warning("CAPTCHA: %s %s [%s]. Waiting up to 30s for it to resolve.",
                        first, last, name)
            captcha_seen = True
            # Try waiting for the challenge to resolve naturally
            resolved = False
            for wait_s in (5, 10, 15):
                time.sleep(5)
                if "Just a moment" not in page.title():
                    log.info("  challenge resolved after %ds", wait_s + 5)
                    resolved = True
                    break
            if not resolved:
                log.warning("  challenge did not resolve. Backing off 30s.")
                time.sleep(CAPTCHA_BACKOFF_SECONDS)
            continue

        try:
            total, cands = parse_results_page(page)
        except Exception as e:
            log.warning("Parse error %s %s: %s", first, last, e)
            any_error = True
            continue

        # Tag each candidate with the strategy that found it, so the
        # HTML viewer can show "Found by: B1-exact (firstname=John&...)"
        cands = tag_candidates_with_found_by(cands, name, params)
        log.info("  %s %-12s [%s] -> %d results", first, last, name, total)
        strategy_runs.append((name, cands))
        # No early-stop — collect all candidates across all strategies

    # Merge and score
    merged = merge_candidates(strategy_runs)
    for c in merged:
        s, breakdown = score_candidate(local, c)
        c["score"] = round(s, 3)
        c["score_breakdown"] = breakdown

    merged.sort(key=lambda c: -c["score"])
    record["ranked_candidates"] = merged[:MAX_CANDIDATES_PER_PENSIONER]

    if merged:
        record["best_score"] = merged[0]["score"]
        record["best_candidate"] = {
            "memorial_id": merged[0]["memorial_id"],
            "slug": merged[0]["slug"],
            "score": merged[0]["score"],
        }

    # Ground-truth validation (if the local record has an expected
    # memorial_id+slug, check if it appears anywhere in the candidates)
    expected_mid = pensioner.get("_expected_memorial_id", "").strip()
    expected_slug = pensioner.get("_expected_slug", "").strip()
    if expected_mid or expected_slug:
        hit_idx = None
        for idx, c in enumerate(merged):
            if expected_mid and c["memorial_id"] == expected_mid:
                hit_idx = idx
                break
            if expected_slug and c["slug"] == expected_slug:
                hit_idx = idx
                break
        if hit_idx is not None:
            record["ground_truth"] = {
                "expected": {"memorial_id": expected_mid, "slug": expected_slug},
                "found": True,
                "rank": hit_idx + 1,  # 1-based
                "score": merged[hit_idx]["score"],
            }
        else:
            record["ground_truth"] = {
                "expected": {"memorial_id": expected_mid, "slug": expected_slug},
                "found": False,
            }

    # Status
    if captcha_seen and not merged:
        record["status"] = S_CAPTCHA
    elif not merged:
        if any_error:
            record["status"] = S_ERROR
        else:
            record["status"] = S_NO_RESULTS
    else:
        # We have at least one result. Decide:
        # - top score >= AUTO_ACCEPT_THRESHOLD and only one candidate -> auto_accept
        # - top score >= AUTO_ACCEPT_THRESHOLD and multiple candidates -> still
        #   "auto_accept but other matches exist" — keep as ambiguous for
        #   human review (the user can verify)
        # - top score below threshold -> ambiguous/too_many
        # Pick the threshold based on whether we have a death year locally.
        local_dy = str(pensioner.get("death_year") or "").strip()
        threshold = AUTO_ACCEPT_THRESHOLD if local_dy and local_dy != "0" else AUTO_ACCEPT_THRESHOLD_NO_DEATH
        if len(merged) == 1 and record["best_score"] >= threshold:
            record["status"] = S_AUTO_ACCEPT
        elif record["best_score"] >= threshold and 2 <= len(merged) <= 10:
            # Check if top is a clear winner (gap over #2)
            if len(merged) >= 2:
                second_score = merged[1]["score"]
                gap = record["best_score"] - second_score
                if gap >= AUTO_ACCEPT_GAP:
                    record["status"] = S_AUTO_ACCEPT
                else:
                    record["status"] = S_AMBIGUOUS
            else:
                record["status"] = S_AUTO_ACCEPT
        elif len(merged) == 1:
            record["status"] = S_AMBIGUOUS  # 1 candidate, score below auto-accept
        elif 2 <= len(merged) <= 10:
            record["status"] = S_AMBIGUOUS
        else:
            # >10 candidates. Check if top is dominant — if so, auto_accept.
            if len(merged) >= 2 and record["best_score"] >= threshold:
                second_score = merged[1]["score"]
                gap = record["best_score"] - second_score
                if gap >= AUTO_ACCEPT_GAP:
                    record["status"] = S_AUTO_ACCEPT
                else:
                    record["status"] = S_TOO_MANY
            else:
                record["status"] = S_TOO_MANY

    return record


# ============================================================
# Main
# ============================================================

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", type=Path, help="Local path to unified.json")
    src.add_argument("--input-url", help="URL to fetch unified.json (e.g. raw GitHub)")
    src.add_argument("--input-csv", type=Path,
                     help="Local path to a generic CSV (dixiedata export, etc.). "
                          "Expected columns: id, first_name, middle_name, last_name, "
                          "unit, company, application_number, memorial_id, slug")
    p.add_argument("--state", type=Path, required=True,
                   help="Output JSONL state file (one line per pensioner)")
    p.add_argument("--limit", type=int, default=0,
                   help="Process at most N pensioners (default: all)")
    p.add_argument("--shuffle", action="store_true",
                   help="Process in random order")
    p.add_argument("--start-from", type=int, default=0,
                   help="Skip the first N pensioners")
    p.add_argument("--ground-truth-csv", type=Path, default=None,
                   help="Optional CSV with expected memorial_id+slug per row. "
                        "When set, the state output includes 'ground_truth_match' "
                        "(true/false/null) per pensioner for validation.")
    p.add_argument("--exclude-csv", type=Path, default=None,
                   help="Skip pensioners whose (last, first) match a row in this CSV. "
                        "Used to skip records we've already validated locally. "
                        "Expected columns: first_name, last_name.")
    p.add_argument("--skipped-out", type=Path, default=None,
                   help="Optional JSONL to write the list of skipped pensioners + reason. "
                        "Defaults to <state>.skipped.jsonl if --exclude-csv is used.")
    args = p.parse_args()

    # Load input
    holder = []
    load_input(args, holder)
    pensioners = holder[0]

    if args.shuffle:
        random.shuffle(pensioners)
    if args.start_from:
        pensioners = pensioners[args.start_from:]
    if args.limit:
        pensioners = pensioners[:args.limit]

    processed = load_processed_ids(args.state)
    log.info("Will process %d pensioners (%d already done)",
             len(pensioners), len(processed))

    # Exclusion filter
    skipped = []
    if args.exclude_csv:
        exclude_csv = Path(args.exclude_csv)
        if exclude_csv.exists():
            exclude_names = set()
            with exclude_csv.open(encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    ln = (r.get("last_name") or "").strip().upper()
                    fn = (r.get("first_name") or "").strip().upper()
                    if ln:
                        exclude_names.add((ln, fn))
            # Also skip pensioners already in the skipped sidecar
            skipped_path_load = args.skipped_out or args.state.with_suffix(".skipped.jsonl")
            already_skipped = load_skipped_ids(skipped_path_load) if skipped_path_load.exists() else set()
            before = len(pensioners)
            kept = []
            for p_data in pensioners:
                pid = p_data.get("id")
                if pid in already_skipped:
                    continue  # already excluded on a prior run
                key = (p_data.get("last_name", "").upper(),
                       p_data.get("first_name", "").upper())
                if key in exclude_names:
                    skipped.append({
                        "pensioner_id": pid,
                        "name_raw": p_data.get("name_raw"),
                        "first_name": p_data.get("first_name"),
                        "last_name": p_data.get("last_name"),
                        "reason": "in exclude-csv",
                    })
                else:
                    kept.append(p_data)
            pensioners = kept
            log.info("Excluded %d pensioners (in %s). Remaining: %d",
                     before - len(pensioners), exclude_csv, len(pensioners))
        else:
            log.warning("--exclude-csv %s does not exist", exclude_csv)

    # Load ground truth if supplied
    ground_truth = {}
    if args.ground_truth_csv:
        ground_truth = load_ground_truth(args.ground_truth_csv)
        # Build a map by application number too, for unified.json
        for p_data in pensioners:
            app = p_data.get('application_number', '').strip()
            if app:
                # If the GT has matching app# we'd need a second column;
                # skip for now
                pass

    with sync_playwright() as pw:
        browser, ctx, page = setup_browser(pw)
        checkpoint_path = args.state.with_suffix(".checkpoint.json")
        log.info("Checkpoint file: %s", checkpoint_path)
        try:
            # Warmup: visit homepage first to establish Cloudflare session
            log.info("Warming up browser session...")
            if not warmup_session(page, log):
                log.warning("Warmup incomplete. First few queries may hit CAPTCHA.")
            count = 0
            for p_data in pensioners:
                pid = p_data.get("id", -1)
                if pid in processed:
                    continue
                count += 1
                log.info("[%d/%d] id=%d  %s %s", count, len(pensioners),
                         pid, p_data.get("first_name", ""),
                         p_data.get("last_name", ""))
                # Wrap each pensioner in try/except so one bad row doesn't
                # kill the whole run. We record the failure and move on.
                try:
                    record = search_one_pensioner(page, p_data)
                    append_state(args.state, record)
                    # Checkpoint: record that we successfully processed this id.
                    write_checkpoint(
                        checkpoint_path,
                        last_processed_id=pid,
                        last_strategy=record.get("strategies_run", [""])[-1] if record.get("strategies_run") else "",
                        pensioner_name=record.get("pensioner_name", ""),
                        run_id=str(int(time.time())),
                        state_file=str(args.state),
                    )
                except Exception as e:
                    log.error("Pensioner %d failed: %s", pid, e, exc_info=False)
                    record_failure(
                        args.state, pid,
                        f"{p_data.get('first_name', '')} {p_data.get('last_name', '')}".strip(),
                        error=str(e)[:500],
                    )
                time.sleep(THROTTLE_SECONDS)
        finally:
            ctx.close()
            browser.close()

    log.info("Done. State file: %s", args.state)

    if skipped:
        skipped_path = args.skipped_out or args.state.with_suffix(".skipped.jsonl")
        write_skipped(skipped_path, skipped)
        log.info("Wrote %d skipped pensioners to %s", len(skipped), skipped_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())