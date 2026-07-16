"""CGR-side dedup: collapse duplicate Confederate Graves Registry
records into canonical persons.

Phase 2 of the post-run pipeline (see
docs/learnings/2026-07-16-run-2-learnings.md § Always-run-FaG
policy). This module is read-only with respect to state.jsonl; it
produces a separate dedup output that downstream phases consume.

Output schema (data/results/run_full_2026_07_16/cgr_dedup.json):

  {
    "version": 1,
    "created_at": "<iso8601 UTC>",
    "thresholds": {"jaro_winkler_first": 0.90, ...},
    "persons": {
      "person_id_1": {
        "member_cgr_ids": [12345, 67890],         # provenance
        "linked_pensioner_ids": [42],             # pensioners linking
        "merged_metadata": {                      # best-evidence merge
          "first_name": "Hugh",
          "last_name": "Akers",
          "middle_name": "H.",
          "birth_year": "1840",
          "death_year": "1920",
          "cemetery_ids": [5678, 9012],
          "spouse": "Mary Smith",
          "regiment": "1st Texas Infantry",
          "company": "A",
          "rank": "Pvt",
          "source_count": 2
        }
      },
      ...
    },
    "cgr_id_to_person_id": {                      # reverse index
      "12345": "person_id_1",
      "67890": "person_id_1",
      ...
    },
    "pensioner_id_to_person_id": {               # reverse index
      "42": "person_id_1",
      ...
    },
    "stats": {                                     # run statistics
      "input_cgr_records": 2593,
      "input_pensioners": 7709,
      "output_persons": <int>,
      "merged_pairs": <int>
    }
  }

DEDUP THRESHOLD (strict, locked 2026-07-16):

  Two CGR records are considered the same person if AND only if:

    (a) Last-name match: c_last_norm == p_last_norm (exact, after
        stripping punctuation and lower-casing).
    (b) First-name similarity: Jaro-Winkler >= 0.90 between
        c_first and p_first (after normalization).
    (c) Tiebreaker: at least ONE of the following matches:
          - Birth year (c_born vs p_born, both non-empty)
          - Death year (c_died vs p_died, both non-empty)
          - Cemetery id (same cemetery)
          - Unit (c_unit vs p_unit, after lowercasing)
          - Rank (c_rank vs p_rank)

  All three conditions (a), (b), (c) must hold. False-negatives
  are safer than false-positives (we do not accidentally merge
  two distinct veterans).

OUTPUT DISCIPLINE:

  - Every input CGR record maps to exactly one person_id.
  - Every input pensioner maps to exactly one person_id (whether
    they linked to any CGR record or not).
  - person_id values are stable strings ("person_0", "person_1", ...)
    so they round-trip across runs.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ============================================================
# Module-level
# ============================================================

# Match behavior — strict thresholds locked 2026-07-16
THRESH_JARO_WINKLER_FIRST = 0.90
THRESH_YEAR_DELTA = 5  # years of birth/death fuzzy match (when non-exact)


# ============================================================
# Normalization helpers (cross-module utility)
# ============================================================

def _norm(s: str) -> str:
    """Lowercase + strip non-alphanumeric (for last-name compare).

    Strips accents too, so "Müller" == "Muller".
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z]", "", s)
    return s


def _norm_first(s: str) -> str:
    """First-name normalization: keep letters only, lowercase."""
    return _norm(s)


def _norm_year(s) -> Optional[int]:
    """Year normalization: accept '1840', '1840-00-00', etc."""
    if s is None:
        return None
    if isinstance(s, int):
        return s if 1700 <= s <= 2100 else None
    m = re.match(r"^\s*(\d{4})", str(s))
    if not m:
        return None
    try:
        return int(m.group(1))
    except (ValueError, TypeError):
        return None


# ============================================================
# Similarity metric
# ============================================================

def jaro_winkler(s1: str, s2: str) -> float:
    """Jaro-Winkler similarity in [0, 1].

    Standard implementation. We don't depend on jellyfish/rapidfuzz
    so dedup works in minimal envs without extra installs.
    """
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0

    # Jaro
    len1, len2 = len(s1), len(s2)
    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j]:
                continue
            if s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    # Transpositions
    k = 0
    transpositions = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1
    transpositions //= 2

    jaro = (
        matches / len1
        + matches / len2
        + (matches - transpositions) / matches
    ) / 3

    # Winkler bonus: common prefix up to 4 chars, scaled by 0.1
    prefix = 0
    for i in range(min(len1, len2, 4)):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break
    return jaro + prefix * 0.1 * (1 - jaro)


# ============================================================
# Tiebreaker checks
# ============================================================

