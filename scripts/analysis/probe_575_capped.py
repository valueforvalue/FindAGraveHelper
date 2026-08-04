"""Full 575-record probe with first-hit-stops optimization.

The existing probe_strategy_yield.py runs ALL strategies per
soldier (575 x 11 x 2.5s = ~4.4 hours). For #137 validation
we only need:

1. Does B1 hit? (already known to be ~93% per docs)
2. For B1 misses, does B10 fire AND hit (for pre-1851 cohort)?
3. For B1 misses, does C1 fire AND hit (for everyone else)?

This script caps at 2 strategies per record: B1 + one targeted
fallback (B10 if pre-1851, C1 otherwise). Stops on first hit
or first miss-with-no-candidates.

Estimated wall time: ~30 min (575 records x ~1.2 strategies x
2.5s throttle).

Honors L1 (2.5s throttle, no bypass), L2 (full browser reset
on closed-target), L8 (Playwright + stealth).
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).parent.parent.parent
DB = ROOT / "dixiedata.db"

from scripts.fag.constants import FAG_SEARCH_BASE_URL
from scripts.fag.filters import apply_location_filter
from scripts.fag.parser import parse_results_page
from scripts.fag.scoring import score_candidate
from scripts.fag.search import setup_browser, warmup_session
from scripts.search.context import SearchContext
from scripts.search.strategies import (
    b1_exact, b10_pre1851_tight, c1_cw_context,
)


def build_input() -> list[dict]:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute(
        """SELECT s.id, s.first_name, s.middle_name, s.last_name,
                  s.death_year, s.buried_in, r.details
           FROM soldiers s
           JOIN records r ON r.person_record_id = s.id
           WHERE r.record_type LIKE '%Find a Grave%'"""
    )
    soldiers = []
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
        state = ""
        if buried and "," in buried:
            tail = buried.rsplit(",", 1)[-1].strip().upper()
            if len(tail) == 2 and tail.isalpha():
                state = tail
        dy_str = str(dy or "").strip()
        by_proxy = ""
        if dy_str.isdigit():
            by = int(dy_str) - 65
            if 1800 <= by <= 1900:
                by_proxy = str(by)
        bucket = "pre1851" if by_proxy and int(by_proxy) < 1851 else "other"
        soldiers.append({
            "soldier_id": sid,
            "first": fn or "",
            "middle": mn or "",
            "last": ln or "",
            "death_year": dy_str,
            "memorial_id": m.group(1),
            "bucket": bucket,
            "state": state,
        })
    return soldiers


def run_one(page, ctx, record: dict, log) -> dict:
    """Run B1, then targeted fallback (B10 or C1) if B1 misses.

    Returns a per-soldier result dict.
    """
    search_ctx = SearchContext(
        first=record["first"],
        middle=record["middle"],
        last=record["last"],
        birth_year="",  # B1 doesn't use birth_year; we use proxy only
                         # for the bucket check, not as input
        death_year=record["death_year"],
        state=record["state"],
    )

    result = {
        "soldier_id": record["soldier_id"],
        "name": f"{record['first']} {record['last']}".strip(),
        "truth": record["memorial_id"],
        "bucket": record["bucket"],
        "state": record["state"],
        "b1_fired": False,
        "b1_cands": 0,
        "b1_hit": False,
        "b1_bias_in_top1": False,
        "fallback_strategy": None,
        "fallback_fired": False,
        "fallback_cands": 0,
        "fallback_hit": False,
        "fallback_bias_in_top1": False,
        "any_error": False,
        "error": None,
    }

    # B1
    b1_params = b1_exact(search_ctx)
    if b1_params is None:
        return result
    result["b1_fired"] = True
    b1_params_with_loc = apply_location_filter(b1_params, record["state"])
    url = FAG_SEARCH_BASE_URL + "?" + urlencode(b1_params_with_loc, doseq=True)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        total, candidates = parse_results_page(page)
    except Exception as e:
        result["any_error"] = True
        result["error"] = f"B1: {str(e)[:120]}"
        return result

    result["b1_cands"] = len(candidates)
    ids = [c.get("memorial_id", "") for c in candidates]
    if record["memorial_id"] in ids:
        result["b1_hit"] = True
        return result

    # Score B1 top candidate, check bias
    if candidates:
        top = candidates[0]
        local = {
            "first_name": record["first"],
            "middle_name": record["middle"],
            "last_name": record["last"],
            "_state_abbr": record["state"],
            "_death_year": record["death_year"],
            "_birth_year": "",
            "_is_widow": False,
        }
        try:
            _, breakdown = score_candidate(local, top)
            if breakdown.get("state_bias") == 0.05:
                result["b1_bias_in_top1"] = True
        except Exception as e:
            log.warning("B1 scoring error: %s", e)

    # Targeted fallback
    if record["bucket"] == "pre1851":
        fb_strategy_name = "B10-pre1851-tight"
        fb_params = b10_pre1851_tight(search_ctx)
    else:
        fb_strategy_name = "C1-cw-context"
        fb_params = c1_cw_context(search_ctx)
    result["fallback_strategy"] = fb_strategy_name

    if fb_params is None:
        return result
    result["fallback_fired"] = True
    fb_params_with_loc = apply_location_filter(fb_params, record["state"])
    url = FAG_SEARCH_BASE_URL + "?" + urlencode(fb_params_with_loc, doseq=True)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        total, candidates = parse_results_page(page)
    except Exception as e:
        result["any_error"] = True
        result["error"] = f"{fb_strategy_name}: {str(e)[:120]}"
        return result

    result["fallback_cands"] = len(candidates)
    ids = [c.get("memorial_id", "") for c in candidates]
    if record["memorial_id"] in ids:
        result["fallback_hit"] = True

    # Score fallback top candidate, check bias
    if candidates:
        top = candidates[0]
        local = {
            "first_name": record["first"],
            "middle_name": record["middle"],
            "last_name": record["last"],
            "_state_abbr": record["state"],
            "_death_year": record["death_year"],
            "_birth_year": "",
            "_is_widow": False,
        }
        try:
            _, breakdown = score_candidate(local, top)
            if breakdown.get("state_bias") == 0.05:
                result["fallback_bias_in_top1"] = True
        except Exception as e:
            log.warning("Fallback scoring error: %s", e)

    return result


def main() -> int:
    log = logging.getLogger("probe_575")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap records (for testing)")
    parser.add_argument("--throttle", type=float, default=2.5)
    parser.add_argument("--output", type=Path,
                        default=Path("data/probe_results_575.json"))
    parser.add_argument("--input", type=Path, default=None,
                        help="Use a pre-built input file instead of building fresh")
    args = parser.parse_args()

    if args.input:
        with open(args.input) as f:
            soldiers = json.load(f)
    else:
        soldiers = build_input()
    if args.limit:
        soldiers = soldiers[:args.limit]
    print(f"=== Full {len(soldiers)}-record probe (B1 + targeted fallback) ===")
    n_pre = sum(1 for s in soldiers if s["bucket"] == "pre1851")
    n_other = len(soldiers) - n_pre
    print(f"  pre-1851 cohort: {n_pre}")
    print(f"  other: {n_other}")
    est = len(soldiers) * 1.2 * args.throttle  # avg ~1.2 strategies
    print(f"  estimated wall: ~{est/60:.0f} min @ {args.throttle}s throttle")

    from playwright.sync_api import sync_playwright

    results = []
    last_request = 0.0
    with sync_playwright() as pw:
        browser, ctx, page = setup_browser(pw)
        warmup_session(page, log)
        try:
            for si, r in enumerate(soldiers):
                # Throttle
                now = time.time()
                gap = now - last_request
                if gap < args.throttle:
                    time.sleep(args.throttle - gap)
                last_request = time.time()
                try:
                    result = run_one(page, ctx, r, log)
                except Exception as e:
                    log.error("Unhandled error for soldier %s: %s", r["soldier_id"], e)
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
                    result = {
                        "soldier_id": r["soldier_id"],
                        "name": f"{r['first']} {r['last']}".strip(),
                        "truth": r["memorial_id"],
                        "any_error": True,
                        "error": f"unhandled: {str(e)[:120]}",
                    }
                results.append(result)
                if (si + 1) % 25 == 0 or si == len(soldiers) - 1:
                    pct = (si + 1) / len(soldiers) * 100
                    print(f"  [{si+1}/{len(soldiers)} {pct:.0f}%] "
                          f"errors={sum(1 for x in results if x.get('any_error'))}")
        finally:
            try:
                page.close()
                ctx.close()
                browser.close()
            except Exception:
                pass

    # Save
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {args.output}")

    # Summary
    total = len(results)
    errors = sum(1 for r in results if r.get("any_error"))
    b1_hits = sum(1 for r in results if r.get("b1_hit"))
    b1_missed = total - b1_hits - errors
    fb_ran = [r for r in results if r.get("fallback_strategy")]
    fb_hits = sum(1 for r in fb_ran if r.get("fallback_hit"))
    b1_bias = sum(1 for r in results if r.get("b1_bias_in_top1"))
    fb_bias = sum(1 for r in fb_ran if r.get("fallback_bias_in_top1"))

    # Cumulative hit rate
    cumulative_hits = b1_hits + fb_hits
    cumulative_pct = cumulative_hits / total * 100 if total else 0

    print(f"\n=== Summary ===")
    print(f"Total: {total}")
    print(f"Errors: {errors}")
    print(f"B1 hit: {b1_hits}/{total} ({b1_hits/total*100:.1f}%)")
    print(f"B1 missed (clean): {b1_missed}")
    print(f"Fallbacks run: {len(fb_ran)}")
    print(f"Fallback hit: {fb_hits}/{len(fb_ran)} ({fb_hits/len(fb_ran)*100 if fb_ran else 0:.1f}%)")
    print(f"Cumulative: {cumulative_hits}/{total} ({cumulative_pct:.1f}%)")
    print(f"B1 bias in top-1: {b1_bias}")
    print(f"Fallback bias in top-1: {fb_bias}")

    # Per-bucket
    for bucket in ("pre1851", "other"):
        bucket_results = [r for r in results if r.get("bucket") == bucket]
        if not bucket_results:
            continue
        n = len(bucket_results)
        b1_h = sum(1 for r in bucket_results if r.get("b1_hit"))
        fb_ran_b = [r for r in bucket_results if r.get("fallback_strategy")]
        fb_h = sum(1 for r in fb_ran_b if r.get("fallback_hit"))
        cum = b1_h + fb_h
        print(f"\n  {bucket} cohort (n={n}):")
        print(f"    B1: {b1_h}/{n} ({b1_h/n*100:.1f}%)")
        if fb_ran_b:
            print(f"    Fallback: {fb_h}/{len(fb_ran_b)} ({fb_h/len(fb_ran_b)*100:.1f}%)")
        print(f"    Cumulative: {cum}/{n} ({cum/n*100:.1f}%)")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
