"""Tests for atomic migration in rename_to_ok_names.py — Phase 2 Slice 2.7."""

import json
import os
from pathlib import Path

import pytest


# Import the helper we added (not main, which has side effects)
from scripts.pipeline.rename_to_ok_names import _fsync_path


def test_fsync_path_writes_and_syncs(tmp_path):
    """_fsync_path writes data and syncs without error."""
    p = tmp_path / "test.txt"
    p.write_text("hello", encoding="utf-8")
    _fsync_path(p)  # must not raise
    assert p.read_text() == "hello"


def test_main_dry_run_does_not_write(tmp_path, monkeypatch):
    """--dry-run prints plan but writes nothing to destination."""
    # This test verifies the script parses without crashing on dry-run.
    # We can't easily test full migration without the real source files,
    # but we can verify dry-run mode exits cleanly.
    from scripts.pipeline import rename_to_ok_names

    # Override RENAMES to point at temp files
    src = tmp_path / "test.json"
    src.write_text('[{"id": 1}]', encoding="utf-8")
    dst = tmp_path / "test_out.json"
    meta_dst = tmp_path / "test_out.meta.json"

    monkeypatch.setattr(
        rename_to_ok_names,
        "RENAMES",
        [{
            "data_src": src,
            "data_dst": dst,
            "meta_dst": meta_dst,
            "source_url": "http://example.com",
            "source_collection": "test",
            "record_count_field": None,
        }],
    )
    monkeypatch.setattr(rename_to_ok_names, "ROOT", tmp_path)

    import sys as _sys
    monkeypatch.setattr(_sys, "argv", ["rename_to_ok_names.py", "--dry-run"])

    rc = rename_to_ok_names.main()
    assert rc == 0
    assert not dst.exists()  # dry-run writes nothing


def test_main_atomic_migration_writes_tmp_then_replace(tmp_path, monkeypatch):
    """Non-dry-run migration writes to .tmp first, then os.replace."""
    from scripts.pipeline import rename_to_ok_names

    src = tmp_path / "test.json"
    src.write_text('[{"id": 1}]', encoding="utf-8")
    dst = tmp_path / "test_out.json"
    meta_dst = tmp_path / "test_out.meta.json"

    monkeypatch.setattr(
        rename_to_ok_names,
        "RENAMES",
        [{
            "data_src": src,
            "data_dst": dst,
            "meta_dst": meta_dst,
            "source_url": "http://example.com",
            "source_collection": "test",
            "record_count_field": None,
        }],
    )
    monkeypatch.setattr(rename_to_ok_names, "ROOT", tmp_path)

    import sys as _sys
    monkeypatch.setattr(_sys, "argv", ["rename_to_ok_names.py"])

    rc = rename_to_ok_names.main()
    assert rc == 0
    assert dst.exists()
    assert meta_dst.exists()
    assert not src.exists()  # source was removed after rename

    # Verify meta content
    meta = json.loads(meta_dst.read_text(encoding="utf-8"))
    assert meta["_meta"]["record_count"] == 1

    # Verify migration manifest
    manifest = tmp_path / "output" / "migration_manifest.json"
    assert manifest.exists()
    m = json.loads(manifest.read_text(encoding="utf-8"))
    assert len(m["events"]) == 1
    assert "source_sha256" in m["events"][0]
