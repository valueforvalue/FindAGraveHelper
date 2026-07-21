"""SearchEngine Protocol: domain-agnostic search-engine interface.

A SearchEngine knows how to talk to one specific search backend
(Find a Grave, Ancestry, FamilySearch, Newspapers.com, ...).
The unified pipeline consumes a SearchEngine; it doesn't know
which one is plugged in.

Every engine implements six building blocks:

  - build_url(params)        → str
  - parse_results_page(page, url) → list[dict]
  - score(ctx, candidate)    → (float, evidence_dict)
  - classify_response(page)  → Classification
  - apply_filters(params, ctx) → dict
  - throttle_seconds()       → float

And one top-level method:

  - search_one(page, ctx, *, strategy_name) → dict

The default `search_one` implementation is provided here and
uses the building blocks. Engines that have a different flow
(e.g. a batch API instead of a strategy ladder) override it.

Why a Protocol, not an ABC?

  - Protocol is structural (duck-typed at runtime). Engines
    don't have to inherit from anything; they just need the
    right shape. Easier to test with fakes.

  - Multiple implementations can coexist (FaGEngine, future
    AncestryEngine, NewspapersComEngine, ...). A Protocol
    expresses "any of these shapes is acceptable" without
    forcing a base class.

  - FakeSearchEngine in tests is just a class with the right
    methods; no inheritance needed.

Engine authors should:
  - Read FaGEngine for a worked example. It contains all the
    battle-tested quirks of integrating a hostile search
    backend (Cloudflare Turnstile detection, 1015 rate
    limit, etc.).
  - Implement the six building blocks.
  - Provide a ladder (list of Strategy objects) suited to
    the engine's URL params.
  - Override `search_one` only if the default flow doesn't
    fit (e.g. no pagination, or a single API call instead
    of a per-strategy loop).
"""
from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from scripts.search.context import SearchContext
from scripts.search.strategy import Strategy
from scripts.search.ladder import run_ladder

log = logging.getLogger("search.engine")


# ============================================================
# Result types
# ============================================================


@runtime_checkable
class SearchEngine(Protocol):
    """A search-engine backend (FaG, Ancestry, ...).

    Attributes:
        name:    Short identifier (e.g. "findagrave", "ancestry").
                 Used in stats, audit trails, and the config UI.
        base_url: The engine's results-page URL (used for
                 the warmup goto before the first real search).
        ladder:   Ordered list of Strategy objects to try.
                 The default `search_one` iterates this with
                 run_ladder(). Engines with a different flow
                 (e.g. API call) can ignore this and override
                 `search_one`.
    """

    name: str
    base_url: str
    ladder: list[Strategy]

    # ----- Building blocks (engine-specific) -----

    def build_url(self, params: dict) -> str:
        """Compose a search URL from a params dict.

        The dict comes from a Strategy.params() result; the engine
        decides how to serialise it (FaG uses urlencode, Ancestry
        might build a different query shape, ...).
        """
        ...

    def parse_results_page(self, page, url: str) -> list[dict]:
        """Parse a results page into a list of candidate dicts.

        Each candidate MUST have a stable id field (FaG uses
        memorial_id, Ancestry might use record_id) and any
        evidence fields the engine cares about (slug, snippet,
        etc.). The score() function is responsible for turning
        the candidate into a confidence score; the parser just
        extracts the raw data.
        """
        ...

    def score(
        self, ctx: SearchContext, candidate: dict,
    ) -> tuple[float, dict]:
        """Score a candidate against the local context.

        Returns (score, evidence). Score is in [0, 1]. Evidence
        is a dict the engine can attach to the candidate for
        downstream review (e.g. {"matched_via": "first_and_last",
        "match_strength": "strong"}).
        """
        ...

    def classify_response(self, page) -> "Classification":
        """Classify a response page (normal, challenge, error, ...).

        Used by the runner to decide whether to back off
        (Cloudflare Turnstile, 1015 rate limit) or continue.
        Engines that don't have anti-bot detection return a
        single NORMAL value.
        """
        ...

    def apply_filters(
        self, params: dict, ctx: SearchContext,
    ) -> dict:
        """Apply engine-specific URL-param filters.

        FaG uses this for locationId (state filter),
        birthyear/deathyear windows, and the spouse cross-search
        (linkedToName). Ancestry might add its own filters.
        Returns a NEW params dict (do not mutate the input).
        """
        ...

    def throttle_seconds(self) -> float:
        """Inter-request throttle (seconds). The runner sleeps
        this long between requests. The default 2.5s floor is
        appropriate for search engines that rate-limit; engines
        with more generous limits (or paid APIs) can return
        less.
        """
        ...

    # ----- Wire-format projection -----

    def to_common_candidate(self, candidate: dict) -> dict:
        """Convert an engine-specific candidate to the common
        engine-agnostic shape.

        Every engine MUST implement this so the pipeline and
        view.html can consume any engine's output without
        engine-specific field names.

        Returns a dict with keys:
          - id:       stable identifier (string).
          - title:    display name.
          - url:      link to the source page.
          - score:    confidence in [0, 1].
          - attributes: free-form dict (birth_year, death_year,
                        state, date, location, etc.).
          - evidence: dict with at minimum:
              - score_breakdown: feature → value mapping.
              - raw: the original engine-specific candidate.
        """
        ...


# ============================================================
# Classification (response type)
# ============================================================


