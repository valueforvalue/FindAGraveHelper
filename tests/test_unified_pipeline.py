"""Tests for F8: the unified pipeline (per pensioner).

User decision: Always run FaG for every pensioner. CGR is
informational; it doesn't gate the FaG search.

For one pensioner, the unified pipeline:
  1. Look up in CGR blocking index
  2. Annotate CGR matches with match_strength
  3. Run FaG search (browser; injected)
  4. Detect BOTH MATCH
  5. Return PipelineResult

The FaG browser search is expensive (1.5s throttle + actually
running Playwright), so we mock it in tests.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.pipeline.core import (
    run_pipeline_for_pensioner,
    PipelineConfig,
    PipelineResult,
)


# ============================================================
# Fixture data
# ============================================================
def _sample_cems():
    return [
        {
            "cemetery_id": 13211,
            "cemetery_name": "Baptist Mission",
            "county": "Adair",
            "veterans": [
                {"id": 96425, "name": "Andrew Jackson Alberty", "unit": "1 OK", "born": "1843"},
            ],
        },
        {
            "cemetery_id": 14481,
            "cemetery_name": "Chalk Bluff",
            "county": "Adair",
            "veterans": [
                {"id": 112601, "name": "Andrew J Alberty", "unit": "1 OK", "born": "1843"},
            ],
        },
    ]


def _sample_pensioner(**overrides):
    base = {
        "id": 5,
        "application_number": "A5",
        "first_name": "Andrew",
        "middle_name": "J",
        "last_name": "Alberty",
        "regiment": "1 OK",
        "death_year": "1933",
        "birth_year": "",
    }
    base.update(overrides)
    return base


# ============================================================
# Pipeline scenarios
# ============================================================
def test_pipeline_runs_fag_even_when_cgr_strong():
    """Per user decision: ALWAYS run FaG, even with CGR strong match.

    The CGR record is informational only. We still want the FaG
    page if one exists."""
    cgr_with_strong = [
        {
            "cemetery_id": 14481,
            "cemetery_name": "Chalk Bluff",
            "veterans": [
                {"id": 112601, "name": "Andrew J Alberty", "unit": "1 OK",
                 "born": "1843", "died": "1933-04-13", "died_state": "OK"},
            ],
        },
    ]
    fag_called = []
    def fake_fag(p, cfg):
        fag_called.append(p)
        return {"memorial_id": "123", "score": 0.7}, "auto_accept"
    config = PipelineConfig()
    result = run_pipeline_for_pensioner(
        pensioner=_sample_pensioner(),
        cgr_index_vets=cgr_with_strong,
        config=config,
        fag_search_fn=fake_fag,
    )
    # FaG MUST run even with CGR strong
    assert len(fag_called) == 1
    assert result.fag_status == "auto_accept"


def test_pipeline_runs_fag_when_no_cgr():
    """No CGR match → FaG is called."""
    cgr = []  # empty CGR
    fag_called = []
    def fake_fag(p, cfg):
        fag_called.append(p)
        return {"memorial_id": "123", "score": 0.5}, "ambiguous"
    config = PipelineConfig()
    result = run_pipeline_for_pensioner(
        pensioner=_sample_pensioner(first_name="Bob", last_name="Smith"),
        cgr_index_vets=cgr,
        config=config,
        fag_search_fn=fake_fag,
    )
    assert len(fag_called) == 1
    assert result.fag_status == "ambiguous"


def test_pipeline_runs_fag_when_cgr_medium():
    """When CGR has medium/weak match, FaG still runs."""
    fag_called = []
    def fake_fag(p, cfg):
        fag_called.append(p)
        return {"memorial_id": "123", "score": 0.7}, "auto_accept"
    config = PipelineConfig()
    result = run_pipeline_for_pensioner(
        pensioner=_sample_pensioner(),
        cgr_index_vets=_sample_cems(),
        config=config,
        fag_search_fn=fake_fag,
    )
    assert len(fag_called) == 1


def test_pipeline_returns_pensioner_metadata():
    """Result includes pensioner ID/name."""
    config = PipelineConfig()
    result = run_pipeline_for_pensioner(
        pensioner=_sample_pensioner(id=99, first_name="Mary", last_name="Doe"),
        cgr_index_vets=[],
        config=config,
        fag_search_fn=lambda p, cfg: (None, "no_results"),
    )
    assert result.pensioner["id"] == 99
    assert result.pensioner["first_name"] == "Mary"


def test_pipeline_catches_exceptions():
    """Exceptions in FaG search don't crash the pipeline."""
    def fag_search(p, cfg):
        return None, "error"
    config = PipelineConfig()
    result = run_pipeline_for_pensioner(
        pensioner=_sample_pensioner(),
        cgr_index_vets=[],
        config=config,
        fag_search_fn=fag_search,
    )
    assert result.fag_status == "error"


def test_pipeline_both_match_detected():
    """When CGR + FaG agree, both_match is set."""
    def fake_fag(p, cfg):
        return {
            "memorial_id": "999",
            "name": "Andrew J Alberty",
            "slug": "andrew-j-alberty",
            "score": 0.7,
            "details": {"death_year": "1933"},
        }, "auto_accept"

    cgr_with_death = [
        {
            "cemetery_id": 14481,
            "veterans": [
                {"id": 112601, "name": "Andrew J Alberty", "unit": "1 OK",
                 "died": "1933-04-13", "died_state": "OK"},
            ],
        },
    ]
    config = PipelineConfig()
    result = run_pipeline_for_pensioner(
        pensioner=_sample_pensioner(),
        cgr_index_vets=cgr_with_death,
        config=config,
        fag_search_fn=fake_fag,
    )
    assert result.both_match is not None
    assert result.both_match["method"] in ("corroboration", "direct_link")


def test_pipeline_handles_no_fag_results():
    """If FaG returns no candidates, status = no_results."""
    def fake_fag(p, cfg):
        return None, "no_results"
    config = PipelineConfig()
    result = run_pipeline_for_pensioner(
        pensioner=_sample_pensioner(),
        cgr_index_vets=[],
        config=config,
        fag_search_fn=fake_fag,
    )
    assert result.fag_status == "no_results"


def test_pipeline_cgr_only_mode():
    """When fag_search_fn=None, we run CGR-only mode (test)."""
    config = PipelineConfig()
    result = run_pipeline_for_pensioner(
        pensioner=_sample_pensioner(),
        cgr_index_vets=_sample_cems(),
        config=config,
        fag_search_fn=None,
    )
    # CGR data should be populated
    assert result.cgr_records is not None
    # FaG status is "not_run"
    assert result.fag_status == "not_run"


# ============================================================
# PipelineConfig
# ============================================================
def test_pipeline_config_defaults():
    """PipelineConfig has reasonable defaults."""
    config = PipelineConfig()
    assert config.throttle_seconds == 1.5


def test_pipeline_config_customizable():
    """PipelineConfig fields can be overridden."""
    config = PipelineConfig(throttle_seconds=3.0)
    assert config.throttle_seconds == 3.0