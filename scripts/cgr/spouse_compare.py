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


# Issue #13: scrape-pass default throttle. Lower than the search
# throttle (2.5s) because the scrape pass only navigates to one
# trusted URL pattern (/memorial/<id>/<slug>), already warmed up,
# and doesn't dodge Cloudflare Turnstile bursts the way the
# strategy ladder does.
SCRAPE_THROTTLE_SECONDS: float = 0.5

#: Default TTL for the per-run memorial-page cache.
_MEMORIAL_CACHE_TTL_DAYS: int = 7


class _MemorialCache:
    """Per-run cache of memorial-page HTML, keyed by
    (memorial_id, slug). Persists to a JSONL file so a re-run can
    reuse it; expires entries older than `ttl_days` by file mtime.

    File format (one JSON object per line):
      {"memorial_id": "12345", "slug": "john-doe", "html": "...",
       "cached_at": "2026-07-19T12:34:56Z"}

    Conservative keying: same memorial_id with different slug is
    a separate entry. The HTML body is per-memorial, but the slug
    is part of the public URL and may differ for the same person
    across edits, so we keep (id, slug) as the key.
    """

    def __init__(self, path: Path, ttl_days: int = _MEMORIAL_CACHE_TTL_DAYS):
        self._path = Path(path)
        self._ttl_seconds = ttl_days * 86400
        # In-memory mirror: {(memorial_id, slug): html}
        self._store: dict[tuple[str, str], str] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            mtime = self._path.stat().st_mtime
            if (time.time() - mtime) > self._ttl_seconds:
                # File is older than TTL: treat as miss; ignore
                # contents without raising.
                return
        except OSError:
            return
        try:
            with self._path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        key = (str(entry["memorial_id"]), str(entry["slug"]))
                        self._store[key] = entry["html"]
                    except (json.JSONDecodeError, KeyError):
                        # Skip malformed lines; don't fail the
                        # whole load.
                        continue
        except OSError:
            return

    def get(self, memorial_id: str | int, slug: str) -> str | None:
        return self._store.get((str(memorial_id), str(slug)))

    def put(self, memorial_id: str | int, slug: str, html: str) -> None:
        key = (str(memorial_id), str(slug))
        self._store[key] = html
        # Append to file. We don't dedupe; re-runs load the file
        # and the dict naturally overwrites.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "memorial_id": str(memorial_id),
            "slug": str(slug),
            "html": html,
            "cached_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def opt_in() -> bool:
    """True when env var FAG_SCRAPE_SPOUSE=1."""
    return os.environ.get("FAG_SCRAPE_SPOUSE", "").strip() in ("1", "true", "yes")


def annotate_records(
    results_path: Path,
    top_n: int = 1,
    throttle_seconds: float = SCRAPE_THROTTLE_SECONDS,
    headless: bool = False,
    cache: _MemorialCache | None = None,
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
    cache_hits = 0
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
                        slug = candidate_entry["slug"]
                        if not mem_id or not slug:
                            candidates.append(candidate_entry)
                            continue
                        # Issue #13: cache-aware scrape. On a cache
                        # hit, we skip the navigation and run the
                        # same parse+compare against the cached HTML.
                        # On a miss, we scrape live, then write the
                        # response to the cache for next time.
                        from scripts.fag import spouse_scrape
                        cm = None
                        if cache is not None:
                            cached_html = cache.get(mem_id, slug)
                            if cached_html is not None:
                                captured = spouse_scrape.parse_spouse_from_html(cached_html)
                                if captured is not None:
                                    cm = spouse_scrape.compare_spouses(local, captured)
                                cache_hits += 1
                        if cm is None:
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
                            # Populate cache from the live response
                            # (best-effort: re-fetch is wasteful, so
                            # we call the fetcher directly)
                            if cache is not None and cm is not None:
                                try:
                                    html = spouse_scrape.fetch_spouse_html(
                                        page, str(mem_id), slug)
                                    if html:
                                        cache.put(mem_id, slug, html)
                                except Exception:
                                    pass
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
        "cache_hits": cache_hits,
    }


