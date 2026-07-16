"""Back-compat shim. Real implementation: scripts/fag/search.py (T022).

This file is intentionally minimal. The full 1432-LoC module
lives at scripts/fag/search.py; this shim re-exports its
public surface so existing callers `from scripts.search_fag
import X` keep working.

T022 acceptance: ≤15 LoC. Per the deep-module-engineer rule,
the canonical facade is `scripts.fag.search.search_one_pensioner`;
this shim exists for the one release cycle that callers migrate.
"""
from scripts.fag.search import *  # noqa: F401, F403