"""Probe v1: discover Newspapers.com search surface.

This is a manual-login probe. Run it with:

  python -m scripts.analysis._probe_newspapers

It opens a visible browser, lets you log in to Newspapers.com,
then runs a few searches and saves the result HTML + a cookie
file for future automated runs.

Output:
  data/probe/newspapers_v1.json - findings (counts, titles, HTML head)
  data/probe/newspapers_cookies.json - session cookies for later use
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth


OUT = Path("data/probe/newspapers_v1.json")
COOKIES_OUT = Path("data/probe/newspapers_cookies.json")
OUT.parent.mkdir(parents=True, exist_ok=True)

# The search URL pattern based on what we observed in the
# "Start Free Trial" links: ?keyword=...&date-start=...&date-end=...&entity-types=...
BASE = "https://www.newspapers.com/search/"

QUERIES = [
    # (label, params dict for the URL)
    ("smith_1850_1865", {
        "keyword": "Smith",
        "date-start": "1850",
        "date-end": "1865",
        "entity-types": "page%2Cobituary%2Cmarriage%2Cbirth",
        "sort": "score-desc",
    }),
    ("alice_1850_1865", {
        "keyword": "Alice",
        "date-start": "1850",
        "date-end": "1865",
        "entity-types": "page%2Cobituary%2Cmarriage%2Cbirth",
        "sort": "score-desc",
    }),
    ("john_smith_broad", {
        "keyword": "John Smith",
        "sort": "score-desc",
    }),
]


def build_url(params: dict) -> str:
    """Build a Newspapers.com search URL from a params dict."""
    from urllib.parse import urlencode
    return BASE + "?" + urlencode(params)


def extract_total(html: str) -> str:
    """Try common result-count patterns. Newspapers.com logged-in
    results pages may have a 'X results' header or similar."""
    for pattern in (
        r"([\d,]+)\s+results?",
        r"([\d,]+)\s+matching",
        r"of\s+about\s+([\d,]+)",
        r'"totalCount":\s*(\d+)',
        r'"resultCount":\s*(\d+)',
        r'data-result-count="([\d,]+)"',
    ):
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return "?"


def extract_first_results(html: str, limit: int = 5) -> list[dict]:
    """Pull out the first N result links + visible text. Used
    to understand the result DOM shape. We try a few common
    patterns; the one that matches gets recorded."""
    results = []
    # Try data-test="result-card" or similar
    for pattern in (
        r'<a[^>]*href="(/[^"]+)"[^>]*>(?:<[^>]+>)*([^<]{10,200})',
        r'<article[^>]*>(.*?)</article>',
        r'data-result[^>]*>(.*?)</div>',
    ):
        matches = re.findall(pattern, html, re.DOTALL)
        if matches:
            for m in matches[:limit]:
                if isinstance(m, tuple):
                    results.append({"href": m[0], "text": m[1][:200].strip()})
                else:
                    results.append({"snippet": m[:200].strip()})
            break
    return results


def extract_classes(html: str, substring: str) -> list[str]:
    """Find all class names containing the given substring.
    Used to discover the result-card class on a logged-in
    page (where we can't see the actual results from an
    anonymous session)."""
    classes = re.findall(r'class="([^"]+)"', html)
    out = []
    seen = set()
    for c in classes:
        if substring.lower() in c.lower() and c not in seen:
            seen.add(c)
            out.append(c)
    return out[:10]


def main() -> int:
    findings = {
        "queries": [],
        "notes": [
            "Manual-login probe. Open the visible browser, log in,",
            "wait for the home page, then return to this terminal.",
        ],
    }
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        try:
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
            )
            try:
                Stealth().apply_stealth_sync(ctx)
            except Exception as e:
                findings["notes"].append(f"stealth failed: {e}")
            page = ctx.new_page()
            # Open the home page; the user logs in here.
            print("Opening Newspapers.com home page...")
            print("Log in if prompted, then return to this terminal.")
            page.goto("https://www.newspapers.com/", wait_until="domcontentloaded",
                      timeout=30000)
            # Wait for the user to log in. The home page title
            # for a logged-in user contains "newspapers.com" but
            # not "Sign In" / "Free Trial". Poll for that.
            print("Waiting for login (up to 90s)...")
            try:
                page.wait_for_function(
                    "() => { const t = document.title || ''; "
                    "return t.toLowerCase().includes('newspapers') "
                    "&& !t.toLowerCase().includes('sign in') "
                    "&& !t.toLowerCase().includes('free trial'); }",
                    timeout=90000,
                )
                findings["notes"].append("login detected")
            except Exception:
                findings["notes"].append(
                    "login not auto-detected; proceeding anyway "
                    "(you may be on the home page already)"
                )
            time.sleep(2.0)
            findings["home_title"] = page.title()
            # Save cookies for future runs
            cookies = ctx.cookies()
            COOKIES_OUT.write_text(json.dumps(cookies, indent=2),
                                    encoding="utf-8")
            findings["notes"].append(f"saved {len(cookies)} cookies")

            for label, params in QUERIES:
                url = build_url(params)
                entry = {"label": label, "url": url, "params": params}
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3000)
                    html = page.content()
                    entry["title"] = page.title()
                    entry["total"] = extract_total(html)
                    entry["results"] = extract_first_results(html)
                    # Discover class names that might be the
                    # result cards. Newspapers.com uses
                    # class="<Component>_<part>__<hash>".
                    entry["result_classes"] = (
                        extract_classes(html, "result")
                        + extract_classes(html, "ocr")
                        + extract_classes(html, "article")
                        + extract_classes(html, "hit")
                    )
                    entry["html_length"] = len(html)
                    entry["html_head"] = html[:8000]
                    # Also save the full HTML for offline parsing
                    full_path = Path(f"data/probe/newspapers_q_{label}.html")
                    full_path.write_text(html, encoding="utf-8")
                    entry["full_html"] = str(full_path)
                    # Mark anti-bot / paywall markers
                    for marker in ("captcha", "Cloudflare", "challenge",
                                   "Start Free Trial", "Sign In",
                                   "MarketingResults"):
                        if marker.lower() in html.lower():
                            entry.setdefault("markers", []).append(marker)
                except Exception as e:
                    entry["error"] = str(e)
                findings["queries"].append(entry)
                time.sleep(2.5)
        finally:
            browser.close()
    OUT.write_text(json.dumps(findings, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT}")
    print(f"  home title: {findings.get('home_title', '?')}")
    print(f"  queries run: {len(findings['queries'])}")
    for q in findings["queries"]:
        print(f"  {q['label']}: total={q.get('total', '?')}, "
              f"results={len(q.get('results', []))}, "
              f"markers={q.get('markers', [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
