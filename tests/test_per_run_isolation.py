"""Tests for J5-S2: per-run results.jsonl + view.html copy.

Per-run isolation: each run writes to <out_dir>/<results_filename>
(defaults to results.jsonl, NOT state.jsonl) and copies
scripts/view.html into the run dir at startup (no overwrite).
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.pipeline.run_unified import (  # noqa: E402
    UnifiedRunnerConfig,
    run_batch,
    ResumeTracker,
    copy_view_html_if_missing,
)


def _sample_pensioners(n=3):
    return [
        {
            "id": i + 1,
            "first_name": "John",
            "last_name": f"Smith{i}",
            "middle_name": "",
            "regiment": "10 AL",
            "death_year": "1930",
            "application_number": f"A{i+1}",
        }
        for i in range(n)
    ]


def _sample_cems():
    return [{"cemetery_id": 1, "veterans": []}]


def _fake_fag_no_results(pensioner, cfg):
    return [], "no_results"


# ============================================================
# Per-run results filename
# ============================================================
def test_results_file_named_results_jsonl(tmp_path):
    """By default, the per-run results file is results.jsonl, not state.jsonl."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        fag_search_fn=_fake_fag_no_results,
    )
    run_batch(pensioners=_sample_pensioners(2), cemeteries=_sample_cems(),
              config=cfg)
    assert (out_dir / "results.jsonl").exists()
    # state.jsonl should NOT be created by default
    assert not (out_dir / "state.jsonl").exists()


def test_results_filename_customizable(tmp_path):
    """UnifiedRunnerConfig.results_filename controls the per-run file."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        fag_search_fn=_fake_fag_no_results,
        results_filename="batch_a.jsonl",
    )
    run_batch(pensioners=_sample_pensioners(2), cemeteries=_sample_cems(),
              config=cfg)
    assert (out_dir / "batch_a.jsonl").exists()
    assert not (out_dir / "results.jsonl").exists()


def test_results_filename_default_value():
    """UnifiedRunnerConfig.results_filename default is 'results.jsonl'."""
    cfg = UnifiedRunnerConfig()
    assert cfg.results_filename == "results.jsonl"


# ============================================================
# view.html copy
# ============================================================
def test_view_html_copied_to_run_dir(tmp_path):
    """scripts/view.html is copied into the run dir at run start."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        fag_search_fn=_fake_fag_no_results,
        view_html_source=Path("scripts/view.html"),
    )
    run_batch(pensioners=_sample_pensioners(1), cemeteries=_sample_cems(),
              config=cfg)
    assert (out_dir / "view.html").exists()


def test_view_html_copy_byte_identical(tmp_path):
    """The view.html copy preserves the source structure. The
    J9 embed step may replace the EMBEDDED_DATA_PLACEHOLDER
    with a <script> block (when results exist) or drop it
    entirely (when results don't exist yet). Either way, the
    rest of the page must be byte-identical."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    src = Path("scripts/view.html")
    if not src.exists():
        pytest.skip("scripts/view.html not present")
    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        fag_search_fn=_fake_fag_no_results,
        view_html_source=src,
    )
    run_batch(pensioners=_sample_pensioners(1), cemeteries=_sample_cems(),
              config=cfg)
    src_text = src.read_text(encoding="utf-8")
    dst_text = (out_dir / "view.html").read_text(encoding="utf-8")
    # Drop ALL known placeholder regions from BOTH for fair
    # comparison. The second-pass embed (J14 second-pass, J15-S2)
    # may replace these with script blocks; with no DD / spouse
    # sidecars present, the second pass drops them entirely.
    # Also strip any actual <script type="application/json"
    # id="embedded-..."> blocks added by the second-pass embed
    # (the source template never has those blocks).
    import re
    for placeholder in (
        "<!--EMBEDDED_RESULTS_JSONL-->",
        "<!--EMBEDDED_DD_MATCH_JSON-->",
        "<!--EMBEDDED_SPOUSE_MATCH_JSON-->",
        "<!--EMBEDDED_SPOUSE_FOLLOWUPS_JSON-->",
    ):
        src_text = src_text.replace(placeholder, "")
        dst_text = dst_text.replace(placeholder, "")
    # Strip any actual embed blocks (added by the second-pass
    # when results.jsonl exists at end-of-run). The src view.html
    # has the literal <script type="application/json" id="...">
    # inside a JS comment for documentation; we don't want to
    # confuse the regex with that. Require a `{` opening brace
    # immediately after the script tag — only real embed blocks
    # have that pattern.
    for embed_id in ("embedded-results-jsonl", "embedded-dd-match",
                     "embedded-spouse-match", "embedded-spouse-followups"):
        pat = re.compile(
            r'<script\s+type="application/json"\s+id="' + embed_id
            + r'"[^>]*>\s*\{[\s\S]*?</script>\n?',
        )
        dst_text = pat.sub("", dst_text)
    src_text_stripped = src_text
    dst_text_stripped = dst_text
    assert src_text_stripped == dst_text_stripped, (
        "view.html copy diverged from source outside the "
        "J9 embedded-data placeholder; copy_view_html_if_missing "
        "should only mutate the placeholder region."
    )


def test_view_html_copy_skipped_if_exists(tmp_path):
    """If view.html already exists in run dir at first-copy time, it's
    NOT overwritten by the first copy. The second-pass embed (J14) may
    still append missing sidecar script blocks via the id-detect
    mechanism if the embedded-data blocks aren't present yet.

    Rationale: the first copy preserves user edits. The second pass
    ONLY updates the sidecar embeds (idempotent; doesn't touch any
    other content). The two-phase contract keeps user edits safe
    while still letting the page auto-load results.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    sentinel = out_dir / "view.html"
    sentinel.write_text("<!-- sentinel: user edits -->\n", encoding="utf-8")

    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        fag_search_fn=_fake_fag_no_results,
        view_html_source=Path("scripts/view.html"),
    )
    run_batch(pensioners=_sample_pensioners(1), cemeteries=_sample_cems(),
              config=cfg)
    # First-copy contract: when view.html already exists, it's not
    # overwritten (so any user edits ARE preserved at the top of
    # the file). The second-pass may add sidecar scripts; in this
    # test, no sidecars exist (no CGR dedup + no DD match ran),
    # so the file should be untouched.
    assert sentinel.read_text(encoding="utf-8").startswith(
        "<!-- sentinel: user edits -->"
    )


