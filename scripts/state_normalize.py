"""State record normalization for view.html.

The unified state file (from F4) has a different shape from
the legacy FaG-only state file. view.html needs to render both
formats.

This module normalizes records into a uniform shape so view.html
can use one set of accessors. The same logic is mirrored in
view.html (in JS).

Unified shape:
  {
    pensioner_id,
    pensioner_name,
    pensioner_first,
    pensioner_last,
    regiment,
    company,
    pensioncard_backlink,
    cgr_records, cgr_status,
    fag_records, fag_status, cgr_skipped_fag,
    both_match: { method, reason, confidence } | None,
    ranked_candidates: <alias for fag_records, top 20 by score>,
    best_score: <max of fag_records or 0>,
    status: <alias for fag_status>,
    strategies_run: [],
    timestamp,
  }
"""
from __future__ import annotations

# T018: use the typed front from scripts.state.schema. Keeps the
# dict-returning legacy surface for back-compat (view.html is browser-side
# and reads its own JS normalizer), but the Python side now reasons
# about PensionerRecord instead of raw dicts.
from scripts.state.schema import (
    from_dict_pensioner,
    PensionerRecord,
)


# ============================================================
# Format detection
# ============================================================
def is_unified(rec: dict) -> bool:
    """A unified record has fag_records OR cgr_records or
    cgr_skipped_fag or fag_status/cgr_status explicit fields.

    If a record has ANY of the unified-format keys, treat it as
    unified. Pure legacy records only have ranked_candidates."""
    unified_keys = (
        "fag_records", "cgr_records",
        "fag_status", "cgr_status",
        "cgr_skipped_fag", "both_match",
    )
    return any(k in rec for k in unified_keys)


def is_fag_only(rec: dict) -> bool:
    """A FaG-only (legacy) record has ranked_candidates and no
    unified-format keys."""
    return "ranked_candidates" in rec and not is_unified(rec)


# ============================================================
# Field extractors
# ============================================================
def extract_fag_candidates(rec: dict) -> list[dict]:
    """Get FaG candidates regardless of state format."""
    if is_unified(rec):
        return rec.get("fag_records", []) or []
    if is_fag_only(rec):
        return rec.get("ranked_candidates", []) or []
    return []


def extract_cgr_records(rec: dict) -> list[dict]:
    """Get CGR records."""
    return rec.get("cgr_records", []) or []


def get_status(rec: dict) -> str:
    """Get the status string regardless of format."""
    if is_unified(rec):
        # If CGR strong skipped FaG, the fag_status is "skipped_cgr_strong"
        # That's the most informative status for view.html
        if rec.get("fag_status"):
            return rec["fag_status"]
        if rec.get("cgr_status"):
            return rec["cgr_status"]
        return "unknown"
    return rec.get("status", "unknown")


def get_both_match(rec: dict) -> dict | None:
    """Get the BOTH MATCH info from a unified record."""
    return rec.get("both_match") if is_unified(rec) else None


def get_both_match_html_class(rec: dict) -> str:
    """CSS class for BOTH MATCH badge (or empty string)."""
    bm = get_both_match(rec)
    if not bm:
        return ""
    method = bm.get("method", "")
    if method == "direct_link":
        return "both-match-direct"
    if method == "corroboration":
        return "both-match-corroborated"
    return ""


# ============================================================
# Normalization
# ============================================================
def normalize_state_record(rec: dict) -> dict:
    """Normalize a state record to a uniform shape view.html can render.

    Returns a NEW dict; original is untouched.

    T018: parse the input through scripts.state.schema.from_dict_pensioner
    first so we reason about typed fields. Output dict shape stays
    unchanged for back-compat with view.html (browser-side, reads its
    own JS normalizer).
    """
    # Typed parse; schema-version mismatch is silent (forward-compat).
    typed = from_dict_pensioner(rec)

    if is_unified(rec):
        fag_raw = rec.get("fag_records", []) or []
        # Coerce CandidateRecord back to dicts for the legacy output shape.
        fag_dicts = [c.to_dict() if hasattr(c, "to_dict") else c for c in typed.fag_records]
        best = max((c.get("score", 0) or 0) for c in fag_raw) if fag_raw else 0.0
        best_cand = max(fag_raw, key=lambda c: c.get("score", 0)) if fag_raw else None
        return {
            "pensioner_id": typed.pensioner_id,
            "pensioner_name": typed.pensioner_name,
            "pensioner_first": typed.pensioner_first,
            "pensioner_middle": typed.pensioner_middle,
            "pensioner_last": typed.pensioner_last,
            "pensioner_birth_year": typed.pensioner_birth_year,
            "pensioner_death_year": typed.pensioner_death_year,
            "pensioner_app_number": typed.pensioner_app_number,
            "regiment": typed.regiment,
            "company": typed.company,
            "pensioncard_backlink": typed.pensioncard_backlink,
            "backlink": typed.backlink,
            "ranked_candidates": fag_dicts[:20],
            "best_score": best,
            "best_candidate": best_cand,
            "status": get_status(rec),
            "fag_status": typed.fag_status,
            "strategies_run": rec.get("strategies_run", []),
            "cgr_records": typed.cgr_records,
            "cgr_status": typed.cgr_status,
            "cgr_skipped_fag": bool(rec.get("cgr_skipped_fag", False)),
            "both_match": typed.both_match.to_dict() if typed.both_match else None,
            "timestamp": typed.timestamp,
        }

    return {
        "pensioner_id": typed.pensioner_id,
        "pensioner_name": typed.pensioner_name,
        "pensioner_first": typed.pensioner_first,
        "pensioner_middle": "",
        "pensioner_last": "",
        "pensioner_birth_year": "",
        "pensioner_death_year": "",
        "pensioner_app_number": typed.pensioner_app_number,
        "regiment": typed.regiment,
        "company": typed.company,
        "pensioncard_backlink": typed.pensioncard_backlink,
        "backlink": typed.backlink,
        "ranked_candidates": rec.get("ranked_candidates", []) or [],
        "best_score": rec.get("best_score", 0.0),
        "best_candidate": rec.get("best_candidate"),
        "status": rec.get("status", "unknown"),
        "fag_status": rec.get("status", ""),
        "strategies_run": rec.get("strategies_run", []),
        "cgr_records": [],
        "cgr_status": "",
        "cgr_skipped_fag": False,
        "both_match": None,
        "timestamp": typed.timestamp,
    }

def write_normalized_jsonl(
    input_path: Path,
    output_path: Path,
) -> int:
    """Convert a JSONL state file to normalized form. Returns row count."""
    import json
    output_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with input_path.open(encoding="utf-8") as fin, \
         output_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            normalized = normalize_state_record(rec)
            fout.write(json.dumps(normalized, ensure_ascii=False) + "\n")
            n += 1
    return n