"""Phonetic blocking index for fast record linkage.

A blocking index is a pre-computed lookup table that, given
a query (pensioner's name), returns only the CGR veteran IDs
that share a block key with the query.

Why: instead of N search_by_name() calls against CGR (each a
network roundtrip), we make 0 CGR API calls and just look up
in the index (built once from a previous scrape).

Blocking strategies (we use all of them in parallel):
  - surname_metaphone:   jellyfish.metaphone(last_name)
  - surname_nysiis:      jellyfish.nysiis(last_name)
  - firstname_metaphone: jellyfish.metaphone(first_name)
  - surname_prefix:     first 2 chars of last_name (lowercased)

For each query, we return the UNION of CGR IDs in any matching
block. Duplicates are removed.

The index is a flat dict: {block_key: set(vet_ids)}.
"""
from __future__ import annotations

import re
from typing import Iterable

import jellyfish


def metaphone_code(s: str) -> str:
    """Metaphone code for a name. Empty string in -> empty out."""
    s = (s or "").strip()
    if not s:
        return ""
    return jellyfish.metaphone(s)


def nysiis_code(s: str) -> str:
    """NYSIIS code for a name. Empty string in -> empty out."""
    s = (s or "").strip()
    if not s:
        return ""
    return jellyfish.nysiis(s)


def _split_name(name: str) -> tuple[str, str]:
    """Split 'William G Looney' into ('William', 'Looney')."""
    name = (name or "").strip()
    if not name:
        return "", ""
    parts = name.split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


def _block_keys_for_name(name: str) -> list[str]:
    """All the block keys a (first, last) name maps to.

    Returns keys like:
      - 'surname_metaphone:LN'
      - 'surname_nysiis:LANY'
      - 'firstname_metaphone:WLN'
      - 'surname_prefix:lo'
    """
    first, last = _split_name(name)
    keys = []
    if last:
        mp = metaphone_code(last)
        if mp:
            keys.append(f"surname_metaphone:{mp}")
        ny = nysiis_code(last)
        if ny:
            keys.append(f"surname_nysiis:{ny}")
        prefix = last[:2].lower()
        if prefix:
            keys.append(f"surname_prefix:{prefix}")
    if first:
        mp = metaphone_code(first)
        if mp:
            keys.append(f"firstname_metaphone:{mp}")
    return keys


def build_blocking_index(veterans: list[dict]) -> dict[str, set[int]]:
    """Build a blocking index from a flat list of {id, name, ...} dicts.

    Each veteran is indexed under multiple block keys (different
    phonetic algorithms and prefixes). A query for a name will
    hit all of these blocks and union the results.

    Returns:
      dict: {block_key: set(vet_ids)}
    """
    index: dict[str, set[int]] = {}
    for v in veterans:
        vid = v.get("id")
        if vid is None:
            continue
        name = v.get("name", "")
        for key in _block_keys_for_name(name):
            index.setdefault(key, set()).add(vid)
    return index


def build_blocking_index_from_scrape(scrape_records: list[dict]) -> dict[str, set[int]]:
    """Build the index from CGR scrape records (with nested 'veterans').

    CGR scrape records look like:
      {
        "cemetery_id": 12754,
        "veterans": [{"id": 1, "name": "William Looney"}, ...]
      }
    """
    flat = []
    for r in scrape_records:
        for v in r.get("veterans", []):
            flat.append(v)
    return build_blocking_index(flat)


def lookup_block(
    index: dict[str, set[int]],
    first_name: str = "",
    last_name: str = "",
) -> set[int]:
    """Look up CGR vet IDs that share a block with the query.

    Returns the union of all matching blocks. Empty query
    returns empty set.
    """
    if not first_name and not last_name:
        return set()

    # Build a synthetic name from parts (in case first/last are
    # in the index under different keys)
    matches: set[int] = set()
    # Try full name first
    if first_name and last_name:
        full_name = f"{first_name} {last_name}"
        for key in _block_keys_for_name(full_name):
            matches.update(index.get(key, set()))
    # Also try last-name-only (sometimes we have no first)
    if last_name:
        for key in _block_keys_for_name(f"X {last_name}"):  # X is ignored
            if key.startswith("surname_"):
                matches.update(index.get(key, set()))
    # And first-name-only
    if first_name:
        for key in _block_keys_for_name(f"{first_name} X"):  # X is ignored
            if key.startswith("firstname_"):
                matches.update(index.get(key, set()))
    return matches