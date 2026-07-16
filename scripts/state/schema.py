"""Typed dataclasses for the state.jsonl wire format.

T018 of the refactor. Each dataclass wraps a dict from the JSONL
wire format, providing type-checked field access while preserving
unknown fields in to_dict() so the schema can evolve without
silently stripping data.

Public API:
  - PensionerRecord, CandidateRecord, BothMatchRecord
  - from_dict_pensioner, from_dict_candidate, from_dict_both_match
  - SCHEMA_VERSION

Schema source of truth: docs/agents/cross-layer-contract.md
section "The wire format: state.jsonl".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

SCHEMA_VERSION = 1


# ============================================================
# CandidateRecord
# ============================================================
@dataclass
class CandidateRecord:
    """One FaG search result.

    Required: memorial_id.
    Common: slug, name, score, backlink, iiif_url, details, _found_by.
    """
    memorial_id: str = ""
    slug: str = ""
    name: str = ""
    score: float = 0.0
    backlink: str = ""
    # Extra fields not enumerated here live in `extras` and pass
    # through to_dict unchanged.
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        out = {
            "memorial_id": self.memorial_id,
            "slug": self.slug,
            "name": self.name,
            "score": self.score,
            "backlink": self.backlink,
        }
        out.update(self.extras)
        return out


def from_dict_candidate(d: dict) -> CandidateRecord:
    """dict -> CandidateRecord. Unknown fields land in `extras`."""
    known = {"memorial_id", "slug", "name", "score", "backlink"}
    extras = {k: v for k, v in d.items() if k not in known}
    return CandidateRecord(
        memorial_id=str(d.get("memorial_id", "") or ""),
        slug=str(d.get("slug", "") or ""),
        name=str(d.get("name", "") or ""),
        score=float(d.get("score", 0) or 0),
        backlink=str(d.get("backlink", "") or ""),
        extras=extras,
    )


# ============================================================
# BothMatchRecord
# ============================================================
@dataclass
class BothMatchRecord:
    """CGR + FaG corroboration verdict for one pensioner."""
    method: str = ""  # direct_link | corroboration | ""
    confidence: float = 0.0
    reason: str = ""
    fag_memorial_id: str = ""
    # Track which fields were explicitly present in the source dict so
    # to_dict can re-emit them faithfully (round-trip preservation).
    present: set = field(default_factory=set)
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        out: dict = {}
        if "method" in self.present:
            out["method"] = self.method
        if "confidence" in self.present:
            out["confidence"] = self.confidence
        if "reason" in self.present:
            out["reason"] = self.reason
        if "fag_memorial_id" in self.present:
            out["fag_memorial_id"] = self.fag_memorial_id
        out.update(self.extras)
        return out


def from_dict_both_match(d: dict) -> BothMatchRecord:
    """dict -> BothMatchRecord. Round-trip preserves present keys."""
    known = {"method", "confidence", "reason", "fag_memorial_id"}
    extras = {k: v for k, v in d.items() if k not in known}
    present = {k for k in d.keys() if k in known}
    return BothMatchRecord(
        method=str(d.get("method", "") or ""),
        confidence=float(d.get("confidence", 0) or 0),
        reason=str(d.get("reason", "") or ""),
        fag_memorial_id=str(d.get("fag_memorial_id", "") or ""),
        present=present,
        extras=extras,
    )


# ============================================================
# PensionerRecord
# ============================================================
@dataclass
class PensionerRecord:
    """One row in state.jsonl. The top-level record type.

    Required: pensioner_id (int) OR pensioner_name (str fallback).
    Carries fag_records (list of CandidateRecord), cgr_records
    (free-form), both_match (BothMatchRecord or None), and the
    OK-source backlinks.
    """
    pensioner_id: Optional[int] = None
    pensioner_name: str = ""
    pensioner_first: str = ""
    pensioner_middle: str = ""
    pensioner_last: str = ""
    pensioner_app_number: str = ""
    pensioner_birth_year: str = ""
    pensioner_death_year: str = ""
    regiment: str = ""
    company: str = ""
    pensioncard_backlink: str = ""
    backlink: str = ""
    fag_records: list = field(default_factory=list)  # list[CandidateRecord]
    fag_status: str = ""
    cgr_records: list = field(default_factory=list)
    cgr_status: str = ""
    both_match: Optional[BothMatchRecord] = None
    timestamp: str = ""
    error: Optional[str] = None
    # Extra root-level fields (e.g. dd_in_local, leftover_pass).
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        out = {
            "pensioner_id": self.pensioner_id,
            "pensioner_name": self.pensioner_name,
            "pensioner_first": self.pensioner_first,
            "pensioner_middle": self.pensioner_middle,
            "pensioner_last": self.pensioner_last,
            "pensioner_app_number": self.pensioner_app_number,
            "pensioner_birth_year": self.pensioner_birth_year,
            "pensioner_death_year": self.pensioner_death_year,
            "regiment": self.regiment,
            "company": self.company,
            "pensioncard_backlink": self.pensioncard_backlink,
            "backlink": self.backlink,
            "fag_records": [c.to_dict() if isinstance(c, CandidateRecord) else c
                           for c in self.fag_records],
            "fag_status": self.fag_status,
            "cgr_records": self.cgr_records,
            "cgr_status": self.cgr_status,
            "both_match": self.both_match.to_dict() if self.both_match else None,
            "timestamp": self.timestamp,
            "error": self.error,
        }
        out.update(self.extras)
        return out


# Field names consumed by the typed front; everything else goes to extras.
_PENSIONER_KNOWN = {
    "pensioner_id", "pensioner_name", "pensioner_first",
    "pensioner_middle", "pensioner_last", "pensioner_app_number",
    "pensioner_birth_year", "pensioner_death_year",
    "regiment", "company", "pensioncard_backlink", "backlink",
    "fag_records", "fag_status", "cgr_records", "cgr_status",
    "both_match", "timestamp", "error",
}


def from_dict_pensioner(d: dict) -> PensionerRecord:
    """dict -> PensionerRecord. Defensive about every field."""
    # Convert fag_records entries to CandidateRecord.
    fag_records = [from_dict_candidate(c) if isinstance(c, dict) else c
                   for c in d.get("fag_records", []) or []]

    # Convert both_match if present.
    bm_raw = d.get("both_match")
    both_match = None
    if isinstance(bm_raw, dict) and bm_raw:
        both_match = from_dict_both_match(bm_raw)
    elif isinstance(bm_raw, BothMatchRecord):
        both_match = bm_raw

    extras = {k: v for k, v in d.items() if k not in _PENSIONER_KNOWN}

    pid_raw = d.get("pensioner_id")
    pensioner_id = int(pid_raw) if pid_raw is not None and pid_raw != "" else None

    return PensionerRecord(
        pensioner_id=pensioner_id,
        pensioner_name=str(d.get("pensioner_name", "") or ""),
        pensioner_first=str(d.get("pensioner_first", "") or ""),
        pensioner_middle=str(d.get("pensioner_middle", "") or ""),
        pensioner_last=str(d.get("pensioner_last", "") or ""),
        pensioner_app_number=str(d.get("pensioner_app_number", "") or ""),
        pensioner_birth_year=str(d.get("pensioner_birth_year", "") or ""),
        pensioner_death_year=str(d.get("pensioner_death_year", "") or ""),
        regiment=str(d.get("regiment", "") or ""),
        company=str(d.get("company", "") or ""),
        pensioncard_backlink=str(d.get("pensioncard_backlink", "") or ""),
        backlink=str(d.get("backlink", "") or ""),
        fag_records=fag_records,
        fag_status=str(d.get("fag_status", "") or ""),
        cgr_records=d.get("cgr_records", []) or [],
        cgr_status=str(d.get("cgr_status", "") or ""),
        both_match=both_match,
        timestamp=str(d.get("timestamp", "") or ""),
        error=d.get("error"),
        extras=extras,
    )