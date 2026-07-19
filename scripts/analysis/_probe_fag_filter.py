"""Probe v8: verify ?locationId=state_38 (NOT ?state=state_38) filters to OK.

User-supplied working URL:
  ?firstname=s&...&location=Oklahoma%2C+United+States+of+America&locationId=state_38&...

Uses BrowserSession for canonical lifecycle management (Phase 4.6).
"""
import json
import re
import time
from pathlib import Path

from scripts.fag.browser_session import BrowserSession

OUT = Path("data/probe/filter_v8.json")
BASE = "https://www.findagrave.com/memorial/search?firstname=John&lastname=Smith"
URLS = [
    ("baseline",                BASE),
    ("locationId_country_4",    BASE + "&locationId=country_4"),
    ("locationId_state_38",     BASE + "&locationId=state_38"),
    ("locationId_country_4_state_38", BASE + "&locationId=country_4&locationId=state_38"),  # duplicate, last wins?
    ("location_country_state",  BASE + "&location=Oklahoma%2C+United+States+of+America"),
]


def extract_total(text):
    m = re.search(r"([\d,]+)\s+matching\s+records", text)
    return m.group(1) if m else "?"


def main():
    results = []
    session = BrowserSession(
        throttle=0.0,  # no throttle needed for probe
        reset_every=9999,
        headless=False,
        state_filter="",
    )
    session.start()
    try:
        page = session.page

        print("[warmup]")
        page.goto("https://www.findagrave.com/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        for label, url in URLS:
            print(f"\n[{label}]", flush=True)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(5)
                title = page.title()
                body = page.evaluate("() => document.body.innerText.slice(0, 8000)")
                total = extract_total(body)
                foreign_keywords = ['England', 'Canada', 'Australia', 'Scotland',
                                    'Wales', 'Ireland', 'New Zealand', 'Mexico']
                foreign_count = sum(body.count(k) for k in foreign_keywords)
                results.append({"label": label, "url": url, "total": total,
                                "title": title[:80], "foreign_hits": foreign_count})
                print(f"  total={total} foreign_hits={foreign_count} title={title[:50]}", flush=True)
            except Exception as e:
                results.append({"label": label, "url": url, "error": str(e)})
                print(f"  ERR: {e}", flush=True)
    finally:
        session.close()

    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\n=== summary ===")
    for r in results:
        print(f"  {r.get('label','?'):34s} total={r.get('total','?'):>10s}  foreign_hits={r.get('foreign_hits','?')}")


if __name__ == "__main__":
    main()