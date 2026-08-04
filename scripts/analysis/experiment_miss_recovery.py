"""Diagnose why B1 misses certain pre-1851 records.

For each B1 miss in the 575 probe, fetch FaG with multiple URL
variants and check if the ground truth appears:

  A. Original (B1 with locationId=country_4 + ACW date window)
  B. B1 with no locationId at all
  C. B1 with locationId=country_4, no date window
  D. B1 with no filters
  E. B10 (birthyearfilter=3)
  F. B10 with no locationId

If the ground truth appears in D but not in A, the issue is
over-filtering. If it appears in C but not A, the date window
is the culprit. If it appears in D but not E, B10 is wrong.

Output: data/diagnosis_results.json + a per-miss breakdown.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).parent.parent.parent
sys.path = [str(ROOT)] + sys.path

from scripts.fag.constants import FAG_SEARCH_BASE_URL
from scripts.fag.filters import (
    apply_location_filter, apply_location_only,
    FAG_COUNTRY_FILTER_US,
)
from scripts.fag.parser import parse_results_page
from scripts.fag.search import setup_browser, warmup_session
from scripts.search.context import SearchContext
from scripts.search.strategies import b1_exact, b10_pre1851_tight


def build_b1_url(ctx: SearchContext, state: str, *,
                 location: str = "country",  # "country" | "none" | "state"
                 date_window: bool = True) -> str:
    """Build a B1 URL with explicit control over location + date filters."""
    params = b1_exact(ctx) or {}
    if location == "none":
        # Strip any locationId the strategy or apply added
        params.pop("locationId", None)
        p = dict(params)
    elif location == "state":
        p = apply_location_filter(params, state)
    elif location == "country":
        p = apply_location_filter(params, state)  # empty state -> country_4
    if not date_window:
        p.pop("birthyear", None)
        p.pop("birthyearfilter", None)
        p.pop("deathyear", None)
        p.pop("deathyearfilter", None)
    return FAG_SEARCH_BASE_URL + "?" + urlencode(p, doseq=True)


def build_b10_url(ctx: SearchContext, state: str, *,
                  location: str = "country") -> str:
    params = b10_pre1851_tight(ctx) or {}
    if location == "none":
        params.pop("locationId", None)
        p = dict(params)
    elif location == "country":
        p = apply_location_filter(params, state)
    p.pop("birthyear", None)
    p.pop("birthyearfilter", None)  # we're testing B10's own filter
    # Actually keep B10's filter -- that's the whole point
    # Re-add since apply_location_filter doesn't strip them
    return FAG_SEARCH_BASE_URL + "?" + urlencode(p, doseq=True)


def main() -> int:
    log = logging.getLogger("diag")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    # Load the 575 probe results
    probe = json.load(open(ROOT / "data" / "probe_575.json"))
    # Pick B1 misses: 5 pre-1851 + 5 other (different from earlier samples)
    pre_misses = [r for r in probe
                  if not r.get("b1_hit") and r.get("bucket") == "pre1851"
                  and r.get("fallback_strategy") == "B10-pre1851-tight"
                  and not r.get("any_error")][:5]
    other_misses = [r for r in probe
                    if not r.get("b1_hit") and r.get("bucket") == "other"
                    and r.get("fallback_strategy") == "C1-cw-context"
                    and not r.get("any_error")][:5]
    sample = pre_misses + other_misses
    print(f"=== Diagnosis: {len(sample)} B1 misses ===")
    for r in sample:
        bucket = "PRE" if r.get("bucket") == "pre1851" else "OTH"
        print(f"  [{bucket}] soldier {r['soldier_id']}: {r['name']} "
              f"state='{r.get('state','')}' truth={r['truth']}")

    variants = [
        ("A.orig",       "country", True),    # what B1+filter currently sends
        ("B.no_loc",     "none",    True),    # strip locationId only
        ("C.no_date",    "country", False),   # strip date window
        ("D.bare",       "none",    False),   # B1 with no filters at all
    ]

    from playwright.sync_api import sync_playwright
    last_request = 0.0
    THROTTLE = 2.5
    results = []

    with sync_playwright() as pw:
        browser, ctx, page = setup_browser(pw)
        warmup_session(page, log)
        try:
            for ri, r in enumerate(sample):
                # Reconstruct the SearchContext from the probe
                # We need first/middle/last/death_year/state
                # Pull from dixiedata.db
                con = sqlite3.connect(ROOT / "dixiedata.db")
                cur = con.cursor()
                cur.execute("""SELECT first_name, middle_name, last_name,
                                      death_year, buried_in
                               FROM soldiers WHERE id=?""",
                            (r["soldier_id"],))
                row = cur.fetchone()
                con.close()
                fn, mn, ln, dy, buried = row
                state = ""
                if buried and "," in buried:
                    tail = buried.rsplit(",", 1)[-1].strip().upper()
                    if len(tail) == 2 and tail.isalpha():
                        state = tail
                search_ctx = SearchContext(
                    first=fn or "", middle=mn or "", last=ln or "",
                    birth_year="",  # B1 doesn't need birth
                    death_year=str(dy or ""),
                    state=state,
                )

                record_result = {
                    "soldier_id": r["soldier_id"],
                    "name": r["name"],
                    "truth": r["truth"],
                    "bucket": r.get("bucket"),
                    "state": state,
                    "variants": {},
                }
                for vname, loc, dw in variants:
                    url = build_b1_url(search_ctx, state, location=loc, date_window=dw)
                    record_result["variants"][vname] = {"url": url}
                    now = time.time()
                    gap = now - last_request
                    if gap < THROTTLE:
                        time.sleep(THROTTLE - gap)
                    last_request = time.time()
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=20000)
                        total, candidates = parse_results_page(page)
                        ids = [c.get("memorial_id", "") for c in candidates]
                        hit = r["truth"] in ids
                        rank = ids.index(r["truth"]) + 1 if hit else None
                        record_result["variants"][vname].update({
                            "cands": len(candidates),
                            "total": total,
                            "hit": hit,
                            "rank": rank,
                        })
                    except Exception as e:
                        log.warning("%s error: %s", vname, e)
                        # L2: full reset
                        try:
                            page.close()
                            ctx.close()
                            browser.close()
                        except Exception:
                            pass
                        browser, ctx, page = setup_browser(pw)
                        warmup_session(page, log)
                        last_request = time.time()
                        record_result["variants"][vname]["error"] = str(e)[:120]
                results.append(record_result)
                # Per-record summary
                line = f"  [{ri+1}/{len(sample)}] {r['name']}:"
                for vname, _, _ in variants:
                    v = record_result["variants"][vname]
                    if "hit" in v:
                        marker = f"HIT@{v['rank']}" if v["hit"] else f"miss({v['cands']})"
                    else:
                        marker = "ERR"
                    line += f" {vname.split('.')[1]}={marker}"
                print(line)
        finally:
            try:
                page.close()
                ctx.close()
                browser.close()
            except Exception:
                pass

    # Save
    out = ROOT / "data" / "diagnosis_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults: {out}")

    # Summary
    print(f"\n=== Diagnosis summary ===")
    for vname, _, _ in variants:
        n_hit = sum(1 for r in results
                    if r["variants"][vname].get("hit"))
        n_total = sum(1 for r in results
                      if "hit" in r["variants"][vname])
        print(f"  {vname}: {n_hit}/{n_total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
