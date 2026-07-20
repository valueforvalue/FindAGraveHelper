"""CGR <-> FaG dedup: post-run classification of pensioner records.

After the FaG search runs, this module compares each pensioner
record against the CGR (Confederate Graves Registry) blocking
index and assigns one of four statuses:

  - duplicate:              CGR has them AND FaG auto-resolved them
                            (CGR-side row is now redundant for review)
  - follow_up_candidate:    CGR has them but FaG did NOT auto-resolve
                            (FaG missed; the CGR match is the best
                            lead; reviewer should re-examine the FaG
                            candidates or do a targeted second search)
  - clear:                  no CGR candidate for this pensioner
                            (FaG is the only signal)
  - no_fag_match:           no CGR candidate AND FaG found nothing
                            (cold lead; needs manual research)

The module is invoked as a post-run step from
scripts/pipeline/run_unified.py. It rewrites results.jsonl in
place to add a `cgr_dedup_status` field per record, and writes a
separate `cgr_fag_dedup.json` summary.

Public surface:
  extract_year(s) -> str | None
  normalize_unit(unit) -> str   (placeholder; alias logic lives in
                                cgr_matcher.py)
  match_strength(pensioner, cgr_row) -> str ('strong'|'medium'|'weak'|'none')
  classify_pensioner(pensioner, cgr_candidates) -> dict
  run_dedup(results_path, cgr_path, output_path) -> dict
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Bootstrap so this script can be imported when run as a module
_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.cgr.cgr_matcher import match_pensioner_to_cgr  # noqa: E402


VERSION = 1


# ============================================================
# Year extraction
# ============================================================
_YEAR_RE = re.compile(r"\b(\d{4})\b")


def extract_year(value) -> Optional[str]:
    """Extract a 4-digit year from a CGR date string.

    Handles:
      - "1845-01-21"  -> "1845"
      - "1844"        -> "1844"
      - "about 1845"  -> "1845"  (best-effort)
      - "" / None     -> None
      - "unknown"     -> None
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = _YEAR_RE.search(s)
    return m.group(1) if m else None


