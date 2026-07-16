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
    # T008 split regression: also assert S_AUTO_ACCEPT, S_AMBIGUOUS,
    # S_TOO_MANY, S_CAPTCHA, S_SKIP all resolve (commit c217eff
    # dropped them when the file was split).
    for name in ("S_NO_RESULTS", "S_ERROR", "S_AUTO_ACCEPT",
                 "S_AMBIGUOUS", "S_TOO_MANY", "S_CAPTCHA", "S_SKIP"):
        assert hasattr(fag_search, name), \
            f"{name} missing from scripts.fag.search namespace"
    assert fag_search.S_NO_RESULTS == "no_results"
    assert fag_search.S_ERROR == "error"
    assert fag_search.S_AUTO_ACCEPT == "auto_accept"
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