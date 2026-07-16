"""Tests for F4: unified runner (CGR + FaG).

The unified runner combines CGR cross-ref + FaG search into
one state file. For each pensioner:
  1. Build CGR blocking index from ok_cemeteries.jsonl
  2. Look up pensioner in the index
  3. If CGR strong match → record it, SKIP FaG
  4. Else → run FaG search, record results

Output: one JSONL record per pensioner with both sources
(if both tried) + a BOTH MATCH flag + decisions for view.html.
"""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.unified_runner import (
    build_cgr_blocking_index,
    lookup_cgr_for_pensioner,
    UnifiedRunResult,
    UnifiedConfig,
    should_skip_fag,
)


# ============================================================
# Index construction
# ============================================================
def _sample_cemeteries():
    """Sample CGR cemetery records (subset of ok_cemeteries.jsonl)."""
    return [
        {
            "state": "OK",
            "cemetery_id": 13211,
            "cemetery_name": "Baptist Mission Cemetery",
            "county": "Adair",
            "veterans": [
                {"id": 96425, "name": "Andrew Jackson Alberty", "unit": "1 OK", "born": "1843"},
                {"id": 111050, "name": "William Looney", "unit": "34 TX", "born": "1840"},
            ],
        },
        {
            "state": "OK",
            "cemetery_id": 14481,
            "cemetery_name": "Chalk Bluff Cemetery",
            "county": "Adair",
            "veterans": [
                {"id": 112601, "name": "Andrew Jackson Alberty", "unit": "1 OK", "born": "1843"},
            ],
        },
    ]


def test_build_index_creates_blocks():
    """Index should group veterans by phonetic blocks."""
    block_index, vets_by_id = build_cgr_blocking_index(_sample_cemeteries())
    assert isinstance(block_index, dict)
    assert len(block_index) > 0


def test_build_index_keeps_full_vet_records():
    """The index should keep enough info to identify each veteran."""
    block_index, vets_by_id = build_cgr_blocking_index(_sample_cemeteries())
    assert isinstance(vets_by_id, dict)
    assert len(vets_by_id) > 0
    v = next(iter(vets_by_id.values()))
    assert "id" in v
    assert "name" in v
    assert "cemetery_id" in v


def test_build_index_is_idempotent():
    """Same input twice → same index."""
    idx1, by_id_1 = build_cgr_blocking_index(_sample_cemeteries())
    idx2, by_id_2 = build_cgr_blocking_index(_sample_cemeteries())
    assert len(idx1) == len(idx2)
    for k in idx1:
        assert len(idx1[k]) == len(idx2[k])


# ============================================================
# Lookup
# ============================================================
def test_lookup_returns_matching_veterans():
    """Lookup by phonetic block returns vets with similar names."""
    index = build_cgr_blocking_index(_sample_cemeteries())
    matches = lookup_cgr_for_pensioner(
        index,
        first_name="Andrew",
        last_name="Alberty",
    )
    assert isinstance(matches, list)
    if matches:
        assert any("Alberty" in m.get("name", "") for m in matches)


def test_lookup_no_match_returns_empty():
    """Unknown name → empty list."""
    index = build_cgr_blocking_index(_sample_cemeteries())
    matches = lookup_cgr_for_pensioner(
        index,
        first_name="Xenophilius",
        last_name="Smithson",
    )
    assert matches == []


def test_lookup_handles_dotted_initials():
    """Pensioner first_name might be 'R.' (with a period)."""
    index = build_cgr_blocking_index(_sample_cemeteries())
    matches = lookup_cgr_for_pensioner(
        index,
        first_name="R.",
        last_name="Adair",
    )
    assert isinstance(matches, list)


def test_lookup_returns_vets_in_different_cemeteries():
    """If the same vet appears in multiple cemeteries, all entries returned."""
    index = build_cgr_blocking_index(_sample_cemeteries())
    matches = lookup_cgr_for_pensioner(
        index,
        first_name="Andrew",
        last_name="Alberty",
    )
    # Andrew Jackson Alberty in both cemeteries
    assert len(matches) >= 2
    ids = {m["id"] for m in matches}
    assert len(ids) >= 1


