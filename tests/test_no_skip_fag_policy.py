"""Regression tests for unconditional FaG search policy.

CGR evidence annotates pensioners; it never gates FaG search.
"""


def test_removed_skip_policy_stays_out_of_pipeline_contract():
    """Obsolete skip controls stay absent from canonical Python seam."""
    from scripts.pipeline import core

    assert not hasattr(core, "should_skip_fag")
    assert "skip_fag_on_strong_cgr" not in core.UnifiedConfig.__dataclass_fields__
    assert "cgr_skipped_fag" not in core.PipelineResult.__dataclass_fields__

    result = core.UnifiedRunResult(
        pensioner={
            "id": 1,
            "first_name": "X",
            "middle_name": "",
            "last_name": "Y",
            "regiment": "",
            "death_year": "",
        }
    )
    assert "cgr_skipped_fag" not in result.to_dict()


def test_view_html_no_skipped_badge():
    """Review UI must not surface obsolete skip-FaG policy."""
    from pathlib import Path

    view_html = (Path("scripts") / "view.html").read_text(encoding="utf-8")
    assert "FaG skipped" not in view_html
    assert "cgr_skipped_fag" not in view_html