def test_view_html_copy_missing_source_does_not_crash(tmp_path):
    """If the source view.html doesn't exist, the run still completes."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    missing_src = tmp_path / "no_such_view.html"
    assert not missing_src.exists()
    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        fag_search_fn=_fake_fag_no_results,
        view_html_source=missing_src,
    )
    # Must not raise
    run_batch(pensioners=_sample_pensioners(1), cemeteries=_sample_cems(),
              config=cfg)
    assert not (out_dir / "view.html").exists()
    # And the batch still produced results
    assert (out_dir / "results.jsonl").exists()


# ============================================================
# Backward compat: legacy state.jsonl path still works
# ============================================================
def test_legacy_state_jsonl_path_still_works(tmp_path):
    """Setting results_filename='state.jsonl' reproduces the old layout."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        fag_search_fn=_fake_fag_no_results,
        results_filename="state.jsonl",
    )
    run_batch(pensioners=_sample_pensioners(2), cemeteries=_sample_cems(),
              config=cfg)
    assert (out_dir / "state.jsonl").exists()


def test_resume_tracker_reads_results_jsonl(tmp_path):
    """ResumeTracker works against results.jsonl (not just state.jsonl)."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    results = out_dir / "results.jsonl"
    results.write_text(
        json.dumps({"pensioner_id": 1}) + "\n" +
        json.dumps({"pensioner_id": 2}) + "\n",
        encoding="utf-8",
    )
    rt = ResumeTracker(state_path=results)
    assert rt.completed_ids == {1, 2}


def test_run_batch_skips_completed_via_results_jsonl(tmp_path):
    """Resume against results.jsonl: pensioners already done are skipped."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    results = out_dir / "results.jsonl"
    results.write_text(
        json.dumps({"pensioner_id": 1, "fag_status": "no_results"}) + "\n",
        encoding="utf-8",
    )

    fag_called = []
    def fake_fag(p, c):
        fag_called.append(p["id"])
        return [], "no_results"

    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        fag_search_fn=fake_fag,
        results_filename="results.jsonl",
    )
    run_batch(pensioners=_sample_pensioners(3), cemeteries=_sample_cems(),
              config=cfg)
    assert 1 not in fag_called
    assert 2 in fag_called
    assert 3 in fag_called


# ============================================================
# copy_view_html_if_missing (unit)
# ============================================================
def test_copy_view_html_if_missing_copies(tmp_path):
    src = tmp_path / "src.html"
    src.write_text("<html></html>", encoding="utf-8")
    dst_dir = tmp_path / "run"
    dst_dir.mkdir()
    copy_view_html_if_missing(src, dst_dir)
    assert (dst_dir / "view.html").exists()
    assert (dst_dir / "view.html").read_text(encoding="utf-8") == "<html></html>"


def test_copy_view_html_if_missing_no_overwrite(tmp_path):
    src = tmp_path / "src.html"
    src.write_text("<html>NEW</html>", encoding="utf-8")
    dst_dir = tmp_path / "run"
    dst_dir.mkdir()
    (dst_dir / "view.html").write_text("<html>EXISTING</html>", encoding="utf-8")
    copy_view_html_if_missing(src, dst_dir)
    assert (dst_dir / "view.html").read_text(encoding="utf-8") == "<html>EXISTING</html>"


def test_copy_view_html_if_missing_handles_missing_source(tmp_path):
    src = tmp_path / "no_such.html"
    dst_dir = tmp_path / "run"
    dst_dir.mkdir()
    # Must not raise
    copy_view_html_if_missing(src, dst_dir)
    assert not (dst_dir / "view.html").exists()