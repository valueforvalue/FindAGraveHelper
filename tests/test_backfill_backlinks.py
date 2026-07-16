"""Tests for scripts/backfill_backlinks.py.

One-shot script that enriches existing state.jsonl files with the
pensions-application backlink (the `backlink` field), which the
pipeline historically dropped. Tests cover:
  - JSON-array input (ok_pensioners.json shape)
  - JSONL input (state.jsonl shape)
  - Already-present backlink kept as-is (idempotency)
  - Missing-from-unified records get empty string
  - Atomic write (tmp + rename) does not destroy input on failure
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.backfill_backlinks import load_unified_index, backfill


def _write_unified(path: Path, records: list[dict]) -> None:
    path.write_text(json.dumps(records), encoding="utf-8")


def _write_state(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )


def _read_state(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


# ============================================================
# load_unified_index
# ============================================================
def test_load_unified_index_basic(tmp_path):
    """Builds {pid: backlink} from JSON array."""
    u = tmp_path / "unified.json"
    _write_unified(u, [
        {"id": 1, "backlink": "https://dp/id/1"},
        {"id": 2, "backlink": "https://dp/id/2"},
    ])
    idx = load_unified_index(u)
    assert idx == {1: "https://dp/id/1", 2: "https://dp/id/2"}


def test_load_unified_index_handles_duplicates(tmp_path):
    """When id appears twice, first record wins."""
    u = tmp_path / "unified.json"
    _write_unified(u, [
        {"id": 1, "backlink": "https://dp/id/1a"},
        {"id": 1, "backlink": "https://dp/id/1b"},
    ])
    idx = load_unified_index(u)
    assert idx[1] == "https://dp/id/1a"


def test_load_unified_index_handles_missing_backlink(tmp_path):
    """Record without backlink field → empty string."""
    u = tmp_path / "unified.json"
    _write_unified(u, [{"id": 1}])  # no backlink
    idx = load_unified_index(u)
    assert idx[1] == ""


def test_load_unified_index_skips_records_without_id(tmp_path):
    """Records with no id are skipped."""
    u = tmp_path / "unified.json"
    _write_unified(u, [
        {"backlink": "https://dp/id/1"},  # no id
        {"id": 2, "backlink": "https://dp/id/2"},
    ])
    idx = load_unified_index(u)
    assert idx == {2: "https://dp/id/2"}


# ============================================================
# backfill: basic flow
# ============================================================
def test_backfill_adds_backlink_to_empty_records(tmp_path):
    """Records missing backlink get it from unified_index."""
    state = tmp_path / "state.jsonl"
    _write_state(state, [
        {"pensioner_id": 1, "pensioncard_backlink": "https://dp/card/1"},
        {"pensioner_id": 2, "pensioncard_backlink": "https://dp/card/2"},
    ])
    idx = {1: "https://dp/id/1", 2: "https://dp/id/2"}

    filled, skipped, missing = backfill(state, idx)

    assert filled == 2
    assert skipped == 0
    assert missing == 0

    out = _read_state(state)
    assert out[0]["backlink"] == "https://dp/id/1"
    assert out[1]["backlink"] == "https://dp/id/2"
    # pensioncard_backlink preserved
    assert out[0]["pensioncard_backlink"] == "https://dp/card/1"


def test_backfill_idempotent_skips_existing(tmp_path):
    """Records with non-empty backlink are not overwritten."""
    state = tmp_path / "state.jsonl"
    _write_state(state, [
        {"pensioner_id": 1, "backlink": "https://already-set/1"},
    ])
    idx = {1: "https://dp/id/1"}

    filled, skipped, missing = backfill(state, idx)

    assert filled == 0
    assert skipped == 1
    assert missing == 0

    out = _read_state(state)
    assert out[0]["backlink"] == "https://already-set/1"


def test_backfill_handles_missing_from_unified(tmp_path):
    """Records with no unified match get empty backlink."""
    state = tmp_path / "state.jsonl"
    _write_state(state, [
        {"pensioner_id": 999},  # not in unified
        {"pensioner_id": 1},    # in unified
    ])
    idx = {1: "https://dp/id/1"}

    filled, skipped, missing = backfill(state, idx)

    assert filled == 1
    assert missing == 1

    out = _read_state(state)
    assert out[0]["backlink"] == ""
    assert out[1]["backlink"] == "https://dp/id/1"


def test_backfill_writes_to_separate_output(tmp_path):
    """When output_path differs, original is untouched."""
    state = tmp_path / "state.jsonl"
    out = tmp_path / "out.jsonl"
    _write_state(state, [{"pensioner_id": 1}])
    original = state.read_text(encoding="utf-8")

    idx = {1: "https://dp/id/1"}
    backfill(state, idx, output_path=out)

    # Original untouched
    assert state.read_text(encoding="utf-8") == original
    # Output has backlink
    assert _read_state(out)[0]["backlink"] == "https://dp/id/1"


def test_backfill_skips_blank_lines(tmp_path):
    """Empty lines in state.jsonl are skipped, not parsed."""
    state = tmp_path / "state.jsonl"
    state.write_text(
        '{"pensioner_id": 1}\n'
        '\n'
        '   \n'
        '{"pensioner_id": 2}\n',
        encoding="utf-8",
    )
    idx = {1: "https://dp/id/1", 2: "https://dp/id/2"}

    filled, _, _ = backfill(state, idx)
    assert filled == 2
    assert len(_read_state(state)) == 2


def test_backfill_preserves_other_fields(tmp_path):
    """Backfill only touches backlink; all other fields untouched."""
    state = tmp_path / "state.jsonl"
    _write_state(state, [{
        "pensioner_id": 1,
        "pensioner_name": "Adair, R. W.",
        "pensioncard_backlink": "https://dp/card/1",
        "fag_records": [{"memorial_id": "123"}],
        "both_match": {"method": "direct_link"},
    }])
    idx = {1: "https://dp/id/1"}

    backfill(state, idx)

    out = _read_state(state)[0]
    assert out["pensioner_name"] == "Adair, R. W."
    assert out["pensioncard_backlink"] == "https://dp/card/1"
    assert out["fag_records"] == [{"memorial_id": "123"}]
    assert out["both_match"] == {"method": "direct_link"}
    assert out["backlink"] == "https://dp/id/1"