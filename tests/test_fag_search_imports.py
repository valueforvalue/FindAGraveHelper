"""Regression test for issue #12: scripts/fag/search.py references
undefined S_NO_RESULTS + S_ERROR after the T008 split.

The fix: add S_NO_RESULTS + S_ERROR to the import block from
scripts.fag.filters (lines 71-73).
"""
from pathlib import Path

import pytest

from scripts.fag import search as fag_search


def test_search_module_imports_without_name_error():
    """Importing scripts.fag.search should not leak NameError at
    runtime when search helpers are called."""
    # Sanity: the constants resolve through the module's namespace
    assert hasattr(fag_search, "S_NO_RESULTS"), \
        "S_NO_RESULTS missing from scripts.fag.search namespace (issue #12)"
    assert hasattr(fag_search, "S_ERROR"), \
        "S_ERROR missing from scripts.fag.search namespace (issue #12)"
    # S_CAPTCHA + S_SKIP are FaG-internal signals used locally in
    # search.py (not canonical PensionerRecord.status values).
    # The canonical STATUS_* values live in
    # scripts.pipeline.scoring_constants and are imported from
    # there as needed (issue #31).
    for name in ("S_NO_RESULTS", "S_ERROR", "S_CAPTCHA", "S_SKIP"):
        assert hasattr(fag_search, name), \
            f"{name} missing from scripts.fag.search namespace"
    assert fag_search.S_NO_RESULTS == "no_results"
    assert fag_search.S_ERROR == "error"
    assert fag_search.S_CAPTCHA == "captcha"


def test_search_module_no_undefined_names_at_module_level():
    """Source-level check: any reference to S_NO_RESULTS or S_ERROR
    in scripts/fag/search.py must come AFTER the import block that
    binds those names."""
    import re
    src = Path(fag_search.__file__).read_text(encoding="utf-8")
    # Find the import-from-filters block; names bound by it must
    # include S_NO_RESULTS + S_ERROR.
    m = re.search(
        r"from\s+scripts\.fag\.filters\s+import\s+\(([^)]+)\)",
        src, re.DOTALL,
    )
    assert m, "no `from scripts.fag.filters import (...)` block found"
    imports_block = m.group(1)
    for name in ("S_NO_RESULTS", "S_ERROR"):
        assert re.search(rf"\b{name}\b", imports_block), (
            f"{name} not imported from scripts.fag.filters (issue #12)"
        )

# ============================================================
# Issue #31: S_AUTO_ACCEPT / S_AMBIGUOUS / S_TOO_MANY in
# fag/search.py are dead constants (defined, never used in the
# file). They duplicate scoring_constants.STATUS_* values. The
# right fix is to delete the dead locals and rely on the
# canonical module. S_CAPTCHA and S_SKIP are still used locally
# (different concept from STATUS_*, kept).
# ============================================================
class TestFagSearchConstantsCleanup:
    """The FaG-search layer should not re-declare canonical
    STATUS_* values. The dead constants in scripts/fag/search.py
    were a redundant copy of scoring_constants."""

    def test_dead_status_constants_are_gone(self):
        import scripts.fag.search as fs
        # These three are dead in scripts/fag/search.py and were
        # duplicates of scoring_constants.STATUS_*. After #31
        # they must be removed from the file.
        for name in ("S_AUTO_ACCEPT", "S_AMBIGUOUS", "S_TOO_MANY"):
            assert not hasattr(fs, name), (
                f"scripts.fag.search.{name} is dead code "
                f"(use scripts.pipeline.scoring_constants.STATUS_* instead)"
            )

    def test_local_only_constants_still_exist(self):
        """S_CAPTCHA and S_SKIP are FAG-internal signal values
        (not canonical PensionerRecord.status values) and are
        used locally in this file. They must remain."""
        import scripts.fag.search as fs
        assert hasattr(fs, "S_CAPTCHA")
        assert hasattr(fs, "S_SKIP")

    def test_canonical_status_imports_work(self):
        """The canonical STATUS_* constants must be importable
        from scoring_constants and match the wire-format values
        that used to be duplicated in fag/search.py."""
        from scripts.pipeline.scoring_constants import (
            STATUS_AUTO_ACCEPT,
            STATUS_AMBIGUOUS,
            STATUS_TOO_MANY,
        )
        assert STATUS_AUTO_ACCEPT == "auto_accept"
        assert STATUS_AMBIGUOUS == "ambiguous"
        assert STATUS_TOO_MANY == "too_many"
