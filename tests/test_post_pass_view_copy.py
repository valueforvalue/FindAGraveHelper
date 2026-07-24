"""Tests for scripts/post_pass/view_copy.py — Slice 3.

Pin the post-pass extraction: the moved function must copy
view.html into the output directory iff it doesn't already exist,
and embed any present sidecar JSONs into the page, identically
to the old in-line `copy_view_html_if_missing`.

Slice 3 acceptance criterion (from
docs/designs/post-pass-extraction.md §Slice 3 + Q3):
    "After Slice 3, the runner's view.html copy is invoked via
    `scripts/post_pass/view_copy.run(...)` and returns a
    PostPassStats. The legacy `copy_view_html_if_missing` symbol
    stays importable from `scripts.pipeline.run_unified` for
    back-compat (re-exported)."
"""

from __future__ import annotations

from pathlib import Path

from scripts.post_pass.view_copy import (
    ViewCopyConfig,
    copy_view_html_if_missing,
    run,
)


class _NullLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


def test_run_copies_when_missing(tmp_path: Path):
    """First run copies view.html; dest did not exist."""
    src = tmp_path / "src.html"
    src.write_text("<html>v1</html>", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    config = ViewCopyConfig(source=src, dest_dir=out_dir)

    stats = run(config=config, log=_NullLogger())

    assert stats.name == "view_copy"
    assert stats.skipped is False
    assert stats.matched == 1
    assert (out_dir / "view.html").read_text(encoding="utf-8") == "<html>v1</html>"


def test_run_skips_when_dest_exists(tmp_path: Path):
    """Second run is a no-op (dest already there)."""
    src = tmp_path / "src.html"
    src.write_text("<html>v1</html>", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "view.html").write_text("<html>existing</html>", encoding="utf-8")
    config = ViewCopyConfig(source=src, dest_dir=out_dir)

    stats = run(config=config, log=_NullLogger())

    assert stats.skipped is True
    assert stats.matched == 0
    # Existing file is NOT overwritten
    assert (out_dir / "view.html").read_text(encoding="utf-8") == "<html>existing</html>"


def test_run_skipped_when_source_missing(tmp_path: Path):
    """No source → skip; never raises."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    config = ViewCopyConfig(source=tmp_path / "nonexistent.html", dest_dir=out_dir)

    stats = run(config=config, log=_NullLogger())

    assert stats.skipped is True
    assert not (out_dir / "view.html").exists()


def test_run_skipped_when_source_none(tmp_path: Path):
    """source=None → skip."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    config = ViewCopyConfig(source=None, dest_dir=out_dir)

    stats = run(config=config, log=_NullLogger())

    assert stats.skipped is True


def test_run_embeds_results_jsonl(tmp_path: Path):
    """Placeholder gets replaced with embedded JSONL script block."""
    src = tmp_path / "src.html"
    src.write_text(
        "<html><body><main></main>\n"
        "<!--EMBEDDED_RESULTS_JSONL-->\n"
        "</body></html>",
        encoding="utf-8",
    )
    results = tmp_path / "results.jsonl"
    results.write_text('{"pensioner_id": 1}\n', encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    config = ViewCopyConfig(
        source=src,
        dest_dir=out_dir,
        results_path=results,
    )

    run(config=config, log=_NullLogger())

    html = (out_dir / "view.html").read_text(encoding="utf-8")
    assert 'id="embedded-results-jsonl"' in html
    assert '{"pensioner_id": 1}' in html
    assert "<!--EMBEDDED_RESULTS_JSONL-->" not in html


def test_copy_view_html_if_missing_backcompat(tmp_path: Path):
    """The legacy helper stays importable from view_copy + run_unified."""
    src = tmp_path / "src.html"
    src.write_text("<html>v1</html>", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    # Direct call to the moved function (back-compat path).
    assert copy_view_html_if_missing(src, out_dir) is True
    assert (out_dir / "view.html").exists()

    # Also importable from the old location.
    from scripts.pipeline import run_unified

    assert hasattr(run_unified, "copy_view_html_if_missing")
    assert hasattr(run_unified, "EMBEDDED_DATA_PLACEHOLDER")
    assert run_unified.EMBEDDED_DATA_PLACEHOLDER == "<!--EMBEDDED_RESULTS_JSONL-->"