def normalize_unit(unit: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Full alias expansion (e.g. '4 LA' -> '4th Louisiana') lives in
    scripts/cgr/cgr_matcher.py. This is the bare normalization used
    for matching keys.
    """
    if not unit:
        return ""
    s = unit.lower()
    # Strip punctuation except hyphens
    s = re.sub(r"[^a-z0-9\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ============================================================
# Per-row match strength
# ============================================================
def match_strength(pensioner: dict, cgr_row: dict) -> str:
    """Return one of 'strong' / 'medium' / 'weak' / 'none'.

    strong:   last name exact + first name exact (phonetic OK) +
              (unit match OR birth-year match within ±2)
    medium:   last name exact + first name match (any closeness)
    weak:     last name exact + first name differs significantly
    none:     last name differs
    """
    p_last = (pensioner.get("pensioner_last") or pensioner.get("last_name") or "").lower().strip()
    c_last = (cgr_row.get("last_name") or "").lower().strip()
    if not p_last or p_last != c_last:
        return "none"

    p_first = (pensioner.get("pensioner_first") or pensioner.get("first_name") or "").lower().strip()
    c_first = (cgr_row.get("first_name") or "").lower().strip()
    # Last name matches. Now first name:
    if not p_first or not c_first:
        return "weak"  # one of them has no first name
    if p_first == c_first:
        first_match = "exact"
    else:
        # Try phonetic match (Double Metaphone) via the CGR matcher
        try:
            matches, _ = match_pensioner_to_cgr(
                {"first_name": p_first, "last_name": c_last},
                [{"first_name": c_first, "last_name": c_last}],
            )
            first_match = "phonetic" if matches else "different"
        except Exception:
            # Conservative: assume different
            first_match = "different"

    if first_match == "different":
        return "weak"

    # First name matches. Now check unit or year for STRONG:
    p_unit = normalize_unit(pensioner.get("regiment") or pensioner.get("unit") or "")
    c_unit = normalize_unit(cgr_row.get("unit") or "")
    unit_match = bool(p_unit and c_unit and (p_unit in c_unit or c_unit in p_unit))

    p_birth = pensioner.get("pensioner_birth_year") or pensioner.get("birth_year") or ""
    c_birth = extract_year(cgr_row.get("born") or cgr_row.get("birth_year"))
    year_match = False
    if p_birth and c_birth:
        try:
            year_match = abs(int(p_birth) - int(c_birth)) <= 2
        except (TypeError, ValueError):
            year_match = False

    if unit_match or year_match:
        return "strong"
    return "medium"


# ============================================================
# Per-pensioner dedup classification
# ============================================================
# A FaG result is "auto-resolved" when the harness classified it
# with a status that doesn't need human review. CGR is the
# confirmation signal, not a replacement for the FaG ladder.
#
# This set MUST contain only canonical FaG status strings (the
# values in scripts.pipeline.scoring_constants.STATUS_*).
# 'both_match' is a CGR cross-confirmation record field, NOT a
# status — it is consumed by scripts.state.report_generator and
# must never enter the status check. 'BOTH_MATCH' is an internal
# label, not a status enum value.
from scripts.pipeline.scoring_constants import STATUS_AUTO_ACCEPT
_AUTO_RESOLVED_FAG_STATUSES = frozenset({STATUS_AUTO_ACCEPT})


def classify_pensioner(
    pensioner: dict,
    cgr_candidates: list[dict],
) -> dict:
    """Classify one pensioner against its CGR candidates.

    Returns a dict ready to merge into the pensioner's record:

      {
        "cgr_dedup_status": "duplicate" | "follow_up_candidate"
                              | "clear" | "no_fag_match",
        "cgr_match_summary": { ... } | None,
        "cgr_candidates_count": <int>,
      }
    """
    # Score every CGR candidate; pick the strongest
    best = None
    best_strength = "none"
    for c in cgr_candidates:
        s = match_strength(pensioner, c)
        if s == "none":
            continue
        rank = {"strong": 3, "medium": 2, "weak": 1}.get(s, 0)
        best_rank = {"strong": 3, "medium": 2, "weak": 1}.get(best_strength, 0)
        if rank > best_rank:
            best = c
            best_strength = s

    fag_status = pensioner.get("fag_status", "")
    fag_records = pensioner.get("fag_records") or []
    fag_auto = fag_status in _AUTO_RESOLVED_FAG_STATUSES

    if best is None:
        # No CGR match
        if fag_records or fag_status and fag_status not in ("no_results", "error", ""):
            return {
                "cgr_dedup_status": "clear",
                "cgr_match_summary": None,
                "cgr_candidates_count": len(cgr_candidates),
            }
        # No CGR + no FaG
        return {
            "cgr_dedup_status": "no_fag_match",
            "cgr_match_summary": None,
            "cgr_candidates_count": 0,
        }

    # Have a CGR candidate. Build the summary.
    summary = {
        "cgr_id": best.get("id"),
        "cgr_name": best.get("name") or "",
        "cgr_cemetery": best.get("cemetery_name") or "",
        "cgr_unit": best.get("unit") or "",
        "cgr_birth_year": extract_year(best.get("born")),
        "cgr_death_year": extract_year(best.get("died")),
        "cgr_died_state": best.get("died_state") or "",
        "match_strength": best_strength,
    }

    if best_strength in ("strong", "medium"):
        if fag_auto:
            return {
                "cgr_dedup_status": "duplicate",
                "cgr_match_summary": summary,
                "cgr_candidates_count": len(cgr_candidates),
            }
        else:
            return {
                "cgr_dedup_status": "follow_up_candidate",
                "cgr_match_summary": summary,
                "cgr_candidates_count": len(cgr_candidates),
            }

    # Weak CGR match (last name only) — treat as noise
    return {
        "cgr_dedup_status": "clear",
        "cgr_match_summary": {
            **summary,
            "match_strength": "weak",
            "note": "Weak CGR match (last name only); not used for dedup.",
        },
        "cgr_candidates_count": len(cgr_candidates),
    }


# ============================================================
# CGR blocking index lookup per pensioner
# ============================================================
def lookup_cgr_candidates_for_pensioner(
    pensioner: dict,
    cgr_blocking_index,
) -> list[dict]:
    """Find CGR records that block on this pensioner.

    Uses the same blocking index the pipeline builds (see
    scripts.pipeline.core.build_cgr_blocking_index). Returns a
    list of full CGR record dicts.
    """
    from scripts.pipeline.core import lookup_cgr_for_pensioner as _lookup
    first = (pensioner.get("pensioner_first")
             or pensioner.get("first_name") or "")
    last = (pensioner.get("pensioner_last")
            or pensioner.get("last_name") or "")
    try:
        return _lookup(cgr_blocking_index, first, last, limit=20)
    except Exception:
        return []


# ============================================================
# Top-level run_dedup
# ============================================================
def _load_results(results_path: Path) -> list[dict]:
    if not results_path.exists():
        return []
    out = []
    with results_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _load_cgr(cgr_path: Path) -> list[dict]:
    if not cgr_path.exists():
        return []
    out = []
    with cgr_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def run_dedup(
    results_path: Path,
    cgr_path: Path,
    output_path: Path,
    cgr_blocking_index=None,
) -> dict:
    """Compare results.jsonl against CGR; annotate records in place;
    write a summary report.

    Args:
        results_path: Path to results.jsonl. Read, annotated, written
            back atomically (in-place).
        cgr_path: Path to ok_vets_enriched.jsonl (or any compatible
            CGR JSONL).
        output_path: Path to write cgr_fag_dedup.json.
        cgr_blocking_index: Optional pre-built blocking index (for
            speed). If None, this function loads CGR records and
            builds the index once.

    Returns:
        The summary report dict (also written to output_path).
    """
    results_path = Path(results_path)
    cgr_path = Path(cgr_path)
    output_path = Path(output_path)

    records = _load_results(results_path)
    cgr_records = _load_cgr(cgr_path)

    # Build the blocking index from CGR records (if not provided).
    # The pipeline's build_cgr_blocking_index takes a list of
    # cemetery dicts; our CGR JSONL has flat records. Wrap each
    # record as a single-vet cemetery dict so the builder is happy.
    if cgr_blocking_index is None and cgr_records:
        try:
            from scripts.pipeline.core import build_cgr_blocking_index
            # Wrap each CGR record as a single-vet cemetery dict
            wrapped = [
                {
                    "cemetery_id": r.get("cemetery_id"),
                    "cemetery_name": r.get("cemetery_name", ""),
                    "county": r.get("county", ""),
                    "state": r.get("state", "OK"),
                    "veterans": [r],
                }
                for r in cgr_records
            ]
            cgr_blocking_index = build_cgr_blocking_index(wrapped)
        except Exception as e:
            # Fall back to a per-pensioner scan
            print(f"WARNING: cgr_blocking_index build failed: {e}", file=sys.stderr)
            cgr_blocking_index = None

    # Classify each pensioner
    by_status = {"duplicate": 0, "follow_up_candidate": 0, "clear": 0, "no_fag_match": 0}
    pensioner_summaries = {}

    annotated = []
    for rec in records:
        pid = rec.get("pensioner_id")
        # Find CGR candidates via blocking index
        if cgr_blocking_index is not None:
            candidates = lookup_cgr_candidates_for_pensioner(rec, cgr_blocking_index)
        else:
            # Last-resort fallback: scan all CGR records for last-name
            # match. O(N*M) but only used when blocking fails.
            p_last = (rec.get("pensioner_last") or rec.get("last_name") or "").lower().strip()
            candidates = [
                c for c in cgr_records
                if (c.get("last_name") or "").lower().strip() == p_last
            ][:10]

        verdict = classify_pensioner(rec, candidates)
        rec.update(verdict)
        by_status[verdict["cgr_dedup_status"]] += 1
        if pid is not None:
            pensioner_summaries[str(pid)] = verdict
        annotated.append(rec)

    # Atomic write of results.jsonl
    tmp = results_path.with_suffix(results_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in annotated:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(results_path)

    # Build the report
    report = {
        "version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "results_path": str(results_path),
        "cgr_path": str(cgr_path),
        "stats": {
            "pensioners_processed": len(records),
            "cgr_records_loaded": len(cgr_records),
            "pensioner_count_by_status": by_status,
        },
        "pensioners": pensioner_summaries,
        "follow_up_candidates": [
            {"pensioner_id": k, **v}
            for k, v in pensioner_summaries.items()
            if v["cgr_dedup_status"] == "follow_up_candidate"
        ],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report


__all__ = [
    "VERSION",
    "extract_year",
    "normalize_unit",
    "match_strength",
    "classify_pensioner",
    "run_dedup",
    "lookup_cgr_candidates_for_pensioner",
]