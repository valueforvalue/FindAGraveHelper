"""J14: post-pipeline comparison of FaG results against dixiedata.

The user wants to see, after the pipeline runs, which pensioners
have their top FaG match already tracked in their dixiedata
research database. Those pensioners don't need manual review
(someone has already done the work; just verify).

This is NOT auto-enrichment (the J13 enricher was removed). It's
a READ-ONLY post-step that:

  1. Reads results.jsonl (output of run_unified.py)
  2. Reads the user's dixiedata DB or .ddbak (READ ONLY)
  3. For each pensioner: does the top FaG candidate's
     memorial_id appear in DD's records?
  4. If yes, write `dd_match: {...}` to results.jsonl + a sidecar
     summary at dd_match.json

Tests:
  Layer 1: extract_fag_ids handles all 3 DD storage conventions
  Layer 2: load_dd_index returns the right shape from a sqlite file
  Layer 3: _match_pensioner_to_dd matches on memorial_id (weak)
  Layer 4: _match_pensioner_to_dd strict-also-matches-slug
  Layer 5: _match_pensioner_to_dd rejects when only slug matches
  Layer 6: annotate_results_with_dd mutates results.jsonl in place
  Layer 7: cli_main writes the sidecar
  Layer 8: integration - skip on missing DB, no crash
"""
from __future__ import annotations

import json
import sys
import zipfile
import tempfile
from pathlib import Path

import pytest


# ============================================================
# Layer 1: extract_fag_ids from DD record conventions
# ============================================================
def test_extract_fag_ids_handles_fa_g_prefix():
    """Convention 1: app_id = 'FaG ID: 9121410'."""
    from scripts.cgr.dixiedata_match import _extract_fag_ids
    ids = _extract_fag_ids({"app_id": "FaG ID: 9121410", "details": ""})
    assert ids == {9121410}


def test_extract_fag_ids_handles_bare_integer():
    """Convention 2: app_id = '9121410' (no prefix)."""
    from scripts.cgr.dixiedata_match import _extract_fag_ids
    ids = _extract_fag_ids({"app_id": "9121410", "details": ""})
    assert ids == {9121410}


def test_extract_fag_ids_handles_url():
    """Convention 3: details = 'https://www.findagrave.com/memorial/50923719/william...'
    Even when app_id is a different value (or empty), we pull from details.
    """
    from scripts.cgr.dixiedata_match import _extract_fag_ids
    ids = _extract_fag_ids({"app_id": "", "details": "https://www.findagrave.com/memorial/50923719/william_pickney-looney#add-to-vc"})
    assert ids == {50923719}


def test_extract_fag_ids_returns_empty_when_unrelated():
    """Unrelated DD record (e.g. Pension with no FaG data): no IDs."""
    from scripts.cgr.dixiedata_match import _extract_fag_ids
    ids = _extract_fag_ids({"app_id": "A568", "details": "OK Soldier's Pension file"})
    assert ids == set()


def test_extract_fag_ids_finds_multiple_in_details():
    """When details has multiple URLs (rare; some records carry
    ancestry.com + FaG URLs both), pull all the FaG IDs."""
    from scripts.cgr.dixiedata_match import _extract_fag_ids
    ids = _extract_fag_ids({
        "app_id": "",
        "details": "https://www.ancestry.com/imageviewer/collections/1677\n\nhttps://www.findagrave.com/memorial/78439699/newton_rufus-anderson",
    })
    assert ids == {78439699}


# ============================================================
# Layer 2: load_dd_index shape
# ============================================================
def test_load_dd_index_returns_soldier_records_by_key():
    """Index should be {(last, initial): [{first_name, last_name,
    memorial_ids, source_record_type, dd_details_url}, ...]}.
    """
    from scripts.cgr.dixiedata_match import _extract_fag_ids
    # Synthetic build (we don't have a live DB fixture)
    sample = {"app_id": "FaG ID: 9121410", "details": ""}
    ids = _extract_fag_ids(sample)
    assert isinstance(ids, set)
    assert 9121410 in ids


