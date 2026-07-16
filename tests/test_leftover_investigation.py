"""Tests for scripts/leftover_investigation.py (Phase 3).

Runs the orchestration in --no-fag mode so we don't need
Playwright/Chromium. The strategy parameter builders and the
trigger logic are exercised directly; the orchestration test
exercises state.jsonl read/write round-trip.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestTriggerLogic:
    def test_should_investigate_low_score_no_results(self):
        from scripts.leftover_investigation import should_investigate
        r = {"fag_status": "no_results", "best_score": 0.0}
        assert should_investigate(r) is True

    def test_should_investigate_low_score_ambiguous(self):
        from scripts.leftover_investigation import should_investigate
        r = {"fag_status": "ambiguous", "best_score": 0.6}
        assert should_investigate(r) is True

    def test_should_investigate_low_confidence_auto_accept(self):
        """Even auto_accepts with low scores get investigated."""
        from scripts.leftover_investigation import should_investigate
        r = {"fag_status": "auto_accept", "best_score": 0.7}
        assert should_investigate(r) is True

    def test_should_not_investigate_high_score_auto_accept(self):
        from scripts.leftover_investigation import should_investigate
        r = {"fag_status": "auto_accept", "best_score": 0.95}
        assert should_investigate(r) is False

    def test_should_not_investigate_error_status(self):
        """Errors are out of scope for Phase 3; retry_errors
        is the right tool for those."""
        from scripts.leftover_investigation import should_investigate
        r = {"fag_status": "error", "best_score": 0.0}
        assert should_investigate(r) is False

    def test_should_not_investigate_skip_status(self):
        from scripts.leftover_investigation import should_investigate
        r = {"fag_status": "skip", "best_score": 0.0}
        assert should_investigate(r) is False

    def test_score_threshold_matches_documented_value(self):
        from scripts.leftover_investigation import INVESTIGATE_BELOW_SCORE
        # Documentation anchor: the threshold must match what's in
        # the design doc.
        assert INVESTIGATE_BELOW_SCORE == 0.85


class TestStrategyParameterBuilders:
    def test_spouse_cross_search_requires_spouse_name(self):
        from scripts.pipeline.leftover_investigation import _spouse_cross_search_params
        # No spouse name -> None
        assert _spouse_cross_search_params({}, {}) is None
        # Only first name in spouse -> None (need last)
        pensioner = {"spouse_name": "Mary"}
        assert _spouse_cross_search_params(pensioner, {}) is None
        # Good
        pensioner = {"spouse_name": "Mary Smith"}
        params = _spouse_cross_search_params(pensioner, {})
        assert params["firstname"] == "Mary"
        assert params["lastname"] == "Smith"
        assert params["isVeteran"] == "true"

    def test_spouse_cross_search_with_partner_in_cgr(self):
        from scripts.pipeline.leftover_investigation import _spouse_cross_search_params
        pensioner = {"spouse_name": "Mary Smith"}
        cgr_row = {"spouse": "John Smith"}
        params = _spouse_cross_search_params(pensioner, cgr_row)
        assert params is not None
        # Both sides have spouse data; the strategy fires.
        assert "firstname" in params

    def test_birth_state_narrowing_requires_state(self):
        from scripts.pipeline.leftover_investigation import _birth_state_narrowing_params
        assert _birth_state_narrowing_params({}) is None
        assert _birth_state_narrowing_params({"birth_state": ""}) is None
        params = _birth_state_narrowing_params({
            "first_name": "Hugh", "last_name": "Akers",
            "birth_state": "VA",
        })
        assert "VA" in params["bio"]

    def test_regiment_bio_death_year_requires_both(self):
        from scripts.pipeline.leftover_investigation import _regiment_bio_death_year_params
        # No regiment
        assert _regiment_bio_death_year_params({}) is None
        # No death year
        assert _regiment_bio_death_year_params({
            "regiment": "1 TX",
        }) is None
        # Both present
        params = _regiment_bio_death_year_params({
            "first_name": "Hugh", "last_name": "Akers",
            "regiment": "1 TX", "death_year": "1920",
        })
        assert params["deathyear"] == "1920"
        assert params["deathyearfilter"] == "5"
        assert "Confederate" in params["bio"]

    def test_nickname_variants(self):
        from scripts.pipeline.leftover_investigation import _nickname_variants
        # Wm -> William
        assert "william" in _nickname_variants("Wm")
        # William -> Wm
        assert "wm" in _nickname_variants("William")
        # Unknown name -> empty
        assert _nickname_variants("XYZ") == []
        # Empty -> empty
        assert _nickname_variants("") == []


class TestRunInvestigationNoFaG:
    """End-to-end orchestration in --no-fag mode (no browser)."""

    def _fixtures(self, tmp_path):
        # Tiny state.jsonl + pensioners JSON
        state = [
            {"pensioner_id": 1, "fag_status": "no_results",
             "best_score": 0.0, "cgr_records": []},
            {"pensioner_id": 2, "fag_status": "auto_accept",
             "best_score": 0.95, "cgr_records": []},  # already conclusive
            {"pensioner_id": 3, "fag_status": "ambiguous",
             "best_score": 0.5, "cgr_records": [],
             "pensioner_name": "Test"},
            {"pensioner_id": 4, "fag_status": "error",
             "best_score": 0.0, "cgr_records": []},   # errors out of scope
        ]
        pensioners = [
            {"id": 1, "first_name": "X", "last_name": "Y"},
            {"id": 2, "first_name": "A", "last_name": "B"},
            {"id": 3, "first_name": "Wm", "last_name": "Smith"},
            {"id": 4, "first_name": "P", "last_name": "Q"},
        ]
        state_path = tmp_path / "state.jsonl"
        pensions_path = tmp_path / "ok.json"
        cgr_path = tmp_path / "cgr.json"
        with state_path.open("w", encoding="utf-8") as f:
            for r in state:
                f.write(json.dumps(r) + "\n")
        with pensions_path.open("w", encoding="utf-8") as f:
            json.dump(pensioners, f)
        # Empty dedup file is fine; Phase 3 proceeds without cgr data.
        cgr_path.write_text(json.dumps({"persons": {}, "cgr_id_to_person_id": {}}))
        return state_path, pensions_path, cgr_path

    def test_investigation_runs_in_no_fag_mode(self, tmp_path):
        sp, pp, cp = self._fixtures(tmp_path)
        from scripts.leftover_investigation import run_investigation
        summary = run_investigation(
            state_path=sp,
            pensioners_path=pp,
            cgr_dedup_path=cp,
            no_fag=True,
        )
        # Two records eligible: pid 1 and pid 3 (pid 2 is conclusive
        # already, pid 4 is error -> out of scope).
        assert summary["investigate_candidates"] == 2
        # Both get "skipped" disposition under --no-fag (no real
        # search was performed).
        # Pid 1 has no applicable strategies (no spouse, no state,
        # no nickname, no regiment+death).
        # Pid 3 has nickname "william" so it's eligible.
        disposition_by_pid = {}
        for line in (sp.parent / "leftover_investigation.jsonl").read_text(
                encoding="utf-8").splitlines():
            if line.strip():
                o = json.loads(line)
                disposition_by_pid[o["pensioner_id"]] = o["disposition"]
        # Pid 1: no strategies -> skipped (with strategies_run empty)
        assert disposition_by_pid[1] == "skipped"
        # Pid 3: nickname swap applicable -> 'skipped' under --no-fag
        # (we still record the strategies we'd have run).
        assert disposition_by_pid[3] == "skipped"
        assert summary["skipped_no_prereq"] >= 1
        # Strategy usage: pid 3 ran the nickname strategy
        assert summary["strategy_usage"].get("nickname_initial_swap", 0) >= 1

    def test_state_jsonl_round_trip_after_investigation(self, tmp_path):
        sp, pp, cp = self._fixtures(tmp_path)
        from scripts.leftover_investigation import run_investigation
        run_investigation(
            state_path=sp, pensioners_path=pp, cgr_dedup_path=cp,
            no_fag=True,
        )
        # Re-read state.jsonl and verify pid 1 and pid 3 have
        # leftover_pass annotations.
        with sp.open(encoding="utf-8") as f:
            out = [json.loads(line) for line in f if line.strip()]
        assert "leftover_pass" in next(r for r in out if r["pensioner_id"] == 1)
        assert "leftover_pass" in next(r for r in out if r["pensioner_id"] == 3)
        # Pid 2 (high score, not investigated) does NOT have leftover_pass.
        assert "leftover_pass" not in next(
            r for r in out if r["pensioner_id"] == 2
        )
        # Pid 4 (error status, out of scope) does NOT have leftover_pass.
        assert "leftover_pass" not in next(
            r for r in out if r["pensioner_id"] == 4
        )

    def test_summary_file_written(self, tmp_path):
        sp, pp, cp = self._fixtures(tmp_path)
        from scripts.leftover_investigation import run_investigation
        run_investigation(
            state_path=sp, pensioners_path=pp, cgr_dedup_path=cp,
            no_fag=True,
        )
        summary_path = sp.parent / "leftover_investigation_summary.json"
        assert summary_path.exists()
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert "investigate_candidates" in summary
        assert "strategy_usage" in summary


class TestPolicyAlignment:
    """Phase 3 must respect the always-run-FaG policy."""

    def test_module_docstring_states_policy_alignment(self):
        from scripts.pipeline import leftover_investigation
        docstring = leftover_investigation.__doc__ or ""
        assert "always-run-FaG" in docstring or "policy" in docstring.lower(), (
            "leftover_investigation.py module must reference the "
            "always-run-FaG policy that this phase implements."
        )

    def test_no_skip_fast_path(self):
        """No code path skips the strategies when conditions are met."""
        import inspect
        from scripts.pipeline import leftover_investigation
        src = inspect.getsource(leftover_investigation)
        # If a 'skip_fast_path' function or class appeared, that's
        # policy drift.
        assert "skip_fast_path" not in src
        assert "FAST_PATH" not in src.upper() or "FAST" not in src.upper().split(
            "FAST_PATH"
        )[0]  # tolerate the F-string "f"" mention

    def test_disposition_values_are_documented(self):
        """All disposition values must appear in the docstring so a
        reader of the output file knows what they mean.
        """
        from scripts.pipeline import leftover_investigation
        docstring = leftover_investigation.__doc__ or ""
        for d in ("found_conclusive", "no_fag_memorial", "skipped"):
            assert d in docstring, (
                f"Disposition '{d}' must be documented in the module "
                f"docstring."
            )
