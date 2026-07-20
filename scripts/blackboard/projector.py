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

        row: dict[str, Any] = {
            "pensioner_id": pensioner_id,
            "pensioner_name": (
                f"{pensioner_data.get('last_name', '')}, "
                f"{pensioner_data.get('first_name', '')}"
            ).strip(", "),
            "status": decision.status,
            "best_score": decision.top_score,
            "ranked_candidates": candidates,
            "fag_records": candidates,
            "_policy_version": self.policy_version,
        }

        # Merge base pensioner fields
        for key in (
            "first_name", "last_name", "regiment", "company",
            "birth_year", "death_year", "application_number",
        ):
            if key in pensioner_data:
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
        if engine == "newspapers_com":
            common_candidates = [
                _convert_np_candidate_for_projection(c) for c in candidates
            ]
        else:
            common_candidates = [
                _convert_fag_candidate_for_projection(c) for c in candidates
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
                "dd_match": dd_data or {},
                "spouse_match": spouse_data or {},
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
    evidence = c.get("score_evidence") or {}
    score_breakdown = evidence.get("score_breakdown", {})
    common_bd = {}
    if score_breakdown:
        common_bd = {
            "last_name": score_breakdown.get("last", 0),
            "first_name": score_breakdown.get("first", 0),
            "middle_name": score_breakdown.get("middle", 0),
            "year_window": score_breakdown.get("death", 0),
            "state": score_breakdown.get("state", 0),
            "ok_burial": score_breakdown.get("ok_burial", 0),
            "veteran": score_breakdown.get("veteran", 0),
        }
    return {
        "id": str(c.get("memorial_id", "")),
        "title": c.get("name", ""),
        "url": c.get("backlink", ""),
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
