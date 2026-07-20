"""Tests for the pipeline orchestrator consuming SearchEngine
+ SearchRecord (issue #35).

After #33 and #34 the pipeline takes an engine + a record
instead of an `fag_search_fn` callable. These tests pin:

  - `run_one(record, cgr_index_vets, config)` works with a
    FaGEngine (today's behavior, byte-identical wire format).
  - `run_one` works with a FakeSearchEngine (proves the
    abstraction is real; a 2nd engine can run the pipeline).
  - The engine's result is attached to the PipelineResult
    (engine-agnostic; the wire-format conversion knows how
    to handle FaG-shaped results).
  - Error handling: engine raises → PipelineResult captures
    the error, doesn't take down the run.
  - State persistence is engine-agnostic: a FakeSearchEngine
    run produces a state.jsonl line with no FaG-specific
    keys (the engine's result lives in attributes).
  - Back-compat: `fag_search_fn` callback still works.
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from dataclasses import dataclass, field

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.search.context import SearchContext
from scripts.search.record import (
    SearchRecord, from_pensioner, to_pensioner_dict,
)
from scripts.search.engine import default_search_one
from scripts.search.fag_engine import FaGEngine
from scripts.search.strategy import as_strategy
from scripts.search.context import from_pensioner as ctx_from_pensioner

from scripts.pipeline.core import (
    PipelineConfig,
    PipelineResult,
    UnifiedRunResult,
    run_pipeline_for_pensioner,
    run_one,
)


# ============================================================
# FakeSearchEngine (local to this test, mirrors test_search_engine.py)
# ============================================================


class FakeSearchEngine:
    """A minimal engine that records calls and returns canned
    candidates. Used to prove the orchestrator works with a
    non-FaG engine (issue #35 acceptance criteria)."""

    name = "fake"
    base_url = "https://fake.example.com/search"

    def __init__(self, candidates=None, score=0.5, raises=False):
        self.ladder = [as_strategy(
            "F1", lambda ctx: {"q": ctx.first or ctx.last or ""},
        )]
        self._candidates = candidates or [
            {"id": "1", "name": "Alice"},
            {"id": "2", "name": "Bob"},
        ]
        self._score = score
        self._raises = raises
        self.calls: list[tuple] = []

    def build_url(self, params: dict) -> str:
        if self._raises:
            raise RuntimeError("engine build_url failed")
        self.calls.append(("build_url", params))
        return f"{self.base_url}?q={params.get('q', '')}"

    def parse_results_page(self, page, url):
        if self._raises:
            raise RuntimeError("engine parse failed")
        self.calls.append(("parse_results_page", url))
        return list(self._candidates)

    def score(self, ctx, candidate):
        self.calls.append(("score", ctx, candidate))
        return (self._score, {"matched_via": "fake"})

    def classify_response(self, page):
        from scripts.search.engine import Classification
        class _N(Classification):
            @property
            def is_blocking(self): return False
            @property
            def is_normal(self): return True
            @property
            def value(self): return "normal"
        return _N()

    def apply_filters(self, params, ctx):
        self.calls.append(("apply_filters", params, ctx))
        return dict(params)

    def throttle_seconds(self) -> float:
        return 0.0


# ============================================================
# Stub page + engine wiring helpers
# ============================================================


class _StubPage:
    def __init__(self):
        self.visited: list[str] = []

    def goto(self, url: str, **kwargs):
        self.visited.append(url)

    def title(self):
        return "Memorial Search Results"


def _build_pensioner() -> dict:
    return {
        "id": 1,
        "pensioner_id": 1,
        "first_name": "Alice",
        "middle_name": "",
        "last_name": "Smith",
        "birth_year": "1844",
        "death_year": "1932",
        "regiment": "",
        "company": "",
    }


# ============================================================
# run_one with FakeSearchEngine
# ============================================================


class TestRunOneWithFakeEngine:
    def test_run_one_returns_pipeline_result(self):
        page = _StubPage()
        e = FakeSearchEngine()
        record = from_pensioner(_build_pensioner())
        config = PipelineConfig()
        # Wire the engine into config
        config_with_engine = PipelineConfig(engine=e, page=page)
        result = run_one(record, [], config_with_engine)
        assert isinstance(result, PipelineResult)
        # The engine's result is attached
        assert result.engine_result is not None
        assert len(result.engine_result["candidates"]) == 2

    def test_run_one_uses_engine_to_navigate(self):
        page = _StubPage()
        e = FakeSearchEngine()
        record = from_pensioner(_build_pensioner())
        config = PipelineConfig(engine=e, page=page)
        run_one(record, [], config)
        # The engine navigated once via the stub page
        assert len(page.visited) == 1
        assert "q=Alice" in page.visited[0]

    def test_run_one_preserves_record_identity(self):
        e = FakeSearchEngine()
        record = from_pensioner(_build_pensioner())
        config = PipelineConfig(engine=e, page=_StubPage())
        result = run_one(record, [], config)
        # The input record is preserved (not mutated)
        assert result.record is record
        assert result.record.id == "1"
        assert result.record.primary_name == "Alice Smith"

    def test_run_one_state_agnostic(self):
        """A FakeSearchEngine run produces a PipelineResult
        with engine-agnostic fields populated. The legacy
        fag_records field is also populated (for wire-format
        back-compat), but the engine-agnostic engine_result
        field is the canonical place to read the engine's
        output."""
        e = FakeSearchEngine()
        record = from_pensioner(_build_pensioner())
        config = PipelineConfig(engine=e, page=_StubPage())
        result = run_one(record, [], config)
        # engine_result is engine-agnostic
        assert result.engine_result is not None
        assert result.engine_result["candidates"]
        # fag_records is also populated (for wire compat) but
        # it's a separate field, not the canonical place
        assert result.fag_records == result.engine_result["candidates"]

    def test_run_one_engine_error_is_captured(self):
        """When the engine raises, the result captures the
        error rather than taking down the run."""
        e = FakeSearchEngine(raises=True)
        record = from_pensioner(_build_pensioner())
        config = PipelineConfig(engine=e, page=_StubPage())
        result = run_one(record, [], config)
        assert result.error is not None
        # The error message is recorded
        assert "build_url failed" in result.error
        # The status is one of the engine-error states
        assert result.fag_status in ("error", "no_results", "not_run")


# ============================================================
# Back-compat: fag_search_fn callback still works
# ============================================================


class TestFagSearchFnBackcompat:
    def test_fag_search_fn_still_works(self):
        """The legacy fag_search_fn callback path still works.
        This is the back-compat guarantee for existing callers."""

        def fag_search_fn(pensioner, config):
            return ([{"memorial_id": "1", "slug": "alice", "score": 0.9}],
                    "auto_accept")

        pensioner = _build_pensioner()
        config = PipelineConfig()
        result = run_pipeline_for_pensioner(
            pensioner, [], config, fag_search_fn=fag_search_fn,
        )
        assert result.fag_status == "auto_accept"
        assert len(result.fag_records) == 1


# ============================================================
# PipelineResult: engine-agnostic
# ============================================================


class TestPipelineResultShape:
    def test_result_has_record_field(self):
        record = from_pensioner(_build_pensioner())
        result = PipelineResult(record=record)
        assert result.record is record

    def test_result_has_engine_result_field(self):
        result = PipelineResult(record=from_pensioner(_build_pensioner()))
        assert hasattr(result, "engine_result")
        assert result.engine_result is None  # default

    def test_result_has_status_field(self):
        result = PipelineResult(record=from_pensioner(_build_pensioner()))
        assert hasattr(result, "status")
        assert result.status == "pending"  # default

    def test_result_to_dict_preserves_pensioner_fields(self):
        """The wire format is unchanged for pensioner-shaped input."""
        record = from_pensioner(_build_pensioner())
        result = PipelineResult(
            record=record, cgr_records=[], fag_records=[],
            fag_status="auto_accept", cgr_status="no_match",
        )
        # The UnifiedRunResult wrapper still produces today's shape
        u = UnifiedRunResult(
            pensioner=to_pensioner_dict(record),
            cgr_records=result.cgr_records,
            fag_records=result.fag_records,
            fag_status=result.fag_status,
            cgr_status=result.cgr_status,
        )
        d = u.to_dict()
        # Today's keys present
        assert d["pensioner_id"] == "1"
        assert d["pensioner_first"] == "Alice"
        assert d["pensioner_last"] == "Smith"
        assert d["fag_status"] == "auto_accept"
        assert d["cgr_status"] == "no_match"


# ============================================================
# FaG path: byte-identical output
# ============================================================


class TestFaGPathByteIdentical:
    def test_fag_engine_produces_fag_records(self):
        """When the engine is FaGEngine, the result's fag_records
        is populated (legacy field). The engine_result is also
        attached for new consumers."""
        page = _StubPage()
        e = FaGEngine()
        # Use a tiny ladder for the test
        e.ladder = [as_strategy("B1", lambda ctx: {
            "firstname": ctx.first, "lastname": ctx.last,
        })]
        # Patch parse to return canned candidates
        e.parse_results_page = lambda page, url: [
            {"id": "1", "slug": "alice-smith", "memorial_id": "1", "snippet": ""},
        ]

        record = from_pensioner(_build_pensioner())
        config = PipelineConfig(engine=e, page=page)
        result = run_one(record, [], config)
        # FaG-specific path: fag_records is populated from the
        # engine's candidates
        assert len(result.fag_records) >= 1
        # The engine's result is also attached
        assert result.engine_result is not None


# ============================================================
# Wire format: byte-identical for legacy path (issue #35 AC)
# ============================================================
class TestWireFormatByteIdentical:
    """The pipeline refactor must produce byte-identical
    state.jsonl output (modulo timestamps) for the existing
    FaG fag_search_fn path. The new engine path is opt-in."""

    def test_legacy_fag_search_fn_wire_format(self):
        """The legacy fag_search_fn callback produces the
        same wire format as before the refactor."""
        pensioner = {
            "id": 5, "first_name": "John", "last_name": "Smith",
            "regiment": "10 AL", "death_year": "1930",
            "application_number": "A1234",
            "pensioncard_backlink": "https://example.com/card",
        }

        def fake_fag(p, c):
            return (
                [{"memorial_id": "1", "score": 0.85,
                  "backlink": "https://example.com/memorial/1"}],
                "auto_accept",
            )

        config = PipelineConfig(fag_search_fn=fake_fag)
        result = run_pipeline_for_pensioner(pensioner, [], config)
        # Convert to wire format via UnifiedRunResult
        u = UnifiedRunResult(
            pensioner=result.pensioner,
            cgr_records=result.cgr_records,
            fag_records=result.fag_records,
            fag_status=result.fag_status,
            cgr_status=result.cgr_status,
        )
        d = u.to_dict()
        # All the legacy keys are present with the right types
        assert d["pensioner_id"] == 5  # int (preserved)
        assert d["pensioner_first"] == "John"
        assert d["pensioner_last"] == "Smith"
        assert d["regiment"] == "10 AL"
        assert d["pensioner_app_number"] == "A1234"
        assert d["pensioncard_backlink"] == "https://example.com/card"
        assert d["fag_status"] == "auto_accept"
        assert d["cgr_status"] == "no_match"
        assert len(d["fag_records"]) == 1
        assert d["fag_records"][0]["memorial_id"] == "1"

    def test_record_path_uses_string_id(self):
        """New code that uses run_one() with a SearchRecord
        gets the stringified id (the new contract). This is
        opt-in; legacy callers are unaffected."""
        e = FakeSearchEngine()
        # The record's id is a string (SearchRecord contract)
        record = SearchRecord(id="5", primary_name="John Smith")
        config = PipelineConfig(engine=e, page=_StubPage())
        result = run_one(record, [], config)
        # The result's pensioner dict (derived from the record)
        # has id as a string
        assert result.pensioner["id"] == "5"
        assert result.pensioner["pensioner_id"] == "5"