def _tiebreaker_ok(rec_a: dict, rec_b: dict) -> bool:
    """At least one tiebreaker must match."""
    a_born = _norm_year(rec_a.get("born") or rec_a.get("cgr_born"))
    b_born = _norm_year(rec_b.get("born") or rec_b.get("cgr_born"))
    if a_born is not None and b_born is not None:
        if abs(a_born - b_born) <= THRESH_YEAR_DELTA:
            return True

    a_died = _norm_year(rec_a.get("died") or rec_a.get("cgr_died"))
    b_died = _norm_year(rec_b.get("died") or rec_b.get("cgr_died"))
    if a_died is not None and b_died is not None:
        if abs(a_died - b_died) <= THRESH_YEAR_DELTA:
            return True

    # Cemetery id (must be the same numeric id, both present)
    a_cem = rec_a.get("cemetery_id")
    b_cem = rec_b.get("cemetery_id")
    if a_cem is not None and b_cem is not None and a_cem == b_cem:
        return True

    # Unit (lower-cased, after stripping punctuation/whitespace)
    a_unit = _norm(str(rec_a.get("unit") or ""))
    b_unit = _norm(str(rec_b.get("unit") or ""))
    if a_unit and b_unit and a_unit == b_unit:
        return True

    # Rank
    a_rank = _norm(str(rec_a.get("rank") or ""))
    b_rank = _norm(str(rec_b.get("rank") or ""))
    if a_rank and b_rank and a_rank == b_rank:
        return True

    return False


# ============================================================
# Two-record same-person predicate
# ============================================================

def same_person(rec_a: dict, rec_b: dict) -> bool:
    """Strict same-person predicate.

    Requires (a) last-name match, (b) first-name JW >= 0.90,
    AND (c) at least one tiebreaker. Returns False otherwise.

    rec_a, rec_b: CGR record dicts with at least the normalized
    first/last name fields + one of the tiebreaker fields.
    """
    last_a = _norm(rec_a.get("last_name") or rec_a.get("cgr_last") or "")
    last_b = _norm(rec_b.get("last_name") or rec_b.get("cgr_last") or "")
    if not last_a or not last_b or last_a != last_b:
        return False

    first_a = _norm_first(rec_a.get("first_name") or rec_a.get("cgr_first") or "")
    first_b = _norm_first(rec_b.get("first_name") or rec_b.get("cgr_first") or "")
    if not first_a or not first_b:
        # No first name on one side: refuse to merge (too noisy).
        return False

    jw = jaro_winkler(first_a, first_b)
    if jw < THRESH_JARO_WINKLER_FIRST:
        return False

    if not _tiebreaker_ok(rec_a, rec_b):
        return False

    return True


# ============================================================
# Union-find for clustering
# ============================================================

class UnionFind:
    """Standard union-find with path compression + union by rank."""

    def __init__(self):
        self.parent: dict[int, int] = {}
        self.rank: dict[int, int] = {}

    def add(self, x: int) -> None:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0

    def find(self, x: int) -> int:
        # Path compression
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        cur = x
        while self.parent[cur] != root:
            nxt = self.parent[cur]
            self.parent[cur] = root
            cur = nxt
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        # Union by rank
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


# ============================================================
# Merge metadata: pick best-evidence values across cluster members
# ============================================================

def _best_nonempty(*vals) -> str:
    """First non-empty string, or ''."""
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def merged_metadata_for(members: list[dict]) -> dict:
    """Build merged_metadata dict from a list of CGR member records.

    Strategy for each field: take the FIRST non-empty value (assuming
    records are roughly in source-fidelity order). Years are taken
    from any record that has them. Cemetery ids are a union.
    """
    if not members:
        return {}
    out = {
        "first_name": "",
        "middle_name": "",
        "last_name": "",
        "birth_year": "",
        "death_year": "",
        "cemetery_ids": [],
        "spouse": "",
        "regiment": "",
        "company": "",
        "rank": "",
        "source_count": len(members),
    }
    cemetery_set: set[int] = set()
    # Pick first non-empty for textual fields
    for f in members:
        out["first_name"] = out["first_name"] or _best_nonempty(
            f.get("first_name"), f.get("cgr_first"),
        )
        out["middle_name"] = out["middle_name"] or _best_nonempty(
            f.get("middle_name"), f.get("cgr_middle"),
        )
        out["last_name"] = out["last_name"] or _best_nonempty(
            f.get("last_name"), f.get("cgr_last"),
        )
        out["spouse"] = out["spouse"] or _best_nonempty(f.get("spouse"))
        out["regiment"] = out["regiment"] or _best_nonempty(
            f.get("unit"), f.get("cgr_unit"),
        )
        out["company"] = out["company"] or _best_nonempty(f.get("company"))
        out["rank"] = out["rank"] or _best_nonempty(f.get("rank"))
        # Birth / death year — take the FIRST non-None year across members
        if not out["birth_year"]:
            by = _norm_year(f.get("born") or f.get("cgr_born"))
            if by is not None:
                out["birth_year"] = str(by)
        if not out["death_year"]:
            dy = _norm_year(f.get("died") or f.get("cgr_died"))
            if dy is not None:
                out["death_year"] = str(dy)
        cid = f.get("cemetery_id")
        if cid is not None:
            cemetery_set.add(int(cid))
    out["cemetery_ids"] = sorted(cemetery_set)
    return out


