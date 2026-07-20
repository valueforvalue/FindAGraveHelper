"""Tests for scoring_constants deduplication (#37).

After commit 8060dd5 (#31) the pipeline layer migrated to
scoring_constants. The blackboard layer (decision_policy.py)
still re-declares its own thresholds + STATUS_* set. Issue #37
fixes the drift by making scoring_constants the single source
of truth, and renaming the FaG-search threshold (0.70) to
FAG_AUTO_ACCEPT_THRESHOLD so the distinction with the
pipeline-decision threshold (0.85) is explicit.

Tests pin:
  - The blackboard decision policy imports its values from
    scoring_constants, not local re-declarations.
  - The FaG-search and pipeline-decision thresholds are
    documented as distinct concepts (even when they share
    a value today).
  - STATUS_* values match scoring_constants.STATUS_*
  - LOW_SCORE_THRESHOLD is shared (same value, single source).
  - Legacy module-level names on decision_policy still work
    for one release (deprecation shim).
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.pipeline import scoring_constants as sc


# ============================================================
# scoring_constants exposes the FaG-search thresholds
# ============================================================
class TestScoringConstantsHasFagThresholds:
    """The FaG-search auto-accept threshold (0.70) and gap (0.10)
    were historically in scripts/blackboard/decision_policy.py
    because that module is what scripts/fag/search.py uses to
    classify each search result. After #37 they live in
    scoring_constants.py with the FAG_ prefix, so the FaG
    layer and the pipeline layer share one source."""

    def test_fag_auto_accept_threshold_present(self):
        assert hasattr(sc, "FAG_AUTO_ACCEPT_THRESHOLD")
        assert sc.FAG_AUTO_ACCEPT_THRESHOLD == 0.70

    def test_fag_auto_accept_threshold_no_death_present(self):
        assert hasattr(sc, "FAG_AUTO_ACCEPT_THRESHOLD_NO_DEATH")
        assert sc.FAG_AUTO_ACCEPT_THRESHOLD_NO_DEATH == 0.60

    def test_fag_auto_accept_gap_present(self):
        assert hasattr(sc, "FAG_AUTO_ACCEPT_GAP")
        assert sc.FAG_AUTO_ACCEPT_GAP == 0.10

    def test_fag_and_pipeline_thresholds_are_distinct_symbols(self):
        """FAG_AUTO_ACCEPT_THRESHOLD (0.70) is the FaG-search
        decision; AUTO_ACCEPT_THRESHOLD (0.85) is the pipeline-
        decision. They share a value? No — they're different
        values for different gates. Test that the module has
        both, distinctly."""
        assert sc.FAG_AUTO_ACCEPT_THRESHOLD != sc.AUTO_ACCEPT_THRESHOLD
        # Pipeline threshold is higher (stricter)
        assert sc.AUTO_ACCEPT_THRESHOLD > sc.FAG_AUTO_ACCEPT_THRESHOLD


# ============================================================
# Blackboard decision policy uses canonical constants
# ============================================================
class TestDecisionPolicyUsesCanonical:
    """decision_policy.py imports its thresholds + status strings
    from scoring_constants, not from local re-declarations."""

    def test_policy_module_imports_from_scoring_constants(self):
        import scripts.blackboard.decision_policy as dp
        # The policy module's FAG_AUTO_ACCEPT_THRESHOLD should be
        # the SAME OBJECT as scoring_constants.FAG_AUTO_ACCEPT_THRESHOLD.
        assert dp.FAG_AUTO_ACCEPT_THRESHOLD is sc.FAG_AUTO_ACCEPT_THRESHOLD
        assert dp.LOW_SCORE_THRESHOLD is sc.LOW_SCORE_THRESHOLD
        assert dp.STATUS_AUTO_ACCEPT is sc.STATUS_AUTO_ACCEPT

    def test_status_constants_match_canonical(self):
        """Every STATUS_* on decision_policy equals the
        scoring_constants version. They MUST be the same
        string value, not a typo'd duplicate."""
        import scripts.blackboard.decision_policy as dp
        for name in (
            "STATUS_AUTO_ACCEPT",
            "STATUS_NEEDS_REVIEW",
            "STATUS_LOW_SCORE",
            "STATUS_NO_CANDIDATES",
            "STATUS_ERROR",
            "STATUS_AMBIGUOUS",
        ):
            assert getattr(dp, name) == getattr(sc, name), (
                f"{name} mismatch: dp={getattr(dp, name)!r} "
                f"sc={getattr(sc, name)!r}"
            )

    def test_legacy_unprefixed_names_still_work(self):
        """For one release, the unprefixed names (AUTO_ACCEPT_THRESHOLD)
        remain as deprecated re-exports so existing callers compile.
        A DeprecationWarning is emitted on import.
        """
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import scripts.blackboard.decision_policy as dp
            # Re-import to force the deprecation path
            import importlib
            importlib.reload(dp)
            # The legacy name should still resolve
            assert hasattr(dp, "AUTO_ACCEPT_THRESHOLD")
            assert dp.AUTO_ACCEPT_THRESHOLD == sc.FAG_AUTO_ACCEPT_THRESHOLD
            # And it should be flagged as deprecated
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert any(
                "AUTO_ACCEPT_THRESHOLD" in str(x.message)
                for x in deprecation_warnings
            ), \
                "expected a DeprecationWarning naming the legacy name"


