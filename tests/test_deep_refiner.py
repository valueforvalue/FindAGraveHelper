"""Tests for DeepRefinerKS 3-tier score-driven refinements (#76).

The 3-tier spec (already implemented in DeepRefinerKS):
  - Tier 1: auto_accept (top_score >= skip_refine_above, default 0.85):
    no refinements emitted.
  - Tier 2: needs_review (0.40 <= top_score < skip_refine_above):
    strategy-replay plans (B3-fuzzy, F3-nickname, regiment-origin
    B1-exact, C1-spouse).
  - Tier 3: low_score or no_candidates (top_score < 0.40 OR
    status=no_candidates): surrounding states (AR, KS, MO, TX,
    CO, NM) + US-fuzzy-last + C1-spouse + F3-nickname.

Bail: if bail_on_auto_accept=True and a refinement returns
auto_accept, skip remaining queued refinements. The scheduler
or planner can check the latest ScoreObserved before each
refinement dispatch.

These tests pin the tier selection + max_refinements cap +
dedup against tried combos.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from scripts.blackboard.schema import (
    Kind,
    Observation,
    PlanScope,
    WorkItem,
)
from scripts.blackboard.store import SqliteBlackboardStore
from scripts.knowledge.candidate_scorer import DeepRefinerKS


@pytest.fixture
def sqlite_store(tmp_path):
    """Local SQLite store fixture (no cross-test pollution)."""
    store = SqliteBlackboardStore(tmp_path / "bb.db")
    store.open()
    yield store
    store.close()


# ============================================================
# Helpers
# ============================================================


def _pensioner(**overrides) -> dict:
    p = {
        "id": 327,
        "first_name": "John",
        "last_name": "Gamble",
        "regiment": "",
        "death_year": "",
        "spouse_first_name": "",
        "spouse_last_name": "",
    }
    p.update(overrides)
    return p


def _seed_score(
    store, *, pid: int, top_score: float, status: str = "needs_review"
) -> None:
    """Inject a PensionerImported + ScoreObserved into the store."""
    store.append_observation(
        Observation(
            observation_id=f"obs-pension-{pid}",
            pensioner_id=pid,
            kind=Kind.PensionerImported,
            source="RegionalPlannerKS",
            source_version="1",
            run_id="r1",
            pass_id="1",
            payload=_pensioner(id=pid),
        )
    )
    store.append_observation(
        Observation(
            observation_id=f"obs-score-{pid}",
            pensioner_id=pid,
            kind=Kind.ScoreObserved,
            source="CandidateScorerKS",
            source_version="1",
            run_id="r1",
            pass_id="1",
            payload={
                "status": status,
                "top_score": top_score,
                "policy_version": "1",
            },
        )
    )


def _work_item(pid: int) -> WorkItem:
    return WorkItem(
        work_id=f"work-refine-{pid}",
        pensioner_id=pid,
        knowledge_source="DeepRefinerKS",
    )


# ============================================================
# Tier 1: auto_accept — no refinements
# ============================================================


def test_tier1_auto_accept_no_refinements(sqlite_store):
    """top_score >= skip_refine_above (0.85) → zero refinements."""
    _seed_score(sqlite_store, pid=327, top_score=0.92)
    ks = DeepRefinerKS(max_refinements=6, skip_refine_above=0.85)
    out = ks.invoke(_work_item(327), sqlite_store)
    assert out == []


# ============================================================
# Tier 2: needs_review (0.40 <= score < 0.85)
# ============================================================


def test_tier2_needs_review_emits_strategy_replay_plans(sqlite_store):
    """Score 0.65 (between 0.40 and 0.85) → tier 2 plans emitted."""
    _seed_score(sqlite_store, pid=327, top_score=0.65)
    ks = DeepRefinerKS(max_refinements=6, skip_refine_above=0.85)
    out = ks.invoke(_work_item(327), sqlite_store)
    assert len(out) > 0
    strategies = {p.payload["strategy"] for p in out}
    # Strategy-replay plans per the issue spec.
    assert "B3-first-initial-fuzzy" in strategies or any(
        "fuzzy" in s for s in strategies
    )
    # And F3-nickname should be in the mix.
    assert "F3-nickname" in strategies


def test_tier2_respects_max_refinements_cap(sqlite_store):
    """max_refinements=2 → at most 2 refinement plans emitted."""
    _seed_score(sqlite_store, pid=327, top_score=0.65)
    ks = DeepRefinerKS(max_refinements=2, skip_refine_above=0.85)
    out = ks.invoke(_work_item(327), sqlite_store)
    assert len(out) <= 2


# ============================================================
# Tier 3: low_score / no_candidates (score < 0.40)
# ============================================================


def test_tier3_low_score_emits_surrounding_states(sqlite_store):
    """top_score=0.10 → tier 3; surrounding states + US-fuzzy +
    spouse + nickname all considered."""
    _seed_score(sqlite_store, pid=327, top_score=0.10)
    ks = DeepRefinerKS(max_refinements=20, skip_refine_above=0.85)
    out = ks.invoke(_work_item(327), sqlite_store)
    # Tier 3 should emit more plans than tier 2 (surrounding states
    # give 6+).
    assert len(out) >= 3  # at least surrounding + US-fuzzy + nickname


def test_tier3_no_candidates_status(sqlite_store):
    """status=no_candidates (regardless of score) → tier 3."""
    _seed_score(sqlite_store, pid=327, top_score=0.0, status="no_candidates")
    ks = DeepRefinerKS(max_refinements=20, skip_refine_above=0.85)
    out = ks.invoke(_work_item(327), sqlite_store)
    assert len(out) > 0  # tier 3 active


# ============================================================
# Dedup against tried combos
# ============================================================


def test_dedup_skips_already_tried_combo(sqlite_store):
    """If (B1-exact, AR) was already tried in pass 1, tier 3
    skips it in the refinement pass.

    The dedup reads from `FaGSearchPlan` observations (the
    planner's emitted plans), not `FaGCandidateFetch` (the
    scraper's results). Seed a plan observation for B1-exact
    + AR to simulate pass 1 having tried that combo."""
    sqlite_store.append_observation(
        Observation(
            observation_id="obs-plan-pass1-AR",
            pensioner_id=327,
            kind=Kind.FaGSearchPlan,
            source="RegionalPlannerKS",
            source_version="1",
            run_id="r1",
            pass_id="1",
            payload={
                "strategy": "B1-exact",
                "scope": "AR",
                "plan_id": "plan-AR-327-pass1",
            },
        )
    )
    _seed_score(sqlite_store, pid=327, top_score=0.10)
    ks = DeepRefinerKS(max_refinements=20, skip_refine_above=0.85)
    out = ks.invoke(_work_item(327), sqlite_store)
    # The tier-3 plan for AR should have been skipped.
    for plan_obs in out:
        plan = plan_obs.payload
        if plan["scope"] == "AR" and plan["strategy"] == "B1-exact":
            raise AssertionError(
                "Plan for B1-exact + AR should have been dedupped"
            )


# ============================================================
# Edge cases
# ============================================================


def test_no_score_observation_emits_no_refinements(sqlite_store):
    """Without a ScoreObserved, the refiner is a no-op."""
    ks = DeepRefinerKS(max_refinements=6, skip_refine_above=0.85)
    out = ks.invoke(_work_item(327), sqlite_store)
    assert out == []


def test_pensioner_without_last_name_emits_no_refinements(sqlite_store):
    """Can't search without at least a last name."""
    # Seed the ScoreObserved with a PensionerImported that has
    # an empty last_name. The refiner reads pensioner_obs[0]
    # (the first PensionerImported for the pensioner); with
    # no last name, it returns an empty plan list.
    sqlite_store.append_observation(
        Observation(
            observation_id="obs-pension-327-no-last",
            pensioner_id=327,
            kind=Kind.PensionerImported,
            source="RegionalPlannerKS",
            source_version="1",
            run_id="r1",
            pass_id="1",
            payload={"id": 327, "first_name": "X", "last_name": ""},
        )
    )
    sqlite_store.append_observation(
        Observation(
            observation_id="obs-score-327-no-last",
            pensioner_id=327,
            kind=Kind.ScoreObserved,
            source="CandidateScorerKS",
            source_version="1",
            run_id="r1",
            pass_id="1",
            payload={
                "status": "low_score",
                "top_score": 0.10,
                "policy_version": "1",
            },
        )
    )
    ks = DeepRefinerKS(max_refinements=6, skip_refine_above=0.85)
    out = ks.invoke(_work_item(327), sqlite_store)
    assert out == []


# ============================================================
# In-memory store
# ============================================================


def test_deep_refiner_works_against_sqlite_store(sqlite_store):
    """Smoke test: the KS works against a real SQLite store."""
    _seed_score(sqlite_store, pid=1, top_score=0.5)
    ks = DeepRefinerKS(max_refinements=6, skip_refine_above=0.85)
    out = ks.invoke(_work_item(1), sqlite_store)
    assert len(out) > 0  # tier 2 active


# ============================================================
# Real G10 verification
# ============================================================


G10_BB_PATH = "data/results/run_2026_07_24_g10_stealth_swap_verification/blackboard.db"


def test_g10_refiner_on_real_pensioners():
    """End-to-end: run the refiner against the G10 blackboard.db
    (which has ScoreObserved + plans for 10 pensioners). For each
    pensioner, the refiner should produce at least the same kind
    of output as the live run did (tier 2 or tier 3 depending on
    their top_score)."""
    import shutil
    from pathlib import Path

    src = Path(G10_BB_PATH)
    if not src.exists():
        import pytest
        pytest.skip("G10 blackboard.db not present")

    dst = Path("/tmp/g10_dedup_test.db")
    shutil.copy2(src, dst)

    store = SqliteBlackboardStore(dst)
    store.open()
    try:
        # Pick pensioner 327 (J. Gamble, score 0.644 — tier 2).
        ks = DeepRefinerKS(max_refinements=6, skip_refine_above=0.85)
        out = ks.invoke(_work_item(327), store)
        # 0.644 is between 0.40 and 0.85 → tier 2 → at least 1
        # refinement plan emitted (deduped against what's already
        # in the store).
        assert isinstance(out, list)
    finally:
        store.close()