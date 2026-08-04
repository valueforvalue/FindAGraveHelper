"""Property-based tests for parser boilerplate filter + merge.

Covers:
- _strip_fag_boilerplate: idempotent, no boilerplate survives
- _merge_candidates: no duplicate IDs, highest score wins
- apply_location_filter: locationId always present
"""
from __future__ import annotations

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck

from scripts.fag.parser import _strip_fag_boilerplate, _FAG_BOILERPLATE_STRS
from scripts.fag.filters import apply_location_filter
from scripts.search.engine import _merge_candidates


# ── Property 1: _strip_fag_boilerplate is idempotent ──────────


@given(text=st.text(max_size=500))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_strip_boilerplate_idempotent(text: str):
    """Stripping twice must equal stripping once."""
    once = _strip_fag_boilerplate(text)
    twice = _strip_fag_boilerplate(once)
    assert once == twice, (
        f"Idempotent violation:\n  once: {once!r}\n  twice: {twice!r}"
    )


# ── Property 2: no boilerplate string survives ───────────────


@given(text=st.text(max_size=200))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_no_boilerplate_survives(text: str):
    """After stripping, no known boilerplate string appears in the result."""
    result = _strip_fag_boilerplate(text)
    result_lower = result.lower()
    for boilerplate in _FAG_BOILERPLATE_STRS:
        assert boilerplate.lower() not in result_lower, (
            f"'{boilerplate}' survived in: {result!r}"
        )


# ── Property 3: normal text passes through untouched ────────


@given(
    first=st.text(
        min_size=1, max_size=20,
        alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    ),
    last=st.text(
        min_size=1, max_size=20,
        alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    ),
)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_normal_names_pass_through(first: str, last: str):
    """Normal name text must not be altered by the filter.

    Note: the alphabet is restricted to plain letters and the
    test asserts each token appears in the result. As of
    2026-07-25, _FAG_BOILERPLATE_STRS includes short tokens
    like 'HONORING' that are also real names (e.g. memorial
    for "HONORING John Smith"). For those cases, the filter
    strips the tribute header correctly. This property test
    documents the simpler case: tokens that are NOT in the
    boilerplate list pass through.
    """
    
    bp_lower = {b.lower() for b in _FAG_BOILERPLATE_STRS}
    if first.lower() in bp_lower or last.lower() in bp_lower:
        return
    text = f"{first} {last}"
    result = _strip_fag_boilerplate(text)
    assert first in result, f"'{first}' lost from: {result!r}"
    assert last in result, f"'{last}' lost from: {result!r}"


@given(
    boilerplate=st.sampled_from(
        ["HONORING", "IN MEMORY OF", "IN LOVING MEMORY OF",
         "IN HONOR OF", "REST IN PEACE", "Flowers have been left"]
    ),
    real_name=st.text(
        min_size=2, max_size=20,
        alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    ),
)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_boilerplate_phrase_stripped(boilerplate: str, real_name: str):
    """Tribute headers and FaG display noise MUST be stripped
    by the filter (commit eec6865 added HONORING/IN MEMORY OF
    etc.; this property documents the strip guarantee).
    """
    
    bp_lower = {b.lower() for b in _FAG_BOILERPLATE_STRS}
    if real_name.lower() in bp_lower:
        return
    text = f"{boilerplate} {real_name}"
    result = _strip_fag_boilerplate(text)
    assert boilerplate not in result, (
        f"'{boilerplate}' survived in: {result!r}"
    )
    assert real_name in result, (
        f"'{real_name}' lost when stripping '{boilerplate}': {result!r}"
    )


# ── Property 4: apply_location_filter always sets locationId ─


@given(
    state=st.sampled_from(["OK", "TX", "AR", "LA", "MS", "MO", "KS", ""]),
    extra_keys=st.dictionaries(
        keys=st.text(min_size=2, max_size=15, alphabet="abcdefghijklmnopqrstuvwxyz"),
        values=st.text(max_size=20),
        max_size=5,
    ),
)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_apply_location_filter_always_has_location(state: str, extra_keys: dict):
    """After applying location filter, the result always has a locationId
    or country_4 fallback. Empty state → country_4 (US).

    The state filter is a precision tool; we accept some recall loss
    for the precision gain. The full 575-record probe (issue #137
    follow-up) showed that lifting the country_4 fallback for the
    empty-state edge case recovers only 0.2% of records.
    """
    params = {"firstname": "John", "lastname": "Smith", **extra_keys}
    result = apply_location_filter(params, state)
    has_location = "locationId" in result
    assert has_location, (
        f"No locationId in result for state={state!r}: {result}"
    )


# ── Property 5: location filter preserves original params ────


@given(
    state=st.sampled_from(["OK", "TX", "US", ""]),
    first=st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz"),
    last=st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz"),
)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_location_filter_preserves_params(state: str, first: str, last: str):
    """Applying location filter must not drop or alter existing params."""
    params = {"firstname": first, "lastname": last, "exactspelling": "true"}
    result = apply_location_filter(params, state)
    assert result["firstname"] == first
    assert result["lastname"] == last
    assert result["exactspelling"] == "true"


# ── Property 6: _merge_candidates no duplicate IDs ───────────


@given(n=st.integers(min_value=0, max_value=20))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_merge_candidates_no_duplicates(n: int):
    """After merging, no memorial_id appears more than once."""
    if n == 0:
        assert _merge_candidates(None, []) == []
        return

    # Build strategy runs with some intentional duplicates
    class FakeEngine:
        pass

    engine = FakeEngine()
    runs = []
    for i in range(min(n, 5)):
        cands = [
            {"id": str(j % max(1, n // 2 + 1)), "memorial_id": str(j % max(1, n // 2 + 1)),
             "score": float(j % 3) * 0.3, "name": f"candidate{j}"}
            for j in range(i, i + 3)
        ]
        runs.append((f"strategy{i}", cands))

    merged = _merge_candidates(engine, runs)
    ids = [c.get("id") or c.get("memorial_id") for c in merged]
    assert len(ids) == len(set(ids)), (
        f"Duplicate IDs in merge: {ids}"
    )


# ── Property 7: _merge_candidates keeps highest score ────────


@given(seed=st.integers(min_value=0, max_value=100))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_merge_keeps_highest_score(seed: int):
    """When same ID appears in multiple strategies, highest score wins."""
    class FakeEngine:
        pass

    engine = FakeEngine()
    runs = [
        ("s1", [{"id": "1", "score": 0.50, "name": "low"}]),
        ("s2", [{"id": "1", "score": 0.95, "name": "high"}]),
        ("s3", [{"id": "1", "score": 0.30, "name": "lower"}]),
    ]
    merged = _merge_candidates(engine, runs)
    assert len(merged) == 1
    # Convergence bonus: 3 strategies → +10%, 0.95*1.10=1.045, cap 1.0
    assert merged[0]["score"] == 1.0, (
        f"Expected 1.0 (0.95 + convergence bonus capped), got {merged[0]['score']}"
    )
    assert merged[0]["name"] == "high"
    assert merged[0].get("found_by") == "s2", (
        f"found_by should be s2 (highest score), got {merged[0].get('found_by')}"
    )
    assert merged[0]["convergence_count"] == 3
    assert len(merged[0]["found_by_strategies"]) == 3
