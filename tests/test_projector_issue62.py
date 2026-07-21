"""Tests for issue #62: v2 view regressions — pension cards, FaG
links, pensioner JSON info.

The Blackboard projector was emitting a minimal record
(pensioner_id, status, best_score, ranked_candidates) that
missed every v2 field:
- pensioner_first / middle / last / app_number / birth/death
- pensioncard_backlink / pensioncard_pages / pensioncard_iiif_url
- pensioner_spouse_first / middle / last
- candidate backlink / iiif_url
The candidate shape from the engine path uses `url` (canonical)
where v1 + v2 normalizeRecord expect `backlink`. Both keys
must be on the row so v2 renders links + pension card
preview.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.blackboard.projector import (
    ProjectionBuilder,
    _normalize_candidate,
)


# ============================================================
# Candidate normalization: url / backlink / iiif_url
# ============================================================


def test_normalize_candidate_promotes_url_to_backlink():
    """Engine-path candidates use `url`; v2 view reads
    `backlink`. Both must be on the row.
    """
    c = {"memorial_id": "12345", "url": "https://www.findagrave.com/memorial/12345/x"}
    out = _normalize_candidate(c)
    assert out["url"] == c["url"]
    assert out["backlink"] == c["url"]


def test_normalize_candidate_promotes_backlink_to_url():
    """Legacy candidates used `backlink`; the common-candidate
    projection reads `url`. Both must be on the row.
    """
    c = {"memorial_id": "12345", "backlink": "https://www.findagrave.com/memorial/12345/x"}
    out = _normalize_candidate(c)
    assert out["backlink"] == c["backlink"]
    assert out["url"] == c["backlink"]


def test_normalize_candidate_synthesizes_iiif_url():
    """When neither `iiif_url` nor `media.image_url` is set,
    build one from `memorial_id` (FaG IIIF pattern).
    """
    c = {"memorial_id": "12345", "name": "x"}
    out = _normalize_candidate(c)
    expected = (
        "https://www.findagrave.com/iiif/2/"
        "memorial:12345/full/full/0/default.jpg"
    )
    assert out["iiif_url"] == expected
    assert out["media"]["image_url"] == expected


def test_normalize_candidate_preserves_existing_iiif_url():
    """Don't overwrite an existing iiif_url / media.image_url."""
    c = {
        "memorial_id": "12345",
        "iiif_url": "https://existing.example/x",
        "media": {"image_url": "https://other.example/x"},
    }
    out = _normalize_candidate(c)
    assert out["iiif_url"] == "https://existing.example/x"


# ============================================================
# Projector row: pensioner fields
# ============================================================


def _sample_pensioner() -> dict:
    return {
        "id": 272,
        "first_name": "Nancy",
        "middle_name": "A.",
        "last_name": "Eads",
        "application_number": "A5678",
        "pensioncard_backlink": "https://digitalprairie.ok.gov/digital/singleitem/collection/pensioncard/id/11486",
        "pensioncard_iiif_url": "https://digitalprairie.ok.gov/iiif/2/pensioncard:11486/full/full/0/default.jpg",
        "spouse_first_name": "James",
        "spouse_last_name": "Eads",
        "regiment": "CSA",
        "company": "A",
        "all_fields": {},
        "pensioncard_all_fields": {},
        "backlink": "https://digitalprairie.ok.gov/digital/singleitem/collection/pensions/id/272",
    }


