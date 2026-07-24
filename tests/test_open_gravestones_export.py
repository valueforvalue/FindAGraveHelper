"""Tests for the open-burial-data export (#95).

The export emits one JSON-LD record per matched pensioner, with
a `@context` that bundles:

  - Schema.org/Cemetery (https://schema.org/Cemetery)
  - Schema.org/Person (https://schema.org/Person)
  - Dublin Core terms (dcterms)
  - WikiTree profile ID (Trtnik-2 / WikiTree+ tool convention)
  - Wikidata Q-items
  - W3C PROV-DM provenance (prov:Entity / prov:Activity / prov:Agent)

Pin:
  - One record per matched pensioner; NDJSON format.
  - @context declares all six vocabularies; @type is a schema:Person.
  - The WikiTree link column is populated when a match is found.
  - The FaG memorial URL is preserved as sameAs (Schema.org
    convention for "see also" external identifiers).
  - PROV-DM links each row back to the Blackboard Activity and
    the policy_version Agent that produced its decision.
  - Rows with status=no_candidates OR no rank-1 candidate are
    still emitted (the export is the audit trail, not just the
    successful subset).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.exports.open_gravestones import (
    OpenGravestonesConfig,
    build_record,
    run,
)


class _NullLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


# ============================================================
# Helpers
# ============================================================


def _row(
    pid: int = 1,
    *,
    status: str = "auto_accept",
    best_score: float = 0.92,
    rank1: dict | None = None,
    policy_version: str = "1",
    schema_version: int = 2,
) -> dict:
    """Build a minimal state.jsonl row fixture."""
    return {
        "pensioner_id": pid,
        "pensioner_name": "Doe, John",
        "status": status,
        "best_score": best_score,
        "ranked_candidates": [rank1] if rank1 else [],
        "fag_records": [rank1] if rank1 else [],
        "pensioner_first": "John",
        "pensioner_middle": "Q",
        "pensioner_last": "Doe",
        "pensioner_app_number": "12345",
        "pensioner_birth_year": 1840,
        "pensioner_death_year": 1920,
        "regiment": "1st Texas Infantry",
        "company": "A",
        "pensioncard_backlink": "https://digitalprairie.ok.gov/card/12345",
        "pensioner_spouse_first": "Mary",
        "pensioner_spouse_last": "Doe",
        "_policy_version": policy_version,
        "_schema_version": schema_version,
    }


def _rank1_candidate(memorial_id: str = "98765", score: float = 0.92) -> dict:
    """Build a minimal FaG candidate with a memorial_id + URL."""
    return {
        "memorial_id": memorial_id,
        "slug": "john-q-doe",
        "name": "John Q. Doe",
        "score": score,
        "backlink": f"https://www.findagrave.com/memorial/{memorial_id}",
        "url": f"https://www.findagrave.com/memorial/{memorial_id}",
    }


# ============================================================
# build_record unit tests
# ============================================================


def test_build_record_emits_jsonld_context():
    """The exported record's @context declares all six vocabularies."""
    row = _row(rank1=_rank1_candidate())
    rec = build_record(row, source_policy_version="1", run_id="r1")
    assert "@context" in rec
    ctx = rec["@context"]
    # Schema.org
    assert "schema" in ctx
    assert ctx["schema"] == "https://schema.org/"
    # Dublin Core
    assert "dcterms" in ctx
    # WikiTree
    assert "wikitree" in ctx
    # Wikidata
    assert "wd" in ctx
    # PROV-DM
    assert "prov" in ctx
    assert ctx["prov"] == "http://www.w3.org/ns/prov#"


def test_build_record_type_is_schema_person():
    """A pensioner record's @type is Person (the deceased).

    JSON-LD compact form: the @context declares `Person` as a
    compact alias for `schema:Person`, so the @type value is the
    short form.
    """
    row = _row(rank1=_rank1_candidate())
    rec = build_record(row, source_policy_version="1", run_id="r1")
    assert rec["@type"] == "Person"


def test_build_record_includes_fag_sameas():
    """The FaG memorial URL is preserved as schema:sameAs."""
    row = _row(rank1=_rank1_candidate(memorial_id="98765"))
    rec = build_record(row, source_policy_version="1", run_id="r1")
    assert "sameAs" in rec
    assert "https://www.findagrave.com/memorial/98765" in rec["sameAs"]


def test_build_record_includes_provenance():
    """Each record carries PROV-DM wasGeneratedBy + agent refs."""
    row = _row(rank1=_rank1_candidate(), policy_version="1")
    rec = build_record(row, source_policy_version="1", run_id="r1")
    # PROV-DM: wasGeneratedBy
    assert "prov:wasGeneratedBy" in rec
    assert rec["prov:wasGeneratedBy"] == "run:r1"
    # PROV-DM: wasAttributedTo (the policy that decided the verdict)
    assert "prov:wasAttributedTo" in rec
    assert rec["prov:wasAttributedTo"] == "policy:v1"


