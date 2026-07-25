"""Adapters between pensioner dict and SearchRecord / FaGEngine flow.

The Blackboard scheduler uses these adapters via FaGScraperKS.
"""
from __future__ import annotations

from typing import Any

from scripts.search.context import from_pensioner
from scripts.search.engine import default_search_one
from scripts.search.fag_engine import FaGEngine
from scripts.search.record import (
    SearchRecord,
    from_pensioner as record_from_pensioner,
    to_pensioner_dict,
)


def search_record_via_engine(
    page,
    pensioner: dict,
    *,
    engine: FaGEngine | None = None,
    strategy_name: str | None = None,
) -> SearchRecord:
    """Run one FaG search using the new engine flow.

    Steps:
      1. Convert the input pensioner dict to a SearchRecord.
      2. Build a SearchContext from the record.
      3. Run default_search_one with the engine.
      4. Return a new SearchRecord (same id + source) with
         the search result attached as `attributes["result"]`.

    This is the "engine-friendly" version of
    search_one_pensioner. It uses the SearchEngine Protocol
    and FaGEngine rather than the hard-coded FaG flow. The
    output is a SearchRecord; callers that need today's
    dict shape can call to_pensioner_dict() on the result.

    The full FaG orchestration (CAPTCHA waits, 1015 backoff,
    per-strategy throttle) is NOT yet wired into
    FaGEngine.search_one(). This is the simple flow. It's
    sufficient for: tests, dry-runs, dry runs against
    FakeSearchEngine, and any future code that wants the
    engine abstraction.
    """
    eng = engine or FaGEngine()
    record = record_from_pensioner(pensioner)
    ctx = from_pensioner(pensioner)
    result = default_search_one(eng, page, ctx, strategy_name=strategy_name)
    # Attach the result to the record as an attribute
    return record.with_attribute("result", result)