def test_projector_writes_v1_pensioner_field_names():
    """v2 view reads pensioner_first / middle / last / app_number
    / birth_year / death_year / pensioncard_backlink /
    pensioncard_iiif_url / pensioner_spouse_first / middle / last
    / backlink off the state.jsonl row. Projector must populate
    all of them from the input pensioner dict.
    """
    builder = ProjectionBuilder(policy_version="1")
    row = builder.build_state_row(
        pensioner_id=272,
        pensioner_data=_sample_pensioner(),
        candidates=[],
    )
    assert row["pensioner_first"] == "Nancy"
    assert row["pensioner_middle"] == "A."
    assert row["pensioner_last"] == "Eads"
    assert row["pensioner_app_number"] == "A5678"
    assert row["pensioncard_backlink"] == (
        "https://digitalprairie.ok.gov/digital/singleitem/"
        "collection/pensioncard/id/11486"
    )
    assert row["pensioncard_iiif_url"] == (
        "https://digitalprairie.ok.gov/iiif/2/"
        "pensioncard:11486/full/full/0/default.jpg"
    )
    assert row["pensioner_spouse_first"] == "James"
    assert row["pensioner_spouse_last"] == "Eads"
    assert row["backlink"] == (
        "https://digitalprairie.ok.gov/digital/singleitem/"
        "collection/pensions/id/272"
    )


# ============================================================
# Projector row: candidate fields (backlink + iiif_url)
# ============================================================


def test_projector_normalizes_engine_candidates_to_legacy_shape():
    """Engine path emits `url`; projector must also write
    `backlink` and `iiif_url` so v2 view's normalizeRecord
    legacy path can render FaG links + thumbnails.
    """
    builder = ProjectionBuilder(policy_version="1")
    row = builder.build_state_row(
        pensioner_id=272,
        pensioner_data=_sample_pensioner(),
        candidates=[
            {
                "memorial_id": "14994932",
                "slug": "nancy-alice-eads",
                "name": "Nancy Alice Haynes Eads",
                "score": 0.445,
                "url": "https://www.findagrave.com/memorial/14994932/nancy-alice-eads",
            }
        ],
    )
    c = row["ranked_candidates"][0]
    # Engine path: only `url` set; projector promotes to both
    assert c["url"] == "https://www.findagrave.com/memorial/14994932/nancy-alice-eads"
    assert c["backlink"] == "https://www.findagrave.com/memorial/14994932/nancy-alice-eads"
    # iiif_url synthesized from memorial_id
    assert c["iiif_url"] == (
        "https://www.findagrave.com/iiif/2/memorial:14994932/full/full/0/default.jpg"
    )
    # common projection also has media.image_url
    assert row["common"]["candidates"][0]["media"]["image_url"] == c["iiif_url"]


# ============================================================
# Round-trip: projector output renders in v2 normalizeRecord
# ============================================================


def test_projector_output_has_all_fields_v2_normalize_needs():
    """v2 view's normalizeRecord reads pensioner_first,
    pensioncard_backlink, pensioncard_pages, etc. directly
    from the row. Verify the projector output dict has them
    so v2's normalizeRecord legacy path surfaces them.
    """
    builder = ProjectionBuilder(policy_version="1")
    # Inject pensioncard_pages via the sidecar simulation:
    # the scheduler path adds this after build_state_row, so
    # the projector doesn't need to.
    row = builder.build_state_row(
        pensioner_id=272,
        pensioner_data=_sample_pensioner(),
        candidates=[
            {
                "memorial_id": "14994932",
                "name": "x",
                "score": 0.5,
                "url": "https://www.findagrave.com/memorial/14994932/x",
            }
        ],
    )
    row["pensioncard_pages"] = [11484, 11485]
    serialized = json.dumps(row, default=str)

    # All the keys v2 normalizeRecord legacy path reads must
    # round-trip through JSON.
    must_have = [
        "pensioner_first",
        "pensioner_middle",
        "pensioner_last",
        "pensioner_app_number",
        "pensioncard_backlink",
        "pensioncard_iiif_url",
        "pensioncard_pages",
        "pensioner_spouse_first",
        "pensioner_spouse_last",
        "backlink",
    ]
    for k in must_have:
        assert k in serialized, f"missing {k!r} in projector row"
    # pensioner_birth_year / death_year / spouse_middle are
    # absent on OK pensioners; the projector must NOT write
    # them as empty strings (would force v2 to render blanks).
    assert row["pensioner_first"] == "Nancy"
    assert row["pensioncard_pages"] == [11484, 11485]