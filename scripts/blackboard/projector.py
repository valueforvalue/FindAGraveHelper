"""ProjectionBuilder: deterministic projector from Blackboard facts.

Consumes observations + DecisionPolicy and emits canonical review
rows, report stats, and badges. This is the single source of truth
for state.jsonl, view.html, reports, and sidecars.

view.html renders projection; does NOT normalize domain truth.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from scripts.blackboard.decision_policy import (
    Decision,
    DecisionContext,
    classify,
)
from scripts.projection.schema import SCHEMA_VERSION as _SCHEMA_VERSION

# Cap per pensioner so projection rows don't carry 100+
# zero-score candidates that view.html never renders and that
# bloat state.jsonl and run_audit.jsonl (issue #104 follow-up).
# The engine path (default_search_one → Blackboard → projector)
# doesn't have a cap; the legacy path used 20 in search.py.
MAX_CANDIDATES_PER_PENSIONER = 20


class ProjectionBuilder:
    """Deterministic projector from observations to review output.

    Pure function — no side effects. Takes a list of observations
    grouped by pensioner_id and produces state rows, report stats,
    and badge data.
    """

    def __init__(self, policy_version: str = "1") -> None:
        self.policy_version = policy_version

    def build_state_row(
        self,
        pensioner_id: int,
        pensioner_data: dict[str, Any],
        candidates: list[dict[str, Any]],
        cgr_data: dict[str, Any] | None = None,
        spouse_data: dict[str, Any] | None = None,
        dd_data: dict[str, Any] | None = None,
        engine: str = "findagrave",
    ) -> dict[str, Any]:
        """Build one state.jsonl row from projection inputs.

        Args:
            pensioner_id: pensioner identifier.
            pensioner_data: base fields (name, regiment, dates, etc.).
            candidates: scored FaG candidates.
            cgr_data: CGR corroboration evidence (optional).
            spouse_data: spouse match evidence (optional).
            dd_data: DixieData match evidence (optional).
            engine: engine name for common projection ("findagrave",
                "newspapers_com").

        Returns:
            A dict compatible with state.jsonl row format.
        """
        local_dy = str(pensioner_data.get("death_year") or "").strip()
        ctx = DecisionContext(
            candidates=candidates,
            local_death_year=local_dy if local_dy else None,
        )
        decision = classify(ctx)

        # Issue #104: ranked_candidates was previously emitted in
        # observation insertion order, which surfaced photo-caption
        # noise (score 0.0) above real matches when they happened
        # to fire first. Sort descending by score so the top of the
        # list is always the engine's best match. Stable sort so
        # equal-score entries keep observation order.
        sorted_candidates = sorted(
            candidates,
            key=lambda c: c.get("score", 0.0),
            reverse=True,
        )
        # Cap to top N so state.jsonl + view.html don't carry
        # scores of zero-score tail entries from the engine.
        capped_candidates = sorted_candidates[:MAX_CANDIDATES_PER_PENSIONER]

        row: dict[str, Any] = {
            "pensioner_id": pensioner_id,
            "pensioner_name": (
                f"{pensioner_data.get('last_name', '')}, "
                f"{pensioner_data.get('first_name', '')}"
            ).strip(", "),
            "status": decision.status,
            "best_score": decision.top_score,
            # Issue #62: engine path emits candidates with `url`;
            # the v1 + projector legacy shape used `backlink` and
            # `iiif_url`. Normalize here so downstream consumers
            # (state.jsonl, v2 normalizeRecord, v2 normalizeRecordV2)
            # see both keys.
            "ranked_candidates": [_normalize_candidate(c) for c in capped_candidates],
            "fag_records": [_normalize_candidate(c) for c in capped_candidates],
            "_policy_version": self.policy_version,
            # Issue #98: per-row schema version so view.html (or any
            # downstream consumer) can detect shape drift. The
            # canonical value lives in `scripts.projection.schema`.
            "_schema_version": _SCHEMA_VERSION,
        }

        # Merge base pensioner fields. v2 (the canonical review
        # UI) reads the v1 names directly off the state.jsonl
        # row: pensioner_first / pensioner_middle / pensioner_last,
        # pensioner_app_number, pensioner_birth_year,
        # pensioner_death_year, pensioncard_backlink,
        # pensioncard_pages, pensioner_spouse_first,
        # pensioner_spouse_middle, pensioner_spouse_last,
        # backlink (the pensioner record itself, not the
        # candidate). Issue #62 close: missing fields broke v2
        # display.
        v1_pensioner_keys = (
            "pensioner_first", "pensioner_middle", "pensioner_last",
            "pensioner_app_number", "pensioner_birth_year",
            "pensioner_death_year", "regiment", "company",
            "pensioncard_backlink", "pensioncard_iiif_url",
            "pensioncard_pages",
            "pensioner_spouse_first", "pensioner_spouse_middle",
            "pensioner_spouse_last", "backlink",
        )
        for v1_key in v1_pensioner_keys:
            # The input pensioner uses the un-prefixed names
            # (first_name, application_number, etc.); the v2
            # view reads the pensioner_-prefixed names. Map
            # both for back-compat.
            if v1_key in pensioner_data:
                row[v1_key] = pensioner_data[v1_key]
                continue
            # Map: pensioner_first -> first_name;
            # pensioner_app_number -> application_number;
            # pensioner_birth_year -> birth_year (input has
            # no birth_year; the v1 records did). Spouse fields
            # are spouse_first_name / spouse_middle_name /
            # spouse_last_name in the input.
            if v1_key == "pensioner_app_number":
                unprefixed = "application_number"
            elif v1_key == "pensioner_birth_year":
                unprefixed = "birth_year"
            elif v1_key == "pensioner_death_year":
                unprefixed = "death_year"
            elif v1_key == "pensioner_spouse_first":
                unprefixed = "spouse_first_name"
            elif v1_key == "pensioner_spouse_middle":
                unprefixed = "spouse_middle_name"
            elif v1_key == "pensioner_spouse_last":
                unprefixed = "spouse_last_name"
            elif v1_key == "pensioner_first":
                unprefixed = "first_name"
            elif v1_key == "pensioner_middle":
                unprefixed = "middle_name"
            elif v1_key == "pensioner_last":
                unprefixed = "last_name"
            elif v1_key == "backlink":
                unprefixed = "backlink"
            elif v1_key in ("pensioncard_backlink", "pensioncard_iiif_url"):
                # Input has both `pensioncard_backlink` and
                # `pensioncard_iiif_url` directly.
                continue
            else:
                unprefixed = v1_key
            if unprefixed in pensioner_data:
                row[v1_key] = pensioner_data[unprefixed]

        # Also keep the un-prefixed short names so the legacy
        # surfaces (e.g. scripts/state/report_generator) keep
        # working.
        for key in (
            "first_name", "middle_name", "last_name",
            "regiment", "company", "application_number",
            "birth_year", "death_year",
            "pensioncard_backlink", "pensioncard_pages",
        ):
            if key in pensioner_data and key not in row:
                row[key] = pensioner_data[key]

        # Badges (computed by projection, not mutated by passes)
        badges: list[str] = []
        if cgr_data and cgr_data.get("match_found"):
            badges.append("cgr_match")
        if spouse_data and spouse_data.get("match_confirmed"):
            badges.append("spouse_match")
        if dd_data and dd_data.get("match_found"):
            badges.append("dd_match")
        row["badges"] = badges

        # Common engine-agnostic projection (issue #39).
        # Convert candidates to common shape for v2 view.html.
        # Normalize first so the common projection sees both
        # `url` and `backlink` keys (issue #62).
        if engine == "newspapers_com":
            common_candidates = [
                _convert_np_candidate_for_projection(c) for c in capped_candidates
            ]
        else:
            common_candidates = [
                _convert_fag_candidate_for_projection(
                    _normalize_candidate(c)
                )
                for c in capped_candidates
            ]
        row["common"] = {
            "id": pensioner_id,
            "title": row["pensioner_name"],
            "engine": engine,
            "status": decision.status,
            "best_score": decision.top_score,
            "candidates": common_candidates,
            "corroboration": {
                "cgr": cgr_data or {},
                "dd_match": dd_data or None,
                "spouse_match": spouse_data or None,
            },
        }

        return row

    def build_report_stats(
        self, rows: list[dict[str, Any]]
    ) -> dict[str, int]:
        """Compute report statistics from a list of state rows."""
        stats: dict[str, int] = {
            "total": len(rows),
            "auto_accept": 0,
            "needs_review": 0,
            "low_score": 0,
            "no_candidates": 0,
            "error": 0,
        }
        for row in rows:
            status = row.get("status", "error")
            if status in stats:
                stats[status] += 1
        return stats

    def build_projection_digest(self, rows: list[dict[str, Any]]) -> str:
        """SHA-256 digest of the sorted projection for determinism checks."""
        canonical = json.dumps(
            sorted(rows, key=lambda r: r.get("pensioner_id", 0)),
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


# ============================================================
# Candidate conversion helpers (issue #39)
# ============================================================

def _convert_fag_candidate_for_projection(c: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw FaG candidate to common shape."""
    details = c.get("details") or {}
    # The scraper row stores the flat evidence dict under "evidence"
    # (not "score_evidence"). Map it to the view's score_breakdown shape.
    flat_evidence = c.get("evidence") or c.get("score_evidence") or {}
    score_breakdown = flat_evidence.get("score_breakdown", None)
    if score_breakdown is not None and isinstance(score_breakdown, dict) and score_breakdown:
        # Nested score_breakdown (engine path, engine-agnostic wrap)
        bd = dict(score_breakdown)
    else:
        # Flat evidence dict from the scraper row
        bd = flat_evidence
    common_bd = {
        "last_name": bd.get("last", 0),
        "first_name": bd.get("first", 0),
        "middle_name": bd.get("middle", 0),
        "year_window": bd.get("death", 0),
        "state": bd.get("state", 0),
        "ok_burial": bd.get("ok_burial", 0),
        "veteran": bd.get("veteran", 0),
        # Issue #110: widow/maiden/convergence badges in view.
        "widow_pension": bd.get("widow_pension", 0),
        "maiden_name": bd.get("maiden_name", 0),
        "_convergence_count": bd.get("_convergence_count", 0),
        "_spouse_linked": bool(c.get("_spouse_linked", False)),
        "_spouse_verified": bool(c.get("_spouse_verified", False)),
    }
    return {
        "id": str(c.get("memorial_id", "")),
        "title": c.get("name", ""),
        # Issue #62: engine path emits `url` (canonical); the
        # legacy path emitted `backlink`. Map both.
        "url": c.get("backlink") or c.get("url", ""),
        "score": c.get("score", 0),
        "attributes": {
            "birth_year": details.get("birth_year", ""),
            "death_year": details.get("death_year", ""),
            "state": details.get("state", ""),
        },
        "media": {
            "image_url": c.get("iiif_url", ""),
        },
        "evidence": {
            "score_breakdown": common_bd,
            "raw": c,
        },
        "search_url": c.get("search_url", ""),
        "search_urls": c.get("search_urls", []),
    }


