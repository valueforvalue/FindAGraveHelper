"""Tests for the RegionalPlannerKS dedup integration (issue #77).

The dedup helper `plan_already_completed` (on BlackboardStore)
is injected into RegionalPlannerKS at construction time. The
planner skips plans whose (strategy, scope) combo already
completed in a prior run.

These tests pin the integration: given a dedup_fn that
mimics a prior run, the planner emits fewer plans.
"""

from __future__ import annotations

from typing import Any

from scripts.knowledge.regional_planner import RegionalPlannerKS


def _make_pensioner(
    *, last: str = "Gamble", first: str = "John", regiment: str = "",
    burial_state: str = "", notes: str = "",
) -> dict[str, Any]:
    return {
        "id": 327,
        "first_name": first,
        "last_name": last,
        "regiment": regiment,
        "burial_state": burial_state,
        "notes": notes,
    }


def test_planner_emits_full_ladder_without_dedup():
    """No dedup_fn → all plans emitted (default behavior)."""
    planner = RegionalPlannerKS(enable_search=True, dedup_fn=None)
    plans = planner.plan_for_pensioner(_make_pensioner(), 327)
    # OK + (regiment origin if any) + (TX if evidence) + US fallback
    assert len(plans) >= 2  # at minimum: OK + US fallback


def test_planner_skips_completed_plans_via_dedup_fn():
    """When dedup_fn returns True for OK + US, the planner
    emits an empty list (every plan is dedupped)."""
    def _dedup(pid: int, strategy: str, scope: str) -> bool:
        return True  # everything already done

    planner = RegionalPlannerKS(enable_search=True, dedup_fn=_dedup)
    plans = planner.plan_for_pensioner(_make_pensioner(), 327)
    assert plans == []


def test_planner_partial_dedup_only_skips_matching_combos():
    """Dedup on OK + US, NOT on regiment-origin → only the
    regiment plan is emitted."""
    def _dedup(pid: int, strategy: str, scope: str) -> bool:
        if scope in ("OK", "US"):
            return True  # done
        return False  # not done

    planner = RegionalPlannerKS(enable_search=True, dedup_fn=_dedup)
    plans = planner.plan_for_pensioner(
        _make_pensioner(regiment="41st Georgia Infantry"),
        327,
    )
    # OK is dedupped; regiment-origin (Georgia) is NOT; US is
    # dedupped. So only the regiment plan is emitted.
    assert len(plans) == 1
    assert plans[0].scope.value == "RegimentOrigin"


def test_planner_dedup_failure_falls_through_gracefully():
    """When dedup_fn raises (e.g. transient DB error), the
    planner treats it as 'not dedupped' and emits the plan.
    A flaky dedup helper should not block all progress."""
    def _dedup(pid: int, strategy: str, scope: str) -> bool:
        raise RuntimeError("transient DB error")

    planner = RegionalPlannerKS(enable_search=True, dedup_fn=_dedup)
    plans = planner.plan_for_pensioner(_make_pensioner(), 327)
    # Despite the dedup error, the plans are still emitted.
    assert len(plans) >= 2


def test_planner_dedup_does_not_affect_no_dedup_arg():
    """When dedup_fn is None (explicit default), no dedup
    happens — same as the no-arg constructor."""
    planner = RegionalPlannerKS()
    plans = planner.plan_for_pensioner(_make_pensioner(), 327)
    # No dedup = full ladder.
    assert len(plans) >= 2