"""Back-compat shim. Real implementation: scripts/fag/search.py (T022).

This file is intentionally minimal. The full search engine
lives at scripts/fag/search.py; this shim re-exports its
public surface plus the strategy ladder from
scripts/search/strategies.py (T017).

T022 acceptance: ≤15 LoC. Per the deep-module-engineer rule,
the canonical facade is `scripts.fag.search.search_one_pensioner`;
this shim exists for the one release cycle that callers migrate.
"""
from scripts.fag.search import *  # noqa: F401, F403
from scripts.search.strategies import *  # noqa: F401, F403