"""NewspapersComEngine: the Newspapers.com implementation of SearchEngine.

The 2nd real engine (after FaGEngine). Validates that the
SearchEngine Protocol + SearchRecord + run_ladder abstractions
are sufficient to add a new search backend without touching
the pipeline. This engine is intentionally much smaller than
FaGEngine: no memorial-page detail, no spouse scrape, no
CGR. Just search → results → score.

Result shape (from probe data/probe/newspapers_q_*.html):

  <div id="{record_id}" class="SearchResult_ArticleResult__...">
    <a href="/image/{record_id}/?match={position}&terms=...">
      <h2>{paper_name} \u2022 Page {page_num}</h2>
      <span>{date: "Weekday, Month DD, YYYY"}</span>
      <span>{location: "City, State/Region, Country"}</span>
      <img src="...thumbnail...">
    </a>
  </div>

Each result has:
  - id: the numeric record id (the image id)
  - href: the link to the full page view
  - title: "Paper Name \u2022 Page N"
  - date: "Saturday, August 22, 1896" (parsed to ISO 8601)
  - location: "Melbourne, Victoria, Australia"
  - match: the search position on the source page (informational)
  - thumbnail: image URL

The Newspapers.com result has no memorial-style "match strength"
or "score" in the FaG sense. The scoring function in this engine
derives a confidence from how well the title/location match the
local pensioner context (e.g. last name in title, state in
location, year close to the pensioner's lifespan).

Limitations:
  - Logged-in session required for full results. Without a
    subscription or trial, the public page shows the upsell
    modal. The engine still works against the page; the
    result count may be smaller than the true count.
  - Cloudflare Turnstile may be present. The engine treats
    that as a blocking response and the runner backs off.
  - The anti-bot is less aggressive than FaG; the throttle
    can be 1.0s instead of 2.5s.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from scripts.search.context import SearchContext
from scripts.search.engine import Classification, SearchEngine
from scripts.search.strategy import FunctionStrategy


# ============================================================
# Newspapers.com URL builder constants
# ============================================================


BASE_URL = "https://www.newspapers.com/search/"

#: Anti-bot throttle (seconds). Lower than FaG's 2.5s because
#: Newspapers.com's rate limiting is more lenient.
THROTTLE_SECONDS: float = 1.0

#: Default year range for pensioner searches (covers
#: pre-Civil-War through post-Civil-War pensioners).
DEFAULT_YEAR_START: int = 1840
DEFAULT_YEAR_END: int = 1930

#: Entity types filter (page + obituary + marriage + birth).
#: These are the types most relevant to a pensioner search.
#: Stored as a Python list; the engine joins with commas
#: at URL-build time so urlencode() encodes the commas once.
DEFAULT_ENTITY_TYPES: list[str] = ["page", "obituary", "marriage", "birth"]


# ============================================================
# Result parser
# ============================================================


#: Match a single result block. Newspapers.com wraps each
#: result in <div id="{record_id}" class="SearchResult_ArticleResult...">
#: The greedy .*? in DOTALL mode matches the per-result content.
_RESULT_BLOCK_RE = re.compile(
    r'<div id="(\d+)" class="SearchResult_ArticleResult[^"]*">'
    r'(.*?)'
    r'</div></div></div></div></div>',
    re.DOTALL,
)

#: Match the result id, href, and match-position from a block.
_HREF_RE = re.compile(
    r'<a href="(/image/(\d+)/\?match=(\d+)&amp;[^"]+)"',
)

#: Match the title ("Paper Name • Page N"). Newspapers.com uses
#: &nbsp;&bull;&nbsp; (U+00B7 = middle dot) between paper and page.
_TITLE_RE = re.compile(r'<h2>([^<]+)</h2>')

#: Match the date ("Weekday, Month DD, YYYY"). Weekday is one
#: of Monday, Tuesday, Wednesday, Thursday, Friday, Saturday,
#: Sunday. Followed by a comma, then the date.
_DATE_RE = re.compile(
    r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+'
    r'([A-Z][a-z]+)\s+(\d+),\s+(\d{4})',
)

#: Match the location ("City, State, Country"). After the
#: MapPinIcon SVG. We pick the text content of the location span.
_LOCATION_RE = re.compile(
    r'aria-label="Location"[^>]*>(?:<[^>]+>)*\s*([^<]+?)\s*</span>',
    re.DOTALL,
)

#: Match the thumbnail URL.
_THUMB_RE = re.compile(r'src="(/img/thumbnail/[^"]+\.jpg[^"]*)"')

#: Result count pattern ("X of Y matches on this page" gives
#: the page-level count; the per-page limit is ~72).
_PAGE_HIT_RE = re.compile(r'(\d+)\s+of\s+(\d+)\s+matches?')

#: Total count pattern (the search-result header). May not
#: appear on the page if the result is fully rendered.
_TOTAL_RE = re.compile(r'([\d,]+)\s+results?', re.IGNORECASE)


def _parse_date(date_str: str | None) -> str:
    """Parse "Saturday, August 22, 1896" to "1896-08-22".
    Returns "" if the input can't be parsed."""
    if not date_str:
        return ""
    m = _DATE_RE.search(date_str)
    if not m:
        return ""
    month_name, day, year = m.group(1), int(m.group(2)), int(m.group(3))
    try:
        d = datetime.strptime(f"{month_name} {day} {year}", "%B %d %Y")
        return d.strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _parse_block(block_html: str) -> dict | None:
    """Parse one Newspapers.com result block into a candidate dict.

    Returns None if the block doesn't have the expected shape.
    """
    m_id = re.match(r'<div id="(\d+)"', block_html)
    if not m_id:
        return None
    record_id = m_id.group(1)

    m_href = _HREF_RE.search(block_html)
    href = ""
    match_position = ""
    if m_href:
        href = m_href.group(1).replace("&amp;", "&")
        match_position = m_href.group(3)

    m_title = _TITLE_RE.search(block_html)
    title = m_title.group(1).strip() if m_title else ""
    # Clean the &nbsp; entities that the title may have
    title = title.replace("\xa0", " ")

    m_date = _DATE_RE.search(block_html)
    date_str = ""
    if m_date:
        date_str = f"{m_date.group(0).split(',')[0]}, {m_date.group(1)} {m_date.group(2)}, {m_date.group(3)}"
    iso_date = _parse_date(date_str)

    m_loc = _LOCATION_RE.search(block_html)
    location = m_loc.group(1).strip() if m_loc else ""

    m_thumb = _THUMB_RE.search(block_html)
    thumbnail = m_loc and m_thumb.group(1) if m_thumb else ""
    if m_thumb:
        thumbnail = m_thumb.group(1)

    return {
        "id": record_id,
        "href": href,
        "title": title,
        "date": date_str,
        "iso_date": iso_date,
        "location": location,
        "match_position": match_position,
        "thumbnail": thumbnail,
    }


