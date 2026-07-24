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