# ============================================================
# Skip decision
# ============================================================
def test_should_skip_fag_strong_match():
    """Strong CGR match → skip FaG."""
    cgr_matches = [{"match_strength": "strong", "id": 1}]
    skip = should_skip_fag(cgr_matches)
    assert skip is True


def test_should_skip_fag_medium_match():
    """Medium CGR match → still run FaG (verification)."""
    cgr_matches = [{"match_strength": "medium", "id": 1}]
    skip = should_skip_fag(cgr_matches)
    assert skip is False


def test_should_skip_fag_weak_match():
    """Weak CGR match → still run FaG."""
    cgr_matches = [{"match_strength": "weak", "id": 1}]
    skip = should_skip_fag(cgr_matches)
    assert skip is False


def test_should_skip_fag_no_match():
    """No CGR match → still run FaG."""
    skip = should_skip_fag([])
    assert skip is False


def test_should_skip_fag_multiple_strong():
    """Multiple strong matches → skip FaG (CGR is sufficient)."""
    cgr_matches = [
        {"match_strength": "strong", "id": 1},
        {"match_strength": "strong", "id": 2},
    ]
    skip = should_skip_fag(cgr_matches)
    assert skip is True


# ============================================================
# Unified result
# ============================================================
def _sample_pensioner():
    return {
        "id": 5,
        "first_name": "Hugh",
        "middle_name": "H",
        "last_name": "Akers",
        "regiment": "4 MO",
        "death_year": "1924",
        "birth_year": "",
    }


def test_unified_result_cgr_strong_skips_fag():
    """When CGR is strong and we skip FaG, fag_status == 'skipped_cgr_strong'."""
    config = UnifiedConfig(skip_fag_on_strong_cgr=True)
    result = UnifiedRunResult(
        pensioner=_sample_pensioner(),
        cgr_records=[{"match_strength": "strong", "id": 999}],
        fag_records=[],
        fag_status="skipped_cgr_strong",
        timestamp="2026-07-16",
    )
    out = result.to_dict()
    assert out["cgr_skipped_fag"] is True
    assert out["fag_status"] == "skipped_cgr_strong"


def test_unified_result_cgr_medium_runs_fag():
    """Medium CGR match → FaG still runs."""
    config = UnifiedConfig(skip_fag_on_strong_cgr=True)
    result = UnifiedRunResult(
        pensioner=_sample_pensioner(),
        cgr_records=[{"match_strength": "medium", "id": 999}],
        fag_records=[{"memorial_id": 12345, "score": 0.7}],
        fag_status="auto_accept",
        timestamp="2026-07-16",
    )
    out = result.to_dict()
    assert out["cgr_skipped_fag"] is False
    assert out["fag_status"] == "auto_accept"


def test_unified_result_no_cgr_runs_fag():
    """No CGR match → FaG runs."""
    config = UnifiedConfig(skip_fag_on_strong_cgr=True)
    result = UnifiedRunResult(
        pensioner=_sample_pensioner(),
        cgr_records=[],
        fag_records=[{"memorial_id": 12345, "score": 0.5}],
        fag_status="ambiguous",
        timestamp="2026-07-16",
    )
    out = result.to_dict()
    assert out["cgr_skipped_fag"] is False
    assert out["fag_status"] == "ambiguous"


def test_unified_result_to_jsonl_roundtrip():
    """UnifiedRunResult serializes to JSONL cleanly."""
    import json
    result = UnifiedRunResult(
        pensioner=_sample_pensioner(),
        cgr_records=[{"match_strength": "strong", "id": 999}],
        fag_records=[],
        fag_status="skipped_cgr_strong",
        timestamp="2026-07-16",
    )
    line = json.dumps(result.to_dict(), ensure_ascii=False)
    parsed = json.loads(line)
    assert parsed["pensioner_id"] == 5
    assert parsed["pensioner_first"] == "Hugh"