# ============================================================
# Cluster → person_id mapping
# ============================================================

def cluster_to_person_id(
    uf: UnionFind,
    cgr_ids_in_cluster: list[int],
) -> str:
    """Stable person_id for a cluster, derived from the smallest cgr_id."""
    if not cgr_ids_in_cluster:
        return "person_unknown"
    # Sort for determinism
    sorted_ids = sorted(cgr_ids_in_cluster)
    return f"person_{sorted_ids[0]}"


# ============================================================
# Main entry point
# ============================================================

def build_dedup(
    cgr_records: list[dict],
    pensioner_to_cgr_links: dict[int, list[int]],
    pensioners_by_id: Optional[dict[int, dict]] = None,
) -> dict:
    """Build the full cgr_dedup output.

    Args:
      cgr_records: every CGR record (rich dict). Each must have at
        minimum a stable id field.
      pensioner_to_cgr_links: {pensioner_id: [cgr_id, cgr_id, ...]}
        extracted from state.jsonl (the CGR records that the
        blocking index returned for each pensioner). Pensioners
        with no CGR records will have empty lists / won't appear.

    Returns:
      Dict matching the schema above (the whole output document).
    """
    # 1) Add every CGR record to the union-find
    uf = UnionFind()
    cgr_id_to_record: dict[int, dict] = {}
    for rec in cgr_records:
        cid = rec.get("id")
        if cid is None:
            cid = rec.get("cgr_id")
        if cid is None:
            continue
        cid = int(cid)
        uf.add(cid)
        cgr_id_to_record[cid] = rec

    # 2) Bucket by last name to keep comparisons cheap
    by_last: dict[str, list[int]] = defaultdict(list)
    for cid, rec in cgr_id_to_record.items():
        last = _norm(rec.get("last_name") or rec.get("cgr_last"))
        if last:
            by_last[last].append(cid)

    # 3) Pairwise compare within each last-name bucket
    merged_pairs = 0
    for last, ids in by_last.items():
        if len(ids) < 2:
            continue
        # All-pairs (small buckets; the worst case is surnames with
        # ~hundreds of records, which is at most a few hundred
        # comparisons).
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                rec_a = cgr_id_to_record[ids[i]]
                rec_b = cgr_id_to_record[ids[j]]
                if same_person(rec_a, rec_b):
                    uf.union(ids[i], ids[j])
                    merged_pairs += 1

    # 4) Group by root to form clusters
    clusters: dict[int, list[int]] = defaultdict(list)
    for cid in cgr_id_to_record.keys():
        clusters[uf.find(cid)].append(cid)

    # 5) Build persons map
    persons: dict[str, dict] = {}
    cgr_id_to_person_id: dict[int, str] = {}
    pensioner_id_to_person_id: dict[int, str] = {}

    # First pass: assign person_ids and member_cgr_ids
    for root, member_cgr_ids in clusters.items():
        pid = cluster_to_person_id(uf, member_cgr_ids)
        merged = merged_metadata_for(
            [cgr_id_to_record[c] for c in member_cgr_ids]
        )
        persons[pid] = {
            "member_cgr_ids": sorted(member_cgr_ids),
            "linked_pensioner_ids": [],   # filled in pass 2
            "merged_metadata": merged,
        }
        for cid in member_cgr_ids:
            cgr_id_to_person_id[cid] = pid

    # 6) Reverse: pensioner_id -> person_id (via CGR membership)
    for pensioner_id, linked_cgr_ids in pensioner_to_cgr_links.items():
        # Determine which person_id this pensioner belongs to.
        # A pensioner might have multiple CGR links that are in
        # different persons — that's a data conflict. Pick the
        # smallest member_cgr_ids group's person_id (deterministic).
        person_ids = set()
        for cid in linked_cgr_ids:
            if cid in cgr_id_to_person_id:
                person_ids.add(cgr_id_to_person_id[cid])
        if not person_ids:
            # Pensioner linked to CGR records but those records
            # weren't found in our input set. Treat as orphan.
            pensioner_id_to_person_id[int(pensioner_id)] = (
                f"pensioner_{int(pensioner_id)}"
            )
            persons.setdefault(
                f"pensioner_{int(pensioner_id)}",
                {
                    "member_cgr_ids": [],
                    "linked_pensioner_ids": [int(pensioner_id)],
                    "merged_metadata": {},
                },
            )
            continue
        # Pick the smallest person_id (deterministic).
        pid = sorted(person_ids)[0]
        pensioner_id_to_person_id[int(pensioner_id)] = pid
        # Merge linked_pensioner_ids
        persons.setdefault(pid, {
            "member_cgr_ids": [],
            "linked_pensioner_ids": [],
            "merged_metadata": {},
        })
        if int(pensioner_id) not in persons[pid]["linked_pensioner_ids"]:
            persons[pid]["linked_pensioner_ids"].append(int(pensioner_id))

    # 7) Pensioners that link to NO CGR records at all get their
    # own person_id (singleton).
    if pensioners_by_id is not None:
        for pensioner_id in pensioners_by_id:
            if int(pensioner_id) in pensioner_id_to_person_id:
                continue
            pid = f"pensioner_{int(pensioner_id)}"
            pensioner_id_to_person_id[int(pensioner_id)] = pid
            persons.setdefault(pid, {
                "member_cgr_ids": [],
                "linked_pensioner_ids": [int(pensioner_id)],
                "merged_metadata": {},
            })

    # Sort linked_pensioner_ids for determinism
    for pid, p in persons.items():
        p["linked_pensioner_ids"] = sorted(p["linked_pensioner_ids"])

    return {
        "version": 1,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "thresholds": {
            "jaro_winkler_first": THRESH_JARO_WINKLER_FIRST,
            "year_delta": THRESH_YEAR_DELTA,
        },
        "persons": persons,
        "cgr_id_to_person_id": {
            str(k): v for k, v in sorted(cgr_id_to_person_id.items())
        },
        "pensioner_id_to_person_id": {
            str(k): v for k, v in sorted(pensioner_id_to_person_id.items())
        },
        "stats": {
            "input_cgr_records": len(cgr_records),
            "input_pensioners": (
                len(pensioners_by_id) if pensioners_by_id is not None
                else len(pensioner_to_cgr_links)
            ),
            "output_persons": len(persons),
            "merged_pairs": merged_pairs,
        },
    }


