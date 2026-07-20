"""Tests for scheduler/legacy smoke-diff harness configuration."""

import json

from scripts.smoke_diff import _run_legacy, _run_scheduler


def _fixtures(tmp_path):
    pensioners = tmp_path / "pensioners.json"
    pensioners.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "first_name": "John",
                    "last_name": "Smith",
                    "regiment": "5th Alabama",
                }
            ]
        ),
        encoding="utf-8",
    )
    cgr = tmp_path / "cgr.json"
    cgr.write_text("[]", encoding="utf-8")
    return pensioners, cgr


def test_smoke_diff_no_fag_runs_both_paths_without_browser(tmp_path, monkeypatch):
    pensioners, cgr = _fixtures(tmp_path)

    class ForbiddenBrowserSession:
        def __init__(self, **kwargs):
            raise AssertionError("BrowserSession started in no-FaG smoke run")

    monkeypatch.setattr(
        "scripts.fag.browser_session.BrowserSession", ForbiddenBrowserSession
    )

    scheduler_rows = _run_scheduler(
        pensioners, cgr, tmp_path / "scheduler", 1, None, False
    )
    legacy_rows = _run_legacy(
        pensioners, cgr, tmp_path / "legacy", 1, None, False
    )

    assert [row["pensioner_id"] for row in scheduler_rows] == [1]
    assert [row["pensioner_id"] for row in legacy_rows] == [1]
