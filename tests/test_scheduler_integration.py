"""Integration smoke tests for scheduler wiring — Phase W4."""

import json
import uuid
from pathlib import Path

from scripts.blackboard.schema import (
    Kind,
    Observation,
    WorkItem,
)
from scripts.blackboard.store import SqliteBlackboardStore
from scripts.pipeline.run_unified import (
    BatchResult,
    UnifiedRunnerConfig,
    run_batch_scheduler,
)

import pytest


def _pensioner(pid: int, first="John", last="Smith") -> dict:
    return {
        "id": pid,
        "first_name": first,
        "last_name": last,
        "regiment": "5th Alabama",
        "birth_year": "1840",
    }


def _cemetery() -> dict:
    return {
        "id": 1,
        "name": "Test Cemetery",
        "county": "Adair",
        "veterans": [
            {"id": 1, "first_name": "John", "last_name": "Smith",
             "born": "1840", "unit": "5 AL Inf", "state": "AL"},
        ],
    }


def _make_config(tmp_path, store) -> UnifiedRunnerConfig:
    """Build a minimal UnifiedRunnerConfig for scheduler testing."""
    import uuid as _uuid
    from scripts.blackboard.schema import RunManifest

    cfg = UnifiedRunnerConfig(
        out_dir=tmp_path / "out",
        results_filename="results.jsonl",
        blackboard_db_path=tmp_path / "bb.db",
        enable_fag=False,
        run_manifest=RunManifest(
            manifest_id=f"test-{_uuid.uuid4().hex[:8]}",
            run_id="test-run",
        ),
    )
    cfg._blackboard_store = store  # type: ignore[attr-defined]
    return cfg


def test_scheduler_path_runs_pensioners(tmp_path):
    """run_batch_scheduler ingests pensioners, runs scheduler, projects output."""
    db_path = tmp_path / "bb.db"
    store = SqliteBlackboardStore(db_path)
    store.open()

    cfg = _make_config(tmp_path, store)
    pensioners = [_pensioner(1), _pensioner(2), _pensioner(3)]
    cems = [_cemetery()]

    result = run_batch_scheduler(pensioners, cems, cfg)

    assert isinstance(result, BatchResult)
    assert result.processed > 0

    # Verify state.jsonl was written
    state_path = tmp_path / "out" / "results.jsonl"
    assert state_path.exists()

    rows = [
        json.loads(line)
        for line in state_path.read_text(encoding="utf-8").strip().split("\n")
        if line.strip()
    ]
    assert len(rows) == 3
    assert rows[0]["pensioner_id"] == 1
    assert rows[1]["pensioner_id"] == 2
    assert rows[2]["pensioner_id"] == 3

    store.close()


def test_scheduler_observations_persisted(tmp_path):
    """Observations written during scheduler run are readable afterward."""
    db_path = tmp_path / "bb.db"
    store = SqliteBlackboardStore(db_path)
    store.open()

    cfg = _make_config(tmp_path, store)
    result = run_batch_scheduler([_pensioner(1)], [_cemetery()], cfg)

    obs = store.read_observations_since(None)
    # Should have pensioner import + CGR vet + planner work output
    assert len(obs) >= 2  # at least pensioner import + CGR vet

    imports = [o for o in obs if o.kind == Kind.PensionerImported]
    assert len(imports) == 1
    assert imports[0].pensioner_id == 1

    store.close()


def test_scheduler_empty_input_produces_empty_projection(tmp_path):
    """Zero pensioners → zero output rows, no crash."""
    db_path = tmp_path / "bb.db"
    store = SqliteBlackboardStore(db_path)
    store.open()

    cfg = _make_config(tmp_path, store)
    result = run_batch_scheduler([], [], cfg)

    state_path = tmp_path / "out" / "results.jsonl"
    assert state_path.exists()
    rows = state_path.read_text(encoding="utf-8").strip()
    assert rows == ""

    store.close()


def test_scheduler_projection_flushes_and_fsyncs_each_row(tmp_path, monkeypatch):
    """Atomic projection fsyncs every row before replacing state (L3)."""
    import os

    store = SqliteBlackboardStore(tmp_path / "bb.db")
    store.open()
    cfg = _make_config(tmp_path, store)
    fsync_calls: list[int] = []
    monkeypatch.setattr(os, "fsync", lambda fd: fsync_calls.append(fd))

    run_batch_scheduler([_pensioner(1), _pensioner(2)], [], cfg)

    assert len(fsync_calls) == 2
    store.close()


