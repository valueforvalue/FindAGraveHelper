"""Report generator for the unified pipeline.

Produces a bulletproof final report:
  - report.md: human-readable
  - report.json: machine-readable

Report contents:
  - Total records
  - Status distribution (auto_accept, ambiguous, no_results, error, captcha)
  - BOTH MATCH counts (direct_link, corroboration, total)
  - Outlier counts (per outlier_classifier)
  - Score distribution
  - Top 10 BOTH MATCH exemplars
  - Field completeness (% with each field)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from scripts.matching.outlier_classifier import (
    OutlierConfig,
    classify_record,
    is_outlier,
)


# ============================================================
# Score bucketing
# ============================================================
_SCORE_BUCKETS = [
    ("<0.20", 0.0, 0.20),
    ("0.20-0.40", 0.20, 0.40),
    ("0.40-0.60", 0.40, 0.60),
    ("0.60-0.80", 0.60, 0.80),
    ("0.80-0.95", 0.80, 0.95),
    ("0.95-1.00", 0.95, 1.01),
]


def score_distribution(scores: list[float]) -> dict:
    """Bucket scores into the standard ranges."""
    out = {label: 0 for label, _, _ in _SCORE_BUCKETS}
    for s in scores:
        s = max(0.0, min(1.0, s or 0))
        for label, lo, hi in _SCORE_BUCKETS:
            if lo <= s < hi:
                out[label] += 1
                break
    return out


# ============================================================
# ReportStats
# ============================================================
@dataclass
class ReportStats:
    """Aggregate stats for the run."""
    total: int = 0
    auto_accepts: int = 0
    ambiguous: int = 0
    no_results: int = 0
    errors: int = 0
    captchas: int = 0
    too_many: int = 0
    skipped: int = 0
    # BOTH MATCH
    both_match_total: int = 0
    both_match_direct: int = 0
    both_match_corroborated: int = 0
    # Outliers
    outliers_total: int = 0
    outliers_low_score: int = 0
    outliers_no_results: int = 0
    outliers_error: int = 0
    # Score distribution
    score_distribution: dict = field(default_factory=dict)
    # Field completeness (% of non-empty values per field)
    field_completeness: dict = field(default_factory=dict)
    # Top BOTH MATCH exemplars
    top_both_match: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# build_report
# ============================================================
def _status_counts(records: list[dict]) -> dict[str, int]:
    """Tally each status."""
    s = {
        "auto_accept": 0, "ambiguous": 0, "no_results": 0,
        "error": 0, "captcha": 0, "too_many": 0, "skip": 0,
        "other": 0,
    }
    for r in records:
        status = r.get("fag_status") or r.get("status", "")
        if status in s:
            s[status] += 1
        else:
            s["other"] += 1
    return s


def _field_completeness(records: list[dict]) -> dict[str, float]:
    """What % of records have each field filled?"""
    fields = [
        "pensioner_first", "pensioner_last", "regiment",
        "pensioner_birth_year", "pensioner_death_year",
        "pensioncard_backlink",
    ]
    if not records:
        return {f: 0.0 for f in fields}
    out = {}
    n = len(records)
    for f in fields:
        count = sum(1 for r in records if r.get(f))
        out[f] = round((count / n) * 100, 1)
    return out


def _both_match_exemplars(records: list[dict], top_n: int = 10) -> list[dict]:
    """Top BOTH MATCH records by confidence."""
    bm_records = [
        r for r in records
        if r.get("both_match") and r.get("both_match", {}).get("method")
    ]
    # Sort by confidence, desc
    bm_records.sort(
        key=lambda r: r.get("both_match", {}).get("confidence", 0) or 0,
        reverse=True,
    )
    out = []
    for r in bm_records[:top_n]:
        out.append({
            "pensioner_id": r.get("pensioner_id"),
            "pensioner_name": r.get("pensioner_name"),
            "method": r["both_match"].get("method"),
            "confidence": r["both_match"].get("confidence"),
            "reason": r["both_match"].get("reason"),
            "fag_memorial_id": r["both_match"].get("fag_memorial_id"),
            "fag_backlink": f"https://www.findagrave.com/memorial/{r['both_match'].get('fag_memorial_id')}",
            "pensioncard_backlink": r.get("pensioncard_backlink", ""),
            "backlink": r.get("backlink", ""),
        })
    return out


def build_report(
    records: list[dict],
    low_score_threshold: float = 0.40,
) -> ReportStats:
    """Build ReportStats from a list of unified state records."""
    stats = ReportStats()
    stats.total = len(records)

    sc = _status_counts(records)
    stats.auto_accepts = sc["auto_accept"]
    stats.ambiguous = sc["ambiguous"]
    stats.no_results = sc["no_results"]
    stats.errors = sc["error"]
    stats.captchas = sc["captcha"]
    stats.too_many = sc["too_many"]
    stats.skipped = sc["skip"]

    # BOTH MATCH
    for r in records:
        bm = r.get("both_match")
        if not bm or not bm.get("method"):
            continue
        stats.both_match_total += 1
        method = bm.get("method")
        if method == "direct_link":
            stats.both_match_direct += 1
        elif method == "corroboration":
            stats.both_match_corroborated += 1

    # Outliers
    cfg = OutlierConfig(low_score_threshold=low_score_threshold)
    for r in records:
        if is_outlier(r, cfg):
            stats.outliers_total += 1
            fag_records = r.get("fag_records", []) or []
            if fag_records:
                score = max((c.get("score", 0) or 0) for c in fag_records)
            else:
                score = 0.0
            status = r.get("fag_status", "")
            if status == "no_results":
                stats.outliers_no_results += 1
            elif status in ("error", "captcha"):
                stats.outliers_error += 1
            elif score < low_score_threshold:
                stats.outliers_low_score += 1

    # Score distribution
    scores = [r.get("best_score", 0) or 0 for r in records]
    stats.score_distribution = score_distribution(scores)

    # Field completeness
    stats.field_completeness = _field_completeness(records)

    # Top BOTH MATCH
    stats.top_both_match = _both_match_exemplars(records)

    return stats


# ============================================================
# report_to_markdown
# ============================================================
def report_to_markdown(stats: ReportStats, records: list[dict]) -> str:
    """Render ReportStats as Markdown."""
    lines = []
    lines.append("# Find a Grave Helper — Run Report")
    lines.append("")
    lines.append(f"Generated: {stats.score_distribution and 'see created_at'}".rstrip())
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total pensioners processed:** {stats.total}")
    n_both = stats.both_match_total
    pct = round((n_both / stats.total) * 100, 1) if stats.total else 0
    lines.append(f"- **BOTH MATCH (CGR + FaG agree):** {n_both} ({pct}%)")
    lines.append(f"  - Direct link: {stats.both_match_direct}")
    lines.append(f"  - Corroboration: {stats.both_match_corroborated}")
    lines.append("")
    lines.append("### Status Distribution")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|---|---|")
    lines.append(f"| auto_accept | {stats.auto_accepts} |")
    lines.append(f"| ambiguous | {stats.ambiguous} |")
    lines.append(f"| too_many | {stats.too_many} |")
    lines.append(f"| no_results | {stats.no_results} |")
    lines.append(f"| error | {stats.errors} |")
    lines.append(f"| captcha | {stats.captchas} |")
    lines.append(f"| skipped (CGR strong / no name) | {stats.skipped} |")
    lines.append("")

    # Outliers
    lines.append("### Outliers (need follow-up runs)")
    lines.append("")
    lines.append(f"Total: {stats.outliers_total}")
    lines.append(f"  - Low score: {stats.outliers_low_score}")
    lines.append(f"  - No results: {stats.outliers_no_results}")
    lines.append(f"  - Error/Captcha: {stats.outliers_error}")
    lines.append("")

    # Score distribution
    lines.append("### Score Distribution")
    lines.append("")
    lines.append("| Range | Count |")
    lines.append("|---|---|")
    for label, _, _ in _SCORE_BUCKETS:
        lines.append(f"| {label} | {stats.score_distribution.get(label, 0)} |")
    lines.append("")

    # Field completeness
    lines.append("### Field Completeness (% non-empty)")
    lines.append("")
    lines.append("| Field | % |")
    lines.append("|---|---|")
    for field_name, pct in stats.field_completeness.items():
        lines.append(f"| {field_name} | {pct}% |")
    lines.append("")

    # Top BOTH MATCH
    lines.append("### Top BOTH MATCH Exemplars")
    lines.append("")
    if stats.top_both_match:
        lines.append("| Pensioner | Method | Confidence | Reason | FaG | Pension card | Application |")
        lines.append("|---|---|---|---|---|---|---|")
        for bm in stats.top_both_match:
            card_cell = (
                f"[card]({bm['pensioncard_backlink']})"
                if bm.get("pensioncard_backlink") else "—"
            )
            app_cell = (
                f"[app]({bm['backlink']})"
                if bm.get("backlink") else "—"
            )
            lines.append(
                f"| #{bm['pensioner_id']} {bm['pensioner_name']} "
                f"| {bm['method']} | {bm['confidence']*100:.0f}% "
                f"| {bm['reason']} "
                f"| [open]({bm['fag_backlink']}) "
                f"| {card_cell} "
                f"| {app_cell} |"
            )
    else:
        lines.append("_No BOTH MATCH records found._")
    lines.append("")

    return "\n".join(lines)


# ============================================================
# report_to_json
# ============================================================
def report_to_json(stats: ReportStats) -> str:
    """Serialize ReportStats as JSON."""
    return json.dumps(stats.to_dict(), indent=2, ensure_ascii=False)


def write_report(
    stats: ReportStats,
    records: list[dict],
    out_dir: Path,
    timestamp: str = "",
) -> tuple[Path, Path]:
    """Write report.md and report.json to out_dir. Returns paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    md = report_to_markdown(stats, records)
    js = report_to_json(stats)
    if timestamp:
        md_path = out_dir / f"report_{timestamp}.md"
        js_path = out_dir / f"report_{timestamp}.json"
    else:
        md_path = out_dir / "report.md"
        js_path = out_dir / "report.json"
    md_path.write_text(md, encoding="utf-8")
    js_path.write_text(js, encoding="utf-8")
    return md_path, js_path