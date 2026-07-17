"""J15-S2: post-pipeline spouse scrape pass.

After the FaG search loop is done (and CGR dedup + DD match
have run), walk the per-pensioner results.jsonl. For each
record that has:

  - pensioner_spouse_first + pensioner_spouse_last populated
    (from ok_pensioners.json / the input), AND
  - at least one fag_record (so we have a candidate to look up)

fetch the top-1 candidate's memorial page, parse the Family
Members > Spouse section, compare names, and write a
`spouse_match` dict into the record.

Opt-in via env var `FAG_SCRAPE_SPOUSE=1`. Skipped silently
otherwise. Read-only on FaG.

CLI:

  python -m scripts.cgr.spouse_compare \\
      --results path/to/results.jsonl \\
      [--sidecar-out path/to/spouse_match.json] \\
      [--top-n 1] \\
      [--headless]

Default throttle is 1.5s (matches the rest of the pipeline).
At default throttle + top-1, this is 1 extra page-hit per
pensioner with spouse data. For 7,709 pensioners where ~50%
have spouse data, that's ~3,800 hits = ~95 min extra.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

log = logging.getLogger("cgr.spouse_compare")


def opt_in() -> bool:
    """True when env var FAG_SCRAPE_SPOUSE=1."""
    return os.environ.get("FAG_SCRAPE_SPOUSE", "").strip() in ("1", "true", "yes")


def annotate_records(
    results_path: Path,
    top_n: int = 1,
    throttle_seconds: float = 1.5,
    headless: bool = False,
) -> dict:
    """For each record in results.jsonl, scrape the top-1
    candidate's memorial page for spouse info; compare with
    pensioner_spouse_*; write spouse_match back to the record.

    Returns a stats dict {matched, total_with_spouse,
    total_attempted, errors, ...}.

    Skips records that:
      - lack pensioner_spouse_first + last
      - have no fag_records (no candidate to look up)

    Notes:
      - Read-only on FaG (we GET memorial pages; never POST).
      - Uses a fresh playwright+stealth browser (avoids coupling
        with the per-pensioner search browser that already closed
        by the time this step runs).
      - Mutates results.jsonl in place via tmp+rename.
    """
    results_path = Path(results_path)
    if not results_path.exists():
        return {"matched": 0, "total": 0, "error": "results.jsonl missing"}

    # Lazy import so opting out doesn't require playwright.
    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth
    except ImportError as e:
        return {"matched": 0, "total": 0,
                "error": f"playwright or stealth not importable: {e}"}

    from scripts.fag.spouse_scrape import scrape_and_compare

    tmp_path = results_path.with_suffix(results_path.suffix + ".tmp")
    matched = 0
    total_attempted = 0
    errors = 0
    matched_ranks: list[int] = []
    matched_strength: dict = {"strong": 0, "medium": 0, "weak": 0}

    with sync_playwright() as pw:
        log.info("Spouse-scrape: spinning fresh browser (headless=%s)...", headless)
        browser = pw.chromium.launch(headless=headless)
        try:
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
                locale="en-US",
                timezone_id="America/Chicago",
            )
            try:
                Stealth().apply_stealth_sync(ctx)
            except Exception:
                pass
            page = ctx.new_page()
            # Warmup
            try:
                page.goto("https://www.findagrave.com/",
                          wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)
            except Exception:
                pass

            with results_path.open("r", encoding="utf-8") as fin, \
                 tmp_path.open("w", encoding="utf-8") as fout:
                for line in fin:
                    line = line.rstrip("\n")
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        fout.write(line + "\n")
                        continue
                    local_first = (rec.get("pensioner_spouse_first") or "").strip()
                    local_last  = (rec.get("pensioner_spouse_last") or "").strip()
                    local_mid   = (rec.get("pensioner_spouse_middle") or "").strip()
                    fag_records = rec.get("fag_records") or []
                    if not local_first or not local_last or not fag_records:
                        rec["spouse_match"] = None
                        rec["spouse_candidates"] = []
                        fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        continue
                    # Top-N: try candidates in rank order; first
                    # match wins. We always emit a spouse_candidates
                    # array (one entry per scraped candidate) so the
                    # reviewer can see what we tried.
                    n = max(1, min(top_n, len(fag_records)))
                    candidates: list[dict] = []
                    winning_match = None
                    winning_rank = None
                    local = {"first": local_first,
                             "middle": local_mid,
                             "last": local_last}
                    for rank_idx in range(n):
                        cand = fag_records[rank_idx]
                        rank = rank_idx + 1
                        candidate_entry: dict = {
                            "rank": rank,
                            "memorial_id": cand.get("memorial_id") or cand.get("id"),
                            "slug": cand.get("slug") or "",
                            "captured_first": "",
                            "captured_middle": "",
                            "captured_last": "",
                            "captured_display": "",
                            "match": None,
                        }
                        mem_id = candidate_entry["memorial_id"]
                        if not mem_id or not candidate_entry["slug"]:
                            candidates.append(candidate_entry)
                            continue
                        total_attempted += 1
                        try:
                            cm = scrape_and_compare(
                                page,
                                cand,
                                local,
                                throttle_seconds=0,
                            )
                        except Exception as e:
                            log.warning("Spouse scrape failed for pensioner %s rank %d: %s",
                                        rec.get("pensioner_id"), rank, e)
                            errors += 1
                            cm = None
                        if cm:
                            # Capture parsed fields for the audit trail
                            candidate_entry["captured_first"] = cm.get("captured_first", "")
                            candidate_entry["captured_middle"] = cm.get("captured_middle", "")
                            candidate_entry["captured_last"] = cm.get("captured_last", "")
                            candidate_entry["captured_display"] = cm.get("captured_display", "")
                            candidate_entry["match"] = {
                                "matched": True,
                                "matched_via": cm.get("matched_via", "first_and_last"),
                                "match_strength": cm.get("match_strength", "medium"),
                                "matched_via_rank": rank,
                            }
                            if winning_match is None:
                                winning_match = cm
                                winning_rank = rank
                        candidates.append(candidate_entry)
                        if winning_match is not None and rank < n:
                            # We found a match before exhausting top_n;
                            # don't waste cycles on the remaining
                            # candidates. Mark them as skipped so the
                            # audit trail still records the full top-N
                            # we considered.
                            for skipped_rank in range(rank + 1, n + 1):
                                cand = fag_records[skipped_rank - 1]
                                candidates.append({
                                    "rank": skipped_rank,
                                    "memorial_id": cand.get("memorial_id") or cand.get("id"),
                                    "slug": cand.get("slug") or "",
                                    "captured_first": "",
                                    "captured_middle": "",
                                    "captured_last": "",
                                    "captured_display": "",
                                    "match": {"matched": False, "skipped": True,
                                              "match_strength": None},
                                })
                            break
                    rec["spouse_candidates"] = candidates
                    if winning_match:
                        winning_match["matched_via_rank"] = winning_rank
                        matched += 1
                        matched_ranks.append(winning_rank)
                        ms = winning_match.get("match_strength", "medium")
                        matched_strength[ms] = matched_strength.get(ms, 0) + 1
                    rec["spouse_match"] = winning_match
                    if throttle_seconds > 0 and total_attempted % 5 == 0:
                        time.sleep(throttle_seconds)
                    fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fout.flush()
        finally:
            browser.close()
    tmp_path.replace(results_path)
    rank_hist = {}
    for r in matched_ranks:
        rank_hist[str(r)] = rank_hist.get(str(r), 0) + 1
    return {
        "matched": matched,
        "total_with_spouse": total_attempted,
        "errors": errors,
        "matched_strength_breakdown": matched_strength,
        "matched_rank_histogram": rank_hist,
        "throttle_seconds": throttle_seconds,
        "top_n": top_n,
    }


def cli_main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--sidecar-out", type=Path, default=None,
                   help="Optional: write stats sidecar JSON")
    p.add_argument("--top-n", type=int, default=1)
    p.add_argument("--throttle", type=float, default=1.5)
    p.add_argument("--headless", action="store_true")
    args = p.parse_args(argv)
    if not opt_in():
        print("INFO: FAG_SCRAPE_SPOUSE not set; nothing to do. "
              "Set FAG_SCRAPE_SPOUSE=1 to enable.",
              file=sys.stderr)
        if args.sidecar_out:
            args.sidecar_out.write_text(json.dumps({
                "matched": 0, "total_with_spouse": 0,
                "note": "FAG_SCRAPE_SPOUSE not set; step skipped",
            }, indent=2))
        return 0
    stats = annotate_records(
        results_path=args.results,
        top_n=args.top_n,
        throttle_seconds=args.throttle,
        headless=args.headless,
    )
    log.info("Spouse scrape: %d matches of %d attempted", stats["matched"],
             stats["total_with_spouse"])
    if args.sidecar_out:
        args.sidecar_out.parent.mkdir(parents=True, exist_ok=True)
        args.sidecar_out.write_text(json.dumps(stats, indent=2))
        log.info("Sidecar: %s", args.sidecar_out)
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
