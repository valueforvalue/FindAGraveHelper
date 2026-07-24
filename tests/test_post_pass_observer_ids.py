"""Tests for deterministic observation IDs in PostPassObserver (L11).

L11 (CONTEXT.md) requires every observation carry a deterministic
ID derived from its payload. The previous PostPassObserver used
uuid.uuid4(); this test pins that the helper now derives IDs from
sha256(kind|pid|source|version|run_id|pass_id)[:12].

Slice 1 acceptance criterion (Q1, locked decision):
    "the same (kind, pensioner_id, source, version, run_id,
    pass_id) produces the same observation_id across calls."
"""

from __future__ import annotations

from scripts.pipeline.post_pass_observer import PostPassObserver


def test_cgr_id_is_deterministic():
    obs = PostPassObserver(run_id="r1")
    o1 = obs.observe_cgr_corroboration(
        pensioner_id=42, match_found=True, cgr_match={"x": 1}
    )
    o2 = obs.observe_cgr_corroboration(
        pensioner_id=42, match_found=True, cgr_match={"x": 1}
    )
    assert o1.observation_id == o2.observation_id


def test_dd_id_is_deterministic():
    obs = PostPassObserver(run_id="r1")
    o1 = obs.observe_dixiedata_match(
        pensioner_id=99, match_found=False, dd_match={"y": 2}
    )
    o2 = obs.observe_dixiedata_match(
        pensioner_id=99, match_found=False, dd_match={"y": 2}
    )
    assert o1.observation_id == o2.observation_id


def test_spouse_id_is_deterministic():
    obs = PostPassObserver(run_id="r1")
    o1 = obs.observe_spouse_match(
        pensioner_id=7, match_confirmed=True, spouse_match={"z": 3}
    )
    o2 = obs.observe_spouse_match(
        pensioner_id=7, match_confirmed=True, spouse_match={"z": 3}
    )
    assert o1.observation_id == o2.observation_id


def test_different_run_id_produces_different_observation_id():
    """run_id participates in the hash, so different runs differ."""
    o1 = PostPassObserver(run_id="run-a").observe_dixiedata_match(
        pensioner_id=1, match_found=True
    )
    o2 = PostPassObserver(run_id="run-b").observe_dixiedata_match(
        pensioner_id=1, match_found=True
    )
    assert o1.observation_id != o2.observation_id


def test_different_pensioner_id_produces_different_observation_id():
    """pensioner_id participates in the hash, so different pids differ."""
    obs = PostPassObserver(run_id="r1")
    o1 = obs.observe_dixiedata_match(pensioner_id=1, match_found=True)
    o2 = obs.observe_dixiedata_match(pensioner_id=2, match_found=True)
    assert o1.observation_id != o2.observation_id


def test_id_has_expected_prefix_and_length():
    """L11-compatible IDs are 12-char hex with the kind prefix."""
    obs = PostPassObserver(run_id="r1")
    o = obs.observe_cgr_corroboration(pensioner_id=1, match_found=True)
    assert o.observation_id.startswith("obs-cgr-")
    assert len(o.observation_id) == len("obs-cgr-") + 12
    o2 = obs.observe_dixiedata_match(pensioner_id=1, match_found=True)
    assert o2.observation_id.startswith("obs-dd-")
    o3 = obs.observe_spouse_match(pensioner_id=1, match_confirmed=True)
    assert o3.observation_id.startswith("obs-spouse-")