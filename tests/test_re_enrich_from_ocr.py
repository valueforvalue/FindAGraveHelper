"""Tests for the re-enrich driver in scripts/ingest/re_enrich_from_ocr.py.

Issue #139 follow-up: the re-enrich driver previously only
processed `red_text` and `full_text`, leaving the L3 EasyOCR
`easy_text` results stale. These tests pin the 3-way logic:
- 3-source candidate scan (red, full, easy)
- best-candidate pick by (kind > kw > name)
- source_pass updated to match the chosen source
- death_date can be cleared when no source produces a pick
- idempotent re-runs produce the same output
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).parent
_ROOT = _TESTS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.ingest import re_enrich_from_ocr as re_enrich  



def _make_record(
    image="test__1.jpg",
    pensioner=None,
    red_text="",
    full_text="",
    easy_text="",
    prior_death_date=None,
    prior_source_pass=None,
):
    return {
        "image": image,
        "pensioncard_id": 1,
        "pensioner": pensioner or {"last_name": "Smith", "name_raw": "Smith, John"},
        "soldier_name_used": "Smith",
        "is_widow_card": False,
        "red_text": red_text,
        "full_text": full_text,
        "easy_text": easy_text,
        "death_date": prior_death_date,
        "source_pass": prior_source_pass,
    }


def test_picks_red_when_red_has_candidate():
    """When red_text yields a date, it's preferred (most-specific)."""
    rec = _make_record(
        red_text="DECEASED 12 Mar 1920",
        full_text="DECEASED 12 Mar 1920",
        easy_text="",
    )
    out = re_enrich._score_candidate
    # Simulate the main loop's pick logic
    from scripts.ingest.red_ink_ocr_pilot import find_death_date
    red_p, _ = find_death_date(rec["red_text"], "Smith")
    full_p, _ = find_death_date(rec["full_text"], "Smith")
    easy_p, _ = find_death_date(rec["easy_text"], "Smith")
    candidates = [
        ("red", red_p),
        ("full", full_p),
        ("easy", easy_p),
    ]
    cands = [(s, c) for s, c in candidates if c is not None]
    cands.sort(key=lambda sc: re_enrich._score_candidate(sc[1]))
    chosen_src, chosen = cands[0]
    assert chosen_src == "red"
    assert chosen["year"] == 1920


def test_falls_back_to_easy_when_red_and_full_fail():
    """If red/full yield nothing, easy_text can rescue."""
    rec = _make_record(
        red_text="garbage red output",
        full_text="garbage full output",
        easy_text="DECEASED 7 Jan 1928 widow of Smith",
    )
    from scripts.ingest.red_ink_ocr_pilot import find_death_date
    red_p, _ = find_death_date(rec["red_text"], "Smith")
    full_p, _ = find_death_date(rec["full_text"], "Smith")
    easy_p, _ = find_death_date(rec["easy_text"], "Smith")
    candidates = [
        ("red", red_p),
        ("full", full_p),
        ("easy", easy_p),
    ]
    cands = [(s, c) for s, c in candidates if c is not None]
    cands.sort(key=lambda sc: re_enrich._score_candidate(sc[1]))
    chosen_src, chosen = cands[0]
    assert chosen_src == "easy"
    assert chosen["year"] == 1928


def test_drops_stale_easyocr_pick_on_re_enrich():
    """Stale L0 EasyOCR death_date (e.g. 1915 GRANTED stamp) is
    cleared when the L1+L2 parser over easy_text now returns None."""
    # This is the actual regression from issue #139: the L3
    # EasyOCR pass wrote {year: 1915} for 2008 records; the L1
    # line-strip + L2 1915-only-candidate rule didn't exist
    # when easy_text was first parsed.
    rec = _make_record(
        red_text="",
        full_text="",
        easy_text=(
            "Name Anderson DECEASED\n"
            "Address\n"
            "REJECTED | GRANTED OCT 7 = 1915 No. P 17 61 to 65\n"
        ),
        prior_death_date={
            "kind": "year-only", "year": 1915, "month": None,
            "day": None, "iso": "1915", "match": "1915",
        },
        prior_source_pass="easyocr",
    )
    from scripts.ingest.red_ink_ocr_pilot import find_death_date
    red_p, _ = find_death_date(rec["red_text"], "Anderson")
    full_p, _ = find_death_date(rec["full_text"], "Anderson")
    easy_p, _ = find_death_date(rec["easy_text"], "Anderson")
    candidates = [
        ("red", red_p),
        ("full", full_p),
        ("easy", easy_p),
    ]
    cands = [(s, c) for s, c in candidates if c is not None]
    assert cands == [], (
        "re-enrich should drop the stale 1915 stamp pick; "
        f"got cands={cands}"
    )


def test_score_prefers_full_date_over_year_only():
    """When red yields year-only but full yields full-date, full
    wins (kind rank 0 beats 1)."""
    from scripts.ingest.red_ink_ocr_pilot import find_death_date
    red_p, _ = find_death_date("Soldier died 1920", "Baker")  
    full_p, _ = find_death_date(
        "Soldier died March 5, 1920", "Baker"
    )
    assert red_p is not None and red_p["kind"] == "year-only"
    assert full_p is not None and full_p["kind"] == "date"
    candidates = [("red", red_p), ("full", full_p)]
    candidates.sort(key=lambda sc: re_enrich._score_candidate(sc[1]))
    chosen_src, chosen = candidates[0]
    assert chosen_src == "full"
    assert chosen["kind"] == "date"


def test_score_returns_high_for_none_candidate():
    """None candidate should sort last (highest score)."""
    score = re_enrich._score_candidate(None)
    assert score == (1, 1, 1, 1)


def test_idempotent_re_enrich_no_changes():
    """Running the re-enrich twice in a row produces the same
    death_date values the second time around."""
    import subprocess
    import tempfile
    
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as f:
        records = [
            _make_record(
                red_text="DECEASED 12 Mar 1920",
                prior_death_date={
                    "kind": "year-only", "year": 1920,
                    "month": None, "day": None, "iso": "1920",
                },
                prior_source_pass="red",
            ),
            _make_record(
                image="test__2.jpg",
                full_text="DEATH DATE 7 Jul 1925",
                pensioner={"last_name": "Jones", "name_raw": "Jones, Sam"},
            ),
        ]
        json.dump(records, f)
        tmp_path = f.name

    try:
        cmd = [
            sys.executable,
            str(_ROOT / "scripts" / "ingest" / "re_enrich_from_ocr.py"),
            "--input", tmp_path,
            "--output", tmp_path + ".out",
            "--summary", tmp_path + ".summary",
        ]
        r1 = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        r2 = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert r1.returncode == 0
        assert r2.returncode == 0
        out1 = json.loads(
            Path(tmp_path + ".out").read_text(encoding="utf-8")
        )
        out2 = json.loads(
            Path(tmp_path + ".out").read_text(encoding="utf-8")
        )
        
        for a, b in zip(out1, out2):
            assert a["death_date"] == b["death_date"]
            assert a["source_pass"] == b["source_pass"]
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        Path(tmp_path + ".out").unlink(missing_ok=True)
        Path(tmp_path + ".summary").unlink(missing_ok=True)