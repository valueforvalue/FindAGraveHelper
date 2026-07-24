"""Tests for scripts/post_pass/spouse.py — Slice 5.

Pin the post-pass extraction: the spouse post-pass must invoke
`annotate_records_via_session` and persist SpouseMatch
observations to the store, identically to the inline behavior
in run_unified.py.

Slice 5 acceptance criterion (from
docs/designs/post-pass-extraction.md §Slice 5):
    "After Slice 5 lands, running the runner with
    FAG_SCRAPE_SPOUSE=1 produces SpouseMatch observations in
    the store identical to before the slice."
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.blackboard.schema import Kind
from scripts.blackboard.store import SqliteBlackboardStore
from scripts.post_pass.spouse import SpouseConfig, run


class _NullLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


@pytest.fixture
def sqlite_store(tmp_path):
    store = SqliteBlackboardStore(tmp_path / "bb.db")
    store.open()
    yield store
    store.close()


def test_run_skipped_when_disabled(sqlite_store):
    """No opt-in → skipped=True, no observations."""
    config = SpouseConfig(enabled=False, browser_session=None, results_path=None)
    stats = run(
        sqlite_store,
        config=config,
        run_id="r1",
        log=_NullLogger(),
    )
    assert stats.skipped is True
    assert stats.matched == 0
    assert sqlite_store.read_observations_since(None) == []


def test_run_returns_stats_when_enabled(sqlite_store, tmp_path):
    """Enabled + browser → stats returned, observations appended."""
    results_path = tmp_path / "results.jsonl"
    config = SpouseConfig(
        enabled=True,
        browser_session="fake-session",
        results_path=results_path,
    )

    fake_stats = {
        "matched": 2,
        "total_attempted": 5,
        "errors": 1,
    }

    def _fake_annotate(results_path, session=None, top_n=1, store=None):
        # Append a synthetic observation as if the real pass did
        from scripts.blackboard.schema import Observation

        store.append_observation(
            Observation(
                observation_id="obs-spouse-test",
                pensioner_id=1,
                kind=Kind.SpouseMatch,
                source="spouse_compare",
                source_version="1",
                run_id="r1",
                pass_id="post",
                payload={"match_confirmed": True},
            )
        )
        return fake_stats

    with patch(
        "scripts.cgr.spouse_compare.annotate_records_via_session",
        side_effect=_fake_annotate,
    ):
        stats = run(
            sqlite_store,
            config=config,
            run_id="r1",
            log=_NullLogger(),
        )

    assert stats.name == "spouse"
    assert stats.matched == 2
    assert stats.attempted == 5
    assert stats.errors == 1
    obs = sqlite_store.read_observations_since(None)
    assert len(obs) == 1
    assert obs[0].kind == Kind.SpouseMatch


def test_run_handles_exception_non_fatal(sqlite_store):
    """Exception inside annotate_records_via_session is logged + counted."""
    config = SpouseConfig(
        enabled=True,
        browser_session="fake-session",
        results_path=None,
    )

    with patch(
        "scripts.cgr.spouse_compare.annotate_records_via_session",
        side_effect=RuntimeError("browser crashed"),
    ):
        stats = run(
            sqlite_store,
            config=config,
            run_id="r1",
            log=_NullLogger(),
        )

    assert stats.errors == 1
    assert stats.skipped is True


def test_run_returns_post_pass_stats_shape(sqlite_store):
    """Stats object carries name + counts even when skipped."""
    config = SpouseConfig(enabled=False, browser_session=None, results_path=None)
    stats = run(
        sqlite_store,
        config=config,
        run_id="r1",
        log=_NullLogger(),
    )
    assert stats.name == "spouse"
    assert stats.errors == 0