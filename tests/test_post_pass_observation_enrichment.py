"""Tests for scripts/post_pass/observation_enrichment.py — Slice 1.

Pin the post-pass extraction: the moved function must enrich
state.jsonl rows with CGR/DD/Spouse evidence from the Blackboard
store, identically to the old in-line `_enrich_state_rows_with_observations`.

Slice 1 acceptance criterion (from
docs/designs/post-pass-extraction.md §Slice 1):
    "running the runner produces a state.jsonl whose rows are
    enriched with CGR/DD/spouse observations identically to
    before the slice, AND post-pass observation IDs are
    deterministic across runs."
"""

from __future__ import annotations

import pytest

from scripts.blackboard.schema import (
    Kind,
    Observation,
)
from scripts.blackboard.store import SqliteBlackboardStore
from scripts.post_pass.observation_enrichment import (
    ObservationEnrichmentConfig,
    run,
)
from scripts.state.repository import InMemoryStateRepository


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def sqlite_store(tmp_path):
    """Open a SQLite store in a temp directory."""
    store = SqliteBlackboardStore(tmp_path / "blackboard.db")
    store.open()
    yield store
    store.close()


def _row(pid: int, **extra) -> dict:
    """Build a minimal state row for testing."""
    return {
        "pensioner_id": pid,
        "name_raw": f"Test Pensioner {pid}",
        "best_score": 0.0,
        "status": "unknown",
        **extra,
    }


# ============================================================
# Acceptance tests
# ============================================================


def test_run_enriches_cgr_match(sqlite_store):
    """A CGRCorroboration observation for pid=1 enriches row 1."""
    state_repo = InMemoryStateRepository([_row(1), _row(2)])
    sqlite_store.append_observation(
        Observation(
            observation_id="obs-cgr-1",
            pensioner_id=1,
            kind=Kind.CGRCorroboration,
            source="cgr_fag_dedup",
            source_version="1",
            run_id="r1",
            pass_id="post",
            payload={"match_found": True, "match_details": {"name": "X"}},
        )
    )

    stats = run(
        state_repo,
        sqlite_store,
        config=ObservationEnrichmentConfig(),
        run_id="r1",
        log=_NullLogger(),
    )

    row_1 = state_repo.get(1)
    assert row_1 is not None
    assert "cgr_match" in row_1
    assert row_1["cgr_match"]["match_found"] is True
    row_2 = state_repo.get(2)
    assert "cgr_match" not in row_2
    assert stats.matched == 1


def test_run_enriches_dd_and_spouse(sqlite_store):
    """DD and Spouse observations enrich their respective rows."""
    state_repo = InMemoryStateRepository([_row(10)])
    sqlite_store.append_observation(
        Observation(
            observation_id="obs-dd-10",
            pensioner_id=10,
            kind=Kind.DixieDataMatch,
            source="dixiedata_match",
            source_version="1",
            run_id="r1",
            pass_id="post",
            payload={"match_found": True, "match_details": {"slug": "y"}},
        )
    )
    sqlite_store.append_observation(
        Observation(
            observation_id="obs-spouse-10",
            pensioner_id=10,
            kind=Kind.SpouseMatch,
            source="spouse_compare",
            source_version="1",
            run_id="r1",
            pass_id="post",
            payload={"match_confirmed": True, "match_details": {}},
        )
    )

    stats = run(
        state_repo,
        sqlite_store,
        config=ObservationEnrichmentConfig(),
        run_id="r1",
        log=_NullLogger(),
    )

    row = state_repo.get(10)
    assert "dd_match" in row
    assert "spouse_match" in row
    assert stats.matched == 1


def test_run_is_idempotent(sqlite_store):
    """Re-running on already-enriched rows does not double-write or fail.

    First run matches 1 row. Second run sees `cgr_match` already present
    and matches 0 NEW rows, but must not raise and must not overwrite
    the existing evidence.
    """
    state_repo = InMemoryStateRepository([_row(1)])
    sqlite_store.append_observation(
        Observation(
            observation_id="obs-cgr-1",
            pensioner_id=1,
            kind=Kind.CGRCorroboration,
            source="cgr_fag_dedup",
            source_version="1",
            run_id="r1",
            pass_id="post",
            payload={"match_found": True, "match_details": {"name": "X"}},
        )
    )
    config = ObservationEnrichmentConfig()
    log = _NullLogger()
    first = run(state_repo, sqlite_store, config=config, run_id="r1", log=log)
    assert first.matched == 1
    first_evidence = state_repo.get(1)["cgr_match"]
    # Second run must not raise; cgr_match already present, no new matches.
    second = run(state_repo, sqlite_store, config=config, run_id="r1", log=log)
    assert second.matched == 0
    assert state_repo.get(1)["cgr_match"] == first_evidence


def test_run_noop_when_no_observations(sqlite_store):
    """Empty store + populated repo returns skipped=True, no writes."""
    state_repo = InMemoryStateRepository([_row(1)])
    stats = run(
        state_repo,
        sqlite_store,
        config=ObservationEnrichmentConfig(),
        run_id="r1",
        log=_NullLogger(),
    )
    assert stats.skipped is True
    assert stats.matched == 0
    assert "cgr_match" not in state_repo.get(1)


def test_run_skips_pensioner_id_zero(sqlite_store):
    """Observations with pensioner_id=0 are ignored (per existing behavior)."""
    state_repo = InMemoryStateRepository([_row(1)])
    sqlite_store.append_observation(
        Observation(
            observation_id="obs-cgr-0",
            pensioner_id=0,
            kind=Kind.CGRCorroboration,
            source="cgr_fag_dedup",
            source_version="1",
            run_id="r1",
            pass_id="post",
            payload={"match_found": True, "match_details": {}},
        )
    )
    stats = run(
        state_repo,
        sqlite_store,
        config=ObservationEnrichmentConfig(),
        run_id="r1",
        log=_NullLogger(),
    )
    assert stats.skipped is True


def test_run_returns_post_pass_stats(sqlite_store):
    """Stats object carries name + counts."""
    state_repo = InMemoryStateRepository([_row(1)])
    sqlite_store.append_observation(
        Observation(
            observation_id="obs-cgr-1",
            pensioner_id=1,
            kind=Kind.CGRCorroboration,
            source="cgr_fag_dedup",
            source_version="1",
            run_id="r1",
            pass_id="post",
            payload={"match_found": True, "match_details": {}},
        )
    )
    stats = run(
        state_repo,
        sqlite_store,
        config=ObservationEnrichmentConfig(),
        run_id="r1",
        log=_NullLogger(),
    )
    assert stats.name == "observation_enrichment"
    assert stats.errors == 0


# ============================================================
# Helpers
# ============================================================


class _NullLogger:
    """Stand-in logger that accepts any method call."""

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass