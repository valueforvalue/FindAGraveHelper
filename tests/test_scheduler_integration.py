"""Integration smoke tests for scheduler wiring — Phase W4."""

import json
import uuid

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


def test_old_path_still_imports():
    """run_batch is still importable (backward compat)."""
    from scripts.pipeline.run_unified import run_batch
    assert run_batch is not None