# ============================================================
# CLI
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cgr", type=Path, required=True,
                        help="Path to ok_vets_enriched.jsonl (input CGR data).")
    parser.add_argument("--state", type=Path, required=True,
                        help="Path to state.jsonl (post-run FaG output).")
    parser.add_argument("--pensioners", type=Path, required=True,
                        help="Path to ok_pensioners.json (input pensioner list).")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output path for cgr_dedup.json.")
    args = parser.parse_args()

    log_t0 = time.time()

    # Load CGR records
    cgr_records = []
    cgr_by_id: dict[int, dict] = {}
    with args.cgr.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            cgr_records.append(rec)
            cid = rec.get("id")
            if cid is not None:
                cgr_by_id[int(cid)] = rec
    print(f"Loaded {len(cgr_records)} CGR records")

    # Load pensioners
    with args.pensioners.open(encoding="utf-8") as f:
        pensioners = json.load(f)
    pensioners_by_id = {}
    for p in pensioners:
        pid = p.get("id")
        if pid is not None:
            pensioners_by_id[int(pid)] = p
    print(f"Loaded {len(pensioners_by_id)} pensioners")

    # Load state.jsonl; build pensioner -> cgr_id links
    pensioner_to_cgr_links: dict[int, list[int]] = defaultdict(list)
    with args.state.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            pid = r.get("pensioner_id")
            if pid is None:
                continue
            for cr in r.get("cgr_records") or []:
                cid = cr.get("id") or cr.get("cgr_id")
                if cid is not None:
                    pensioner_to_cgr_links[int(pid)].append(int(cid))
    print(f"Loaded {sum(len(v) for v in pensioner_to_cgr_links.values())} "
          f"pensioner->CGR links across {len(pensioner_to_cgr_links)} pensioners")

    out = build_dedup(
        cgr_records=cgr_records,
        pensioner_to_cgr_links=dict(pensioner_to_cgr_links),
        pensioners_by_id=pensioners_by_id,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, sort_keys=False)
    elapsed = time.time() - log_t0
    print(f"Wrote {args.out} "
          f"({out['stats']['output_persons']} persons, "
          f"{out['stats']['merged_pairs']} CGR pairs merged, "
          f"{elapsed:.1f}s elapsed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
