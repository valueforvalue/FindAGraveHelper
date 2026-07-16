"""Regression tests for the POLICY-LOCKED 2026-07-16 decision:

We ALWAYS run FaG for every pensioner. The CGR blocking index
exists only to annotate matches for human display and post-run
dedup work; it MUST NOT gate whether we search FaG.

These tests pin that contract. If a future change re-introduces
a skip-on-CGR-strong gate, these tests fail.

See scripts/pipeline/core.py module docstring 'DECISION POLICY'.
"""
import pytest


def test_should_skip_fag_function_removed():
    """should_skip_fag() must not exist — it was a would-be skip
    predicate marked POLICY-LOCKED and never wired in."""
    from scripts.pipeline import core as core_mod
    assert not hasattr(core_mod, "should_skip_fag"), (
        "should_skip_fag() must be removed. The policy locks the "
        "FaG search as unconditional; re-introducing this function "
        "risks accidentally re-wiring the skip path. See "
        "scripts/pipeline/core.py 'DECISION POLICY (LOCKED 2026-07-16)'."
    )


def test_unified_config_skip_field_removed():
    """UnifiedConfig.skip_fag_on_strong_cgr must not exist."""
    from scripts.pipeline.core import UnifiedConfig
    assert "skip_fag_on_strong_cgr" not in UnifiedConfig.__dataclass_fields__, (
        "UnifiedConfig.skip_fag_on_strong_cgr must be removed. The "
        "field was dead code (marked POLICY-LOCKED) and risks being "
        "honored by a future change."
    )


def test_pipeline_result_cgr_skipped_fag_removed():
    """PipelineResult.cgr_skipped_fag must not exist in the DTO."""
    from scripts.pipeline.core import PipelineResult
    # dataclass fields() lists the canonical set
    assert "cgr_skipped_fag" not in PipelineResult.__dataclass_fields__, (
        "PipelineResult.cgr_skipped_fag must be removed. The field "
        "represented a behavior that was deliberately disabled by "
        "policy; carrying it forward invites re-use."
    )


def test_pipeline_result_to_dict_no_cgr_skipped_fag():
    """UnifiedRunResult.to_dict() output must not contain cgr_skipped_fag."""
    from scripts.pipeline.core import UnifiedRunResult
    pensioner = {
        "id": 1, "first_name": "X", "last_name": "Y",
        "middle_name": "", "regiment": "", "death_year": "",
    }
    pr = UnifiedRunResult(pensioner=pensioner)
    d = pr.to_dict()
    assert "cgr_skipped_fag" not in d, (
        f"UnifiedRunResult.to_dict() emitted cgr_skipped_fag={d.get('cgr_skipped_fag')!r}; "
        "field must be removed entirely."
    )


def test_state_normalize_drops_cgr_skipped_fag():
    """state_normalize.py must not reference cgr_skipped_fag."""
    from scripts import state_normalize
    # The module's source must not contain the string as an identifier
    import inspect
    src = inspect.getsource(state_normalize)
    assert "cgr_skipped_fag" not in src, (
        "state_normalize.py still references cgr_skipped_fag; remove "
        "all references since the field is gone from the DTO."
    )


def test_view_html_no_skipped_badge():
    """view.html must not render a 'FaG skipped — CGR strong match'
    badge since the condition never fires."""
    from pathlib import Path
    view_html = (Path("scripts") / "view.html").read_text(encoding="utf-8")
    assert "FaG skipped" not in view_html, (
        "view.html still renders a 'FaG skipped' badge for cgr_skipped_fag; "
        "remove it (the condition never fires; see policy)."
    )
    assert "cgr_skipped_fag" not in view_html, (
        "view.html still references cgr_skipped_fag; remove all references."
    )


def test_test_unified_runner_skip_tests_removed():
    """tests/test_unified_runner.py must not contain tests that assert
    the skip behavior."""
    from pathlib import Path
    test_src = (Path("tests") / "test_unified_runner.py").read_text(encoding="utf-8")
    # The old tests asserted skip behavior (test_should_skip_fag_*,
    # test_unified_result_cgr_strong_skips_fag). These pins inverted
    # the policy and must be removed.
    forbidden_substrings = [
        "test_should_skip_fag_strong_match",
        "test_should_skip_fag_medium_match",
        "test_should_skip_fag_weak_match",
        "test_should_skip_fag_no_match",
        "test_should_skip_fag_multiple_strong",
        "test_unified_result_cgr_strong_skips_fag",
        "skip_fag_on_strong_cgr=True",
    ]
    for substr in forbidden_substrings:
        assert substr not in test_src, (
            f"tests/test_unified_runner.py still has forbidden token {substr!r}. "
            "These tests pin the disabled-by-policy skip behavior and must be removed."
        )