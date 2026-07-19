"""Tests for scripts/knowledge/regional_planner.py — Phase 6 Slice 6.1."""

from scripts.knowledge.regional_planner import RegionalPlannerKS


def _pensioner(**kwargs) -> dict:
    d = {
        "first_name": "John",
        "last_name": "Smith",
        "regiment": "",
        "birth_year": "",
        "notes": "",
        "burial_state": "",
    }
    d.update(kwargs)
    return d


def test_planner_always_emits_ok_first():
    """OK plan is always first."""
    ks = RegionalPlannerKS()
    plans = ks.plan_for_pensioner(_pensioner(), 1)
    assert len(plans) >= 2  # OK + US at minimum
    assert plans[0].scope.value == "OK"
    assert plans[0].reason == "Project default: Oklahoma-first search."


def test_planner_us_is_last():
    """US-wide fallback is always last."""
    ks = RegionalPlannerKS()
    plans = ks.plan_for_pensioner(_pensioner(), 1)
    assert plans[-1].scope.value == "US"


def test_planner_regiment_state_added():
    """Regiment origin state appears between OK and US."""
    ks = RegionalPlannerKS()
    plans = ks.plan_for_pensioner(
        _pensioner(regiment="5th Alabama Infantry"), 1
    )
    scopes = [p.scope.value for p in plans]
    assert "OK" == scopes[0]
    assert "RegimentOrigin" in scopes
    assert scopes[-1] == "US"


def test_planner_texas_evidence_adds_texas_scope():
    """Texas migration evidence triggers a Texas plan."""
    ks = RegionalPlannerKS()
    plans = ks.plan_for_pensioner(
        _pensioner(notes="Family migrated to Texas after war"), 1
    )
    scopes = [p.scope.value for p in plans]
    assert "Texas" in scopes


def test_planner_no_last_name_returns_empty():
    """Cannot plan without at least a last name."""
    ks = RegionalPlannerKS()
    plans = ks.plan_for_pensioner(
        _pensioner(last_name=""), 1
    )
    assert len(plans) == 0


def test_planner_does_not_duplicate_ok():
    """If regiment state is OK, don't add a duplicate."""
    ks = RegionalPlannerKS()
    plans = ks.plan_for_pensioner(
        _pensioner(regiment="1st Oklahoma Cavalry"), 1
    )
    # Should not have two OK plans
    ok_count = sum(1 for p in plans if p.scope.value == "OK")
    assert ok_count == 1
