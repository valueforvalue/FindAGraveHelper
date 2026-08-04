"""URL-shape validator for all v5 strategies.

For each of the 11 strategies (10 generic + B10), builds the URL
with a sample pensioner, fetches FaG, and reports:
  - URL validity (FaG returned a results page)
  - Page-1 result count
  - Whether the truth memorial_id (if known) appears
  - Any error (Cloudflare block, parse error, etc.)

Reuses the diagnosis harness pattern from
scripts/analysis/experiment_miss_recovery.py. This is the
"systematic test of every strategy's URL against real FaG" that
the user requested after the 137 follow-up probes.

Why this exists: the 137 diagnosis showed that one URL parameter
(locationId) was excluding truth from results on some records.
A broader sweep can catch similar URL-shape bugs across all 11
strategies before they cost a full run.

Honors L1 (2.5s throttle), L2 (full browser reset on errors),
L8 (Playwright + stealth).
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).parent.parent.parent
sys.path = [str(ROOT)] + sys.path

from scripts.fag.constants import FAG_SEARCH_BASE_URL
from scripts.fag.filters import apply_location_filter
from scripts.fag.parser import parse_results_page
from scripts.fag.search import setup_browser, warmup_session
from scripts.search.context import SearchContext
from scripts.search.strategies import STRATEGIES


def build_sample(n: int = 20) -> list[dict]:
    """Pick n pensioner records from the 575-pair set, stratified
    so each strategy gets a representative mix of cohorts."""
    con = sqlite3.connect(ROOT / "dixiedata.db")
    cur = con.cursor()
    cur.execute(
        """SELECT s.id, s.first_name, s.middle_name, s.last_name,
                  s.death_year, s.buried_in, r.details
           FROM soldiers s
           JOIN records r ON r.person_record_id = s.id
           WHERE r.record_type LIKE '%Find a Grave%'"""
    )
    rows = []
    seen = set()
    for sid, fn, mn, ln, dy, buried, det in cur.fetchall():
        if not det:
            continue
        m = re.search(r"memorial/(\d+)", det) or re.search(
            r"memorial_id\D*(\d+)",
            det,
        )
        if not m:
            continue
        key = (sid, m.group(1))
        if key in seen:
            continue
        seen.add(key)
        dy_str = str(dy or "").strip()
        by_proxy = ""
        if dy_str.isdigit():
            by = int(dy_str) - 65
            if 1800 <= by <= 1900:
                by_proxy = str(by)
        bucket = "pre1851" if by_proxy and int(by_proxy) < 1851 else "other"
        # State: production-equivalent (OK for OK pensioners)
        state = "OK"
        rows.append({
            "soldier_id": sid,
            "first": fn or "",
            "middle": mn or "",
            "last": ln or "",
            "death_year": dy_str,
            "birth_year_proxy": by_proxy,
            "memorial_id": m.group(1),
            "bucket": bucket,
            "state": state,
        })
    # Sort + take first n
    rows.sort(key=lambda r: r["soldier_id"])
    return rows[:n]


def make_search_context(record: dict) -> SearchContext:
    return SearchContext(
        first=record["first"],
        middle=record["middle"],
        last=record["last"],
        birth_year=record["birth_year_proxy"],
        death_year=record["death_year"],
        state=record["state"],
    )


def main() -> int:
    log = logging.getLogger("validate_urls")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    sample = build_sample(n=20)
    print(f"=== URL-shape validator: {len(STRATEGIES)} strategies × "
          f"{len(sample)} records = {len(STRATEGIES) * len(sample)} fetches ===")
    est = len(STRATEGIES) * len(sample) * 2.5
    print(f"  est wall: ~{est/60:.0f} min @ 2.5s throttle")
    n_pre = sum(1 for r in sample if r["bucket"] == "pre1851")
    print(f"  pre-1851: {n_pre}, other: {len(sample) - n_pre}")

    from playwright.sync_api import sync_playwright

    results: list[dict] = []  # one per (strategy, record)
    last_request = 0.0
    THROTTLE = 2.5

    with sync_playwright() as pw:
        browser, ctx, page = setup_browser(pw)
        warmup_session(page, log)
        try:
            for si, strat in enumerate(STRATEGIES):
                strat_name = strat.name
                print(f"\n  Strategy {si+1}/{len(STRATEGIES)}: {strat_name}")
                for ri, r in enumerate(sample):
                    search_ctx = make_search_context(r)
                    try:
                        params = strat.params(search_ctx)
                    except Exception as e:
                        log.warning("%s raised for soldier %s: %s",
                                    strat_name, r["soldier_id"], e)
                        results.append({
                            "strategy": strat_name,
                            "soldier_id": r["soldier_id"],
                            "soldier_name": f"{r['first']} {r['last']}",
                            "bucket": r["bucket"],
                            "applies": False,
                            "error": f"params raised: {str(e)[:80]}",
                        })
                        continue
                    if params is None:
                        results.append({
                            "strategy": strat_name,
                            "soldier_id": r["soldier_id"],
                            "soldier_name": f"{r['first']} {r['last']}",
                            "bucket": r["bucket"],
                            "applies": False,
                            "error": "not_applicable",
                        })
                        continue
                    # Apply location filter
                    try:
                        params_with_loc = apply_location_filter(
                            params, r["state"],
                        )
                    except Exception as e:
                        log.warning("filter raised: %s", e)
                        results.append({
                            "strategy": strat_name,
                            "soldier_id": r["soldier_id"],
                            "soldier_name": f"{r['first']} {r['last']}",
                            "bucket": r["bucket"],
                            "applies": True,
                            "error": f"filter raised: {str(e)[:80]}",
                        })
                        continue
                    url = FAG_SEARCH_BASE_URL + "?" + urlencode(
                        params_with_loc, doseq=True,
                    )

                    # Throttle
                    now = time.time()
                    gap = now - last_request
                    if gap < THROTTLE:
                        time.sleep(THROTTLE - gap)
                    last_request = time.time()

                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=20000)
                        total, candidates = parse_results_page(page)
                    except Exception as e:
                        log.warning("fetch error %s/%s: %s",
                                    strat_name, r["soldier_id"], e)
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
                        results.append({
                            "strategy": strat_name,
                            "soldier_id": r["soldier_id"],
                            "soldier_name": f"{r['first']} {r['last']}",
                            "bucket": r["bucket"],
                            "applies": True,
                            "url": url,
                            "error": f"fetch: {str(e)[:80]}",
                        })
                        continue

                    ids = [c.get("memorial_id", "") for c in candidates]
                    truth = r["memorial_id"]
                    hit = truth in ids
                    rank = ids.index(truth) + 1 if hit else None
                    results.append({
                        "strategy": strat_name,
                        "soldier_id": r["soldier_id"],
                        "soldier_name": f"{r['first']} {r['last']}",
                        "bucket": r["bucket"],
                        "applies": True,
                        "url": url,
                        "cands": len(candidates),
                        "hit": hit,
                        "rank": rank,
                    })
                # Per-strategy progress
                s_results = [x for x in results if x["strategy"] == strat_name]
                applies = sum(1 for x in s_results if x.get("applies"))
                fetched = sum(1 for x in s_results
                              if x.get("applies") and "cands" in x)
                hits = sum(1 for x in s_results if x.get("hit"))
                errors = sum(1 for x in s_results if x.get("error"))
                print(f"    applies={applies}/{len(sample)} "
                      f"fetched={fetched} hits={hits} errors={errors}")
        finally:
            try:
                page.close()
                ctx.close()
                browser.close()
            except Exception:
                pass

    # Save
    out = ROOT / "data" / "strategy_url_validation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults: {out}")

    # Per-strategy summary
    print(f"\n=== Per-strategy summary ===")
    by_strat = defaultdict(list)
    for r in results:
        by_strat[r["strategy"]].append(r)
    print(f"{'strategy':<25} {'applies':>8} {'fetched':>8} {'hits':>6} "
          f"{'hit_rate':>9} {'errors':>7} {'mean_cands':>10}")
    for strat_name, srs in by_strat.items():
        applies = sum(1 for r in srs if r.get("applies"))
        fetched = [r for r in srs if r.get("applies") and "cands" in r]
        hits = sum(1 for r in fetched if r.get("hit"))
        errors = sum(1 for r in srs if r.get("error"))
        cands = [r["cands"] for r in fetched]
        mean_cands = sum(cands) / len(cands) if cands else 0
        hit_rate = hits / len(fetched) * 100 if fetched else 0
        print(f"{strat_name:<25} {applies:>8} {len(fetched):>8} "
              f"{hits:>6} {hit_rate:>8.1f}% {errors:>7} {mean_cands:>10.1f}")

    # Sanity checks
    print(f"\n=== Sanity checks ===")
    zero_results = [r for r in results
                    if r.get("applies") and r.get("cands") == 0]
    if zero_results:
        print(f"  WARN: {len(zero_results)} (strategy, record) pairs returned "
              f"ZERO results. May indicate URL filter too tight.")
        for r in zero_results[:5]:
            print(f"    {r['strategy']} on {r['soldier_name']}: {r.get('url','')[:120]}")
    huge_results = [r for r in results
                    if r.get("applies") and r.get("cands", 0) > 100]
    if huge_results:
        print(f"  WARN: {len(huge_results)} pairs returned >100 results. "
              f"Filter not narrowing enough.")
    error_results = [r for r in results if r.get("error")]
    if error_results:
        print(f"  WARN: {len(error_results)} pairs had errors.")
        err_counter = Counter(r["error"][:40] for r in error_results)
        for err, count in err_counter.most_common(5):
            print(f"    {count}x: {err}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
