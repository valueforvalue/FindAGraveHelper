"""Tests for the POST_PASSES registry — Slice 7.

Pin the registry shape: the list contains every moved post-pass;
`run_post_passes()` runs them in order, threading the run context
through each factory.
"""

from __future__ import annotations

from pathlib import Path

from scripts.post_pass import POST_PASSES, PostPassStats, run_post_passes


class _NullLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


def test_registry_contains_all_moved_passes():
    """Every Slice 1-6 pass is registered."""
    names = {entry[0] for entry in POST_PASSES}
    assert names == {
        "dd",
        "spouse",
        "observation_enrichment",
        "pensioncard_pages",
        "view_copy",
        "labels",
        "state_schema",
    }


def test_registry_preserves_order():
    """Order: dd → spouse → observation_enrichment → pensioncard_pages → view_copy → labels → state_schema."""
    names = [entry[0] for entry in POST_PASSES]
    assert names == [
        "dd",
        "spouse",
        "observation_enrichment",
        "pensioncard_pages",
        "view_copy",
        "labels",
        "state_schema",
    ]


def test_registry_entries_are_tuples():
    """Each entry is (name, callable, factory)."""
    for entry in POST_PASSES:
        assert isinstance(entry, tuple)
        assert len(entry) == 3
        assert isinstance(entry[0], str)
        assert callable(entry[1])
        assert callable(entry[2])


def test_run_post_passes_returns_stats_in_order(monkeypatch, tmp_path):
    """Driver returns one stats per pass in execution order."""
    # Force all env-gated passes to skip cleanly.
    monkeypatch.delenv("DIXIEDATA_DB", raising=False)
    monkeypatch.delenv("DIXIEDATA_ZIP_BACKUP", raising=False)
    monkeypatch.delenv("FAG_SCRAPE_SPOUSE", raising=False)

    class _FakeRepo:
        path = tmp_path / "results.jsonl"

    class _FakeStore:
        def read_observations_since(self, cursor):
            return []

    results = run_post_passes(
        config=None,
        run_id="r1",
        log=_NullLogger(),
        out_dir=tmp_path,
        state_repo=_FakeRepo(),
        store=_FakeStore(),
        browser_session=None,
        view_html_source=None,
    )

    assert len(results) == 7
    assert [r.name for r in results] == [
        "dd",
        "spouse",
        "observation_enrichment",
        "pensioncard_pages",
        "view_copy",
        "labels",
        "state_schema",
    ]
    # All env/recipe-gated; most should report skipped=True.
    for r in results:
        assert isinstance(r, PostPassStats)


def test_run_post_passes_continues_after_pass_error(monkeypatch, tmp_path):
    """A failing pass does not abort the loop."""
    monkeypatch.delenv("DIXIEDATA_DB", raising=False)
    monkeypatch.delenv("DIXIEDATA_ZIP_BACKUP", raising=False)
    monkeypatch.delenv("FAG_SCRAPE_SPOUSE", raising=False)

    class _FakeRepo:
        path = tmp_path / "results.jsonl"

    class _FakeStore:
        def read_observations_since(self, cursor):
            return []

    # Make view_copy.run raise; the loop must continue past it.
    # The registry holds the function reference at import time;
    # patch the bound entry directly.
    import scripts.post_pass._registry as reg

    original_fn = reg.POST_PASSES[4][1]

    def _explode(*args, **kwargs):
        raise RuntimeError("simulated view_copy failure")

    reg.POST_PASSES[4] = ("view_copy", _explode, reg.POST_PASSES[4][2])

    try:
        results = run_post_passes(
            config=None,
            run_id="r1",
            log=_NullLogger(),
            out_dir=tmp_path,
            state_repo=_FakeRepo(),
            store=_FakeStore(),
            browser_session=None,
            view_html_source=None,
        )
    finally:
        reg.POST_PASSES[4] = ("view_copy", original_fn, reg.POST_PASSES[4][2])

    # 7 results returned; view_copy raised but is reported as a
    # PostPassStats with errors=1 (driver records the failure and
    # continues). Subsequent passes ran.
    assert len(results) == 7
    failed = [r for r in results if r.name == "view_copy"]
    assert len(failed) == 1
    assert failed[0].errors == 1
    assert results[-1].name == "state_schema"


def test_run_post_passes_logs_errors(monkeypatch, tmp_path):
    """Passes that report errors trigger a warning log."""
    monkeypatch.delenv("DIXIEDATA_DB", raising=False)
    monkeypatch.delenv("DIXIEDATA_ZIP_BACKUP", raising=False)
    monkeypatch.delenv("FAG_SCRAPE_SPOUSE", raising=False)

    class _FakeRepo:
        path = tmp_path / "results.jsonl"

    class _FakeStore:
        def read_observations_since(self, cursor):
            return []

    warnings: list[str] = []

    class _CaptureLogger:
        def info(self, *args, **kwargs):
            pass

        def warning(self, msg, *args, **kwargs):
            warnings.append(msg % args if args else msg)

        def error(self, *args, **kwargs):
            pass

        def debug(self, *args, **kwargs):
            pass

    # Force dd.run to return an error stat. Registry holds the
    # function reference at import time; patch the entry directly.
    import scripts.post_pass._registry as reg

    original_fn = reg.POST_PASSES[0][1]

    def _error_run(*args, **kwargs):
        return PostPassStats(
            name="dd",
            skipped=True,
            errors=1,
            notes="forced failure",
        )

    reg.POST_PASSES[0] = ("dd", _error_run, reg.POST_PASSES[0][2])

    try:
        run_post_passes(
            config=None,
            run_id="r1",
            log=_CaptureLogger(),
            out_dir=tmp_path,
            state_repo=_FakeRepo(),
            store=_FakeStore(),
            browser_session=None,
            view_html_source=None,
        )
    finally:
        reg.POST_PASSES[0] = ("dd", original_fn, reg.POST_PASSES[0][2])

    assert any("dd" in w and "1 error(s)" in w for w in warnings)