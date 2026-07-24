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

from scripts.post_pass.pensioncard_pages import (
    PensioncardPagesConfig,
    run,
)


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