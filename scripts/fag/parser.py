"""scripts.fag.parser: FaG search-results page parser + merge.

Extracted from scripts.fag.search.py (T008).

Public surface:
  - parse_results_page(page) -> (total_count, candidates_list)
  - merge_candidates(strategy_runs) -> merged_candidates
"""
import re

from playwright.sync_api import Page

from scripts.fag.filters import _STATE_NAMES_LOWER  # state name -> abbr lookup

# Cap on the number of result pages we parse. FaG soft-caps at 200
# results per page; this constant is the per-strategy total.
MAX_FAG_RESULTS_TO_PARSE = 20

# Regex constants (T008 split regression: restored from pre-split
# scripts/search_fag.py — they were inlined before the split and
# not migrated when the file was split into private modules.)
_MEMORIAL_PATH_RE = re.compile(
    r'(?:^|[\"\'])'
    r'((?:https?://www\.findagrave\.com)?/memorial/(\d+)/([^/?\"\'#]+))',
    re.I,
)
DATE_RANGE_RE = re.compile(r"(\d{4})\s*[\u2013\-]\s*(\d{4})")
def parse_results_page(page: Page) -> tuple[int, list[dict]]:
    """Parse the search results page.

    Returns (total_count, list_of_candidate_dicts).
    Each candidate has: memorial_id, slug, name, snippet, details,
    is_veteran, dates, cemetery.
    """
    # Wait for at least one result link to appear (the result list is
    # client-rendered after a few hundred ms). wait_for_selector()
    # returns an ElementHandle; dispose it explicitly so the page's
    # DOM ref count doesn't grow across strategies (otherwise each
    # strategy leak adds a small handle allocation that accumulates
    # over the 7709-record run).
    try:
        handle = page.wait_for_selector('a[href*="/memorial/"]', timeout=15000)
        if handle:
            try:
                handle.dispose()
            except Exception:
                pass
    except PWTimeout:
        pass

    # Memory-efficient count lookup. The previous implementation
    # called `page.inner_text("body")` to grab the whole-page text
    # (potentially 5MB+ for 200K-result pages) and regex'd for the
    # "X matching records" string. This allocated MB-sized Python
    # strings per call that the OS allocator never reclaimed; over a
    # full run that was a sustained ~30 MB/min RSS growth.
    #
    # Instead, query the specific element that holds the count. The
    # FaG result page renders the count inside the page header; we
    # grab it via a small JavaScript expression that returns a
    # short string. If the selector doesn't match (FaG may change it),
    # we return 0 — `total` is only used for the "too_many" decision
    # which already has its own fallback path.
    body = ""
    try:
        body = page.evaluate(
            '''() => {
                const el = document.querySelector('[data-test-id="total-records"]')
                  || document.querySelector('.total-records')
                  || document.querySelector('.memorial-search-results-header');
                if (el) return el.innerText || el.textContent || '';
                return '';
            }'''
        )
    except Exception:
        body = ""
    m = re.search(r"(\d[\d,]*)\s+matching records?", body or "")
    total = int(m.group(1).replace(",", "")) if m else 0
    try:
        del body
    except Exception:
        pass

    # Soft cap: if the result count is overwhelming (e.g. 200K+ matches
    # for super-common names), don't try to enumerate every result.
    # The DOM materialization is the expensive step. We've verified
    # the query succeeded; cap based on MAX_FAG_RESULTS_TO_PARSE.
    if total > MAX_FAG_RESULTS_TO_PARSE * 100:  # 20 * 100 = 2000
        log.debug("Too many results (%d); capping parse", total)

    # Pull per-result details from the DOM (richer than HTML regex)
    candidates = []
    seen = set()
    try:
        # Only materialize up to MAX_FAG_RESULTS_TO_PARSE locator refs.
        # For wildly-popular queries (e.g. "John Smith" returns 200K
        # results), materializing all locator refs would crash or time
        # out.
        locator = page.locator('a[href*="/memorial/"]')
        n_locator = min(locator.count(), MAX_FAG_RESULTS_TO_PARSE)
        link_locators = [locator.nth(i) for i in range(n_locator)]
    except Exception as e:
        log.warning("Locator query failed: %s", e)
        link_locators = []

    for link in link_locators:
        try:
            href = link.get_attribute("href") or ""
        except Exception:
            continue
        m = _MEMORIAL_PATH_RE.search(href)
        if not m:
            continue
        mem_id, slug = m.group(2), m.group(3)
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

        # Extract state from the link text. Previously this used a
        # `link.evaluate('el => parentElement.parentElement.innerText')`
        # JS round-trip per candidate. Over a full run that added up
        # to millions of V8 IPC calls and a steady Chromium RSS leak.
        # Use `text` (already computed above) instead — it's the link's
        # own innerText, which on FaG result cards contains the state
        # abbreviation or full state name.
        card_text = text  # alias; preserves existing logic below.

        # Extract state from the card text. Location is rendered like:
        #   "Eolian, Stephens County, Texas"  (one entry)
        #   or "Battle Creek Cemetery Eolian, Stephens County, Texas"
        # After whitespace normalization, commas may or may not be present
        # between city and county. Use a state-name lookup that works in
        # both cases: find a state name or 2-letter code anywhere in the
        # card text, prioritizing the LAST match (state is always last).
        cand_state = None
        # First try comma-separated tokens (works for "City, County, State")
        for tok in reversed(re.split(r',\s*', card_text)):
            tok_clean = tok.strip().rstrip('.').lower()
            if tok_clean in _STATE_NAMES_LOWER:
                cand_state = _STATE_NAMES_LOWER[tok_clean]
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
            for name, code in _STATE_NAMES_LOWER.items():
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

    # Memory hygiene: drop all locator refs and the body text before
    # returning. Each Locator (parent `locator` AND every per-index
    # `link_locators[i]`) retains a handle to the Playwright connection;
    # on long runs these add up. The `body` string can be 100 KB+ for
    # huge-result pages — release it as well.
    try:
        link_locators.clear()
        del link_locators
    except Exception:
        pass
    # Drop the parent locator too: each per-index call kept an internal
    # frame ref under the parent. Without this, even after the children
    # list is cleared, the parent survives until the next assignment.
    try:
        del locator
    except Exception:
        pass
    try:
        del body
    except Exception:
        pass
    # Encourage the interpreter to free cycle references promptly
    # every 5 records. Live monitoring of the resumed Run #2 showed
    # Python RSS growing ~15 MB/min at the previous cadence (every
    # 25 records); 5 reduces the long-run RSS growth rate materially
    # with negligible CPU cost (~1 ms).
    import gc as _gc
    n = getattr(parse_results_page, "_record_count", 0) + 1
    parse_results_page._record_count = n
    if n % 5 == 0:
        _gc.collect()

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
