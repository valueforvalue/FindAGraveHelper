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
    """Normal name text must not be altered by the filter."""
    text = f"{first} {last}"
    result = _strip_fag_boilerplate(text)
    assert first in result, f"'{first}' lost from: {result!r}"
    assert last in result, f"'{last}' lost from: {result!r}"


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
    or country_4 fallback. Empty state → country_4 (US)."""
    params = {"firstname": "John", "lastname": "Smith", **extra_keys}
    result = apply_location_filter(params, state)
    # Must have either a state locationId or country_4
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
    assert merged[0]["score"] == 0.95, (
        f"Expected highest score 0.95, got {merged[0]['score']}"
    )
    assert merged[0]["name"] == "high"
    assert merged[0].get("found_by") == "s2", (
        f"found_by should be s2 (highest score), got {merged[0].get('found_by')}"
    )
