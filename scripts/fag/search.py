#!/usr/bin/env python3
"""Batch Find a Grave searcher for OK Confederate pensioners.

Loads the unified OK Confederate pensioner list, iterates each
record, applies the v5 strategy ladder, parses FaG search results,
scores candidates, and writes a state file (one JSON line per
pensioner). The output state is designed to be reviewed in the
companion HTML viewer (scripts/view.html).

Each output record contains:
  - pensioner_id, name, regiment
  - status: auto_accept | ambiguous | no_results | too_many | captcha | skip | error
  - ranked_candidates: top 20 FaG candidates seen, each with
      memorial_id, slug, name, score, score_breakdown,
      details (is_veteran, birth_year, death_year),
      backlink, iiif_url
  - decision: null (filled in by human via view.html)
  - ground_truth: optional, set when --ground-truth-csv is used.
    Records whether the expected memorial_id/slug was found in the
    candidate list, and at what rank.

Prerequisites:
  pip install playwright playwright-stealth
  playwright install chromium

Usage:
  # First time: from local file
  python scripts/search_fag.py \\
      --input docs/research/digitalprairie/ok_pensioners.json \\
      --state out/search_state.jsonl

  # From raw GitHub
  python scripts/search_fag.py \\
      --input-url https://raw.githubusercontent.com/valueforvalue/FindAGraveHelper/master/docs/research/digitalprairie/ok_pensioners.json \\
      --state out/search_state.jsonl

  # Test on a few records first
  python scripts/search_fag.py \\
      --input docs/research/digitalprairie/ok_pensioners.json \\
      --state out/test_state.jsonl --limit 20

Notes:
  - Must be run with a VISIBLE browser window (headless=False) on
    Windows because Cloudflare Turnstile blocks headless Chromium.
  - 2.5s throttle between requests; 30s backoff on CAPTCHA.
  - Resume-safe: re-running skips already-processed pensioners.
  - State file is one JSON record per line (JSONL). Easy to grep,
    version-control, parse.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

# Allow imports from this script's directory when run as a script.
sys.path.insert(0, str(Path(__file__).parent))
from scripts.pipeline.checkpoint import write_checkpoint, read_checkpoint, record_failure
from urllib.parse import urlencode
from scripts.matching.regiment_keyword import strategy_regiment_bio, extract_regiment_phrases
from scripts.matching.nickname_match import strategy_with_nickname, nickname_candidates

# Internal modules (T008 split)
from scripts.fag.filters import (
    apply_location_filter, parse_slug,
    extract_state_from_regiment, extract_candidate_details,
    S_NO_RESULTS, S_ERROR,
)
from scripts.search.strategies import STRATEGIES
from scripts.fag.scoring import score_candidate, tag_candidates_with_found_by
from scripts.fag.parser import parse_results_page, merge_candidates
from scripts.fag.state_io import (
    load_processed_ids, load_skipped_ids, append_state, write_skipped,
)
from scripts.fag.inputs import (
    load_unified_from_url, load_unified_from_file, load_local_csv,
    load_input, load_ground_truth,
)

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from playwright.sync_api import TimeoutError as PWTimeout

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("search")

# ============================================================
# Tunables
# ============================================================
# Status values (T008 split regression: these were dropped from
# scripts/fag/search.py when the file was split into private
# modules in commit c217eff; restored from the pre-split
# scripts/search_fag.py.)
S_AUTO_ACCEPT = "auto_accept"
S_AMBIGUOUS = "ambiguous"
S_TOO_MANY = "too_many"
S_CAPTCHA = "captcha"
S_SKIP = "skip"

# Auto-accept when score is high. With our scoring function, exact
# last+first+middle + veteran + death + state all match → 0.80.
# When local state is known AND candidate state matches, we get
# 0.80; when it doesn't, we cap at 0.735. So 0.75 is a reasonable
# threshold: at or above this, we're confident the top candidate
# is the right person.
AUTO_ACCEPT_THRESHOLD = 0.70  # name+veteran+death match is sufficient
# When local has no death year, the max achievable score is lower
# (~0.64 = name match + veteran flag). Use a lower threshold for those.
AUTO_ACCEPT_THRESHOLD_NO_DEATH = 0.60
AUTO_ACCEPT_GAP = 0.10  # top must beat #2 by this much for auto-accept
PROMPT_THRESHOLD = 0.60
THROTTLE_SECONDS = 2.5
CAPTCHA_BACKOFF_SECONDS = 30.0
MAX_CANDIDATES_PER_PENSIONER = 20
MAX_FAG_RESULTS_TO_PARSE = 20  # per strategy

BASE_URL = "https://www.findagrave.com/memorial/search"

# FaG's location filter URL params. Verified via probes v7 + v8:
#
#   data/probe/filter_v7.json — ?locationId=country_4 works for US.
#   data/probe/filter_v8.json — ?locationId=state_38 works for OK state.
#
# Empirical results for "John Smith" baseline:
#   no filter                                  -> 97,291 (global, with foreign hits)
#   ?locationId=country_4                      -> 62,632 (US only, 0 foreign)
#   ?locationId=state_38 (Oklahoma)            ->  1,087 (OK only, 0 foreign)
#
# The ?location=... text field is the visible "Cemetery Location" input; FaG
# reads only locationId. Both states and countries share the locationId key
# (last write wins; pass one at a time).
#
# Without locationId, FaG returns global results — pulling Australian, UK,
# Canadian matches that get scored as too_many / ambiguous and waste the
# strategy ladder.
FAG_COUNTRY_FILTER_US = {"locationId": "country_4"}

# FaG's state-level filter uses the same locationId key with a state_<id>
# value. The 52 US states + districts + territories were enumerated from
# data/probe/page_html_baseline.html (the browse-page radio list).
FAG_STATE_IDS = {
    "AL": "state_3", "AK": "state_2", "AZ": "state_5", "AR": "state_4",
    "CA": "state_6", "CO": "state_7", "CT": "state_8", "DE": "state_9",
    "DC": "state_10", "FL": "state_11", "GA": "state_12", "HI": "state_13",
    "ID": "state_14", "IL": "state_15", "IN": "state_16", "IA": "state_17",
    "KS": "state_18", "KY": "state_19", "LA": "state_20", "ME": "state_21",
    "MD": "state_22", "MA": "state_23", "MI": "state_24", "MN": "state_25",
    "MS": "state_26", "MO": "state_27", "MT": "state_28", "NE": "state_29",
    "NV": "state_30", "NH": "state_31", "NJ": "state_32", "NM": "state_33",
    "NY": "state_34", "NC": "state_35", "ND": "state_36", "OH": "state_37",
    "OK": "state_38", "OR": "state_39", "PA": "state_40", "RI": "state_41",
    "SC": "state_42", "SD": "state_43", "TN": "state_44", "TX": "state_45",
    "UT": "state_46", "VT": "state_47", "VA": "state_48", "WA": "state_49",
    "WV": "state_50", "WI": "state_51", "WY": "state_52",
}


def setup_browser(p):
    from playwright_stealth import Stealth
    b = p.chromium.launch(
        headless=False,
        args=['--disable-blink-features=AutomationControlled', '--no-sandbox'],
    )
    ctx = b.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        viewport={'width': 1280, 'height': 720},
        locale='en-US',
        timezone_id='America/Chicago',
    )
    page = ctx.new_page()
    # Apply stealth to the CONTEXT (not the page). When applied to a
    # page, the init scripts get re-injected on every navigation; the
    # CDP round-trip + Python serialization buffers add up to ~8 MB/
    # pensioner over a full run. At the context level the init scripts
    # persist across all navigations within that context, eliminating
    # the leak.
    try:
        Stealth().apply_stealth_sync(ctx)
    except Exception:
        # Fallback: if context-level stealth isn't supported in this
        # version of playwright-stealth, apply per-page (old behaviour).
        Stealth().apply_stealth_sync(page)
    return b, ctx, page


def warmup_session(page: Page, log_) -> bool:
    """Visit FaG homepage to establish a Cloudflare session.

    Without this warmup, the very first /memorial/search request
    triggers a Turnstile challenge because the browser context has
    no CF cookies. Visiting the homepage first primes the session.

    Returns True if homepage loaded without challenge.
    """
    try:
        page.goto('https://www.findagrave.com/', wait_until='domcontentloaded', timeout=30000)
        time.sleep(3)
        t = page.title()
        if 'Just a moment' in t:
            log_.warning('Warmup: still on challenge page after homepage')
            return False
        log_.info('Warmup: homepage loaded, title=%r', t)
        return True
    except Exception as e:
        log_.warning('Warmup failed: %s', e)
        return False


# ============================================================
# Per-pensioner search
# ============================================================

def search_one_pensioner(page: Page, pensioner: dict,
                          throttle_seconds: Optional[float] = None,
                          state_filter: Optional[str] = None) -> dict:
    """Run the strategy ladder for one pensioner. Return a state record.

    throttle_seconds: if provided, sleep this long between
    strategy navigations as well as between pensioners. The
    fag_browser wrapper already throttles between pensioners, but
    each pensioner runs ~10 strategies back-to-back. Without an
    intra-pensioner pause, popular-name records slam FaG with
    10+ requests in 5-10 seconds flat, hitting Cloudflare's
    burst-rate limit.

    state_filter: a state abbr ("OK", "TX"), "US" for country_4,
    or "" to disable. When provided, this OVERRIDES the default
    behavior of scoping FaG searches to the pensioner's regiment
    state. Pass "OK" to scope all searches to Oklahoma (the
    project goal per AGENTS.md). When None (default), legacy
    behavior is preserved (scope = regiment state).
    """
    first = pensioner.get("first_name", "")
    middle = pensioner.get("middle_name", "")
    last = pensioner.get("last_name", "")
    if state_filter is not None:
        state_abbr = state_filter
    else:
        state_abbr = extract_state_from_regiment(pensioner.get("regiment", ""))
    pensioner_id = pensioner.get("id", -1)
    record = {
        "pensioner_id": pensioner_id,
        "pensioner_app_number": pensioner.get("application_number", ""),
        "pensioner_name": f"{first} {middle} {last}".strip().replace("  ", " "),
        "pensioner_first": first,
        "pensioner_middle": middle,
        "pensioner_last": last,
        "pensioner_birth_year": pensioner.get("birth_year", ""),
        "pensioner_death_year": pensioner.get("death_year", ""),
        "regiment": pensioner.get("regiment", ""),
        "company": pensioner.get("company", ""),
        "pensioncard_backlink": pensioner.get("pensioncard_backlink", ""),
        "ranked_candidates": [],
        "status": S_NO_RESULTS,
        "best_score": 0.0,
        "best_candidate": None,
        "strategies_run": [],
        "decision": None,  # {memorial_id, slug, by, at, notes}
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    if not last:
        record["status"] = S_SKIP
        record["error"] = "no last name"
        return record

    local = {
        "first_name": first,
        "middle_name": middle,
        "last_name": last,
        "_state_abbr": state_abbr,
        "_death_year": pensioner.get("death_year", ""),
        "_birth_year": pensioner.get("birth_year", ""),
    }

    strategy_runs = []  # (strategy_name, [candidates])
    captcha_seen = False
    any_error = False
    parse_error_streak = 0

    for name, fn in STRATEGIES:
        # Build per-strategy closure for F2/F3 which need pensioner
        if name == "F2-regiment-bio":
            params = strategy_regiment_bio(first, middle, last, pensioner.get("regiment", ""), pensioner.get("death_year"))
        elif name == "F3-nickname":
            params = strategy_with_nickname(first, middle, last, pensioner.get("birth_year"), pensioner.get("death_year"), pensioner)
        else:
            params = fn(first, middle, last, pensioner.get("birth_year"), pensioner.get("death_year"))
        if params is None:
            continue
        # Restrict FaG to US (and US state if known) + ACW date window +
        # spouse name (if known from ok_pensioners.json) — J15:
        # linkedToName pre-filters candidates to those linked to the
        # pensioner's known spouse in someone's family tree. A
        # candidate that comes back with linkedToName=Spouse is a
        # much stronger match than one that doesn't (post-pipeline
        # comparison in scripts/cgr/dixiedata_compare.py will score
        # this as a high-quality piece of evidence).
        params = apply_location_filter(
            params, state_abbr,
            spouse_first=pensioner.get("spouse_first_name", "") or "",
            spouse_last=pensioner.get("spouse_last_name", "") or "",
            spouse_middle=pensioner.get("spouse_middle_name", "") or "",
        )
        url = BASE_URL + "?" + urlencode(params)
        record["strategies_run"].append(name)

        # Inter-strategy throttle. Without this, a single pensioner
        # with 10 strategies issues 10 page.goto() calls in ~5-10
        # seconds flat, which trips FaG's burst rate limit. Cap the
        # inter-strategy pause at the same throttle as inter-
        # pensioner; the outer wrapper handles inter-pensioner.
        if throttle_seconds and throttle_seconds > 0 and strategy_runs:
            time.sleep(throttle_seconds)

        try:
            page.goto(url, wait_until='domcontentloaded', timeout=20000)
        except PWTimeout:
            log.warning("Nav timeout: %s %s [%s]", first, last, name)
            any_error = True
            time.sleep(CAPTCHA_BACKOFF_SECONDS)
            continue

        title = page.title()
        from scripts.fag.response_classifier import (
            Classification,
            ResponseClassifier,
        )

        page_class = ResponseClassifier.classify(title=title)
        if ResponseClassifier.is_blocking(page_class):
            cooldown = ResponseClassifier.cooldown_seconds(page_class)
            if page_class == Classification.RateLimit1015:
                log.warning(
                    "CLOUDFLARE 1015 RATE LIMIT: %s %s [%s]. Backing off "
                    "%ds + resetting session cookies.",
                    first, last, name, cooldown,
                )
                captcha_seen = True
                time.sleep(cooldown)
                continue
            log.warning("CAPTCHA: %s %s [%s]. Waiting up to 30s for it to resolve.",
                        first, last, name)
            captcha_seen = True
            # Try waiting for the challenge to resolve naturally
            resolved = False
            for wait_s in (5, 10, 15):
                time.sleep(5)
                if ResponseClassifier.classify(title=page.title()) == Classification.NormalPage:
                    log.info("  challenge resolved after %ds", wait_s + 5)
                    resolved = True
                    break
            if not resolved:
                log.warning("  challenge did not resolve. Backing off %ds.", cooldown)
                time.sleep(CAPTCHA_BACKOFF_SECONDS)
            continue

        try:
            total, cands = parse_results_page(page)
        except Exception as e:
            import traceback
            tb_lines = traceback.format_exc().splitlines()
            # Surface only the last 5 lines so the run.log stays
            # readable.
            short_tb = "\n  ".join(tb_lines[-5:])
            log.warning(
                "Parse error %s %s [%s]: %s\n  %s",
                first, last, name, e, short_tb,
            )
            any_error = True
            parse_error_streak += 1
            # Detect sustained Cloudflare rate-limit stalls. When
            # parse_results_page errors multiple times in a row
            # across strategies, FaG is almost certainly returning
            # an interstitial/captcha page whose DOM our parser
            # can't read. Back off hard + reset the browser cookies
            # via the periodic reset (every N strategies) trigger.
            if parse_error_streak >= 3:
                log.warning(
                    "Sustained parse errors (%d in a row). Cloudflare "
                    "is likely rate-limiting or stalling; backing off "
                    "60s before continuing.",
                    parse_error_streak,
                )
                time.sleep(60.0)
                parse_error_streak = 0
            continue

        # Tag each candidate with the strategy that found it, so the
        # HTML viewer can show "Found by: B1-exact (firstname=John&...)"
        cands = tag_candidates_with_found_by(cands, name, params)
        parse_error_streak = 0  # reset on successful parse
        log.info("  %s %-12s [%s] -> %d results", first, last, name, total)
        strategy_runs.append((name, cands))
        # No early-stop — collect all candidates across all strategies

    # Merge and score
    merged = merge_candidates(strategy_runs)
    for c in merged:
        s, breakdown = score_candidate(local, c)
        c["score"] = round(s, 3)
        c["score_breakdown"] = breakdown

    merged.sort(key=lambda c: -c["score"])
    record["ranked_candidates"] = merged[:MAX_CANDIDATES_PER_PENSIONER]

    if merged:
        record["best_score"] = merged[0]["score"]
        record["best_candidate"] = {
            "memorial_id": merged[0]["memorial_id"],
            "slug": merged[0]["slug"],
            "score": merged[0]["score"],
        }

    # Ground-truth validation (if the local record has an expected
    # memorial_id+slug, check if it appears anywhere in the candidates)
    expected_mid = pensioner.get("_expected_memorial_id", "").strip()
    expected_slug = pensioner.get("_expected_slug", "").strip()
    if expected_mid or expected_slug:
        hit_idx = None
        for idx, c in enumerate(merged):
            if expected_mid and c["memorial_id"] == expected_mid:
                hit_idx = idx
                break
            if expected_slug and c["slug"] == expected_slug:
                hit_idx = idx
                break
        if hit_idx is not None:
            record["ground_truth"] = {
                "expected": {"memorial_id": expected_mid, "slug": expected_slug},
                "found": True,
                "rank": hit_idx + 1,  # 1-based
                "score": merged[hit_idx]["score"],
            }
        else:
            record["ground_truth"] = {
                "expected": {"memorial_id": expected_mid, "slug": expected_slug},
                "found": False,
            }

    # Status
    if captcha_seen and not merged:
        record["status"] = S_CAPTCHA
    elif not merged:
        if any_error:
            record["status"] = S_ERROR
        else:
            record["status"] = S_NO_RESULTS
    else:
        from scripts.blackboard.decision_policy import (
            DecisionContext,
            classify,
        )

        local_dy = str(pensioner.get("death_year") or "").strip()
        ctx = DecisionContext(
            candidates=merged,
            local_death_year=local_dy if local_dy else None,
        )
        decision = classify(ctx)
        record["best_score"] = decision.top_score
        record["status"] = decision.status
        record["_decision"] = decision.to_dict()

    return record


# ============================================================
# Main
# ============================================================

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", type=Path, help="Local path to ok_pensioners.json")
    src.add_argument("--input-url", help="URL to fetch ok_pensioners.json (e.g. raw GitHub)")
    src.add_argument("--input-csv", type=Path,
                     help="Local path to a generic CSV (dixiedata export, etc.). "
                          "Expected columns: id, first_name, middle_name, last_name, "
                          "unit, company, application_number, memorial_id, slug")
    p.add_argument("--state", type=Path, required=True,
                   help="Output JSONL state file (one line per pensioner)")
    p.add_argument("--limit", type=int, default=0,
                   help="Process at most N pensioners (default: all)")
    p.add_argument("--shuffle", action="store_true",
                   help="Process in random order")
    p.add_argument("--start-from", type=int, default=0,
                   help="Skip the first N pensioners")
    p.add_argument("--ground-truth-csv", type=Path, default=None,
                   help="Optional CSV with expected memorial_id+slug per row. "
                        "When set, the state output includes 'ground_truth_match' "
                        "(true/false/null) per pensioner for validation.")
    p.add_argument("--exclude-csv", type=Path, default=None,
                   help="Skip pensioners whose (last, first) match a row in this CSV. "
                        "Used to skip records we've already validated locally. "
                        "Expected columns: first_name, last_name.")
    p.add_argument("--skipped-out", type=Path, default=None,
                   help="Optional JSONL to write the list of skipped pensioners + reason. "
                        "Defaults to <state>.skipped.jsonl if --exclude-csv is used.")
    args = p.parse_args()

    # Load input
    holder = []
    load_input(args, holder)
    pensioners = holder[0]

    if args.shuffle:
        random.shuffle(pensioners)
    if args.start_from:
        pensioners = pensioners[args.start_from:]
    if args.limit:
        pensioners = pensioners[:args.limit]

    processed = load_processed_ids(args.state)
    log.info("Will process %d pensioners (%d already done)",
             len(pensioners), len(processed))

    # Exclusion filter
    skipped = []
    if args.exclude_csv:
        exclude_csv = Path(args.exclude_csv)
        if exclude_csv.exists():
            exclude_names = set()
            with exclude_csv.open(encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    ln = (r.get("last_name") or "").strip().upper()
                    fn = (r.get("first_name") or "").strip().upper()
                    if ln:
                        exclude_names.add((ln, fn))
            # Also skip pensioners already in the skipped sidecar
            skipped_path_load = args.skipped_out or args.state.with_suffix(".skipped.jsonl")
            already_skipped = load_skipped_ids(skipped_path_load) if skipped_path_load.exists() else set()
            before = len(pensioners)
            kept = []
            for p_data in pensioners:
                pid = p_data.get("id")
                if pid in already_skipped:
                    continue  # already excluded on a prior run
                key = (p_data.get("last_name", "").upper(),
                       p_data.get("first_name", "").upper())
                if key in exclude_names:
                    skipped.append({
                        "pensioner_id": pid,
                        "name_raw": p_data.get("name_raw"),
                        "first_name": p_data.get("first_name"),
                        "last_name": p_data.get("last_name"),
                        "reason": "in exclude-csv",
                    })
                else:
                    kept.append(p_data)
            pensioners = kept
            log.info("Excluded %d pensioners (in %s). Remaining: %d",
                     before - len(pensioners), exclude_csv, len(pensioners))
        else:
            log.warning("--exclude-csv %s does not exist", exclude_csv)

    # Load ground truth if supplied
    ground_truth = {}
    if args.ground_truth_csv:
        ground_truth = load_ground_truth(args.ground_truth_csv)
        # Build a map by application number too, for ok_pensioners.json
        for p_data in pensioners:
            app = p_data.get('application_number', '').strip()
            if app:
                # If the GT has matching app# we'd need a second column;
                # skip for now
                pass

    with sync_playwright() as pw:
        browser, ctx, page = setup_browser(pw)
        checkpoint_path = args.state.with_suffix(".checkpoint.json")
        log.info("Checkpoint file: %s", checkpoint_path)
        try:
            # Warmup: visit homepage first to establish Cloudflare session
            log.info("Warming up browser session...")
            if not warmup_session(page, log):
                log.warning("Warmup incomplete. First few queries may hit CAPTCHA.")
            count = 0
            for p_data in pensioners:
                pid = p_data.get("id", -1)
                if pid in processed:
                    continue
                count += 1
                log.info("[%d/%d] id=%d  %s %s", count, len(pensioners),
                         pid, p_data.get("first_name", ""),
                         p_data.get("last_name", ""))
                # Wrap each pensioner in try/except so one bad row doesn't
                # kill the whole run. We record the failure and move on.
                try:
                    record = search_one_pensioner(page, p_data)
                    append_state(args.state, record)
                    # Checkpoint: record that we successfully processed this id.
                    write_checkpoint(
                        checkpoint_path,
                        last_processed_id=pid,
                        last_strategy=record.get("strategies_run", [""])[-1] if record.get("strategies_run") else "",
                        pensioner_name=record.get("pensioner_name", ""),
                        run_id=str(int(time.time())),
                        state_file=str(args.state),
                    )
                except Exception as e:
                    log.error("Pensioner %d failed: %s", pid, e, exc_info=False)
                    record_failure(
                        args.state, pid,
                        f"{p_data.get('first_name', '')} {p_data.get('last_name', '')}".strip(),
                        error=str(e)[:500],
                    )
                time.sleep(THROTTLE_SECONDS)
        finally:
            ctx.close()
            browser.close()

    log.info("Done. State file: %s", args.state)

    if skipped:
        skipped_path = args.skipped_out or args.state.with_suffix(".skipped.jsonl")
        write_skipped(skipped_path, skipped)
        log.info("Wrote %d skipped pensioners to %s", len(skipped), skipped_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())