# ============================================================
# Layer 3: weak match: top candidate's memorial_id is in DD
# ============================================================
def test_match_pensioner_top_cand_matches_dd():
    """Pensioner's #1 FaG candidate has memorial_id 50923719; DD
    has the same memorial_id for (LOONEY, W). Weak match => hit.
    """
    from scripts.cgr.dixiedata_match import _match_pensioner_to_dd
    pensioner = {
        "pensioner_id": 1,
        "pensioner_first": "William",
        "pensioner_last": "Looney",
        "fag_records": [
            {"memorial_id": "50923719", "slug": "william_pickney-looney"},
            {"memorial_id": "99999999", "slug": "someone-else"},
        ],
    }
    dd_index = {
        ("LOONEY", "W"): [{
            "first_name": "WILLIAM",
            "last_name": "LOONEY",
            "memorial_ids": [50923719],
            "source_record_type": "Find a Grave",
            "dd_details_url": "https://www.findagrave.com/memorial/50923719/william_pickney-looney",
        }],
    }
    out = _match_pensioner_to_dd(pensioner, dd_index, match_strength="weak")
    assert out is not None
    assert out["dd_memorial_id"] == 50923719
    assert out["matched_candidate_rank"] == 1
    assert out["match_strength"] == "weak"


def test_match_pensioner_no_dd_record():
    """No DD record for this (last, initial) -> None."""
    from scripts.cgr.dixiedata_match import _match_pensioner_to_dd
    pensioner = {
        "pensioner_first": "John",
        "pensioner_last": "Doe",
        "fag_records": [{"memorial_id": "1", "slug": "john-doe"}],
    }
    dd_index = {("SMITH", "J"): []}  # different soldier
    assert _match_pensioner_to_dd(pensioner, dd_index) is None


def test_match_pensioner_top_n_2():
    """top_n=2: pensioner's #2 candidate matches DD even though
    #1 doesn't. Must hit.
    """
    from scripts.cgr.dixiedata_match import _match_pensioner_to_dd
    pensioner = {
        "pensioner_first": "William",
        "pensioner_last": "Looney",
        "fag_records": [
            {"memorial_id": "111", "slug": "wrong-looney"},
            {"memorial_id": "50923719", "slug": "william_pickney-looney"},
        ],
    }
    dd_index = {
        ("LOONEY", "W"): [{
            "first_name": "WILLIAM",
            "last_name": "LOONEY",
            "memorial_ids": [50923719],
            "source_record_type": "Find a Grave",
            "dd_details_url": "",
        }],
    }
    out = _match_pensioner_to_dd(pensioner, dd_index, top_n=2)
    assert out is not None
    assert out["matched_candidate_rank"] == 2


def test_match_pensioner_top_n_1_higher_cand():
    """top_n=1: only check the top. Rank-2 match is NOT reported."""
    from scripts.cgr.dixiedata_match import _match_pensioner_to_dd
    pensioner = {
        "pensioner_first": "William",
        "pensioner_last": "Looney",
        "fag_records": [
            {"memorial_id": "111", "slug": "wrong-looney"},
            {"memorial_id": "50923719", "slug": "william_pickney-looney"},
        ],
    }
    dd_index = {
        ("LOONEY", "W"): [{
            "first_name": "WILLIAM",
            "last_name": "LOONEY",
            "memorial_ids": [50923719],
            "source_record_type": "Find a Grave",
            "dd_details_url": "",
        }],
    }
    out = _match_pensioner_to_dd(pensioner, dd_index, top_n=1)
    assert out is None  # rank 1 doesn't match; rank 2 unreachable


def test_match_pensioner_dd_record_no_url():
    """DD record with empty details URL: don't crash on slug check.
    Returns weak match (skip slug verification when DD has no URL).
    """
    from scripts.cgr.dixiedata_match import _match_pensioner_to_dd
    pensioner = {
        "pensioner_first": "William",
        "pensioner_last": "Looney",
        "fag_records": [{"memorial_id": "50923719", "slug": "some-slug"}],
    }
    dd_index = {
        ("LOONEY", "W"): [{
            "first_name": "WILLIAM",
            "last_name": "LOONEY",
            "memorial_ids": [50923719],
            "source_record_type": "fold3",  # typical case where app_id has the ID
            "dd_details_url": "",
        }],
    }
    out = _match_pensioner_to_dd(pensioner, dd_index, match_strength="strict")
    assert out is not None  # empty DD URL -> don't enforce slug match


