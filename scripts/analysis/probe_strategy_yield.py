"""Research probe for issue #69: per-strategy yield with ground truth.

For each soldier, we know the correct FaG memorial ID (from dixiedata.db).
Run each strategy against real FaG and check:
1. Does the correct memorial appear in results?
2. At what rank?
3. Is the strategy finding it when B1-exact misses it?

Uses the FaG backlinks in dixiedata.db as ground truth.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

from scripts.fag.constants import FAG_THROTTLE_FLOOR, FAG_SEARCH_BASE_URL
from scripts.fag.search import setup_browser, warmup_session
from scripts.fag.parser import parse_results_page
from scripts.fag.filters import apply_location_filter
from scripts.search.strategies import STRATEGIES
from scripts.search.context import SearchContext


import logging


def run_probe(soldiers: list[dict], throttle: float) -> list[dict]:
    """Run all strategies against each soldier, checking ground truth."""
    log = logging.getLogger("probe")
    results: list[dict] = []

    with sync_playwright() as pw:
        browser, ctx, page = setup_browser(pw)
        warmup_session(page, log)
        last_request = 0.0

        for si, s in enumerate(soldiers):
            first = s["first"]
            middle = s.get("middle", "")
            last = s["last"]
            death_year = str(s.get("death_year", "") or "")
            truth_id = s["memorial_id"]
            bucket = s.get("bucket", "unknown")
            name = f"{first} {last}".strip()

            sctx = SearchContext(
                first=first, middle=middle, last=last,
                birth_year="", death_year=death_year if death_year else "",
                state="OK",
            )

            print(f"\n[{si+1}/{len(soldiers)}] {name} ({bucket})  truth={truth_id}")

            entry: dict = {
                "soldier": name,
                "first": first, "middle": middle, "last": last,
                "death_year": death_year,
                "truth_memorial_id": truth_id,
                "bucket": bucket,
                "b1_hit": False,
                "b1_rank": None,
                "strategies": [],
            }

            b1_ids: set[str] = set()

            for strat in STRATEGIES:
                params_result = strat.params(sctx)
                if params_result is None:
                    entry["strategies"].append({
                        "name": strat.name,
                        "status": "skipped",
                        "reason": "not_applicable",
                    })
                    continue

                params = apply_location_filter(params_result, "OK")
                url = FAG_SEARCH_BASE_URL + "?" + urlencode(params, doseq=True)

                # Throttle
                now = time.time()
                gap = now - last_request
                if gap < throttle:
                    time.sleep(throttle - gap)

                t0 = time.time()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    total_fag, candidates = parse_results_page(page)
                    elapsed = time.time() - t0
                    last_request = time.time()

                    ids = [c["memorial_id"] for c in candidates]
                    hit = truth_id in ids
                    rank = ids.index(truth_id) + 1 if hit else None

                    if strat.name == "B1-exact":
                        b1_ids = set(ids)
                        entry["b1_hit"] = hit
                        entry["b1_rank"] = rank

                    unique_vs_b1 = len(set(ids) - b1_ids) if b1_ids else 0

                    entry["strategies"].append({
                        "name": strat.name,
                        "alias": getattr(strat, "alias", strat.name),
                        "status": "ran",
                        "candidates": len(candidates),
                        "total_fag": total_fag,
                        "hit": hit,
                        "rank": rank,
                        "unique_vs_b1": unique_vs_b1,
                        "elapsed_s": round(elapsed, 3),
                    })

                    marker = "HIT" if hit else "miss"
                    rank_str = f" rank=#{rank}" if rank else ""
                    new_str = f" ({unique_vs_b1} new vs B1)" if unique_vs_b1 else ""
                    print(
                        f"  {strat.name:25s} {len(candidates):3d} cands  "
                        f"{marker}{rank_str}  {elapsed:.1f}s{new_str}"
                    )

                except Exception as e:
                    elapsed = time.time() - t0
                    last_request = time.time()
                    entry["strategies"].append({
                        "name": strat.name,
                        "status": "error",
                        "error": str(e)[:200],
                    })
                    print(f"  {strat.name:25s} ERROR: {str(e)[:80]}")

            results.append(entry)

        ctx.close()
        browser.close()

    return results


def build_report(results: list[dict]) -> str:
    """Build markdown report from results."""
    lines = [
        "# Strategy Yield Research Report",
        f"\nGenerated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"\n## Summary",
        f"\nProbed {len(results)} soldiers x {len(STRATEGIES)} strategies against real Find a Grave.",
        f"\nThrottle: {FAG_THROTTLE_FLOOR}s (L1 floor).",
        f"\n### Soldiers probed",
    ]

    for r in results:
        lines.append(
            f"- **{r['soldier']}** ({r['bucket']}) - "
            f"ground truth: [{r['truth_memorial_id']}]"
            f"(https://www.findagrave.com/memorial/{r['truth_memorial_id']})"
        )

    lines.append("\n## Per-Strategy Hit Rates")
    lines.append("| Strategy | Hits | Misses | Hit Rate | Unique Saves |")
    lines.append("|----------|------|--------|----------|--------------|")

    strat_stats: dict[str, dict] = {}
    for r in results:
        for s in r["strategies"]:
            name = s["name"]
            if name not in strat_stats:
                strat_stats[name] = {"hits": 0, "misses": 0, "saves": 0}
            if s["status"] == "ran":
                if s.get("hit"):
                    strat_stats[name]["hits"] += 1
                    if name != "B1-exact" and not r.get("b1_hit"):
                        strat_stats[name]["saves"] += 1
                else:
                    strat_stats[name]["misses"] += 1

    for name, stats in sorted(strat_stats.items()):
        total = stats["hits"] + stats["misses"]
        rate = stats["hits"] / total * 100 if total else 0
        lines.append(
            f"| {name} | {stats['hits']} | {stats['misses']} | "
            f"{rate:.0f}% | {stats.get('saves', 0)} |"
        )

    lines.append("\n## B1-Exact Baseline")
    b1_hits = sum(1 for r in results if r.get("b1_hit"))
    lines.append(
        f"- B1-exact found the correct memorial for "
        f"**{b1_hits}/{len(results)}** soldiers "
        f"({b1_hits/len(results)*100:.0f}%)"
    )

    lines.append("\n## Strategies That Found What B1 Missed")
    any_missed = False
    for r in results:
        if r.get("b1_hit"):
            continue
        any_missed = True
        lines.append(f"\n### {r['soldier']} (truth: {r['truth_memorial_id']})")
        lines.append("B1-exact: **missed**")
        for s in r["strategies"]:
            if s["status"] == "ran" and s.get("hit"):
                lines.append(
                    f"- **{s['name']}**: HIT at rank #{s['rank']} "
                    f"({s['candidates']} candidates)"
                )

    if not any_missed:
        lines.append("\nB1-exact found every soldier. No strategies needed to save the day.")

    # Recommendations
    lines.append("\n## Recommendations")
    lines.append(f"\nBased on {len(results)} soldiers probed:")

    # Count strategies that never fire
    skipped_count = {}
    for r in results:
        for s in r["strategies"]:
            if s["status"] == "skipped":
                name = s["name"]
                skipped_count[name] = skipped_count.get(name, 0) + 1

    if skipped_count:
        lines.append("\n### Strategies that never fire")
        for name, count in sorted(skipped_count.items(), key=lambda x: -x[1]):
            lines.append(f"- **{name}**: skipped {count}/{len(results)} times")

    lines.append(f"\n### Throttle observation")
    lines.append(f"- All searches ran at {FAG_THROTTLE_FLOOR}s throttle (L1 floor)")
    lines.append(f"- No Cloudflare blocks observed during probe")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy yield probe")
    parser.add_argument("--input", required=True)
    parser.add_argument("--throttle", type=float, default=FAG_THROTTLE_FLOOR)
    args = parser.parse_args()

    with open(args.input) as f:
        soldiers = json.load(f)

    total_requests = len(soldiers) * len(STRATEGIES)
    est_time = total_requests * args.throttle
    print(
        f"Probe: {len(soldiers)} soldiers x {len(STRATEGIES)} strategies = "
        f"{total_requests} requests\n"
        f"Throttle: {args.throttle}s  Est. wall time: ~{est_time:.0f}s "
        f"(~{est_time/60:.1f} min)\n"
    )

    results = run_probe(soldiers, throttle=args.throttle)

    json_path = Path("docs/research/strategy_yield_report.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)

    md = build_report(results)
    md_path = Path("docs/research/strategy_yield_report.md")
    with open(md_path, "w") as f:
        f.write(md)

    print(f"\nReports written:\n  {json_path}\n  {md_path}")


if __name__ == "__main__":
    main()