class Classification:
    """Result of classifying an engine response page.

    The default engine implementation can use the
    ResponseClassifier from scripts.fag.response_classifier
    or its own. This is a thin base so engines that don't
    share a FaG-shaped classification (e.g. API errors) can
    return their own type.

    For now, the runner only cares about the boolean
    is_blocking; engines can return a rich enum and the
    runner coerces to that.
    """

    @property
    def is_blocking(self) -> bool:
        """True if the runner should back off (challenge page,
        rate limit, fatal error)."""
        return False

    @property
    def is_normal(self) -> bool:
        """True if the page is a normal results page and
        parsing should proceed."""
        return True

    @property
    def value(self) -> str:
        """Human-readable label (for stats / logs)."""
        return "unknown"


# ============================================================
# Default search_one
# ============================================================


def default_search_one(
    engine: SearchEngine,
    page,
    ctx: SearchContext,
    *,
    strategy_name: str | None = None,
    throttle_fn: Callable[[], None] | None = None,
) -> dict:
    """Default search_one implementation.

    Iterates the engine's ladder via run_ladder; for each
    applicable strategy, builds a URL, navigates the page,
    classifies the response, parses if normal, scores
    candidates, and returns the merged best result.

    Args:
        throttle_fn: optional callable invoked BEFORE each
            `page.goto()`. Used by the Blackboard scheduler
            to thread a per-strategy throttle (e.g. a
            `RequestGate.wait()`) through the engine flow
            so a single default_search_one call can't
            burst-fire multiple navigations inside the
            L1 floor. Issue #61 close: was missing; engine
            path was burning the throttle budget.

    Engines CAN override this for a fundamentally different
    flow (e.g. one API call instead of a strategy loop).
    The default is provided here so engine authors can
    inherit it and only override what differs.
    """
    from typing import Callable

    # Build a working ladder (filtered by strategy_name if given)
    # Issue #55: use ordered_ladder() when engine supports it (ranker).
    if hasattr(engine, "ordered_ladder"):
        ladder = engine.ordered_ladder(ctx)
    else:
        ladder = engine.ladder
    if strategy_name is not None:
        ladder = [s for s in ladder if s.name == strategy_name]
        if not ladder:
            raise ValueError(f"Unknown {engine.name} strategy: {strategy_name}")

    from scripts.search.ladder import run_ladder

    all_candidates = []  # (strategy_name, [candidates])
    strategies_run = []
    error = None
    classification = None
    for strat in ladder:
        try:
            params = strat.params(ctx)
        except Exception:
            params = None
        if params is None:
            continue
        # Engine-specific filtering
        params = engine.apply_filters(params, ctx)
        # Build URL
        try:
            url = engine.build_url(params)
        except Exception as e:
            error = f"build_url failed: {e}"
            continue
        # Per-strategy throttle: callers MUST provide a
        # throttle_fn that enforces min_interval between
        # navigations; without it the engine fires in burst
        # mode and Cloudflare flips to 1015. (Issue #61.)
        if throttle_fn is not None:
            try:
                throttle_fn()
            except Exception as e:
                log.warning("throttle_fn raised: %s", e)
        # Navigate
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            error = f"nav timeout: {e}"
            continue
        # Classify
        try:
            classification = engine.classify_response(page)
        except Exception as e:
            error = f"classify failed: {e}"
            continue
        if classification.is_blocking:
            # Don't bail out; let other strategies try. The
            # throttle will catch up. Surface the classification
            # so the caller can decide.
            continue
        # Parse
        try:
            cands = engine.parse_results_page(page, url)
        except Exception as e:
            error = f"parse failed: {e}"
            continue
        # Score + tag
        scored = []
        for c in cands:
            try:
                score, evidence = engine.score(ctx, c)
                c = dict(c)
                c["score"] = score
                c["score_evidence"] = evidence
            except Exception as e:
                # A buggy scorer MUST NOT take down the run;
                # record the candidate with score 0 and the
                # error in the evidence.
                c = dict(c)
                c["score"] = 0.0
                c["score_evidence"] = {"error": str(e)}
            scored.append(c)
        all_candidates.append((strat.name, scored))
        strategies_run.append(strat.name)

    # Merge by candidate id (highest score wins)
    merged = _merge_candidates(engine, all_candidates)
    # Pick best
    best = max(merged, key=lambda c: c.get("score", 0.0)) if merged else None
    return {
        "strategies_run": strategies_run,
        "candidates": merged,
        "best": best,
        "error": error,
        "classification": classification.value if classification else None,
    }


def _merge_candidates(
    engine: SearchEngine,
    strategy_runs: list[tuple[str, list[dict]]],
) -> list[dict]:
    """Merge candidates across strategies. Same id → keep
    highest score; keep the strategy that surfaced it as
    'found_by'."""
    by_id: dict[str, dict] = {}
    for strat_name, cands in strategy_runs:
        for c in cands:
            cid = str(c.get("id") or c.get("memorial_id") or c.get("record_id") or "")
            if not cid:
                continue
            if cid not in by_id or c.get("score", 0.0) > by_id[cid].get("score", 0.0):
                tag = dict(c)
                tag["found_by"] = strat_name
                by_id[cid] = tag
    return list(by_id.values())


# ============================================================
# Helpers
# ============================================================


def engine_supports(engine: object, protocol: type = SearchEngine) -> bool:
    """Runtime check: does `engine` quack like a SearchEngine?

    Use this in place of `isinstance(engine, SearchEngine)`
    since SearchEngine is a Protocol (runtime_checkable
    already gives isinstance, but this name is clearer at
    call sites).
    """
    return isinstance(engine, protocol)
