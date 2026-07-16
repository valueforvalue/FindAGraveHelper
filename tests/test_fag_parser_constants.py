"""Regression test for the T008 split (commit c217eff): scripts/fag/parser.py
references _MEMORIAL_PATH_RE and DATE_RANGE_RE that were never migrated
when the file was extracted from scripts/search_fag.py.
"""
from scripts.fag import parser as fag_parser


def test_parser_module_exposes_regex_constants():
    """The pre-split regexes must be defined at module level so the
    parser functions can resolve them at call time."""
    assert hasattr(fag_parser, "_MEMORIAL_PATH_RE"), \
        "_MEMORIAL_PATH_RE missing from scripts.fag.parser (T008 regression)"
    assert hasattr(fag_parser, "DATE_RANGE_RE"), \
        "DATE_RANGE_RE missing from scripts.fag.parser (T008 regression)"
    # Sanity: they actually compile and match canonical FaG paths
    m = fag_parser._MEMORIAL_PATH_RE.search(
        'href="/memorial/50923719/william-pickney-looney"'
    )
    assert m is not None
    assert m.group(2) == "50923719"
    assert m.group(3) == "william-pickney-looney"
    # DATE_RANGE_RE matches "1907-1910" or "1907\u20131910"
    assert fag_parser.DATE_RANGE_RE.search("1907-1910") is not None
    assert fag_parser.DATE_RANGE_RE.search("1907\u20131910") is not None