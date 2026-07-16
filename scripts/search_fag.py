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
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

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
AUTO_ACCEPT_THRESHOLD = 0.95   # auto-accept without review
PROMPT_THRESHOLD = 0.70        # show as ambiguous for review
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

def strategy_b1_exact(first, middle, last, birth_year):
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


def strategy_b2_middle_initial(first, middle, last, birth_year):
    """B2: middlename-initial. Only if middle is a single letter."""
    if not middle or len(middle) > 1 or not first or not last:
        return None
    return {
        "firstname": first,
        "middlename": middle,
        "lastname": last,
        "exactspelling": "true",
    }


def strategy_b3_first_initial_fuzzy(first, middle, last, birth_year):
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


def strategy_b4_fuzzy_last(first, middle, last, birth_year):
    """B4: fuzzy last only + middlename."""
    if not last:
        return None
    p = {"lastname": last, "fuzzyNames": "true", "birthyearfilter": "5"}
    if middle:
        p["middlename"] = middle
    return p


def strategy_b5_apostrophe_variants(first, middle, last, birth_year):
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


def strategy_c1_cw_context(first, middle, last, birth_year):
    """C1: civil war bio context catch-all."""
    if not first or not last:
        return None
    return {
        "firstname": first,
        "lastname": last,
        "isVeteran": "true",
        "bio": '"Civil War" OR "CSA" OR "Confederate" OR "GAR"',
    }


STRATEGIES = [
    ("B1-exact",              strategy_b1_exact),
    ("B2-middle-initial",     strategy_b2_middle_initial),
    ("B3-first-initial-fuzzy", strategy_b3_first_initial_fuzzy),
    ("B4-fuzzy-last",         strategy_b4_fuzzy_last),
    ("B5-apostrophe",         strategy_b5_apostrophe_variants),
    ("C1-cw-context",         strategy_c1_cw_context),
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
    m = re.search(
        r"\b(AL|MS|TN|TX|GA|FL|AR|SC|NC|VA|LA|KY|MO|MD|OK|IN|IL|OH|PA|NY|"
        r"NJ|CT|MA|VT|NH|ME|DE|WV|IA|WI|MN|MI|KS|NE|ND|SD|WY|CO|NV|CA|"
        r"OR|WA|ID|UT|MT|AZ|NM|AK|HI|RI)\b",
        regiment.upper())
    return m.group(1) if m else ""


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

    # State match — we don't have state info in the result link's text,
    # so this is currently disabled. (Could be added by visiting each
    # candidate's memorial page and parsing the burial location.)
    state_score = 0.0

    # Veteran flag (CW pensioners were veterans — strong signal!)
    is_veteran = candidate.get("details", {}).get("is_veteran", False)
    veteran_score = 0.5 if is_veteran else 0.0

    # Weights — last + first + middle dominate, state/veteran are tie-breakers
    score = (
        0.35 * last_score +
        0.25 * first_score +
        0.20 * middle_score +
        0.12 * state_score +
        0.08 * veteran_score
    )

    breakdown = {
        "last": round(last_score, 2),
        "first": round(first_score, 2),
        "middle": round(middle_score, 2),
        "state": round(state_score, 2),
        "veteran": round(veteran_score, 2),
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
                continue
    return seen


def append_state(state_path: Path, record: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with state_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


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
    }

    strategy_runs = []  # (strategy_name, [candidates])
    captcha_seen = False
    any_error = False

    for name, fn in STRATEGIES:
        params = fn(first, middle, last, None)
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
        # - top score >= 0.95 -> auto_accept
        # - top score < 0.95 but 2-10 unique candidates -> ambiguous
        # - top score < 0.95 and 1 candidate -> still ambiguous (only one match, but score is mid)
        if record["best_score"] >= AUTO_ACCEPT_THRESHOLD and len(merged) == 1:
            record["status"] = S_AUTO_ACCEPT
        elif len(merged) == 1:
            record["status"] = S_AMBIGUOUS  # 1 candidate, score below auto-accept — review
        elif 2 <= len(merged) <= 10:
            record["status"] = S_AMBIGUOUS
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
    src.add_argument("--input-url", help="URL to fetch unified.json")
    p.add_argument("--state", type=Path, required=True,
                   help="Output JSONL state file (one line per pensioner)")
    p.add_argument("--limit", type=int, default=0,
                   help="Process at most N pensioners (default: all)")
    p.add_argument("--shuffle", action="store_true",
                   help="Process in random order")
    p.add_argument("--start-from", type=int, default=0,
                   help="Skip the first N pensioners")
    args = p.parse_args()

    pensioners = (load_unified_from_url(args.input_url) if args.input_url
                  else load_unified_from_file(args.input))

    if args.shuffle:
        random.shuffle(pensioners)
    if args.start_from:
        pensioners = pensioners[args.start_from:]
    if args.limit:
        pensioners = pensioners[:args.limit]

    processed = load_processed_ids(args.state)
    log.info("Will process %d pensioners (%d already done)",
             len(pensioners), len(processed))

    with sync_playwright() as pw:
        browser, ctx, page = setup_browser(pw)
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
                record = search_one_pensioner(page, p_data)
                append_state(args.state, record)
                time.sleep(THROTTLE_SECONDS)
        finally:
            ctx.close()
            browser.close()

    log.info("Done. State file: %s", args.state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())