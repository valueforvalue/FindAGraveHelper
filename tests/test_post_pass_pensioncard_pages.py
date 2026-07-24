"""Tests for scripts/post_pass/pensioncard_pages.py — Slice 2.

Pin the post-pass extraction: the moved function must annotate
state.jsonl rows with `pensioncard_pages` from a sidecar JSON file,
identically to the old in-line `_annotate_pensioncard_pages`.

Slice 2 acceptance criterion (from
docs/designs/post-pass-extraction.md §Slice 2):
    "After Slice 2 lands, running the runner with a
    pensioncard_pages.json sidecar populates the
    `pensioncard_pages` field on matching state rows identically
    to before the slice."
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.post_pass.pensioncard_pages import (
    PensioncardPagesConfig,
    UPSTREAM_PENSIONCARD_PAGES_PATH,
    run,
)


@pytest.fixture(autouse=True)
def _isolate_upstream_cache(monkeypatch, tmp_path):
    """Pin the upstream cache path to a non-existent file for every
    test by default. Tests that exercise the upstream-cache fallback
    override this fixture by patching UPSTREAM_PENSIONCARD_PAGES_PATH
    to a real file they create. This keeps the pre-#102 tests honest
    (they exercise the auto-derive path, not the upstream cache).
    """
    fake = tmp_path / "no-upstream-cache.json"
    monkeypatch.setattr(
        "scripts.post_pass.pensioncard_pages.UPSTREAM_PENSIONCARD_PAGES_PATH",
        fake,
    )
    yield



# ============================================================
# Helpers
# ============================================================


class _NullLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


def _write_state_jsonl(path: Path, rows: list[dict]) -> None:
    """Write rows as newline-delimited JSON (L5)."""
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_state_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# ============================================================
# Acceptance tests
# ============================================================


def test_run_annotates_matching_rows(tmp_path: Path):
    """Rows whose pensioner_id appears in the sidecar get the field."""
    results = tmp_path / "state.jsonl"
    _write_state_jsonl(
        results,
        [
            {"pensioner_id": 1, "name_raw": "Alice"},
            {"pensioner_id": 2, "name_raw": "Bob"},
            {"pensioner_id": 3, "name_raw": "Carol"},
        ],
    )
    sidecar = tmp_path / "pensioncard_pages.json"
    sidecar.write_text(
        json.dumps({"1": ["page-a", "page-b"], "3": ["page-c"]}),
        encoding="utf-8",
    )

    stats = run(
        results,
        config=PensioncardPagesConfig(sidecar_path=sidecar),
        out_dir=tmp_path,
        log=_NullLogger(),
    )

    rows = _read_state_jsonl(results)
    assert "pensioncard_pages" in rows[0]
    assert rows[0]["pensioncard_pages"] == ["page-a", "page-b"]
    assert "pensioncard_pages" not in rows[1]
    assert "pensioncard_pages" in rows[2]
    assert rows[2]["pensioncard_pages"] == ["page-c"]
    assert stats.matched == 2


def test_run_is_idempotent(tmp_path: Path):
    """Re-running does not duplicate or lose the pensioncard_pages field."""
    results = tmp_path / "state.jsonl"
    _write_state_jsonl(results, [{"pensioner_id": 1, "name_raw": "Alice"}])
    sidecar = tmp_path / "pensioncard_pages.json"
    sidecar.write_text(json.dumps({"1": ["page-a"]}), encoding="utf-8")

    config = PensioncardPagesConfig(sidecar_path=sidecar)
    log = _NullLogger()
    first = run(results, config=config, out_dir=tmp_path, log=log)
    assert first.matched == 1
    second = run(results, config=config, out_dir=tmp_path, log=log)
    # Second run: sidecar still present, row already annotated but no
    # regression; stats must report matched=0 (no new annotation) or
    # still matched=1 if implementation re-reads and re-writes
    # identically — what matters is no duplicate field.
    rows = _read_state_jsonl(results)
    assert "pensioncard_pages" in rows[0]
    # No duplicate key, no nested list.
    assert isinstance(rows[0]["pensioncard_pages"], list)


def test_run_skipped_when_no_sidecar(tmp_path: Path):
    """No sidecar → skipped=True, no write, no error."""
    results = tmp_path / "state.jsonl"
    _write_state_jsonl(results, [{"pensioner_id": 1}])
    stats = run(
        results,
        config=PensioncardPagesConfig(sidecar_path=None),
        out_dir=tmp_path,
        log=_NullLogger(),
    )
    assert stats.skipped is True
    rows = _read_state_jsonl(results)
    assert "pensioncard_pages" not in rows[0]


def test_run_skipped_when_sidecar_empty(tmp_path: Path):
    """Empty sidecar dict → skipped=True."""
    results = tmp_path / "state.jsonl"
    _write_state_jsonl(results, [{"pensioner_id": 1}])
    sidecar = tmp_path / "pensioncard_pages.json"
    sidecar.write_text(json.dumps({}), encoding="utf-8")
    stats = run(
        results,
        config=PensioncardPagesConfig(sidecar_path=sidecar),
        out_dir=tmp_path,
        log=_NullLogger(),
    )
    assert stats.skipped is True


def test_run_auto_detects_sidecar_in_out_dir(tmp_path: Path):
    """When sidecar_path is None but out_dir/pensioncard_pages.json exists, use it."""
    results = tmp_path / "state.jsonl"
    _write_state_jsonl(results, [{"pensioner_id": 5}])
    sidecar = tmp_path / "pensioncard_pages.json"
    sidecar.write_text(json.dumps({"5": ["page-x"]}), encoding="utf-8")
    stats = run(
        results,
        config=PensioncardPagesConfig(sidecar_path=None),
        out_dir=tmp_path,
        log=_NullLogger(),
    )
    assert stats.skipped is False
    assert stats.matched == 1


def test_run_returns_post_pass_stats(tmp_path: Path):
    """Stats object carries name + counts."""
    results = tmp_path / "state.jsonl"
    _write_state_jsonl(results, [{"pensioner_id": 1}])
    sidecar = tmp_path / "pensioncard_pages.json"
    sidecar.write_text(json.dumps({"1": ["a"]}), encoding="utf-8")
    stats = run(
        results,
        config=PensioncardPagesConfig(sidecar_path=sidecar),
        out_dir=tmp_path,
        log=_NullLogger(),
    )
    assert stats.name == "pensioncard_pages"
    assert stats.errors == 0


# ============================================================
# Auto-derive path (issue #101)
# ============================================================
#
# When no sidecar exists, the post-pass derives a minimal sidecar
# from each row's `pensioncard_iiif_url` field. The IIIF URL
# pattern is:
#   https://digitalprairie.ok.gov/iiif/2/pensioncard:{id}/full/.../default.jpg
# For single-page items, the page_id IS the pensioncard_id
# (per scripts/ingest/fetch_pensioncard_pages.py docstring).
# The operator-built sidecar still wins when present.


def _write_state_with_iiif(
    path: Path, rows: list[tuple[int, str | None]]
) -> None:
    """Build rows of (pensioner_id, iiif_url_or_None)."""
    out = []
    for pid, iiif in rows:
        row = {
            "pensioner_id": pid,
            "pensioner_name": f"Pensioner {pid}",
            "pensioncard_backlink": (
                f"https://digitalprairie.ok.gov/digital/singleitem/"
                f"collection/pensioncard/id/{pid}"
                if iiif else ""
            ),
            "pensioncard_iiif_url": iiif or "",
        }
        out.append(row)
    _write_state_jsonl(path, out)


def test_run_auto_derives_from_iiif_url_when_sidecar_missing(tmp_path):
    """No sidecar + rows with pensioncard_iiif_url → post-pass
    derives a sidecar and stamps [pensioncard_id] on each row."""
    results = tmp_path / "state.jsonl"
    _write_state_with_iiif(
        results,
        [
            (327, "https://digitalprairie.ok.gov/iiif/2/pensioncard:3271/full/300,/0/default.jpg"),
            (328, "https://digitalprairie.ok.gov/iiif/2/pensioncard:9346/full/full/0/default.jpg"),
        ],
    )
    config = PensioncardPagesConfig(sidecar_path=None)

    stats = run(
        results,
        config=config,
        out_dir=tmp_path,
        log=_NullLogger(),
    )

    assert stats.name == "pensioncard_pages"
    assert stats.skipped is False
    assert stats.matched == 2

    rows = _read_state_jsonl(results)
    assert rows[0]["pensioncard_pages"] == [3271]
    assert rows[1]["pensioncard_pages"] == [9346]

    # And the derived sidecar is written to out_dir for
    # downstream re-runs.
    derived = tmp_path / "pensioncard_pages.json"
    assert derived.exists()
    sidecar_data = json.loads(derived.read_text(encoding="utf-8"))
    assert sidecar_data["327"] == [3271]
    assert sidecar_data["328"] == [9346]


def test_run_operator_sidecar_wins_over_auto_derive(tmp_path):
    """When both the sidecar AND the IIF URLs are present, the
    operator-built sidecar takes precedence (auto-derive skipped)."""
    results = tmp_path / "state.jsonl"
    _write_state_with_iiif(
        results,
        [
            (
                327,
                "https://digitalprairie.ok.gov/iiif/2/pensioncard:3271/full/300,/0/default.jpg",
            ),
        ],
    )
    # Operator sidecar: a different (curated) value.
    sidecar = tmp_path / "pensioncard_pages.json"
    sidecar.write_text(json.dumps({"327": [99999, 99998]}), encoding="utf-8")
    config = PensioncardPagesConfig(sidecar_path=None)

    run(results, config=config, out_dir=tmp_path, log=_NullLogger())

    rows = _read_state_jsonl(results)
    # Operator sidecar value, not the auto-derived [3271].
    assert rows[0]["pensioncard_pages"] == [99999, 99998]


def test_run_explicit_sidecar_path_takes_precedence(tmp_path):
    """When PensioncardPagesConfig.sidecar_path is set (the
    CLI --pensioncard-pages path), that file wins regardless
    of any out_dir/pensioncard_pages.json."""
    results = tmp_path / "state.jsonl"
    _write_state_with_iiif(
        results,
        [
            (
                327,
                "https://digitalprairie.ok.gov/iiif/2/pensioncard:3271/full/300,/0/default.jpg",
            ),
        ],
    )
    # Two possible sidecars: explicit (curated) vs out_dir (would auto-derive).
    explicit = tmp_path / "explicit.json"
    explicit.write_text(json.dumps({"327": [11111]}), encoding="utf-8")
    out_dir_sidecar = tmp_path / "pensioncard_pages.json"
    out_dir_sidecar.write_text(
        json.dumps({"327": [22222, 22223]}), encoding="utf-8"
    )
    config = PensioncardPagesConfig(sidecar_path=explicit)

    run(results, config=config, out_dir=tmp_path, log=_NullLogger())

    rows = _read_state_jsonl(results)
    # Explicit wins.
    assert rows[0]["pensioncard_pages"] == [11111]


def test_run_no_iiif_url_no_sidecar_no_op(tmp_path):
    """When no sidecar AND no pensioncard_iiif_url, the pass
    skips. No file is written, no annotation happens."""
    results = tmp_path / "state.jsonl"
    _write_state_with_iiif(
        results,
        [
            (1, None),  # row 1 has no IIIF URL
            (2, ""),    # row 2 has empty string
        ],
    )
    config = PensioncardPagesConfig(sidecar_path=None)

    stats = run(
        results,
        config=config,
        out_dir=tmp_path,
        log=_NullLogger(),
    )

    assert stats.skipped is True
    assert stats.matched == 0
    assert not (tmp_path / "pensioncard_pages.json").exists()
    # State.jsonl unchanged: no pensioncard_pages field.
    rows = _read_state_jsonl(results)
    for r in rows:
        assert "pensioncard_pages" not in r


def test_run_auto_derive_partial_match(tmp_path):
    """When some rows have IIIF URLs and some don't, only the
    ones with URLs are annotated; rows without URLs are
    left untouched."""
    results = tmp_path / "state.jsonl"
    _write_state_with_iiif(
        results,
        [
            (10, "https://digitalprairie.ok.gov/iiif/2/pensioncard:100/full/full/0/default.jpg"),
            (11, None),  # no IIIF URL
            (12, "https://digitalprairie.ok.gov/iiif/2/pensioncard:120/full/full/0/default.jpg"),
        ],
    )
    config = PensioncardPagesConfig(sidecar_path=None)

    stats = run(
        results,
        config=config,
        out_dir=tmp_path,
        log=_NullLogger(),
    )

    assert stats.matched == 2
    rows = _read_state_jsonl(results)
    assert rows[0]["pensioncard_pages"] == [100]
    assert "pensioncard_pages" not in rows[1]
    assert rows[2]["pensioncard_pages"] == [120]


def test_run_auto_derive_ignores_malformed_iiif_url(tmp_path):
    """A malformed IIIF URL is silently skipped; well-formed URLs
    in the same run are still annotated."""
    results = tmp_path / "state.jsonl"
    _write_state_with_iiif(
        results,
        [
            (1, "not-a-url"),
            (2, "https://digitalprairie.ok.gov/iiif/2/pensioncard:200/full/full/0/default.jpg"),
        ],
    )
    config = PensioncardPagesConfig(sidecar_path=None)

    stats = run(
        results,
        config=config,
        out_dir=tmp_path,
        log=_NullLogger(),
    )

    assert stats.matched == 1
    rows = _read_state_jsonl(results)
    assert "pensioncard_pages" not in rows[0]
    assert rows[1]["pensioncard_pages"] == [200]


def test_run_auto_derive_writes_compound_item_warning_for_large_runs(tmp_path):
    """For runs > 100 records with auto-derived single-page
    pages, log a warning that compound items may have been
    missed. Pin that the warning fires."""
    results = tmp_path / "state.jsonl"
    rows = [(i, f"https://digitalprairie.ok.gov/iiif/2/pensioncard:{i}/full/full/0/default.jpg") for i in range(101)]
    _write_state_with_iiif(results, rows)
    config = PensioncardPagesConfig(sidecar_path=None)

    warnings: list[str] = []

    class _CaptureLogger:
        def info(self, msg, *args, **kwargs):
            pass

        def warning(self, msg, *args, **kwargs):
            warnings.append(msg % args if args else msg)

        def error(self, *args, **kwargs):
            pass

        def debug(self, *args, **kwargs):
            pass

    run(results, config=config, out_dir=tmp_path, log=_CaptureLogger())
    assert any("compound" in w.lower() for w in warnings), warnings


def test_run_auto_derive_no_compound_warning_for_small_runs(tmp_path):
    """For small runs (≤ 100 records), no compound-item warning
    fires. Keeps the log clean for typical smoke tests."""
    results = tmp_path / "state.jsonl"
    _write_state_with_iiif(
        results,
        [
            (1, "https://digitalprairie.ok.gov/iiif/2/pensioncard:1/full/full/0/default.jpg"),
            (2, "https://digitalprairie.ok.gov/iiif/2/pensioncard:2/full/full/0/default.jpg"),
        ],
    )
    config = PensioncardPagesConfig(sidecar_path=None)

    warnings: list[str] = []

    class _CaptureLogger:
        def info(self, msg, *args, **kwargs):
            pass

        def warning(self, msg, *args, **kwargs):
            warnings.append(msg % args if args else msg)

        def error(self, *args, **kwargs):
            pass

        def debug(self, *args, **kwargs):
            pass

    run(results, config=config, out_dir=tmp_path, log=_CaptureLogger())
    assert not any("compound" in w.lower() for w in warnings)

# ============================================================
# Issue #81: opt-in auto-fetch of compound pensioncard pages
# ============================================================
#
# When FETCH_PENSIONCARD_PAGES=1 is set, the post-pass invokes
# `scripts/ingest/fetch_pensioncard_pages.py` to build a real
# sidecar (including compound items, where the auto-derive
# path produces a wrong page list). When the env var is unset,
# the post-pass skips the fetch and relies on the auto-derive
# path (which still covers the 73% single-page case).
#
# The fetch itself is a real HTTP call to digitalprairie.ok.gov
# — too slow for unit tests. We test the dispatch + the env-var
# gate via an injected `fetch_command` callable.


def test_run_invokes_fetch_script_when_env_var_set(tmp_path, monkeypatch):
    """FETCH_PENSIONCARD_PAGES=1 + a fetch_command callable →
    the post-pass calls the fetch command with the input and
    output paths."""
    results = tmp_path / "state.jsonl"
    _write_state_with_iiif(
        results,
        [
            (1, "https://digitalprairie.ok.gov/iiif/2/pensioncard:1/full/full/0/default.jpg"),
        ],
    )

    calls: list[list[str]] = []

    def _fake_fetch(input_path, output_path, throttle):
        calls.append([str(input_path), str(output_path), str(throttle)])
        # Simulate the script writing the sidecar.
        import json
        output_path.write_text(
            json.dumps({"1": [1, 2]}), encoding="utf-8"
        )

    monkeypatch.setenv("FETCH_PENSIONCARD_PAGES", "1")
    config = PensioncardPagesConfig(
        sidecar_path=None,
        fetch_command=_fake_fetch,
    )

    run(results, config=config, out_dir=tmp_path, log=_NullLogger())

    # The fetch command was called.
    assert len(calls) == 1
    assert calls[0][0] == str(results)
    # And the sidecar was written + read → row got the page list.
    rows = _read_state_jsonl(results)
    assert rows[0]["pensioncard_pages"] == [1, 2]


def test_run_skips_fetch_when_env_var_unset(tmp_path, monkeypatch):
    """No FETCH_PENSIONCARD_PAGES env var → no fetch, even when
    fetch_command is supplied. The auto-derive path still runs."""
    results = tmp_path / "state.jsonl"
    _write_state_with_iiif(
        results,
        [
            (1, "https://digitalprairie.ok.gov/iiif/2/pensioncard:1/full/full/0/default.jpg"),
        ],
    )

    calls: list[list[str]] = []

    def _fake_fetch(input_path, output_path, throttle):
        calls.append([str(input_path), str(output_path), str(throttle)])

    monkeypatch.delenv("FETCH_PENSIONCARD_PAGES", raising=False)
    config = PensioncardPagesConfig(
        sidecar_path=None,
        fetch_command=_fake_fetch,
    )

    run(results, config=config, out_dir=tmp_path, log=_NullLogger())

    # No fetch. Auto-derive still ran (single-page).
    assert calls == []
    rows = _read_state_jsonl(results)
    assert rows[0]["pensioncard_pages"] == [1]


def test_run_fetch_failure_is_non_fatal(tmp_path, monkeypatch):
    """When the fetch raises, the pass logs a warning + still
    runs auto-derive. The pass never aborts the run."""
    results = tmp_path / "state.jsonl"
    _write_state_with_iiif(
        results,
        [
            (1, "https://digitalprairie.ok.gov/iiif/2/pensioncard:1/full/full/0/default.jpg"),
        ],
    )

    def _broken_fetch(input_path, output_path, throttle):
        raise RuntimeError("digitalprairie returned 503")

    warnings: list[str] = []

    class _CaptureLogger:
        def info(self, *a, **k): pass
        def warning(self, msg, *a, **k):
            warnings.append(msg % a if a else msg)
        def error(self, *a, **k): pass
        def debug(self, *a, **k): pass

    monkeypatch.setenv("FETCH_PENSIONCARD_PAGES", "1")
    config = PensioncardPagesConfig(
        sidecar_path=None,
        fetch_command=_broken_fetch,
    )

    run(results, config=config, out_dir=tmp_path, log=_CaptureLogger())

    # Auto-derive still ran.
    rows = _read_state_jsonl(results)
    assert rows[0]["pensioncard_pages"] == [1]
    # And a warning was logged.
    assert any("fetch" in w.lower() for w in warnings)


# ============================================================
# Upstream-cache fallback (issue #102)
# ============================================================
def test_run_falls_back_to_upstream_cache(tmp_path: Path, monkeypatch):
    """When neither --pensioncard-pages nor out_dir/pensioncard_pages.json
    exists, fall back to the upstream cache at
    docs/research/digitalprairie/ok_pensioners.pensioncard_pages.json.
    This is the #102 promise: every subsequent run gets full
    compound-page coverage for free, no flag required.
    """
    upstream = tmp_path / "upstream.json"
    upstream.write_text(
        json.dumps({"1": [96, 97], "2": [42]}), encoding="utf-8"
    )
    monkeypatch.setattr(
        "scripts.post_pass.pensioncard_pages.UPSTREAM_PENSIONCARD_PAGES_PATH",
        upstream,
    )
    results = tmp_path / "state.jsonl"
    _write_state_jsonl(results, [{"pensioner_id": 1}, {"pensioner_id": 2}])
    stats = run(
        results,
        config=PensioncardPagesConfig(sidecar_path=None),
        out_dir=tmp_path,
        log=_NullLogger(),
    )
    assert stats.skipped is False
    assert stats.matched == 2
    rows = _read_state_jsonl(results)
    assert rows[0]["pensioncard_pages"] == [96, 97]
    assert rows[1]["pensioncard_pages"] == [42]


def test_run_upstream_cache_does_not_shadow_out_dir_sidecar(
    tmp_path: Path, monkeypatch
):
    """An explicit <out_dir>/pensioncard_pages.json wins over the
    upstream cache. Per-run curation overrides the repo-wide cache.
    """
    upstream = tmp_path / "upstream.json"
    upstream.write_text(
        json.dumps({"1": [999]}), encoding="utf-8"
    )
    monkeypatch.setattr(
        "scripts.post_pass.pensioncard_pages.UPSTREAM_PENSIONCARD_PAGES_PATH",
        upstream,
    )
    out_dir_sidecar = tmp_path / "pensioncard_pages.json"
    out_dir_sidecar.write_text(
        json.dumps({"1": [42]}), encoding="utf-8"
    )
    results = tmp_path / "state.jsonl"
    _write_state_jsonl(results, [{"pensioner_id": 1}])
    run(
        results,
        config=PensioncardPagesConfig(sidecar_path=None),
        out_dir=tmp_path,
        log=_NullLogger(),
    )
    rows = _read_state_jsonl(results)
    assert rows[0]["pensioncard_pages"] == [42]


def test_run_explicit_sidecar_wins_over_upstream_cache(
    tmp_path: Path, monkeypatch
):
    """Explicit --pensioncard-pages wins over both the upstream cache
    and the out_dir sidecar. Operator-curated sidecar is the highest
    precedence.
    """
    upstream = tmp_path / "upstream.json"
    upstream.write_text(json.dumps({"1": [999]}), encoding="utf-8")
    monkeypatch.setattr(
        "scripts.post_pass.pensioncard_pages.UPSTREAM_PENSIONCARD_PAGES_PATH",
        upstream,
    )
    out_dir_sidecar = tmp_path / "pensioncard_pages.json"
    out_dir_sidecar.write_text(json.dumps({"1": [555]}), encoding="utf-8")
    explicit = tmp_path / "explicit.json"
    explicit.write_text(json.dumps({"1": [111]}), encoding="utf-8")
    results = tmp_path / "state.jsonl"
    _write_state_jsonl(results, [{"pensioner_id": 1}])
    run(
        results,
        config=PensioncardPagesConfig(sidecar_path=explicit),
        out_dir=tmp_path,
        log=_NullLogger(),
    )
    rows = _read_state_jsonl(results)
    assert rows[0]["pensioncard_pages"] == [111]


def test_run_upstream_cache_logs_warning_when_compound_missing(
    tmp_path: Path, monkeypatch
):
    """Operators who never run the ingest script still get a hint
    that the upstream cache is missing. The warning names the
    script so the operator knows what to run.
    """
    monkeypatch.setattr(
        "scripts.post_pass.pensioncard_pages.UPSTREAM_PENSIONCARD_PAGES_PATH",
        tmp_path / "does-not-exist.json",
    )
    # 101 rows => above the compound-warn threshold (100). The
    # auto-derive path then logs the warning that names the
    # fetch script.
    rows = [
        (i, f"https://digitalprairie.ok.gov/iiif/2/pensioncard:{i}/full/full/0/default.jpg")
        for i in range(1, 102)
    ]
    results = tmp_path / "state.jsonl"
    _write_state_with_iiif(results, rows)
    warnings: list[str] = []

    class _CaptureLogger:
        def info(self, *a, **k): pass
        def warning(self, msg, *a, **k):
            warnings.append(msg % a if a else msg)
        def error(self, *a, **k): pass
        def debug(self, *a, **k): pass

    run(
        results,
        config=PensioncardPagesConfig(sidecar_path=None),
        out_dir=tmp_path,
        log=_CaptureLogger(),
    )
    assert any("fetch_pensioncard_pages" in w for w in warnings)
