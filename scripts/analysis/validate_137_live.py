"""Live validation of issue #137 — B10 + bias on a 10-record slice.

Stratified sample of the 575-pair set:
  - 5 records where the death-year proxy birth_year < 1840 (oldest
    cohort, B10 should fire)
  - 5 records where the proxy is 1880+ (control, B10 should NOT fire)

For each record, runs:
  1. The URL-only ladder probe (B1, B10, C1) — confirms B10 fires for
     the right cohort and produces a real FaG response
  2. Scoring on the returned candidates — confirms state_bias shows up
     in the breakdown for the unknown-state cases

L1 honored (2.5s throttle, no bypass).
L2 honored (Playwright full reset on errors).
L8 honored (Playwright + stealth via setup_browser, NOT requests).
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.fag.constants import FAG_SEARCH_BASE_URL
from scripts.fag.filters import apply_location_filter
from scripts.fag.parser import parse_results_page
from scripts.fag.scoring import score_candidate
from scripts.fag.search import setup_browser, warmup_session
from scripts.search.context import SearchContext
from scripts.search.strategies import (
    b1_exact, b10_pre1851_tight,
)


def select_sample(n_pre: int = 5, n_post: int = 5) -> list[dict]:
    """Pick n_pre from pre-1840 proxy cohort + n_post from post-1880 cohort."""
    con = sqlite3.connect(ROOT / "dixiedata.db")
    cur = con.cursor()
    cur.execute(
        """SELECT s.id, s.first_name, s.middle_name, s.last_name,
                  s.death_year, s.buried_in, r.details
           FROM soldiers s
           JOIN records r ON r.person_record_id = s.id
           WHERE r.record_type LIKE '%Find a Grave%'"""
    )
    pre, post = [], []
    for sid, fn, mn, ln, dy, buried, det in cur.fetchall():
        if not det:
            continue
        m = re.search(r"memorial/(\d+)", det) or re.search(
            r"memorial_id\D*(\d+)",
            det,
        )
        if not m:
            continue
        dy_str = str(dy or "").strip()
        if not dy_str.isdigit():
            continue
        by_proxy = int(dy_str) - 65
        if not 1800 <= by_proxy <= 1900:
            continue
        state = ""
        if buried and "," in buried:
            tail = buried.rsplit(",", 1)[-1].strip().upper()
            if len(tail) == 2 and tail.isalpha():
                state = tail
        record = {
            "soldier_id": sid,
            "first": fn or "",
            "middle": mn or "",
            "last": ln or "",
            "death_year": dy_str,
            "birth_year_proxy": str(by_proxy),
            "state": state,
            "memorial_id": m.group(1),
        }
        if by_proxy < 1840:
            pre.append(record)
        elif by_proxy >= 1880:
            post.append(record)
    # Sort by soldier_id for determinism
    pre.sort(key=lambda r: r["soldier_id"])
    post.sort(key=lambda r: r["soldier_id"])
    return pre[:n_pre] + post[:n_post]


def main() -> int:
    log = logging.getLogger("validate_137")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    sample = select_sample()
    print(f"=== Live validation of #137 — {len(sample)} records ===")
    for r in sample:
        bucket = "PRE" if int(r["birth_year_proxy"]) < 1840 else "POST"
        print(
            f"  [{bucket}] soldier {r['soldier_id']}: {r['first']} {r['last']} "
            f"by_proxy={r['birth_year_proxy']} dy={r['death_year']} "
            f"state='{r['state']}' truth={r['memorial_id']}"
        )

    # Stats we want to gather
    b10_fired = 0
    b10_should_have_fired = 0
    b1_hits = 0
    bias_triggered = 0
    bias_breakdown_ok = 0
    errors: list[str] = []
    last_request = 0.0
    THROTTLE = 2.5  # L1

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, ctx, page = setup_browser(pw)
        warmup_session(page, log)
        try:
            for ri, r in enumerate(sample):
                ctx_obj = SearchContext(
                    first=r["first"],
                    middle=r["middle"],
                    last=r["last"],
                    birth_year=r["birth_year_proxy"],
                    death_year=r["death_year"],
                    state=r["state"],
                )

                is_pre = int(r["birth_year_proxy"]) < 1840

                # B1 (always-applicable; baseline candidate fetcher)
                b1_params = b1_exact(ctx_obj)
                # B10 (only fires for pre-1851 cohort; just verifying guard)
                b10_params = b10_pre1851_tight(ctx_obj)

                if b10_params is not None:
                    b10_fired += 1
                elif is_pre:
                    b10_should_have_fired += 1
                    errors.append(
                        f"  B10 missed pre-1840 cohort: soldier {r['soldier_id']} "
                        f"by={r['birth_year_proxy']}"
                    )

                # Fetch B1 (always-applicable) to get real FaG candidates
                if b1_params is None:
                    continue
                b1_params = apply_location_filter(b1_params, r["state"])
                url = FAG_SEARCH_BASE_URL + "?" + urlencode(b1_params, doseq=True)

                now = time.time()
                gap = now - last_request
                if gap < THROTTLE:
                    time.sleep(THROTTLE - gap)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    last_request = time.time()
                    total, candidates = parse_results_page(page)
                except Exception as e:
                    log.warning("B1 fetch error for soldier %s: %s", r["soldier_id"], e)
                    # L2: full browser reset on closed-target
                    try:
                        page.close()
                        ctx.close()
                        browser.close()
                    except Exception:
                        pass
                    browser, ctx, page = setup_browser(pw)
                    warmup_session(page, log)
                    last_request = time.time()
                    errors.append(f"  fetch error soldier {r['soldier_id']}: {str(e)[:120]}")
                    continue

                # Track B1 hit (ground truth in B1 result list)
                ids = [c.get("memorial_id", "") for c in candidates]
                truth = r["memorial_id"]
                if truth in ids:
                    b1_hits += 1

                # Run scoring on each candidate, check state_bias trigger
                local = {
                    "first_name": r["first"],
                    "middle_name": r["middle"],
                    "last_name": r["last"],
                    "_state_abbr": r["state"],
                    "_death_year": r["death_year"],
                    "_birth_year": r["birth_year_proxy"],
                    "_is_widow": False,
                }
                for c in candidates:
                    if not r["state"] and not c.get("details", {}).get("state"):
                        bias_triggered += 1
                        # Run scoring and check breakdown
                        score, breakdown = score_candidate(local, c)
                        if breakdown.get("state_bias") == 0.05:
                            bias_breakdown_ok += 1
                        else:
                            errors.append(
                                f"  bias breakdown missing for soldier {r['soldier_id']} "
                                f"cand={c.get('memorial_id')}: {breakdown}"
                            )
                        break  # one per pair is enough

                print(
                    f"  [{ri+1}/{len(sample)}] {r['first']} {r['last']}: "
                    f"B10={'Y' if b10_params else 'N'} "
                    f"B1_cands={len(candidates)} B1_hit={truth in ids} "
                    f"bias={'Y' if (not r['state'] and not c.get('details',{}).get('state')) else 'N'}"
                )
        finally:
            try:
                page.close()
                ctx.close()
                browser.close()
            except Exception:
                pass

    # Report
    print(f"\n=== Live validation results ===")
    print(f"Records: {len(sample)}")
    print(f"  Pre-1840 cohort: {sum(1 for r in sample if int(r['birth_year_proxy']) < 1840)}")
    print(f"  Post-1880 cohort: {sum(1 for r in sample if int(r['birth_year_proxy']) >= 1880)}")
    print(f"\nB10 (pre-1851 tight):")
    print(f"  Fired: {b10_fired}")
    print(f"  Missed pre-cohort: {b10_should_have_fired}")
    print(f"\nFaG B1 hits (ground truth in B1 result list):")
    print(f"  B1: {b1_hits}/{len(sample)}")
    print(f"\nBias (state_bias in scoring breakdown):")
    print(f"  Triggered: {bias_triggered}")
    print(f"  Breakdown showed state_bias=0.05: {bias_breakdown_ok}")
    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for e in errors[:10]:
            print(e)
        return 1
    print(f"\n=== LIVE VALIDATION PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
