"""Tests for post-pass observer — Phase 7 Slice 7.2."""

from scripts.pipeline.post_pass_observer import PostPassObserver
from scripts.blackboard.schema import Kind


def test_observer_cgr():
    """observe_cgr_corroboration creates CGR observation."""
    obs = PostPassObserver()
    o = obs.observe_cgr_corroboration(
        pensioner_id=1, match_found=True, cgr_match={"name": "John Smith"}
    )
    assert o.kind == Kind.CGRCorroboration
    assert o.payload["match_found"] is True
    assert len(obs.observations) == 1


def test_observer_dd():
    """observe_dixiedata_match creates DD observation."""
    obs = PostPassObserver()
    o = obs.observe_dixiedata_match(pensioner_id=2, match_found=False)
    assert o.kind == Kind.DixieDataMatch
    assert o.payload["match_found"] is False


def test_observer_spouse():
    """observe_spouse_match creates SpouseMatch observation."""
    obs = PostPassObserver()
    o = obs.observe_spouse_match(
        pensioner_id=3, match_confirmed=True,
        spouse_match={"spouse_name": "Mary"}
    )
    assert o.kind == Kind.SpouseMatch
    assert o.payload["match_confirmed"] is True


def test_observer_multiple():
    """Observer accumulates multiple observations."""
    obs = PostPassObserver()
    obs.observe_cgr_corroboration(1, match_found=True)
    obs.observe_dixiedata_match(1, match_found=False)
    obs.observe_spouse_match(1, match_confirmed=True)
    assert len(obs.observations) == 3
