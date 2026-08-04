"""Quick variant of probe_575_capped.py: pass state="" to apply_location_filter.

Tests the hypothesis that NO locationId at all is the right default
(matches the user's intuition: don't add location info when burial
is unknown).
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
from scripts.fag.filters import apply_location_filter
from scripts.fag.parser import parse_results_page
from scripts.fag.search import setup_browser, warmup_session
from scripts.search.context import SearchContext
from scripts.search.strategies import b1_exact, b10_pre1851_tight, c1_cw_context


def build_input() -> list[dict]:
    con = sqlite3.connect(ROOT / "dixiedata.db")
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
            # NO state at all (always global)
            "state": "",
        })
    return soldiers


def run_one(page, ctx, record: dict, log) -> dict:
    search_ctx = SearchContext(
        first=record["first"],
        middle=record["middle"],
        last=record["last"],
        birth_year="",
        death_year=record["death_year"],
        state="",  # always empty
    )
    result = {
        "soldier_id": record["soldier_id"],
        "name": f"{record['first']} {record['last']}".strip(),
        "truth": record["memorial_id"],
        "bucket": record["bucket"],
        "b1_fired": False, "b1_cands": 0, "b1_hit": False,
        "fallback_strategy": None, "fallback_fired": False,
        "fallback_cands": 0, "fallback_hit": False,
        "any_error": False, "error": None,
    }
    b1_params = b1_exact(search_ctx)
    if b1_params is None:
        return result
    result["b1_fired"] = True
    b1_params_with_loc = apply_location_filter(b1_params, "")
    url = FAG_SEARCH_BASE_URL + "?" + urlencode(b1_params_with_loc, doseq=True)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        total, candidates = parse_results_page(page)
    except Exception as e:
        result["any_error"] = True
        result["error"] = f"B1: {str(e)[:120]}"
        return result
    result["b1_cands"] = len(candidates)
    if record["memorial_id"] in [c.get("memorial_id", "") for c in candidates]:
        result["b1_hit"] = True
        return result
    if record["bucket"] == "pre1851":
        fb_name = "B10-pre1851-tight"
        fb_params = b10_pre1851_tight(search_ctx)
    else:
        fb_name = "C1-cw-context"
        fb_params = c1_cw_context(search_ctx)
    result["fallback_strategy"] = fb_name
    if fb_params is None:
        return result
    result["fallback_fired"] = True
    fb_params_with_loc = apply_location_filter(fb_params, "")
    url = FAG_SEARCH_BASE_URL + "?" + urlencode(fb_params_with_loc, doseq=True)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        total, candidates = parse_results_page(page)
    except Exception as e:
        result["any_error"] = True
        result["error"] = f"{fb_name}: {str(e)[:120]}"
        return result
    result["fallback_cands"] = len(candidates)
    if record["memorial_id"] in [c.get("memorial_id", "") for c in candidates]:
        result["fallback_hit"] = True
    return result


def main() -> int:
    log = logging.getLogger("probe_no_state")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    soldiers = build_input()
    print(f"=== Probe: state='' always (NO locationId) ===")
    print(f"  records: {len(soldiers)}")
    est = len(soldiers) * 1.2 * 2.5
    print(f"  est wall: ~{est/60:.0f} min @ 2.5s")

    from playwright.sync_api import sync_playwright

    results = []
    last_request = 0.0
    with sync_playwright() as pw:
        browser, ctx, page = setup_browser(pw)
        warmup_session(page, log)
        try:
            for si, r in enumerate(soldiers):
                now = time.time()
                gap = now - last_request
                if gap < 2.5:
                    time.sleep(2.5 - gap)
                last_request = time.time()
                try:
                    result = run_one(page, ctx, r, log)
                except Exception as e:
                    log.error("Error soldier %s: %s", r["soldier_id"], e)
                    try:
                        page.close(); ctx.close(); browser.close()
                    except Exception:
                        pass
                    browser, ctx, page = setup_browser(pw)
                    warmup_session(page, log)
                    last_request = time.time()
                    result = {"soldier_id": r["soldier_id"], "any_error": True,
                              "error": f"unhandled: {str(e)[:120]}"}
                results.append(result)
                if (si+1) % 50 == 0 or si == len(soldiers)-1:
                    print(f"  [{si+1}/{len(soldiers)}] errors={sum(1 for x in results if x.get('any_error'))}")
        finally:
            try: page.close(); ctx.close(); browser.close()
            except Exception: pass

    out = ROOT / "data" / "probe_575_no_state.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults: {out}")

    total = len(results)
    errors = sum(1 for r in results if r.get("any_error"))
    b1_hits = sum(1 for r in results if r.get("b1_hit"))
    b1_missed = total - b1_hits - errors
    fb_ran = [r for r in results if r.get("fallback_strategy")]
    fb_hits = sum(1 for r in fb_ran if r.get("fallback_hit"))
    cumulative = b1_hits + fb_hits
    print(f"\n=== Summary (no locationId) ===")
    print(f"Total: {total}, Errors: {errors}")
    print(f"B1 hit: {b1_hits}/{total} ({b1_hits/total*100:.1f}%)")
    print(f"Fallback hit: {fb_hits}/{len(fb_ran)}")
    print(f"Cumulative: {cumulative}/{total} ({cumulative/total*100:.1f}%)")
    for bucket in ("pre1851", "other"):
        br = [r for r in results if r.get("bucket") == bucket]
        if not br: continue
        n = len(br)
        bh = sum(1 for r in br if r.get("b1_hit"))
        fbr = [r for r in br if r.get("fallback_strategy")]
        fh = sum(1 for r in fbr if r.get("fallback_hit"))
        cum = bh + fh
        print(f"  {bucket} (n={n}): B1={bh}/{n} ({bh/n*100:.1f}%) "
              f"FB={fh}/{len(fbr) if fbr else 0} "
              f"Cumulative={cum}/{n} ({cum/n*100:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