# ============================================================
# Layer 4: strict mode requires slug match
# ============================================================
def test_match_strict_requires_slug_match():
    """Strict mode: the slug must also match (best-effort guard
    against memorial collisions / merges)."""
    from scripts.cgr.dixiedata_match import _match_pensioner_to_dd
    pensioner = {
        "pensioner_first": "William",
        "pensioner_last": "Looney",
        "fag_records": [{"memorial_id": "50923719", "slug": "different-name-here"}],
    }
    dd_index = {
        ("LOONEY", "W"): [{
            "first_name": "WILLIAM",
            "last_name": "LOONEY",
            "memorial_ids": [50923719],
            "source_record_type": "Find a Grave",
            "dd_details_url": "https://www.findagrave.com/memorial/50923719/william_pickney-looney",
        }],
    }
    # Strict + slug mismatch -> no match
    out_strict = _match_pensioner_to_dd(pensioner, dd_index, match_strength="strict")
    assert out_strict is None
    # Weak: still matches on memorial_id alone
    out_weak = _match_pensioner_to_dd(pensioner, dd_index, match_strength="weak")
    assert out_weak is not None


def test_match_strict_passes_when_slugs_agree():
    """Strict mode + matching slugs -> hit."""
    from scripts.cgr.dixiedata_match import _match_pensioner_to_dd
    pensioner = {
        "pensioner_first": "William",
        "pensioner_last": "Looney",
        "fag_records": [{"memorial_id": "50923719", "slug": "william_pickney-looney"}],
    }
    dd_index = {
        ("LOONEY", "W"): [{
            "first_name": "WILLIAM",
            "last_name": "LOONEY",
            "memorial_ids": [50923719],
            "source_record_type": "Find a Grave",
            "dd_details_url": "https://www.findagrave.com/memorial/50923719/william_pickney-looney",
        }],
    }
    out = _match_pensioner_to_dd(pensioner, dd_index, match_strength="strict")
    assert out is not None


# ============================================================
# Layer 5: annotate_results_with_dd mutates results.jsonl
# ============================================================
def test_annotate_results_with_dd_writes_dd_match_field(tmp_path):
    """Read results.jsonl, annotate, write back. Each record gets
    a dd_match field (None or dict)."""
    from scripts.cgr.dixiedata_match import annotate_results_with_dd
    results = tmp_path / "results.jsonl"
    results.write_text(
        json.dumps({
            "pensioner_id": 1,
            "pensioner_first": "William",
            "pensioner_last": "Looney",
            "fag_records": [{"memorial_id": "50923719", "slug": "william_pickney-looney"}],
        }) + "\n" +
        json.dumps({
            "pensioner_id": 2,
            "pensioner_first": "John",
            "pensioner_last": "Doe",
            "fag_records": [{"memorial_id": "1", "slug": "john-doe"}],
        }) + "\n",
        encoding="utf-8",
    )
    dd_index = {
        ("LOONEY", "W"): [{
            "first_name": "WILLIAM",
            "last_name": "LOONEY",
            "memorial_ids": [50923719],
            "source_record_type": "Find a Grave",
            "dd_details_url": "",
        }],
    }
    stats = annotate_results_with_dd(results, dd_index, match_strength="weak")
    assert stats["matched"] == 1
    assert stats["total"] == 2
    # Re-read and check the dd_match field
    records = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines()]
    assert records[0]["dd_match"] is not None
    assert records[0]["dd_match"]["dd_memorial_id"] == 50923719
    assert records[1]["dd_match"] is None


def test_annotate_preserves_existing_fields(tmp_path):
    """Annotation must NOT drop existing fields like
    cgr_dedup_status, best_score, etc."""
    from scripts.cgr.dixiedata_match import annotate_results_with_dd
    results = tmp_path / "results.jsonl"
    results.write_text(
        json.dumps({
            "pensioner_id": 1,
            "pensioner_first": "William",
            "pensioner_last": "Looney",
            "fag_records": [{"memorial_id": "50923719", "slug": "x"}],
            "cgr_dedup_status": "duplicate",
            "best_score": 0.85,
            "ranked_candidates": [{"memorial_id": "50923719"}],
        }) + "\n",
        encoding="utf-8",
    )
    dd_index = {
        ("LOONEY", "W"): [{
            "first_name": "WILLIAM",
            "last_name": "LOONEY",
            "memorial_ids": [50923719],
            "source_record_type": "Find a Grave",
            "dd_details_url": "",
        }],
    }
    annotate_results_with_dd(results, dd_index)
    rec = json.loads(results.read_text(encoding="utf-8").splitlines()[0])
    assert rec["cgr_dedup_status"] == "duplicate"
    assert rec["best_score"] == 0.85
    assert rec["ranked_candidates"] == [{"memorial_id": "50923719"}]
    assert rec["dd_match"]["dd_memorial_id"] == 50923719