def _convert_np_candidate_for_projection(c: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw Newspapers.com candidate to common shape."""
    return {
        "id": str(c.get("id", "")),
        "title": c.get("title", ""),
        "url": (
            f"https://www.newspapers.com{c['href']}"
            if c.get("href")
            else ""
        ),
        "score": c.get("score", 0),
        "attributes": {
            "date": c.get("iso_date", ""),
            "location": c.get("location", ""),
        },
        "media": {
            "image_url": c.get("thumbnail", ""),
        },
        "evidence": {
            "score_breakdown": c.get("score_evidence", {}),
            "raw": c,
        },
    }


def _normalize_candidate(c: dict[str, Any]) -> dict[str, Any]:
    """Project a candidate dict to the projector-row shape.

    Issue #62: the engine path emits candidates with `url`;
    the legacy v1 path emitted `backlink` and `iiif_url`.
    v2 view's normalizeRecord reads `c.backlink`; the
    common-candidate projection reads `c.url`. Normalize so
    both keys are present, and synthesize `iiif_url` from
    `memorial_id` when missing so v2's candidate thumbnails
    work in either path.
    """
    out = dict(c)  # copy
    if not out.get("backlink") and out.get("url"):
        out["backlink"] = out["url"]
    if not out.get("url") and out.get("backlink"):
        out["url"] = out["backlink"]
    if not out.get("iiif_url") and out.get("memorial_id"):
        out["iiif_url"] = (
            f"https://www.findagrave.com/iiif/2/"
            f"memorial:{out['memorial_id']}/full/full/0/default.jpg"
        )
    if not out.get("media") and out.get("iiif_url"):
        out["media"] = {"image_url": out["iiif_url"]}
    elif out.get("media") and not out["media"].get("image_url") and out.get("iiif_url"):
        out["media"]["image_url"] = out["iiif_url"]
    return out