def cli_main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--sidecar-out", type=Path, default=None,
                   help="Optional: write stats sidecar JSON")
    p.add_argument("--top-n", type=int, default=1)
    p.add_argument("--throttle", type=float, default=SCRAPE_THROTTLE_SECONDS,
                   help=f"Scrape-pass throttle (default {SCRAPE_THROTTLE_SECONDS}s)")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--memorial-cache", type=Path, default=None,
                   help="Path to per-run memorial cache JSONL "
                        "(default: <results_dir>/memorial_cache.jsonl)")
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
    # Default cache path sits next to results.jsonl
    cache_path = args.memorial_cache
    if cache_path is None:
        cache_path = args.results.parent / "memorial_cache.jsonl"
    cache = _MemorialCache(cache_path)
    stats = annotate_records(
        results_path=args.results,
        top_n=args.top_n,
        throttle_seconds=args.throttle,
        headless=args.headless,
        cache=cache,
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


# ============================================================
# Issue #16: spouse follow-up emission
# ============================================================

#: Label that disambiguates a deceased-husband follow-up from a
#: primary pensioner record. The user explicitly asked for
#: non-pensioner labeling.
_SPOUSE_ROLE_LABEL_NO_PENSION = (
    "husband (no ACW pension on file; identified only via widow's pension)"
)


def emit_spouse_followups(
    results_path: Path,
    out_path: Path,
) -> int:
    """Walk results.jsonl and write one follow-up record per
    widow whose spouse_compare found a match. The follow-up
    record describes a deceased husband (NOT a primary pensioner)
    and is meant for the reviewer's research workflow.

    Output: <out_path> JSONL. One record per widow with a match.
    Append-only (the file is an audit log; re-runs append).

    Returns: count of records written.

    Schema (per record):
      widow_pensioner_id         int  — the widow's pensioner_id
      widow_name                 str  — pensioner_first + ' ' + last
      from_top_candidate         int  — the fag_records memorial_id
      spouse_match_strength      str  — strong | medium | weak
      spouse_captured_first      str
      spouse_captured_middle     str
      spouse_captured_last       str
      spouse_captured_display    str
      spouse_captured_memorial_id str
      spouse_captured_slug       str
      spouse_captured_marriage_year str  — may be ""
      spouse_role_label          str  — always marks as non-pensioner
      spouse_research_state      str  — "needs_research" (default)
      captured_at                str  — ISO 8601 UTC
    """
    results_path = Path(results_path)
    out_path = Path(out_path)
    if not results_path.exists():
        return 0
    # Two passes: first count matches, then write only if count > 0.
    # Avoids creating an empty file when nothing matches.
    entries: list[dict] = []
    with results_path.open("r", encoding="utf-8") as fin:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            match = rec.get("spouse_match")
            if not match or not match.get("matched"):
                continue
            captured_mid = match.get("captured_memorial_id") or ""
            if not captured_mid:
                continue
            fag_records = rec.get("fag_records") or []
            from_top = None
            for c in fag_records:
                if str(c.get("memorial_id") or c.get("id") or "") == str(captured_mid):
                    from_top = c.get("memorial_id") or c.get("id")
                    break
            first = (rec.get("pensioner_first") or "").strip()
            last = (rec.get("pensioner_last") or "").strip()
            widow_name = f"{first} {last}".strip()
            entry = {
                "widow_pensioner_id": rec.get("pensioner_id"),
                "widow_name": widow_name,
                "from_top_candidate": from_top,
                "spouse_match_strength": match.get("match_strength", "medium"),
                "spouse_captured_first": match.get("captured_first", ""),
                "spouse_captured_middle": match.get("captured_middle", ""),
                "spouse_captured_last": match.get("captured_last", ""),
                "spouse_captured_display": match.get("captured_display", ""),
                "spouse_captured_memorial_id": str(captured_mid),
                "spouse_captured_slug": match.get("captured_slug", ""),
                "spouse_captured_marriage_year": match.get("captured_marriage_year", ""),
                "spouse_role_label": _SPOUSE_ROLE_LABEL_NO_PENSION,
                "spouse_research_state": "needs_research",
                "captured_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            entries.append(entry)
    if not entries:
        return 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as fout:
        for entry in entries:
            fout.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return len(entries)


# ============================================================
# BrowserSession + RequestGate integration (Phase 4 Slice 4.5)
# ============================================================


def annotate_records_via_session(
    results_path: Path,
    session: Any = None,  # BrowserSession
    top_n: int = 1,
) -> dict:
    """Annotate records using BrowserSession + ResponseClassifier.

    Same logic as annotate_records() but routes navigation through
    the BrowserSession (with its embedded stealth, warmup, and
    RequestGate) and uses ResponseClassifier before reading HTML.

    Returns stats dict.
    """
    from scripts.fag.response_classifier import (
        Classification,
        ResponseClassifier,
    )
    from scripts.pipeline.post_pass_observer import PostPassObserver

    results_path = Path(results_path)
    if not results_path.exists():
        return {"matched": 0, "total": 0, "error": "results.jsonl missing"}

    if session is None:
        return {"matched": 0, "total": 0, "error": "no BrowserSession provided"}

    page = session.page
    observer = PostPassObserver(run_id="spouse")

    records = []
    for line in results_path.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            records.append(json.loads(line))

    stats = {"matched": 0, "total_with_spouse": 0, "total_attempted": 0, "errors": 0}

    for rec in records:
        spouse_first = str(rec.get("pensioner_spouse_first", "")).strip()
        spouse_last = str(rec.get("pensioner_spouse_last", "")).strip()
        if not spouse_first or not spouse_last:
            continue

        stats["total_with_spouse"] += 1
        fag_records = rec.get("fag_records", []) or rec.get("ranked_candidates", []) or []
        if not fag_records:
            continue

        top = fag_records[0]
        memorial_id = top.get("memorial_id", "")
        if not memorial_id:
            continue

        stats["total_attempted"] += 1
        url = f"https://www.findagrave.com/memorial/{memorial_id}"

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            title = page.title()
            classification = ResponseClassifier.classify(title=title)

            if ResponseClassifier.is_blocking(classification):
                log.warning("Spouse: blocked on memorial %s (%s)", memorial_id, classification.value)
                stats["errors"] += 1
                continue

            # Extract spouse section
            body = page.evaluate("() => document.body.innerText")
            match_found = (
                spouse_last.lower() in body.lower()
                and spouse_first.lower() in body.lower()
            )

            observer.observe_spouse_match(
                pensioner_id=rec.get("pensioner_id", 0),
                spouse_match={
                    "spouse_first": spouse_first,
                    "spouse_last": spouse_last,
                    "memorial_id": memorial_id,
                    "match_found": match_found,
                },
                match_confirmed=match_found,
            )
            if match_found:
                stats["matched"] += 1

        except Exception as e:
            log.warning("Spouse scrape failed for memorial %s: %s", memorial_id, e)
            stats["errors"] += 1

    return stats