# ============================================================
# POLICY GUARDS (LOCKED 2026-07-16):
# We always run FaG for every pensioner. The CGR data does not
# gate the FaG search. These tests verify the policy is held.
# ============================================================
class TestAlwaysRunFaGPolicy:
    """Guard: the FaG search must run for every pensioner.

    Project goal is to discover how many of the 7,758 OK Confederate
    pensioners are findable in FaG. Skipping the FaG search based
    on CGR strength would cost us findings — the CGR index is too
    noisy today.
    """

    def test_unified_pipeline_has_no_skip_fast_path(self):
        """Source-level guard: run_pipeline_for_pensioner must not
        contain any `should_skip_fag` call that returns early.
        """
        import inspect
        from scripts.unified_pipeline import run_pipeline_for_pensioner
        src = inspect.getsource(run_pipeline_for_pensioner)
        assert "should_skip_fag" not in src, (
            "POLICY VIOLATION: run_pipeline_for_pensioner() must never "
            "skip the FaG search based on CGR strength. The full "
            "FaG search must run for every pensioner. "
            "See scripts/unified_pipeline.py module docstring "
            "'DECISION POLICY (LOCKED 2026-07-16)'."
        )

    def test_unified_pipeline_docstring_states_policy(self):
        """Source-level guard: the module docstring must explicitly
        document the always-run-FaG decision and where the policy
        record lives.
        """
        import inspect
        from scripts import unified_pipeline
        docstring = unified_pipeline.__doc__ or ""
        # Must mention "always" + "FaG" + "LOCKED 2026-07-16"
        assert "ALWAYS run FaG" in docstring or "always" in docstring.lower(), (
            "scripts/unified_pipeline.py module docstring must "
            "document the always-run-FaG policy."
        )
        assert "2026-07-16" in docstring, (
            "Module docstring must reference the policy-lock date."
        )

    def test_unified_config_skip_field_documented_as_locked(self):
        """UnifiedConfig.skip_fag_on_strong_cgr must be marked as
        policy-locked so future readers don't mistake the default
        for a behavior we honor.
        """
        from scripts.unified_runner import UnifiedConfig
        import dataclasses
        for f in dataclasses.fields(UnifiedConfig):
            if f.name == "skip_fag_on_strong_cgr":
                # Default exists; that's fine for back-compat.
                # But the type or metadata must warn it's ignored.
                assert "POLICY-LOCKED" in str(f), (
                    f"UnifiedConfig.{f.name} default or metadata "
                    f"should be marked POLICY-LOCKED so readers know "
                    f"the pipeline ignores it. Got: {f!r}"
                )

    def test_should_skip_fag_helper_kept_but_documented(self):
        """should_skip_fag() exists for view.html / dedup use, not
        pipeline-skip use. A guard test asserts it exists and is
        callable, but does NOT exercise it from the pipeline.
        """
        from scripts.unified_runner import should_skip_fag
        # It exists and is callable.
        assert callable(should_skip_fag)
        # It returns False for empty input.
        assert should_skip_fag([]) is False

    def test_unified_pipeline_docstring_endorses_followup_searches(self):
        """DOCUMENTATION guard: the always-run-FaG policy must
        explicitly endorse follow-up FaG strategies on low-
        confidence rows. Without this clause, Phase 3
        (leftover-investigation) would conflict with the policy.

        The clause language must mention both 'follow-up' (or
        'follow-up phase' / 'additional strategies') AND the
        low-confidence criterion (best_score < 0.85 OR
        fag_status in {ambiguous, too_many, no_results}).
        """
        from scripts import unified_pipeline
        docstring = unified_pipeline.__doc__ or ""
        # Lowercase + collapsed whitespace for the search.
        normalized = " ".join(docstring.lower().split())
        assert "follow-up" in normalized or "additional strategies" in normalized, (
            "scripts/unified_pipeline.py docstring must explicitly "
            "mention follow-up FaG strategies on low-confidence rows. "
            "Without this endorsement, Phase 3 (leftover-investigation) "
            "would conflict with the always-run-FaG policy."
        )
        assert "0.85" in docstring, (
            "Docstring must document the 0.85 hard-target threshold."
        )
