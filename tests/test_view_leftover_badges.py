"""Tests for view.html's Phase 3 leftover-investigation badges.

view.html is a static HTML/JS file; the badges are computed from the
``leftover_pass`` field on each pensioner record. These tests
verify that the static file contains the expected CSS classes
and JS-side rendering logic for the three dispositions.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

VIEW_HTML = Path(__file__).parent.parent / "scripts" / "view.html"


def _view_html_text() -> str:
    return VIEW_HTML.read_text(encoding="utf-8")


class TestLeftoverBadgeCSS:
    """The CSS classes for the three dispositions must exist."""

    def test_lo_badge_base_class_present(self):
        text = _view_html_text()
        assert ".lo-badge" in text, (
            "view.html must define a .lo-badge base CSS class for "
            "Phase 3 leftover-investigation badges."
        )

    def test_found_conclusive_class_present(self):
        text = _view_html_text()
        assert ".lo-badge.found_conclusive" in text, (
            "view.html must define .lo-badge.found_conclusive."
        )

    def test_no_fag_memorial_class_present(self):
        text = _view_html_text()
        assert ".lo-badge.no_fag_memorial" in text, (
            "view.html must define .lo-badge.no_fag_memorial."
        )

    def test_skipped_class_present(self):
        text = _view_html_text()
        assert ".lo-badge.skipped" in text, (
            "view.html must define .lo-badge.skipped (when no "
            "applicable strategy)."
        )


class TestLeftoverBadgeRendering:
    """The JS-side rendering must read leftover_pass.disposition."""

    def test_renders_found_conclusive(self):
        text = _view_html_text()
        # Must read p.leftover_pass.disposition === 'found_conclusive'.
        assert re.search(
            r"leftover_pass[^\n]*disposition[^']*'found_conclusive'",
            text,
        ), "Found-conclusive badge render branch must exist in view.html"

    def test_renders_no_fag_memorial(self):
        text = _view_html_text()
        assert re.search(
            r"leftover_pass[^\n]*disposition[^']*'no_fag_memorial'",
            text,
        ), "no_fag_memorial badge render branch must exist in view.html"

    def test_renders_skipped(self):
        text = _view_html_text()
        assert re.search(
            r"leftover_pass[^\n]*disposition[^']*'skipped'",
            text,
        ), "skipped badge render branch must exist in view.html"


class TestPolicyAlignment:
    """view.html must not surface any \"skip FaG if CGR strong\" UI."""

    def test_no_skip_fast_path_ui(self):
        """A UI element promising to skip a pensioner's FaG search
        based on CGR strength would violate the always-run-FaG
        policy. Search for any such affordance.
        """
        text = _view_html_text().lower()
        # Look for any "skip if cgr" wording that isn't in a
        # comment/context-of-policy-doc.
        bad_patterns = [
            "skip if cgr",
            "skip cgr strong",
            "skip-fag",
            "skip_fag",
        ]
        for pat in bad_patterns:
            occurrences = text.count(pat)
            # If the CSS class cgr_skipped_fag shows up (it's a legacy
            # badge for the *decision*, not a search gate), it's OK
            # — but only as a label, never as a clickable skip.
            # We're strict: zero uncommented occurrences of skip-fast-path.
            for line in text.splitlines():
                if pat in line and not line.lstrip().startswith("//"):
                    if "skipped_fag_strong" in line.lower():
                        continue  # legacy badge label
                    if "skip fast path" in line.lower():
                        continue  # warning comment
                    if "would skip" in line.lower():
                        continue  # hypothetical comment
                    pytest.fail(
                        f"view.html contains skip-fast-path UI: "
                        f"'{line.strip()}'"
                    )
