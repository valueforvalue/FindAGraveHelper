"""Adapters between today's pensioner dict and the new
SearchRecord / FaGEngine flow.

This module demonstrates the integration: a future migration
of scripts.fag.search.search_one_pensioner would replace
its dict-based flow with a SearchRecord-based flow that uses
FaGEngine. The functions here are the building blocks for
that migration; today they're used by the engine and by tests.

Back-compat: scripts.fag.search.search_one_pensioner continues
to work. The new code path is opt-in via search_one_pensioner_v2
(returns a SearchRecord-based result). When #35 (orchestrator
refactor) lands, v2 becomes the default and v1 is deprecated.
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