# ============================================================
# Strategies
# ============================================================


def _strategy_keyword_only(ctx: SearchContext):
    """Newspapers.com's search takes a `keyword` query. The
    simplest strategy passes the joined name as the keyword
    and adds the year range from the pensioner's dates."""
    if not ctx.first and not ctx.last:
        return None
    keyword = " ".join(filter(None, (ctx.first, ctx.middle, ctx.last)))
    by = int(ctx.birth_year) if (ctx.birth_year and ctx.birth_year.isdigit()) else None
    dy = int(ctx.death_year) if (ctx.death_year and ctx.death_year.isdigit()) else None
    params = {
        "keyword": keyword,
        "entity-types": ",".join(DEFAULT_ENTITY_TYPES),
        "sort": "score-desc",
    }
    if by is not None and dy is not None:
        # Tighten the year window to the pensioner's lifespan
        params["date-start"] = str(max(by - 5, DEFAULT_YEAR_START))
        params["date-end"] = str(min(dy + 5, DEFAULT_YEAR_END))
    elif by is not None:
        params["date-start"] = str(max(by - 5, DEFAULT_YEAR_START))
        params["date-end"] = str(by + 30)
    elif dy is not None:
        params["date-start"] = str(max(dy - 30, DEFAULT_YEAR_START))
        params["date-end"] = str(dy + 5)
    else:
        params["date-start"] = str(DEFAULT_YEAR_START)
        params["date-end"] = str(DEFAULT_YEAR_END)
    return params


def _strategy_lastname_only(ctx: SearchContext):
    """Last-name-only keyword; broader year window."""
    if not ctx.last:
        return None
    return {
        "keyword": ctx.last,
        "entity-types": ",".join(DEFAULT_ENTITY_TYPES),
        "sort": "score-desc",
        "date-start": str(DEFAULT_YEAR_START),
        "date-end": str(DEFAULT_YEAR_END),
    }


def _strategy_with_state(ctx: SearchContext):
    """Include the state abbreviation in the keyword. Helps
    narrow to OK results when the pensioner has a known state."""
    if not ctx.last or not ctx.state:
        return None
    return {
        "keyword": f"{ctx.last} {ctx.state}",
        "entity-types": ",".join(DEFAULT_ENTITY_TYPES),
        "sort": "score-desc",
        "date-start": str(DEFAULT_YEAR_START),
        "date-end": str(DEFAULT_YEAR_END),
    }


# ============================================================
# Classification adapter
# ============================================================


class _NewspapersComClassification(Classification):
    """Newspapers.com's response classification. The page is
    a 'normal' results page if any SearchResult_* block is
    present; otherwise it may be a paywall, captcha, or
    challenge. We use simple heuristics; the page may also be
    a Cloudflare challenge (CF can be detected by the
    'Just a moment' title)."""

    def __init__(self, value: str, *, blocking: bool = False):
        self._value = value
        self._blocking = blocking

    @property
    def is_blocking(self) -> bool:
        return self._blocking

    @property
    def is_normal(self) -> bool:
        return not self._blocking and self._value == "normal"

    @property
    def value(self) -> str:
        return self._value