def test_scheduler_resume_reuses_durable_work(tmp_path):
    """Re-running same store does not enqueue duplicate plans or work."""
    store = SqliteBlackboardStore(tmp_path / "bb.db")
    store.open()
    cfg = _make_config(tmp_path, store)
    pensioners = [_pensioner(1)]

    run_batch_scheduler(pensioners, [], cfg)
    first_counts = {
        "plans": store.con.execute("SELECT COUNT(*) FROM query_plans").fetchone()[0],
        "work": store.con.execute("SELECT COUNT(*) FROM work_items").fetchone()[0],
        "observations": store.con.execute(
            "SELECT COUNT(*) FROM observations"
        ).fetchone()[0],
    }
    run_batch_scheduler(pensioners, [], cfg)
    second_counts = {
        "plans": store.con.execute("SELECT COUNT(*) FROM query_plans").fetchone()[0],
        "work": store.con.execute("SELECT COUNT(*) FROM work_items").fetchone()[0],
        "observations": store.con.execute(
            "SELECT COUNT(*) FROM observations"
        ).fetchone()[0],
    }

    assert second_counts == first_counts
    store.close()


def test_scheduler_does_not_checkpoint_deferred_work(tmp_path, monkeypatch):
    """Retryable work leaves pensioner absent from durable state."""
    store = SqliteBlackboardStore(tmp_path / "bb.db")
    store.open()
    cfg = _make_config(tmp_path, store)

    def fail_planner(*args, **kwargs):
        raise RuntimeError("transient")

    monkeypatch.setattr(
        "scripts.knowledge.regional_planner.RegionalPlannerKS.invoke",
        fail_planner,
    )

    run_batch_scheduler([_pensioner(1)], [], cfg)

    assert (tmp_path / "out" / "results.jsonl").read_text() == ""
    assert store.has_pending_work(1) is True
    store.close()


