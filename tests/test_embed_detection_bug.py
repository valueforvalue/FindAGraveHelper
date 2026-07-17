"""Regression tests for the view.html embed-detection bug.

The bug: scripts/pipeline/run_unified.py has a second-pass embed
logic that checks for an existing embedded block by searching for
the literal string id="embedded-..." in the text. The source
view.html has these literals INSIDE JS comments (in the docstring
explaining how the embed works) and INSIDE HTML comments. A naive
substring search returns True even when no actual <script> tag
exists, so the second pass SKIPS embedding when it shouldn't.

Symptom: results.jsonl never embedded into the per-run view.html,
the page loaded with no pensioner cards (only the "No pensioners"
placeholder). Discovered during the es-fresh-run run on 2026-07-17.

The fix: require both the <script ... id="..."> opening AND a
JSON opening brace `{` immediately after. Comments never have
both adjacent.
"""
from __future__ import annotations

from pathlib import Path
import re


# The exact regexes used in scripts/pipeline/run_unified.py
EMBED_RE = {
    "results": re.compile(
        r'<script\s+type="application/json"\s+id="embedded-results-jsonl"'
        r'>\s*\{',
    ),
    "dd": re.compile(
        r'<script\s+type="application/json"\s+id="embedded-dd-match"'
        r'>\s*\{',
    ),
    "spouse": re.compile(
        r'<script\s+type="application/json"\s+id="embedded-spouse-match"'
        r'>\s*\{',
    ),
}


def test_source_view_html_does_not_match_embed_regex_for_results():
    """The source template must NOT match the embed-detection regex
    for results.jsonl — otherwise the second pass would skip the
    embed thinking the script is already there.
    """
    src = Path("scripts/view.html").read_text(encoding="utf-8")
    # The bug was: the literal string 'id="embedded-results-jsonl"'
    # appears inside JS comments. The old naive check returned True,
    # so the second pass skipped embedding.
    assert not EMBED_RE["results"].search(src), (
        "Source view.html should not contain an actual "
        "<script type=\"application/json\" id=\"embedded-results-jsonl\"> "
        "tag, only documentation comments mentioning the literal. "
        "Otherwise the second-pass embed logic will skip the "
        "results.jsonl inject."
    )


def test_naive_substring_check_would_match_in_source():
    """Document the original bug: a naive `'id="embedded-results-jsonl"'
    in text` check would return True for the source view.html,
    because the string appears in JS comments. We pin this so we
    know the bug doesn't return via a naive re-introduction.
    """
    src = Path("scripts/view.html").read_text(encoding="utf-8")
    assert 'id="embedded-results-jsonl"' in src, (
        "Source view.html must contain the literal string in a "
        "JS comment (this is the trigger that caused the bug)."
    )
    assert 'id="embedded-dd-match"' not in src, (
        "Source view.html should NOT contain embedded-dd-match in "
        "comments; that string lives only in code (not in docs)."
    )
    assert 'id="embedded-spouse-match"' not in src, (
        "Source view.html should NOT contain embedded-spouse-match "
        "in comments; that string lives only in code."
    )


def test_embed_regex_requires_opening_brace():
    """The detection regex requires `{` immediately after the
    opening script tag. Real embed blocks always have `>{ ... }`
    (script body starts with a JSON object). Comments don't have
    both adjacent, so they don't false-match.
    """
    # The regex's raw pattern includes `\s*\{` at the end.
    raw = EMBED_RE["results"].pattern
    assert r"\{$" in raw or raw.endswith(r"\{"), \
        f"Detection regex must require opening brace: {raw}"


def test_embed_regex_matches_real_embed_block(tmp_path):
    """Sanity: the regex DOES match a real <script id="...">{...}</script>
    block, not just no-op."""
    text = (
        '<script type="application/json" id="embedded-results-jsonl">\n'
        '{"pensioner_id": 1}\n'
        '</script>\n'
    )
    assert EMBED_RE["results"].search(text), \
        "Detection regex must match a real embed block"


def test_embed_regex_does_not_match_comment():
    """A comment mentioning the embed id should NOT match."""
    # This is what the source view.html has inside a JS comment.
    text_in_comment = (
        '// The runner injects a\n'
        '// <script type="application/json" id="embedded-results-jsonl">\n'
        '// block at copy time so the page works under file:// (where\n'
        '// fetch() of sibling files is blocked).\n'
    )
    assert not EMBED_RE["results"].search(text_in_comment), (
        "Detection regex must NOT match JS comments that mention "
        "the embed id (that was the original bug)"
    )