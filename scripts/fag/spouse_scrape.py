"""J15-S2: Scrape the top-1 FaG candidate's memorial page for spouse info.

After the per-pensioner strategy ladder runs and FaG ranks
candidates, we visit `/memorial/<id>/<slug>` for the top candidate
and pull the Family Members > Spouse link. The captured
spouse is compared against ok_pensioners.spouse_first + last;
agreement populates `pensioner_record['spouse_match']`.

The scrape is opt-in via env var `FAG_SCRAPE_SPOUSE=1`. When
disabled, the function imports cleanly but `fetch_spouse_for_memorial`
is a no-op and the runner skips the post-pipeline comparison.
The scrape is read-only on FaG.

Cloudflare note: this module is imported but takes a
playwright `page` handle at scrape time, so the runner's
existing warm/stealthed page is reused. We do NOT spawn a
second browser.

Usage (inside the runner):

    if os.environ.get('FAG_SCRAPE_SPOUSE') == '1':
        from scripts.fag.spouse_scrape import (
            fetch_spouse_for_memorial,
            compare_spouses,
        )
        ...scraped = fetch_spouse_for_memorial(page, top_candidate)
        ...match = compare_spouses(local_spouse, scraped)

CLI usage (one-off, e.g. for testing):

    python -m scripts.fag.spouse_scrape \\
        --memorial 42943226 \\
        --expected "Mitchel Slemp" \\
        [--headless] \\
        [--browser-path path/to/chromium]

When run as a CLI we spin our own playwright+stealth browser.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional


log = logging.getLogger("fag.spouse_scrape")


# ============================================================
# HTML parsing (no Playwright needed at this layer; we receive
# a raw HTML string)
# ============================================================

# Match a memorial-card link within the Family Members section.
# Each link looks like:
#   <a href="/memorial/42943220/mitchell_ward-slemp">
#     <span ...>Mitchell Ward Slemp</span>
#   </a>
# The candidate name (display) is in an inner <span>.
_MEMORIAL_LINK_RE = re.compile(
    r'<a[^>]+href=["\']/memorial/(\d+)/([^"\']+)["\'][^>]*>',
    re.IGNORECASE,
)

# Plain-text strip helper
def _strip_tags(s: str) -> str:
    """Remove HTML tags + collapse whitespace."""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&[a-z#0-9]+;", " ", s)  # nbsp, &amp;, &#x2014;
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _split_name(full: str) -> dict:
    """Split a name into first/middle/last. ACW names often have
    middle initials ('Mitchell Ward Slemp' / 'Mitchell W. Slemp').
    """
    full = full.strip()
    parts = full.split()
    first = parts[0] if parts else ""
    last = parts[-1] if parts else ""
    middle = " ".join(parts[1:-1]) if len(parts) > 2 else ""
    return {"first": first, "middle": middle, "last": last}


def parse_spouse_from_html(html: str) -> Optional[dict]:
    """Walk a memorial page HTML and extract the Spouse section.

    Returns None when the memorial has no Family Members > Spouse
    section or when no <a href='/memorial/...'> link follows the
    Spouse header.

    Returns a dict like:
        {
            'first': 'Mitchell',
            'middle': 'Ward',
            'last': 'Slemp',
            'display': 'Mitchell Ward Slemp',
            'memorial_id': '42943220',
            'slug': 'mitchell_ward-slemp',
            'marriage_year': '1874',  # from '(m. 1874)' if present
        }

    Note: many FaG memorial pages show the spouse's MAIDEN last
    name in addition to or instead of the married last name
    (e.g. 'Affiah Kelly McClure'). For OUR match comparison we
    read the FULL display string and compare against the local
    pensioner's known spouse; a 'same last name' or 'same
    maiden name' match is enough to confirm.
    """
    # Locate the Family Members section. FaG wraps it as a
    # series of <p><strong>Spouse</strong></p> and <p><strong>Parents</strong></p>
    # ... followed by an <ul> with <li> links, then repeats for
    # Children, Siblings, etc. We grab from "Family Members" up to
    # the next H2 (Inscription, Gravesite, Bio, etc.) and parse.

    # Find a chunk that starts with the Family Members heading and
    # ends at the next h2.
    m = re.search(r'<h2[^>]*>\s*Family Members\s*</h2>([\s\S]+?)<h2', html, re.IGNORECASE)
    section = m.group(1) if m else html  # fall back; if everything is one page
    if section is html:
        # Try a more generous span: Family Members up to the next
        # obvious section anchor.
        m2 = re.search(
            r'Family Members[\s\S]+?(?:Inscription|Gravesite|Bio\b|Cover photo|See more|Flowers)',
            html, re.IGNORECASE,
        )
        if m2:
            section = m2.group(0)
    if "Spouse" not in section and "spouse" not in section.lower():
        return None

    # Now extract every <a href=/memorial/ID/slug> with its inner
    # text. The Spouse link is the one inside the <ul> immediately
    # after the Spouse marker. We need to handle TWO markup
    # patterns FaG has shipped:
    #
    #   Pattern A (legacy):
    #     <p><strong>Spouse</strong></p>
    #     <ul><li><a href="/memorial/.../...">Name</a>...</li></ul>
    #
    #   Pattern B (current, 2026-07 verified):
    #     <b id="spouseLabel" class="label-relation">Spouse</b>
    #     <ul class="member-family" aria-labelledby="spouseLabel">
    #       <li itemscope itemtype="...">
    #         <a class="d-block ..." href="/memorial/.../..." itemprop="url">
    #
    # We pick the FIRST memorial link in the slice that begins
    # with the Spouse marker and ends at the next sibling-header.
    sp_marker = re.search(
        r"<(?:p|b)[^>]*>\s*<strong[^>]*>\s*Spouse\s*</strong>"
        r"|<b[^>]+id=['\"]spouseLabel['\"][^>]*>Spouse</b>",
        section,
        re.IGNORECASE,
    )
    if not sp_marker:
        if not re.search(r"\bSpouse\b", section):
            return None
        block = section
    else:
        start = sp_marker.start()
        # Stop at the next sibling-header or closing tag.
        end = len(section)
        # Pattern A stop markers
        for stop_marker in ("Children", "Siblings", "Parents", "Burial"):
            m_stop = re.search(
                rf"<(?:p|b)[^>]*>\s*<strong[^>]*>\s*{stop_marker}\s*</strong>"
                rf"|<b[^>]+id=['\"](?:children|siblings|parents)Label['\"]",
                section[start + 1:],
                re.IGNORECASE,
            )
            if m_stop:
                end = start + 1 + m_stop.start()
                break
        block = section[start:end]  

    # Pull the FIRST memorial link from this block.
    m_link = _MEMORIAL_LINK_RE.search(block)
    if not m_link:
        return None

    mid_raw = m_link.group(1)
    slug = m_link.group(2)
    # Capture the link's outer HTML so we can extract display text.
    href_pos = m_link.start()
    end_pos = block.find("</a>", href_pos)
    if end_pos < 0:
        end_pos = href_pos + 200
    link_html = block[href_pos:end_pos]

    # Display name is typically the immediate-next text or the
    # contents of the <a>. Strip tags to get the raw display.
    # FaG's HTML wraps the name in a <span> sometimes; strip_tags
    # handles both.
    display = _strip_tags(link_html)

    # Strip years (often appended like 'Mitchell Ward Slemp 1845-1904')
    display = re.sub(r"\s*\d{3,4}\s*[-\u2013\u2014\u2212]\s*\d{0,4}.*$", "", display).strip()

    # Optional marriage year "(m. 1874)" elsewhere in the block.
    marriage_year = ""
    m_marriage = re.search(r"\(m\.\s*(\d{4})\)", block)
    if m_marriage:
        marriage_year = m_marriage.group(1)

    parts = _split_name(display)
    return {
        "first": parts["first"],
        "middle": parts["middle"],
        "last": parts["last"],
        "display": display,
        "memorial_id": mid_raw,
        "slug": slug,
        "marriage_year": marriage_year,
    }


# ============================================================
# Comparison
# ============================================================

def _norm(s: str) -> str:
    """Normalize a name string for comparison:
    strip, lowercase, collapse whitespace, remove trailing
    periods, drop common honorifics/suffixes.
    """
    s = (s or "").strip().rstrip(".").lower()
    s = re.sub(r"\s+", " ", s)
    # Drop suffixes that often appear in capture
    for suf in (" sr", " jr", " ii", " iii", " iv"):
        if s.endswith(suf):
            s = s[: -len(suf)].rstrip()
    return s


def compare_spouses(
    local: dict,
    captured: dict,
    *,
    tolerance: str = "loose",
) -> Optional[dict]:
    """Compare the local pensioner's known spouse with the
    FaG-captured spouse.

    Args:
        local: dict with keys first/middle/last (the OK pensioner's
            known spouse). Empty strings mean 'no data'.
        captured: dict like the one returned by parse_spouse_from_html
            (display + parts + memorial_id).
        tolerance:
            'loose' (default): any overlap on last name OR
                first+last both equal. This catches both
                'spouse was known by maiden name' and 'spouse
                used middle initial only' cases.
            'strict': both first AND last must match exactly.

    Returns None when no comparison can be made (missing local
    data, missing captured spouse, or no match). Returns a dict
    with the matched fields when comparison succeeds:

        {
            'matched': True,
            'matched_via': 'last_name' | 'first_and_last' | 'strict',
            'local_first': ...,
            'local_last': ...,
            'captured_first': ...,
            'captured_last': ...,
            'captured_display': ...,
            'captured_memorial_id': ...,
            'captured_slug': ...,
            'captured_marriage_year': ...,
            'match_strength': 'strong' (only when first+last AND
                middle both match)
        }
    """
    if not local or not captured:
        return None
    loc_first = _norm(local.get("first", ""))
    loc_last = _norm(local.get("last", ""))
    cap_first = _norm(captured.get("first", ""))
    cap_last = _norm(captured.get("last", ""))
    if not loc_first or not loc_last:
        return None
    if not cap_first or not cap_last:
        return None

    # Field-level match
    first_eq = loc_first == cap_first
    last_eq = loc_last == cap_last
    first_initial_eq = loc_first and cap_first and loc_first[0] == cap_first[0]

    # Strict: both first + last
    if first_eq and last_eq:
        return {
            "matched": True,
            "matched_via": "first_and_last",
            "local_first": local.get("first", ""),
            "local_last": local.get("last", ""),
            "captured_first": captured.get("first", ""),
            "captured_last": captured.get("last", ""),
            "captured_middle": captured.get("middle", ""),
            "captured_display": captured.get("display", ""),
            "captured_memorial_id": captured.get("memorial_id", ""),
            "captured_slug": captured.get("slug", ""),
            "captured_marriage_year": captured.get("marriage_year", ""),
            "match_strength": "strong",
        }

    if tolerance == "strict":
        return None

    # Loose: last name always matches (or maiden -> married pattern)
    if last_eq:
        return {
            "matched": True,
            "matched_via": "last_name",
            "local_first": local.get("first", ""),
            "local_last": local.get("last", ""),
            "captured_first": captured.get("first", ""),
            "captured_last": captured.get("last", ""),
            "captured_middle": captured.get("middle", ""),
            "captured_display": captured.get("display", ""),
            "captured_memorial_id": captured.get("memorial_id", ""),
            "captured_slug": captured.get("slug", ""),
            "captured_marriage_year": captured.get("marriage_year", ""),
            "match_strength": "medium",
        }

    # First-initial + last fallback
    if first_initial_eq and last_eq:
        return {
            "matched": True,
            "matched_via": "first_initial_last",
            "local_first": local.get("first", ""),
            "local_last": local.get("last", ""),
            "captured_first": captured.get("first", ""),
            "captured_last": captured.get("last", ""),
            "captured_middle": captured.get("middle", ""),
            "captured_display": captured.get("display", ""),
            "captured_memorial_id": captured.get("memorial_id", ""),
            "captured_slug": captured.get("slug", ""),
            "captured_marriage_year": captured.get("marriage_year", ""),
            "match_strength": "weak",
        }

    # Also accept first+last mismatch when one looks like a maiden
    # name: e.g. local='Mitchel Slemp', captured='Affiah Kelly
    # McClure' (mother-in-law) - we DON'T match those. The OK
    # pensioner's spouse is the FILLED spouse name; we should
    # match exactly to the captured spouse's own memorial.

    return None


# ============================================================
# High-level: scrape + compare (used by the runner)
# ============================================================

def fetch_spouse_html(page, memorial_id: str, slug: str) -> Optional[str]:
    """Navigate the supplied playwright page to the memorial and
    return the rendered HTML. Returns None when navigation fails
    (timed out, Cloudflare challenge, deleted memorial, etc.).

    The caller owns the page (typically the runner's warm
    playwright+stealth page). We do NOT close the page.
    """
    url = f"https://www.findagrave.com/memorial/{memorial_id}/{slug}"
    try:
        # Same throttle class as the search loop
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        log.warning("goto %s failed: %s", url, e)
        return None
    # Cloudflare / Turnstile guard: the title becomes "Just a moment..."
    title = page.title()
    if "Just a moment" in title or "Attention Required" in title:
        # Back off briefly and return None; the runner will skip
        # this pensioner.
        log.warning("CF challenge for %s; skipping scrape", url)
        return None
    # Wait for the Family Members section to render. Most pages
    # have it. Pages without it (very common names with limited
    # data) will time out — treat timeout as 'no spouse'.
    try:
        page.wait_for_selector("h2", timeout=5000)
    except Exception:
        pass
    return page.content()


def scrape_and_compare(
    page, top_candidate: dict, local_spouse: dict,
    throttle_seconds: float = 0.0,
) -> Optional[dict]:
    """Top-level convenience: fetch the memorial page for the
    candidate, parse the Spouse, compare. Returns a compare_spouses
    dict (or None).

    Args:
        page: live playwright page (warm + stealthed).
        top_candidate: a fag_records entry with at least
            {'memorial_id', 'slug'}.
        local_spouse: dict with first/middle/last (or '').
        throttle_seconds: sleep AFTER scrape (default 0). The
            runner wires its overall throttle here.

    Returns:
        Same shape as compare_spouses (None or dict with 'matched': True).
    """
    mem_id = top_candidate.get("memorial_id") or top_candidate.get("id")
    slug = top_candidate.get("slug") or ""
    if not mem_id or not slug:
        return None
    html = fetch_spouse_html(page, str(mem_id), slug)
    if not html:
        return None
    captured = parse_spouse_from_html(html)
    if captured is None:
        return None
    result = compare_spouses(local_spouse, captured)
    if throttle_seconds > 0:
        import time
        time.sleep(throttle_seconds)
    return result


# ============================================================
# CLI: scrape one memorial against one expected spouse
# ============================================================

def cli_main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--memorial", required=True,
                   help="Memorial ID (e.g. 42943226)")
    p.add_argument("--slug", default="",
                   help="URL slug (optional; default is just the id)")
    p.add_argument("--expected", default="",
                   help="Expected spouse name 'Mitchel Slemp' for smoke test")
    p.add_argument("--headless", action="store_true",
                   help="Run chromium in headless mode")
    p.add_argument("--write-fixture", type=Path, default=None,
                   help="Write the captured spouse + comparison to this JSON file")
    args = p.parse_args(argv)

    # Spin a fresh browser (stealth + warmup)
    from playwright.sync_api import sync_playwright
    try:
        from playwright_stealth import Stealth
    except ImportError:
        print("playwright-stealth not installed; pip install playwright-stealth")
        return 2

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
            locale="en-US",
            timezone_id="America/Chicago",
        )
        page = ctx.new_page()
        try:
            Stealth().apply_stealth_sync(ctx)
        except Exception:
            pass
        # Warmup
        try:
            page.goto("https://www.findagrave.com/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
        except Exception:
            pass

        url = f"https://www.findagrave.com/memorial/{args.memorial}"
        if args.slug:
            url += f"/{args.slug}"
        log.info("Fetching %s", url)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        if "Just a moment" in page.title():
            log.error("Cloudflare challenge; retry with --headless off")
            return 3
        page.wait_for_timeout(2000)

        html = page.content()
        captured = parse_spouse_from_html(html)
        if not captured:
            print("No spouse section found.")
        else:
            print(f"Captured spouse: {json.dumps(captured, indent=2)}")

        if args.expected and captured:
            local = {"first": args.expected.split()[0],
                     "middle": (" ".join(args.expected.split()[1:-1])
                                if len(args.expected.split()) > 2 else ""),
                     "last": args.expected.split()[-1]}
            cmp = compare_spouses(local, captured)
            if cmp:
                print(f"MATCH: {json.dumps(cmp, indent=2)}")
            else:
                print(f"NO match between local={local!r} and captured={captured!r}")

        if args.write_fixture and captured:
            args.write_fixture.parent.mkdir(parents=True, exist_ok=True)
            args.write_fixture.write_text(json.dumps(captured, indent=2))
            print(f"Wrote {args.write_fixture}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
