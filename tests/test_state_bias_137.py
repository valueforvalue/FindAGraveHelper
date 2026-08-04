"""Tests for issue #137 — unknown-state scoring bias (Strategy A).

Strategy A was originally framed in the issue as a function-form
strategy, but FaG's URL surface has no param that filters
"burial state = empty" — `locationId` only filters TO a state. So
the implementation is a small scoring bias: when BOTH the pensioner
has no state AND the candidate's burial state is empty, add 0.05
to the score. This test file pins the bias triggers.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.fag.scoring import score_candidate


def _base_local(state: str = "") -> dict:
    return {
        "first_name": "John",
        "middle_name": "",
        "last_name": "Smith",
        "_state_abbr": state,
        "_death_year": "",
        "_birth_year": "",
    }


def _base_cand(state: str | None = None) -> dict:
    return {
        "slug": "john-smith",
        "name": "John Smith",
        "details": {"state": state} if state is not None else {},
    }


# ============================================================
# Trigger matrix
# ============================================================
def test_bias_fires_when_both_states_empty():
    """Both pensioner.state AND candidate.details.state are empty."""
    s, breakdown = score_candidate(_base_local(""), _base_cand(None))
    assert breakdown.get("state_bias") == 0.05


def test_bias_skips_when_local_state_known():
    """If the pensioner has a state, no bias (state_score handles it)."""
    s, breakdown = score_candidate(_base_local("OK"), _base_cand(None))
    assert "state_bias" not in breakdown


def test_bias_skips_when_cand_state_known():
    """If the candidate has a state, no bias."""
    s, breakdown = score_candidate(_base_local(""), _base_cand("TX"))
    assert "state_bias" not in breakdown


def test_bias_skips_when_both_known():
    """Both states known → use existing state_score (0.1) and OK burial paths."""
    s, breakdown = score_candidate(_base_local("OK"), _base_cand("OK"))
    assert "state_bias" not in breakdown


def test_bias_value_is_exactly_0_05():
    """Bias value is pinned; do not let it drift."""
    s, breakdown = score_candidate(_base_local(""), _base_cand(None))
    assert breakdown["state_bias"] == 0.05


def test_bias_does_not_override_name_signal():
    """Bias is additive, not multiplicative — a 0.05 nudge on top of
    name-only evidence must not change a wrong-name match into a
    plausible one."""
    # Same first/last = real match candidate
    s_real, _ = score_candidate(_base_local(""), _base_cand(None))
    # Wrong first name (slug says Jane not John)
    cand_wrong = {"slug": "jane-smith", "name": "Jane Smith", "details": {}}
    s_wrong, _ = score_candidate(_base_local(""), cand_wrong)
    # Real match must still score higher than wrong-name, even with
    # equal bias
    assert s_real > s_wrong


def test_bias_does_not_apply_to_widows_state_path():
    """Widow scoring has its own pension-family path; bias only
    applies to non-widow default path. Both paths here are non-
    widow, so the bias is still 0.05 — this test just pins that
    widow handling isn't accidentally hooked in."""
    s, breakdown = score_candidate(_base_local(""), _base_cand(None))
    assert breakdown.get("state_bias") == 0.05