# ============================================================
# Decision policy end-to-end: values flow from canonical source
# ============================================================
class TestDecisionPolicyEndToEnd:
    """Run the policy and check that the recorded `threshold_used`
    comes from the canonical source, not a stale local copy."""

    def test_classify_uses_canonical_fag_threshold(self):
        from scripts.blackboard.decision_policy import (
            DecisionContext, classify,
        )
        ctx = DecisionContext(
            candidates=[{"score": 0.75, "memorial_id": "1"}],
            local_death_year="1932",
        )
        d = classify(ctx)
        # 0.75 >= FAG_AUTO_ACCEPT_THRESHOLD (0.70) with death year
        # known → auto_accept
        assert d.status == "auto_accept"
        # The recorded threshold should match the canonical value
        assert d.threshold_used == sc.FAG_AUTO_ACCEPT_THRESHOLD

    def test_classify_uses_canonical_low_score_threshold(self):
        from scripts.blackboard.decision_policy import (
            DecisionContext, classify,
        )
        ctx = DecisionContext(
            candidates=[{"score": 0.10, "memorial_id": "1"}],
            local_death_year="1932",
        )
        d = classify(ctx)
        assert d.status == "low_score"
        # The reason text should reference the canonical threshold
        assert f"{sc.LOW_SCORE_THRESHOLD}" in d.reason


# ============================================================
# Deprecation shim behavior
# ============================================================
class TestDeprecationShim:
    """The unprefixed names on decision_policy are kept as
    deprecated aliases for one release. They MUST emit
    DeprecationWarning on access (so call sites get a
    nudge) and return the same value as the prefixed name."""

    def test_unprefixed_name_emits_warning(self):
        import scripts.blackboard.decision_policy as dp
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            val = dp.AUTO_ACCEPT_THRESHOLD
        deprecation = [
            x for x in w if issubclass(x.category, DeprecationWarning)
        ]
        assert len(deprecation) >= 1, \
            "expected DeprecationWarning when accessing legacy name"
        assert "AUTO_ACCEPT_THRESHOLD" in str(deprecation[0].message)
        # Returns the canonical value
        assert val == sc.FAG_AUTO_ACCEPT_THRESHOLD

    def test_unprefixed_no_death_emits_warning(self):
        import scripts.blackboard.decision_policy as dp
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            val = dp.AUTO_ACCEPT_THRESHOLD_NO_DEATH
        deprecation = [
            x for x in w if issubclass(x.category, DeprecationWarning)
        ]
        assert len(deprecation) >= 1
        assert val == sc.FAG_AUTO_ACCEPT_THRESHOLD_NO_DEATH

    def test_unprefixed_gap_emits_warning(self):
        import scripts.blackboard.decision_policy as dp
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            val = dp.AUTO_ACCEPT_GAP
        deprecation = [
            x for x in w if issubclass(x.category, DeprecationWarning)
        ]
        assert len(deprecation) >= 1
        assert val == sc.FAG_AUTO_ACCEPT_GAP

    def test_unknown_name_raises_attribute_error(self):
        """The PEP 562 __getattr__ falls through to AttributeError
        for names that aren't in the legacy map."""
        import scripts.blackboard.decision_policy as dp
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            with pytest.raises(AttributeError, match="no attribute"):
                dp.NO_SUCH_THING