def test_build_record_includes_dublin_core_metadata():
    """Dublin Core terms for archival metadata."""
    row = _row(rank1=_rank1_candidate())
    rec = build_record(row, source_policy_version="1", run_id="r1")
    # dcterms:identifier (pensioner_app_number)
    assert rec["dcterms:identifier"] == "12345"
    # dcterms:title (pensioner_name)
    assert rec["dcterms:title"] == "Doe, John"
    # dcterms:source (pensioncard_backlink)
    assert rec["dcterms:source"] == "https://digitalprairie.ok.gov/card/12345"


def test_build_record_wikitree_link():
    """WikiTree link column populated when a wikitree_id is supplied."""
    row = _row(rank1=_rank1_candidate())
    rec = build_record(
        row,
        source_policy_version="1",
        run_id="r1",
        wikitree_id="Doe-123",
    )
    assert "wikitree:profile" in rec
    assert rec["wikitree:profile"] == "https://www.wikitree.com/wiki/Doe-123"


def test_build_record_no_wikitree_when_absent():
    """No wikitree_id → no wikitree:profile key in the record."""
    row = _row(rank1=_rank1_candidate())
    rec = build_record(row, source_policy_version="1", run_id="r1")
    assert "wikitree:profile" not in rec


def test_build_record_wikidata_qid():
    """Wikidata Q-item link is preserved when supplied.

    The export uses the full Wikidata URL form (CURIE-safe in
    JSON-LD without needing a @context entry). The wd: prefix
    is also declared in the @context for consumers that prefer
    the compact form.
    """
    row = _row(rank1=_rank1_candidate())
    rec = build_record(
        row,
        source_policy_version="1",
        run_id="r1",
        wikidata_qid="Q12345",
    )
    # The full URL form is emitted (CURIE-safe for any consumer).
    assert "http://www.wikidata.org/entity/Q12345" in rec["sameAs"]


# ============================================================
# run() integration
# ============================================================


def test_run_emits_ndjson_file(tmp_path: Path):
    """run() writes one JSON-LD record per row to the target NDJSON."""
    state_path = tmp_path / "state.jsonl"
    state_path.write_text(
        json.dumps(_row(pid=1, rank1=_rank1_candidate())) + "\n"
        + json.dumps(_row(pid=2, status="low_score", best_score=0.3)) + "\n",
        encoding="utf-8",
    )
    target = tmp_path / "open_gravestones.ndjson"
    config = OpenGravestonesConfig(state_path=state_path, target_path=target)

    stats = run(config=config, run_id="r1", log=_NullLogger())

    assert stats.name == "open_gravestones"
    assert stats.matched == 2
    assert target.exists()
    lines = [
        json.loads(l) for l in target.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    assert len(lines) == 2


def test_run_handles_missing_state_file(tmp_path: Path):
    """Missing state file → skipped=True, no error."""
    config = OpenGravestonesConfig(
        state_path=tmp_path / "nonexistent.jsonl",
        target_path=tmp_path / "out.ndjson",
    )
    stats = run(config=config, run_id="r1", log=_NullLogger())
    assert stats.skipped is True
    assert not (tmp_path / "out.ndjson").exists()


def test_run_handles_corrupt_line_non_fatal(tmp_path: Path):
    """A corrupt JSON line is logged + skipped, not fatal."""
    state_path = tmp_path / "state.jsonl"
    state_path.write_text(
        json.dumps(_row(pid=1, rank1=_rank1_candidate())) + "\n"
        + "{not valid json\n"
        + json.dumps(_row(pid=2, rank1=_rank1_candidate())) + "\n",
        encoding="utf-8",
    )
    target = tmp_path / "out.ndjson"
    config = OpenGravestonesConfig(state_path=state_path, target_path=target)
    stats = run(config=config, run_id="r1", log=_NullLogger())
    # 2 valid rows emitted; corrupt line skipped.
    assert stats.matched == 2
    assert stats.errors >= 1


def test_run_includes_no_candidate_rows(tmp_path: Path):
    """The export is the audit trail; rows with no candidates are
    still emitted (so the consumer can see what was searched)."""
    state_path = tmp_path / "state.jsonl"
    state_path.write_text(
        json.dumps(_row(pid=1, status="no_candidates", best_score=0.0)) + "\n",
        encoding="utf-8",
    )
    target = tmp_path / "out.ndjson"
    config = OpenGravestonesConfig(state_path=state_path, target_path=target)
    run(config=config, run_id="r1", log=_NullLogger())
    lines = [
        json.loads(l) for l in target.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    assert len(lines) == 1
    assert "sameAs" not in lines[0]  # no FaG link since no candidate
    assert lines[0]["schema:status"] == "no_candidates"