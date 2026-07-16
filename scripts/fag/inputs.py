"""scripts.fag.inputs: input loaders for the FaG search pipeline.

Extracted from scripts/fag/search.py (T008). Pure data loading;
no Playwright/browser dependencies. Each function returns a list
of pensioner dicts in the standard shape.

Loaders:
  - load_unified_from_url: fetch ok_pensioners.json from a URL
  - load_unified_from_file: read ok_pensioners.json from disk
  - load_local_csv: read a generic CSV (e.g. dixiedata export)
  - load_input: dispatcher that picks the right loader based on args
  - load_ground_truth: read expected (memorial_id, slug) per row
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("fag.inputs")


def load_unified_from_url(url: str) -> list[dict]:
    import urllib.request
    log.info("Fetching %s ...", url)
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = json.loads(resp.read())
    log.info("Loaded %d records", len(data))
    return data


def load_unified_from_file(path: Path) -> list[dict]:
    log.info("Loading %s ...", path)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    log.info("Loaded %d records", len(data))
    return data


def load_local_csv(path: Path) -> list[dict]:
    """Load a generic CSV (e.g. from local dixiedata export).

    Expected columns (case-insensitive, some optional):
      id, first_name, middle_name, last_name,
      unit, pension_state, application_number, slug, memorial_id
    """
    import csv
    log.info("Loading %s ...", path)
    out = []
    with path.open(encoding='utf-8', errors='replace', newline='') as f:
        rdr = csv.DictReader(f)
        for i, row in enumerate(rdr, start=1):
            lc = {k.lower().strip(): (v or '').strip() for k, v in row.items() if k}
            out.append({
                'id': int(lc.get('id') or i),
                'first_name': lc.get('first_name', ''),
                'middle_name': lc.get('middle_name', ''),
                'last_name': lc.get('last_name', ''),
                'application_number': lc.get('application_number', ''),
                'regiment': lc.get('unit', ''),
                'company': lc.get('company', ''),
                'birth_year': lc.get('birth_year', ''),
                'death_year': lc.get('death_year', ''),
                'pensioncard_backlink': '',
                'backlink': '',
                '_expected_memorial_id': lc.get('memorial_id', ''),
                '_expected_slug': lc.get('slug', ''),
            })
    log.info("Loaded %d records", len(out))
    return out


def load_input(args, pensioners_list_holder: list) -> None:
    """Resolve which input loader to use based on args.

    Mutates pensioners_list_holder[0] to be the loaded list.
    """
    if args.input_url:
        pensioners_list_holder.append(load_unified_from_url(args.input_url))
    elif args.input_csv:
        pensioners_list_holder.append(load_local_csv(args.input_csv))
    else:
        pensioners_list_holder.append(load_unified_from_file(args.input))


def load_ground_truth(path: Path) -> dict[int, dict]:
    """Load expected {memorial_id, slug} per row, keyed by row id.

    The CSV must have columns: id, memorial_id, slug
    (or: id, app_number for matching by application number)
    """
    import csv
    gt = {}
    with path.open(encoding='utf-8', errors='replace', newline='') as f:
        for row in csv.DictReader(f):
            try:
                rid = int(row.get('id') or 0)
            except (ValueError, TypeError):
                continue
            gt[rid] = {
                'memorial_id': (row.get('memorial_id') or '').strip(),
                'slug': (row.get('slug') or '').strip(),
            }
    log.info("Loaded %d ground-truth records from %s", len(gt), path)
    return gt