"""Tests for J3: report generator.

Produces a bulletproof final report for a run:
  - report.md: human-readable summary
  - report.json: machine-readable stats

Report includes:
  - Total records
  - Status distribution (auto_accept, ambiguous, no_results, error, captcha)
  - BOTH MATCH counts (direct_link, corroboration, total)
  - Outlier counts (per outlier_classifier thresholds)
  - Score distribution
  - State integrity check (missing/duplicate pensioners)
  - Top 10 BOTH MATCH exemplars
  - Field completeness (how many records have regiment, death_year, etc.)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.state.report_generator import (
    build_report,
    ReportStats,
    report_to_markdown,
    report_to_json,
    score_distribution,
)


# ============================================================
# Sample data helpers
# ============================================================
def _sample_records():
    return [
        # Auto-accept with strong BOTH MATCH
        {
            "pensioner_id": 1,
            "pensioner_name": "William Looney",
            "pensioner_first": "William",
            "pensioner_last": "Looney",
            "regiment": "34 TX",
            "pensioner_death_year": "1932",
            "pensioncard_backlink": "https://digitalprairie.ok.gov/digital/singleitem/collection/pensioncard/id/100",
            "backlink": "https://digitalprairie.ok.gov/digital/singleitem/collection/pensions/id/5",
            "cgr_records": [
                {"match_strength": "strong", "cgr_name": "William Looney", "cgr_id": 999,
                 "died": "1932-02-28", "died_state": "OK"},
            ],
            "fag_records": [
                {"memorial_id": "50923719", "slug": "william-looney",
                 "score": 0.85, "backlink": "https://www.findagrave.com/memorial/50923719",
                 "details": {"death_year": "1932"}},
            ],
            "best_score": 0.85,
            "fag_status": "auto_accept",
            "both_match": {"method": "corroboration", "confidence": 0.95,
                           "reason": "name + death year + burial state all agree",
                           "fag_memorial_id": "50923719"},
        },
        # No match / outlier
        {
            "pensioner_id": 2,
            "pensioner_name": "John Smith",
            "pensioner_first": "John",
            "pensioner_last": "Smith",
            "regiment": "10 AL",
            "pensioner_death_year": "",
            "cgr_records": [],
            "fag_records": [{"memorial_id": "12345", "score": 0.20}],
            "best_score": 0.20,
            "fag_status": "ambiguous",
            "both_match": None,
        },
        # No results
        {
            "pensioner_id": 3,
            "pensioner_name": "Mary Doe",
            "pensioner_first": "Mary",
            "pensioner_last": "Doe",
            "regiment": "",
            "pensioner_death_year": "",
            "cgr_records": [],
            "fag_records": [],
            "best_score": 0.0,
            "fag_status": "no_results",
            "both_match": None,
        },
        # Direct link BOTH MATCH
        {
            "pensioner_id": 4,
            "pensioner_name": "Hugh Akers",
            "pensioner_first": "Hugh",
            "pensioner_last": "Akers",
            "regiment": "4 MO",
            "pensioner_death_year": "1924",
            "pensioncard_backlink": "https://digitalprairie.ok.gov/digital/singleitem/collection/pensioncard/id/200",
            "backlink": "https://digitalprairie.ok.gov/digital/singleitem/collection/pensions/id/10",
            "cgr_records": [
                {"match_strength": "strong", "cgr_name": "Hugh H Akers", "cgr_id": 1234,
                 "died": "1924-04-29", "died_state": "OK",
                 "vet_details": {"source": "Find a Grave Memorial #98765"}},
            ],
            "fag_records": [
                {"memorial_id": "98765", "score": 0.90,
                 "backlink": "https://www.findagrave.com/memorial/98765"},
            ],
            "best_score": 0.90,
            "fag_status": "auto_accept",
            "both_match": {"method": "direct_link", "confidence": 1.0,
                           "fag_memorial_id": "98765"},
        },
    ]


# ============================================================
# ReportStats fields
# ============================================================
def test_reportstats_to_dict():
    """ReportStats has expected fields."""
    s = ReportStats(
        total=10, auto_accepts=5, ambiguous=3, no_results=1, errors=1,
        both_match_total=4, both_match_direct=1, both_match_corroborated=3,
        outliers_total=2, outliers_low_score=1, outliers_no_results=1,
    )
    d = s.to_dict()
    assert d["total"] == 10
    assert d["both_match_total"] == 4


# ============================================================
# build_report
# ============================================================
def test_build_report_counts_statuses():
    """Status distribution counts."""
    stats = build_report(_sample_records())
    # auto_accept: 2 (#1 William Looney, #4 Hugh Akers)
    assert stats.auto_accepts == 2
    # ambiguous: 1 (#2 John Smith)
    assert stats.ambiguous == 1
    # no_results: 1 (#3 Mary Doe)
    assert stats.no_results == 1


def test_build_report_counts_both_match():
    """BOTH MATCH count by method."""
    stats = build_report(_sample_records())
    assert stats.both_match_total == 2
    assert stats.both_match_direct == 1
    assert stats.both_match_corroborated == 1


def test_build_report_total_records():
    """Total record count."""
    stats = build_report(_sample_records())
    assert stats.total == 4


def test_build_report_outliers():
    """Outlier classification per config."""
    stats = build_report(_sample_records(), low_score_threshold=0.40)
    # #2 John Smith has score 0.20 → outlier (low_score)
    # #3 Mary Doe has no_results → outlier (no_results)
    assert stats.outliers_low_score == 1
    assert stats.outliers_no_results == 1
    assert stats.outliers_total == 2


def test_build_report_score_distribution():
    """Score distribution captured."""
    stats = build_report(_sample_records())
    assert "0.85-1.0" in stats.score_distribution or any(
        v > 0 for v in stats.score_distribution.values()
    )


def test_build_report_no_both_match():
    """Records with both_match=None counted correctly."""
    records = [
        {"pensioner_id": 1, "pensioner_name": "X", "pensioner_first": "X",
         "pensioner_last": "Y", "regiment": "", "pensioner_death_year": "",
         "cgr_records": [], "fag_records": [], "best_score": 0.0,
         "fag_status": "no_results", "both_match": None},
    ]
    stats = build_report(records)
    assert stats.both_match_total == 0


def test_build_report_handles_empty_input():
    """Empty input → zero stats, no crashes."""
    stats = build_report([])
    assert stats.total == 0
    assert stats.both_match_total == 0
    assert stats.outliers_total == 0


# ============================================================
# score_distribution
# ============================================================
def test_score_distribution_buckets():
    """Scores get bucketed correctly."""
    scores = [0.05, 0.20, 0.45, 0.65, 0.85, 0.95]
    dist = score_distribution(scores)
    # 0.05 → <0.20
    # 0.20 → 0.20-0.40
    # 0.45 → 0.40-0.60
    # 0.65 → 0.60-0.80
    # 0.85 → 0.80-0.95
    # 0.95 → 0.95-1.00
    assert dist["<0.20"] == 1
    assert dist["0.20-0.40"] == 1
    assert dist["0.40-0.60"] == 1
    assert dist["0.60-0.80"] == 1
    assert dist["0.80-0.95"] == 1
    assert dist["0.95-1.00"] == 1


def test_score_distribution_handles_zero_scores():
    records = [
        {"best_score": 0.0},
        {"best_score": 0.5},
    ]
    stats = build_report(records)
    # 0.0 → <0.20
    assert stats.score_distribution["<0.20"] == 1


# ============================================================
# report_to_markdown
# ============================================================
def test_report_to_markdown_includes_headline():
    """Markdown report has a clear headline."""
    stats = build_report(_sample_records())
    md = report_to_markdown(stats, _sample_records())
    assert "# Find a Grave Helper — Run Report" in md
    assert "Total pensioners" in md


def test_report_to_markdown_includes_counts():
    """Markdown has all key counts."""
    stats = build_report(_sample_records())
    md = report_to_markdown(stats, _sample_records())
    assert "auto_accept" in md.lower()
    assert "both match" in md.lower()


def test_report_to_markdown_includes_top_both_matches():
    """Markdown lists top BOTH MATCH exemplars."""
    stats = build_report(_sample_records())
    md = report_to_markdown(stats, _sample_records())
    # William Looney and Hugh Akers are the BOTH MATCH exemplars
    assert "William Looney" in md
    assert "Hugh Akers" in md


def test_report_to_markdown_includes_pensioncard_links():
    """Markdown renders pensioncard backlink for each exemplar."""
    stats = build_report(_sample_records())
    md = report_to_markdown(stats, _sample_records())
    # pensioncard URLs from sample records
    assert "/pensioncard/id/100" in md
    assert "/pensioncard/id/200" in md


def test_report_to_markdown_includes_application_links():
    """Markdown renders pensions-application backlink for each exemplar."""
    stats = build_report(_sample_records())
    md = report_to_markdown(stats, _sample_records())
    # application URLs from sample records
    assert "/pensions/id/5" in md
    assert "/pensions/id/10" in md


def test_exemplar_payload_includes_both_backlinks():
    """Top-both-match payload includes pensioncard_backlink + backlink."""
    from scripts.state.report_generator import _both_match_exemplars
    exemplars = _both_match_exemplars(_sample_records())
    assert len(exemplars) >= 2
    for ex in exemplars:
        assert "pensioncard_backlink" in ex
        assert "backlink" in ex


# ============================================================
# report_to_json
# ============================================================
def test_report_to_json_serializes_stats():
    """JSON output is valid JSON."""
    stats = build_report(_sample_records())
    j = report_to_json(stats)
    parsed = json.loads(j)
    assert parsed["total"] == 4
    assert parsed["both_match_total"] == 2


def test_report_to_json_includes_exemplars():
    """JSON includes top BOTH MATCH records."""
    stats = build_report(_sample_records())
    j = report_to_json(stats)
    parsed = json.loads(j)
    assert "top_both_match" in parsed
    assert len(parsed["top_both_match"]) >= 1


# ============================================================
# Field completeness
# ============================================================
def test_report_field_completeness():
    """What % of records have each field."""
    stats = build_report(_sample_records())
    completeness = stats.field_completeness
    assert completeness["pensioner_birth_year"] >= 0  # ok, may be 0%
    assert completeness["pensioner_death_year"] >= 0
    # We have 2/4 with death_year filled (William Looney + Hugh Akers)
    assert completeness["pensioner_death_year"] == 50.0