"""Search strategy ladder: iterate strategies, collect results.

A ladder is just an ordered sequence of Strategy objects. The
runner calls `run_ladder(ladder, ctx)` to either pick the first
applicable strategy (mode="first", the default) or get every
applicable strategy's params (mode="all", for merge/rank
workflows).

The ladder is decoupled from any specific search engine. The
caller takes the returned params dict and uses it however it
needs (build a URL, score candidates, feed into the next layer).
"""
from __future__ import annotations

from typing import Iterable, Sequence

from scripts.search.context import SearchContext
from scripts.search.strategy import Strategy, StrategyResult


#: (strategy_name, params) — the canonical result shape. None
#: for the name means "no strategy was applicable".
LadderResult = tuple[str | None, dict | None]


def run_ladder(
    ladder: Sequence[Strategy] | Iterable[Strategy],
    ctx: SearchContext,
    mode: str = "first",
) -> LadderResult | list[LadderResult]:
    """Iterate the ladder, collect applicable strategies.

    Args:
        ladder: ordered sequence of Strategy objects.
        ctx:    the search context (frozen; never mutated).
        mode:   "first" returns a single (name, params) tuple
                for the first strategy whose params() returns
                non-None (or (None, None) if none apply).
                "all"   returns a list of (name, params) for
                every applicable strategy, in ladder order.

    Returns:
        mode="first" → LadderResult (single tuple)
        mode="all"   → list[LadderResult]
    """
    if mode not in ("first", "all"):
        raise ValueError(f"Unknown ladder mode: {mode!r} (expected 'first' or 'all')")

    applicable: list[LadderResult] = []
    for strat in ladder:
        try:
            params = strat.params(ctx)
        except Exception:
            # A buggy strategy MUST NOT take down the whole ladder.
            # Surface the failure as a non-applicable result; the
            # runner can log it. Tests assert this is caught.
            params = None
        if params is not None:
            applicable.append((strat.name, params))
            if mode == "first":
                return applicable[0]

    if mode == "first":
        return (None, None)
    return applicable