# ============================================================
# Engine
# ============================================================


class NewspapersComEngine:
    """The Newspapers.com search engine.

    Implements the SearchEngine Protocol via the building blocks.
    Smaller surface than FaGEngine: no memorial page detail,
    no spouse scrape, no CGR. The ladder has 3 strategies
    tailored to Newspapers.com's keyword search.
    """

    name = "newspapers_com"
    base_url = BASE_URL
    ladder = [
        FunctionStrategy("N1-keyword", _strategy_keyword_only),
        FunctionStrategy("N2-lastname-only", _strategy_lastname_only),
        FunctionStrategy("N3-with-state", _strategy_with_state),
    ]

    def build_url(self, params: dict) -> str:
        """Compose the Newspapers.com search URL from a params dict."""
        return BASE_URL + "?" + urlencode(params)

    def parse_results_page(self, page, url: str) -> list[dict]:
        """Parse a Newspapers.com results page into candidate dicts.

        Each candidate has: id, href, title, date, iso_date,
        location, match_position, thumbnail.
        """
        html = page.content()
        candidates = []
        for m in _RESULT_BLOCK_RE.finditer(html):
            block = m.group(0)
            parsed = _parse_block(block)
            if parsed is not None:
                candidates.append(parsed)
        return candidates

    def score(
        self, ctx: SearchContext, candidate: dict,
    ) -> tuple[float, dict]:
        """Score a Newspapers.com candidate against the local
        context.

        Newspapers.com doesn't have a "match strength" in the
        FaG sense. We derive a confidence from:
          - Last name in title: 0.4
          - First name in title or location: 0.2
          - State in location (if known): 0.2
          - Year close to birth/death year: 0.2

        Sum: 0.0 to 1.0. The mapping is intentionally simple;
        future iterations can use richer evidence (e.g. match
        snippet OCR, exact title match).
        """
        score = 0.0
        evidence: dict = {}

        title = candidate.get("title", "")
        location = candidate.get("location", "")
        iso_date = candidate.get("iso_date", "")

        # Last name in title
        if ctx.last and ctx.last.lower() in title.lower():
            score += 0.40
            evidence["last_name_in_title"] = True

        # First name in title
        if ctx.first and ctx.first.lower() in title.lower():
            score += 0.20
            evidence["first_name_in_title"] = True

        # State in location
        if ctx.state and ctx.state.lower() in location.lower():
            score += 0.20
            evidence["state_in_location"] = True

        # Year close to birth/death year
        try:
            year = int(iso_date[:4]) if iso_date else None
        except (ValueError, TypeError):
            year = None
        if year is not None:
            by = int(ctx.birth_year) if (ctx.birth_year and ctx.birth_year.isdigit()) else None
            dy = int(ctx.death_year) if (ctx.death_year and ctx.death_year.isdigit()) else None
            window_years = 0
            if by is not None and dy is not None:
                if by - 5 <= year <= dy + 5:
                    score += 0.20
                    window_years = (by - 5, dy + 5)
            elif by is not None:
                if by - 5 <= year <= by + 30:
                    score += 0.20
                    window_years = (by - 5, by + 30)
            elif dy is not None:
                if dy - 30 <= year <= dy + 5:
                    score += 0.20
                    window_years = (dy - 30, dy + 5)
            if window_years:
                evidence["year_in_window"] = window_years

        return min(score, 1.0), evidence

    def classify_response(self, page) -> Classification:
        """Classify a Newspapers.com response page.

        Heuristics:
          - Page title is "Just a moment..." → Cloudflare challenge.
            (The phrase also appears in scripts inside the HTML
            when results are loaded; we only treat the title
            as a challenge signal.)
          - HTML has any SearchResult_ block AND no challenge
            title → normal.
          - HTML has "Start Free Trial" but no SearchResult_ →
            paywall.
          - Otherwise → no_results (probably empty).
        """
        try:
            title = page.title() if hasattr(page, "title") else ""
        except Exception:
            title = ""
        try:
            html = page.content()
        except Exception:
            html = ""
        if title and "Just a moment" in title:
            return _NewspapersComClassification(
                "cloudflare_challenge", blocking=True,
            )
        if "SearchResult_" in html:
            return _NewspapersComClassification("normal")
        if "Start Free Trial" in html:
            return _NewspapersComClassification("paywall", blocking=False)
        return _NewspapersComClassification("no_results")

    def apply_filters(
        self, params: dict, ctx: SearchContext,
    ) -> dict:
        """Apply Newspapers.com-specific URL-param filters.

        Newspapers.com's filters are mostly in the URL params
        (keyword, date range, entity-types). No session-side
        state to set. We just return a copy of the params.
        """
        return dict(params)

    def throttle_seconds(self) -> float:
        """Inter-request throttle (seconds).

        Newspapers.com's rate limiting is more lenient than
        FaG's, but we still need a floor to avoid burst-rate
        issues with the Cloudflare edge.
        """
        return THROTTLE_SECONDS