def test_scheduler_limit_bounds_ingestion_and_projection(tmp_path):
    """Scheduler --limit applies before work is enqueued."""
    store = SqliteBlackboardStore(tmp_path / "bb.db")
    store.open()
    cfg = _make_config(tmp_path, store)
    cfg.limit = 2

    result = run_batch_scheduler(
        [_pensioner(1), _pensioner(2), _pensioner(3)], [], cfg
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "out" / "results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert result.total == 3
    assert [row["pensioner_id"] for row in rows] == [1, 2]
    store.close()


def test_scheduler_browser_mode_starts_and_closes_session(tmp_path, monkeypatch):
    """Default scheduler path registers real FaG provider boundary.

    Issue #61: the Blackboard scheduler now routes FaGScraperKS
    through `engine.default_search_one`, not `session.search`.
    This test mocks the engine's default_search_one so the
    browser boundary can still be asserted end-to-end.
    """
    from scripts.fag import browser_session as browser_session_module
    from scripts.fag.request_gate import RequestGate

    store = SqliteBlackboardStore(tmp_path / "bb.db")
    store.open()
    cfg = _make_config(tmp_path, store)
    cfg.enable_fag = True
    calls: list[str] = []

    class FakeBrowserSession:
        def __init__(self, **kwargs):
            calls.append(f"init:{kwargs['state_filter']}")
            self.state_filter = kwargs.get("state_filter", "OK")
            self.auto_relax = kwargs.get("auto_relax", False)

        def start(self):
            calls.append("start")

        def close(self):
            calls.append("close")

        @property
        def page(self):
            return object()

        def _try_auto_relax_engine(self, engine, page, ctx, ok_result, throttle_fn=None):
            return ok_result

    monkeypatch.setattr(browser_session_module, "BrowserSession", FakeBrowserSession)
    monkeypatch.setattr(
        RequestGate,
        "default_fag",
        classmethod(
            lambda cls, provider="findagrave.com": cls(
                provider=provider, min_interval=0.0
            )
        ),
    )

    # Stub the engine flow so the test doesn't touch the real ladder.
    def fake_default_search_one(engine, page, ctx, *, strategy_name=None, throttle_fn=None):
        calls.append(f"engine_search:{ctx.state}")
        return {
            "candidates": [
                {"id": "1", "slug": "x", "name": "X", "score": 0.5, "evidence": {}}
            ],
            "strategies_run": ["B1-exact"],
            "status": "ambiguous",
            "classification": "normal",
            "error": None,
        }

    import scripts.knowledge.fag_scraper as fag_scraper_module
    monkeypatch.setattr(
        fag_scraper_module, "default_search_one", fake_default_search_one
    )

    run_batch_scheduler([_pensioner(1)], [], cfg)

    assert calls[0:2] == ["init:OK", "start"]
    assert len([call for call in calls if call.startswith("engine_search:")]) >= 2
    assert calls[-1] == "close"
    decision_rows = store.con.execute(
        "SELECT COUNT(*) FROM observations WHERE kind = 'DecisionObserved'"
    ).fetchone()[0]
    assert decision_rows == 0
    score_rows = store.con.execute(
        "SELECT COUNT(*) FROM observations WHERE kind = 'ScoreObserved'"
    ).fetchone()[0]
    refinement_rows = store.con.execute(
        "SELECT COUNT(*) FROM observations WHERE source = 'DeepRefinerKS'"
    ).fetchone()[0]
    assert score_rows >= 2
    assert refinement_rows >= 1
    store.close()


def test_scheduler_no_fag_mode_does_not_start_browser(tmp_path, monkeypatch):
    """Explicit no-FaG mode skips BrowserSession while preserving projection."""
    from scripts.fag import browser_session as browser_session_module

    store = SqliteBlackboardStore(tmp_path / "bb.db")
    store.open()
    cfg = _make_config(tmp_path, store)
    cfg.enable_fag = False

    class ForbiddenBrowserSession:
        def __init__(self, **kwargs):
            raise AssertionError("BrowserSession started during no-FaG run")

    monkeypatch.setattr(
        browser_session_module, "BrowserSession", ForbiddenBrowserSession
    )

    result = run_batch_scheduler([_pensioner(1)], [], cfg)

    assert result.processed > 0
    assert (tmp_path / "out" / "results.jsonl").exists()
    orphan_work = store.con.execute(
        "SELECT COUNT(*) FROM work_items WHERE state = 'ready'"
    ).fetchone()[0]
    assert orphan_work == 0
    store.close()


def test_scheduler_copies_view_html_into_out_dir(tmp_path):
    """Scheduler path must auto-ship a per-run view.html.

    Regression test for the gap where `run_batch_scheduler`
    shipped without a view file in `out_dir`, leaving the
    reviewer with no per-run page. The legacy `run_batch()`
    path already calls `copy_view_html_if_missing`; the
    scheduler path was missing the call. The fix defaults
    `view_html_source` to `scripts/view/v2.html` and calls
    the same copy helper.
    """
    from scripts.pipeline.run_unified import copy_view_html_if_missing
    from scripts.blackboard.schema import RunManifest
    import uuid as _uuid

    store = SqliteBlackboardStore(tmp_path / "bb.db")
    store.open()

    # Explicit source: a tiny HTML file we drop in tmp_path so
    # the test doesn't depend on scripts/view/v2.html existing.
    fake_source = tmp_path / "fake_v2.html"
    fake_source.write_text(
        "<!doctype html><html><body>fake v2</body></html>",
        encoding="utf-8",
    )

    cfg = UnifiedRunnerConfig(
        out_dir=tmp_path / "out",
        results_filename="results.jsonl",
        blackboard_db_path=tmp_path / "bb.db",
        enable_fag=False,
        view_html_source=fake_source,
        run_manifest=RunManifest(
            manifest_id=f"test-{_uuid.uuid4().hex[:8]}",
            run_id="test-run",
        ),
    )
    cfg._blackboard_store = store

    run_batch_scheduler([_pensioner(1)], [_cemetery()], cfg)

    copied = tmp_path / "out" / "view.html"
    assert copied.exists(), "scheduler did not copy view.html"
    assert "fake v2" in copied.read_text(encoding="utf-8")

    # And: a second invocation is idempotent (no overwrite when
    # the per-run copy already exists).
    fake_source.write_text(
        "<!doctype html><html><body>OVERWRITE</body></html>",
        encoding="utf-8",
    )
    run_batch_scheduler([_pensioner(1)], [_cemetery()], cfg)
    assert "OVERWRITE" not in copied.read_text(encoding="utf-8"), (
        "scheduler must not overwrite an existing per-run view.html"
    )

    store.close()


def test_scheduler_default_view_html_source_is_v2(tmp_path):
    """When `view_html_source` is None, scheduler defaults to v2.

    Pinned by docs/agents/cross-layer-contract.md
    ('scripts/view/v2.html, default since 2026-07-19'). The
    fallback exists in `run_batch_scheduler` itself so any
    caller benefits, not just the CLI.
    """
    from scripts.blackboard.schema import RunManifest
    import uuid as _uuid

    store = SqliteBlackboardStore(tmp_path / "bb.db")
    store.open()

    cfg = UnifiedRunnerConfig(
        out_dir=tmp_path / "out",
        results_filename="results.jsonl",
        blackboard_db_path=tmp_path / "bb.db",
        enable_fag=False,
        view_html_source=None,  # explicit None
        run_manifest=RunManifest(
            manifest_id=f"test-{_uuid.uuid4().hex[:8]}",
            run_id="test-run",
        ),
    )
    cfg._blackboard_store = store

    # Scripts/view/v2.html exists in this repo (since 2026-07-19);
    # the scheduler default must point at it. If the file is
    # missing this test should be skipped, not silently pass.
    repo_v2 = Path(__file__).parent.parent / "scripts" / "view" / "v2.html"
    if not repo_v2.exists():
        pytest.skip(f"canonical v2.html not present at {repo_v2}")

    run_batch_scheduler([_pensioner(1)], [_cemetery()], cfg)

    copied = tmp_path / "out" / "view.html"
    assert copied.exists(), "scheduler did not copy default v2.html"
    # v2.html is large; just verify it loaded the canonical file
    assert copied.stat().st_size > 1000, "v2.html copy looks empty"
    store.close()