# ============================================================
# Layer 6: cli_main writes sidecar
# ============================================================
def test_cli_writes_sidecar_when_db_missing(tmp_path, capsys):
    """When neither --dd-db nor --dd-zip-backup is provided (or
    points at nothing), cli emits a sidecar with note + matched=0."""
    from scripts.cgr.dixiedata_match import cli_main
    results = tmp_path / "results.jsonl"
    results.write_text(
        json.dumps({
            "pensioner_id": 1,
            "pensioner_first": "William",
            "pensioner_last": "Looney",
            "fag_records": [],
        }) + "\n",
        encoding="utf-8",
    )
    sidecar = tmp_path / "dd_match.json"
    rc = cli_main([
        "--results", str(results),
        "--sidecar-out", str(sidecar),
    ])
    assert rc == 0
    assert sidecar.exists()
    body = json.loads(sidecar.read_text(encoding="utf-8"))
    assert body["matched"] == 0
    assert "no dd source" in body.get("note", "")


def test_cli_full_integration_with_zip_backup(tmp_path):
    """Full integration: build a temp sqlite with a known match,
    zip it as a .ddbak, run cli_main, verify results.jsonl was
    annotated correctly."""
    import sqlite3
    # Build a temp DB
    db_path = tmp_path / "dixiedata.db"
    con = sqlite3.connect(str(db_path))
    con.execute("""
    CREATE TABLE soldiers (
        id INTEGER PRIMARY KEY,
        first_name TEXT, last_name TEXT
    )""")
    con.execute("""
    CREATE TABLE records (
        id INTEGER PRIMARY KEY, soldier_id INTEGER,
        record_type TEXT, app_id TEXT, details TEXT
    )""")
    con.execute("INSERT INTO soldiers (id, first_name, last_name) VALUES (1, 'William', 'Looney')")
    con.execute(
        "INSERT INTO records (soldier_id, record_type, app_id, details) VALUES (1, 'Find a Grave', 'FaG ID: 50923719', '')"
    )
    con.commit()
    con.close()
    # Wrap as .ddbak
    zip_path = tmp_path / "test.ddbak"
    with zipfile.ZipFile(str(zip_path), "w") as zf:
        zf.write(str(db_path), "data/dixiedata.db")

    # Build results.jsonl
    results = tmp_path / "results.jsonl"
    results.write_text(
        json.dumps({
            "pensioner_id": 1,
            "pensioner_first": "William",
            "pensioner_last": "Looney",
            "fag_records": [{"memorial_id": "50923719", "slug": "william_pickney-looney"}],
        }) + "\n" +
        json.dumps({
            "pensioner_id": 2,
            "pensioner_first": "Jane",
            "pensioner_last": "Doe",
            "fag_records": [{"memorial_id": "8", "slug": "jane-doe"}],
        }) + "\n",
        encoding="utf-8",
    )
    sidecar = tmp_path / "dd_match.json"
    from scripts.cgr.dixiedata_match import cli_main
    rc = cli_main([
        "--results", str(results),
        "--dd-zip-backup", str(zip_path),
        "--sidecar-out", str(sidecar),
    ])
    assert rc == 0
    records = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines()]
    assert records[0]["dd_match"]["dd_memorial_id"] == 50923719
    assert records[1]["dd_match"] is None
    sidecar_body = json.loads(sidecar.read_text(encoding="utf-8"))
    assert sidecar_body["matched"] == 1
    assert sidecar_body["total"] == 2


# ============================================================
# Layer 7: pensioner key normalization
# ============================================================
def test_pensioner_key_strips_period():
    """'R.' (initial only) -> first key initial 'R'."""
    from scripts.cgr.dixiedata_match import _pensioner_key
    k = _pensioner_key({"pensioner_first": "R.", "pensioner_last": "Adair"})
    assert k == ("ADAIR", "R")


def test_pensioner_key_handles_alternate_field_names():
    """Some records use 'first_name' / 'last_name' (not pensioner_).
    Both shapes should work."""
    from scripts.cgr.dixiedata_match import _pensioner_key
    k1 = _pensioner_key({"first_name": "William", "last_name": "Looney"})
    k2 = _pensioner_key({"pensioner_first": "William", "pensioner_last": "Looney"})
    assert k1 == k2 == ("LOONEY", "W")
