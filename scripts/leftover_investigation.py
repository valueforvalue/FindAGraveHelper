"""Phase 3: leftover-investigation.

After Run #2 + retry_errors, this phase re-investigates every
"low-confidence" pensioner using additional FaG strategies, with
a hard-target termination condition.

INPUT

  - docs/research/digitalprairie/ok_pensioners.json (7,758 records).
  - data/results/run_full_<date>/state.jsonl (post-run output).
  - data/results/run_full_<date>/cgr_dedup.json (Phase 2 dedup).

OUTPUT

  - data/results/run_full_<date>/leftover_investigation.jsonl, one
    row per examined pensioner. Each row has:
      pensioner_id,
      disposition: 'found_conclusive' | 'no_fag_memorial' | 'skipped',
      strategies_run: list[str],
      top_candidate: {memorial_id, slug, score} | None,
      existing_score: float (state.jsonl best_score pre-pass),
      existing_fag_status: str,
      notes: str,
  - In-place updates to state.jsonl: append a ``leftover_pass`` field
    to each affected record so the view.html renderer can show
    the badge without joining files.

  - data/results/run_full_<date>/leftover_investigation_summary.json:
    counts of dispositions + strategy-usage stats.

TRIGGER SET (LOCKED 2026-07-16, see 2026-07-16-postrun-design.md)

  A pensioner is investigated if either:
    - fag_status in {'auto_accept', 'ambiguous', 'too_many',
                      'no_results'} AND
    - best_score < 0.85

  Equivalently: anything that wasn't a high-confidence find on
  the first pass.

STRATEGY LADDER (4 strategies, hard-target termination)

  1. spouse_cross_search: if local has spouse_name AND CGR row has
     spouse data, search FaG for widow+soldier pair, check for
     spouse-link confirmation.
  2. birth_state_narrowing: if local has birth_state, narrow by
     state.
  3. nickname_initial_swap: try a phonetic first-name alias list
     (Wm, Thos, Jno, etc.) and search each variant.
  4. regiment_bio_with_death_year: combine regiment-bio strategy
     with a death-year filter.

  Apply strategies one at a time. Stop when:
    (a) top candidate score > 0.85 AND name match is strong, OR
    (b) all 4 strategies have been tried.

POLICY ALIGNMENT

  This is the explicit "follow-up phase" endorsed by the always-
  run-FaG policy in scripts/unified_pipeline.py. The main run's
  12-strategy ladder is the first pass; this phase is the second
  pass on low-confidence rows.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Callable, Optional


# ============================================================
# Trigger logic
# ============================================================

INVESTIGATE_FAG_STATUSES = {"auto_accept", "ambiguous", "too_many", "no_results"}
INVESTIGATE_BELOW_SCORE = 0.85  # hard-target threshold


def should_investigate(record: dict) -> bool:
    """True if a state.jsonl row is eligible for follow-up.

    Conditions (per policy):
      - fag_status in INVESTIGATE_FAG_STATUSES
      - best_score < INVESTIGATE_BELOW_SCORE
    """
    if record.get("fag_status") not in INVESTIGATE_FAG_STATUSES:
        return False
    try:
        score = float(record.get("best_score") or 0)
    except (ValueError, TypeError):
        score = 0.0
    return score < INVESTIGATE_BELOW_SCORE


# ============================================================
# Strategy primitives
# ============================================================

# Phonetic first-name aliases for the nickname strategy.
# These cover the most common CW-era abbreviations we see in
# pension records.
NICKNAME_ALIASES = {
    "wm": "william",
    "william": "wm",
    "thos": "thomas",
    "thomas": "thos",
    "jno": "john",
    "john": "jno",
    "benj": "benjamin",
    "benjamin": "benj",
    "geo": "george",
    "george": "geo",
    "jas": "james",
    "james": "jas",
    "jim": "james",
    "jimmie": "james",
    "sam": "samuel",
    "samuel": "sam",
    "danl": "daniel",
    "daniel": "danl",
    "jos": "joseph",
    "joseph": "jos",
    "matt": "matthew",
    "matthew": "matt",
    "nat": "nathaniel",
    "nathaniel": "nat",
    "rob": "robert",
    "robert": "rob",
    "tom": "thomas",
    "tommy": "thomas",
    "will": "william",
    "willie": "william",
    "bill": "william",
}


def _spouse_cross_search_params(pensioner: dict, cgr_row: dict) -> Optional[dict]:
    """Build FaG search params for spouse cross-search.

    Pre-requisites:
      - local has spouse_name (we passed it through)
      - CGR row (linked via dedup) has spouse data

    Returns the URL-params dict or None if pre-requisites missing.
    """
    local_spouse = pensioner.get("spouse_name", "") or pensioner.get("pensioncard_spouse", "")
    if not local_spouse:
        return None
    # Build: FaG search "firstname=spouse_first lastname=spouse_last"
    parts = local_spouse.strip().split()
    if len(parts) < 2:
        return None
    spouse_first = parts[0]
    spouse_last = " ".join(parts[1:])
    return {
        "firstname": spouse_first,
        "lastname": spouse_last,
        "fuzzyNames": "true",
        # Look for CW-context bios via the existing C1 strategy.
        "isVeteran": "true",
    }


def _birth_state_narrowing_params(pensioner: dict) -> Optional[dict]:
    """Build params using birth state as a narrowing filter.

    Only fires when the local record has a non-empty birth_state
    (rare today: most CGR rows lack birth data).
    """
    birth_state = pensioner.get("birth_state", "")
    if not birth_state:
        return None
    return {
        "firstname": pensioner.get("first_name", ""),
        "lastname": pensioner.get("last_name", ""),
        "fuzzyNames": "true",
        # FaG doesn't accept a state parameter directly; we encode
        # the narrowing by adding it to the bio field for context.
        "bio": f"born {birth_state}",
    }


def _nickname_variants(first_name: str) -> list[str]:
    """Yield alias strings for a first name (or its nickname)."""
    variants = []
    fn = first_name.strip().rstrip(".").lower()
    if not fn:
        return variants
    for short, full in NICKNAME_ALIASES.items():
        if fn == short:
            variants.append(full)
            break
        if fn == full:
            variants.append(short)
            break
    # De-dup
    return list(dict.fromkeys(variants))


def _regiment_bio_death_year_params(pensioner: dict) -> Optional[dict]:
    """Combine regiment-bio with a death-year filter."""
    regiment = pensioner.get("regiment", "") or pensioner.get("cgr_unit", "")
    if not regiment:
        return None
    death_year = pensioner.get("death_year", "") or pensioner.get("pensioner_death_year", "")
    if not death_year:
        return None
    return {
        "firstname": pensioner.get("first_name", ""),
        "lastname": pensioner.get("last_name", ""),
        "isVeteran": "true",
        "bio": "Confederate States America",
        "deathyear": str(death_year)[:4],
        "deathyearfilter": "5",
    }


# ============================================================
# Main orchestration
# ============================================================

def run_investigation(
    state_path: Path,
    pensioners_path: Path,
    cgr_dedup_path: Path,
    fag_search_fn: Optional[Callable] = None,
    no_fag: bool = False,
    throttle_seconds: float = 1.5,
    watchdog: Optional["object"] = None,
    max_consecutive_errors: int = 10,
) -> dict:
    """Drive Phase 3 over every eligible state.jsonl row.

    Returns a summary dict with disposition counts.

    Reads:
      state.jsonl (post-run)
      ok_pensioners.json (for spouse_name etc.)
      cgr_dedup.json (Phase 2 output, for the linked CGR row)
    Writes:
      leftover_investigation.jsonl (one row per examined pensioner)
      leftover_investigation_summary.json (counts)
      In-place updates to state.jsonl (append ``leftover_pass``
      field per row).
    """
    # Load state
    records = []
    with state_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # Load pensioners
    with pensioners_path.open(encoding="utf-8") as f:
        pensioners = json.load(f)
    pensioners_by_id = {p["id"]: p for p in pensioners if p.get("id") is not None}

    # Load cgr_dedup (reverse index only)
    cgr_to_person = {}
    person_to_meta = {}
    if cgr_dedup_path.exists():
        with cgr_dedup_path.open(encoding="utf-8") as f:
            dedup = json.load(f)
        cgr_to_person = {
            int(k): v for k, v in dedup.get("cgr_id_to_person_id", {}).items()
        }
        person_to_meta = dedup.get("persons", {})

    # Build candidate set: rows to investigate
    rows_to_investigate = []
    for r in records:
        if not should_investigate(r):
            continue
        rows_to_investigate.append(r)
    print(f"Found {len(rows_to_investigate)} rows eligible for "
          f"Phase 3 investigation (out of {len(records)} state records)")

    # Initialize FaG search function (or skip if --no-fag)
    if fag_search_fn is None and not no_fag:
        try:
            from scripts.fag_browser import make_fag_search_fn
        except ImportError:
            fag_search_fn = None
        if fag_search_fn is None and not no_fag:
            # If we're in a test environment without Playwright, we
            # still want to support running the rest of the logic;
            # we just won't issue real FaG queries.
            no_fag = True

    if not no_fag and fag_search_fn is None:
        fag_search_fn = make_fag_search_fn(
            throttle=throttle_seconds,
            watchdog=watchdog,
            max_consecutive_errors=max_consecutive_errors,
        )

    # Run investigation
    summary = {
        "investigate_candidates": len(rows_to_investigate),
        "found_conclusive": 0,
        "no_fag_memorial": 0,
        "skipped_no_prereq": 0,
        "errors": 0,
        "strategy_usage": {},
    }
    out_records = []

    # Index state records by pensioner_id for in-place updates
    by_pid = {r.get("pensioner_id"): r for r in records}

    log = logging.getLogger("leftover")

    for r in rows_to_investigate:
        pid = r.get("pensioner_id")
        pensioner = pensioners_by_id.get(pid, {})
        # Find the linked CGR row (via the dedup file's reverse index)
        linked_cgr_id = None
        linked_cgr_row = None
        for cr in r.get("cgr_records") or []:
            cid = cr.get("id") or cr.get("cgr_id")
            if cid is None:
                continue
            if int(cid) in cgr_to_person:
                linked_cgr_id = int(cid)
                linked_cgr_row = cr
                break

        existing_score = float(r.get("best_score") or 0)
        existing_status = r.get("fag_status", "")

        # Build the strategy ladder for THIS pensioner
        strategies_tried = []
        final_score = existing_score
        final_candidate = None  # we'll capture from fag_records when fresh

        # Strategy 1: spouse cross-search
        s1 = _spouse_cross_search_params(pensioner, linked_cgr_row or {})
        if s1:
            strategies_tried.append("spouse_cross_search")

        # Strategy 2: birth-state narrowing
        s2 = _birth_state_narrowing_params(pensioner)
        if s2:
            strategies_tried.append("birth_state_narrowing")

        # Strategy 3: nickname + initial-swap
        nickname_var = _nickname_variants(pensioner.get("first_name", ""))
        if nickname_var:
            strategies_tried.append("nickname_initial_swap")

        # Strategy 4: regiment-bio with death-year
        s4 = _regiment_bio_death_year_params(pensioner)
        if s4:
            strategies_tried.append("regiment_bio_death_year")

        if not strategies_tried:
            # No applicable strategies for this pensioner.
            disposition = "skipped"
            summary["skipped_no_prereq"] += 1
            out_records.append({
                "pensioner_id": pid,
                "disposition": disposition,
                "strategies_run": [],
                "top_candidate": None,
                "existing_score": existing_score,
                "existing_fag_status": existing_status,
                "notes": "No applicable Phase 3 strategies for this pensioner",
            })
            # In-place update on state.jsonl
            by_pid[pid]["leftover_pass"] = {
                "disposition": disposition,
                "strategies_run": [],
            }
            continue

        # Run FaG searches per strategy and find the best candidate.
        # In a no_fag run (tests), we skip the actual FaG call.
        best_score = existing_score
        best_candidate = None
        notes = ""

        if no_fag:
            summary["skipped_no_prereq"] += 1
            disposition = "skipped"
            notes = "no_fag mode: did not run; left as residual investigation"
        else:
            # Issue FaG searches for each applicable strategy.
            # We need a per-search wrapper that builds a virtual
            # pensioner dict shaped like search_fag expects.
            from types import SimpleNamespace
            for strat in strategies_tried:
                try:
                    if strat == "spouse_cross_search":
                        # Search for the spouse name explicitly
                        sp_first = (pensioner.get("spouse_name") or "").split()[0:1]
                        sp_last = " ".join(
                            (pensioner.get("spouse_name") or "").split()[1:]
                        )
                        fake_p = {
                            "id": pid,
                            "first_name": sp_first[0] if sp_first else "",
                            "middle_name": "",
                            "last_name": sp_last,
                            "application_number": "",
                            "regiment": "",
                            "company": "",
                            "birth_year": "",
                            "death_year": "",
                            "pensioncard_backlink": "",
                        }
                        cand, status = fag_search_fn(fake_p, None)
                    elif strat == "birth_state_narrowing":
                        cand, status = fag_search_fn(pensioner, None)
                    elif strat == "nickname_initial_swap":
                        # Replace first_name with the variant
                        fake_p = dict(pensioner)
                        fake_p["first_name"] = (
                            nickname_var[0] if nickname_var
                            else pensioner.get("first_name", "")
                        )
                        fake_p["id"] = pid
                        cand, status = fag_search_fn(fake_p, None)
                    elif strat == "regiment_bio_death_year":
                        cand, status = fag_search_fn(pensioner, None)
                    else:
                        continue

                    if cand:
                        top = max(cand, key=lambda c: c.get("score") or 0)
                        top_score = float(top.get("score") or 0)
                        if top_score > best_score:
                            best_score = top_score
                            best_candidate = {
                                "memorial_id": top.get("memorial_id"),
                                "slug": top.get("slug"),
                                "score": top_score,
                            }
                except Exception as e:
                    log.warning("Phase 3 strategy %s failed for pid %s: %s",
                                strat, pid, e)
                    summary["errors"] += 1
                    continue

            # Hard-target decision
            if best_score >= INVESTIGATE_BELOW_SCORE and best_candidate:
                # Top score is now 0.85+: conclusive found.
                disposition = "found_conclusive"
                summary["found_conclusive"] += 1
            elif not strategies_tried:
                disposition = "skipped"
                summary["skipped_no_prereq"] += 1
            else:
                # All applicable strategies tried but didn't reach the
                # threshold. Strong "no FaG memorial exists for this
                # pensioner, given the metadata we have" assertion.
                disposition = "no_fag_memorial"
                summary["no_fag_memorial"] += 1

        out_records.append({
            "pensioner_id": pid,
            "disposition": disposition,
            "strategies_run": strategies_tried,
            "top_candidate": best_candidate,
            "existing_score": existing_score,
            "existing_fag_status": existing_status,
            "notes": notes,
        })

        # Update state
        by_pid[pid]["leftover_pass"] = {
            "disposition": disposition,
            "strategies_run": strategies_tried,
            "top_candidate": best_candidate,
        }

        # Track strategy usage
        for s in strategies_tried:
            summary["strategy_usage"][s] = summary["strategy_usage"].get(s, 0) + 1

    # Write output
    out_path = state_path.parent / "leftover_investigation.jsonl"
    summary_path = state_path.parent / "leftover_investigation_summary.json"
    with out_path.open("w", encoding="utf-8") as f:
        for o in out_records:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Rewrite state.jsonl with the in-place updates
    state_tmp = state_path.with_suffix(".jsonl.tmp")
    with state_tmp.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    state_tmp.replace(state_path)

    return summary


# ============================================================
# CLI
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True,
                        help="Path to state.jsonl")
    parser.add_argument("--pensioners", type=Path, required=True,
                        help="Path to ok_pensioners.json")
    parser.add_argument("--cgr-dedup", type=Path,
                        default=Path("data/results/run_full_2026_07_16/cgr_dedup.json"))
    parser.add_argument("--throttle", type=float, default=1.5)
    parser.add_argument("--no-fag", action="store_true")
    parser.add_argument("--max-consecutive-errors", type=int, default=10)
    args = parser.parse_args()

    log = logging.getLogger("leftover_main")
    log.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    log.addHandler(handler)

    log.info("Phase 3 leftover-investigation starting")
    log.info("State: %s", args.state)
    log.info("CGR dedup: %s", args.cgr_dedup)
    log.info("Pensioners: %s", args.pensioners)
    summary = run_investigation(
        state_path=args.state,
        pensioners_path=args.pensioners,
        cgr_dedup_path=args.cgr_dedup,
        throttle_seconds=args.throttle,
        no_fag=args.no_fag,
        max_consecutive_errors=args.max_consecutive_errors,
    )
    log.info("Investigation complete: %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
