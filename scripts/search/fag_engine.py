"""FaGEngine: the Find a Grave implementation of SearchEngine.

This is the worked example for future engines. It contains the
battle-tested FaG-specific code (Cloudflare Turnstile detection,
state filter, ACW date window, spouse linkedToName, etc.) wrapped
in the SearchEngine Protocol.

The module re-uses the existing scripts.fag.* functions for the
heavy lifting; the engine class is a thin adapter that:
  1. Bridges SearchContext ↔ FaG's positional signatures
     (scripts.fag.scoring.score_candidate takes a local dict;
     the engine builds that dict from ctx).
  2. Wires the strategy ladder (scripts.search.strategies.STRATEGIES
     + the FaG-specific F2/F3 from scripts.search.fag_strategies).
  3. Owns the FaG-specific URL building (BASE_URL, urlencode).

Back-compat: scripts.fag.search.search_one_pensioner remains
importable and works as before. It is now a thin shim that
calls FaGEngine().search_one(...). The pipeline can migrate
to use the engine directly; the shim is the safe default.
"""
from __future__ import annotations

from typing import Any

# Re-export the FaG-specific building blocks so the engine
# implementation can use them without circular imports.
from scripts.fag.filters import apply_location_filter
from scripts.fag.scoring import score_candidate
from scripts.fag.response_classifier import (
    ResponseClassifier,
    Classification as FaGClassification,
)
from scripts.search.context import SearchContext
from scripts.search.engine import Classification, SearchEngine
from scripts.search.fag_strategies import F2_REGIMENT_BIO, F3_NICKNAME, F4_FOLLOW_UP
from scripts.search.strategies import STRATEGIES as _GENERIC_STRATEGIES


# FaG search-URL builder: import here so the engine owns
# the constant (the runner can read it via engine.base_url).
import urllib.parse as _urlparse
from scripts.fag.search import BASE_URL as _FAG_BASE_URL


# ============================================================
# FaG engine
# ============================================================


class FaGEngine:
    """The Find a Grave search engine.

    Implements the SearchEngine Protocol via the building blocks
    inherited from scripts.fag.*. Future engines follow the same
    pattern: implement the six building blocks, ship a strategy
    ladder, and the pipeline runs the engine unchanged.

    Attributes:
        name: "findagrave" — used in stats / audit trails.
        base_url: FaG's search-results URL.
        ladder: 10 generic strategies + 3 FaG-specific (F2, F3, F4).
            When ranker is provided, ladder is reordered per-pensioner.
    """

    name = "findagrave"
    base_url = _FAG_BASE_URL
    ladder = list(_GENERIC_STRATEGIES) + [F2_REGIMENT_BIO, F3_NICKNAME, F4_FOLLOW_UP]

    def __init__(self, ranker: Any = None):
        """Args:
            ranker: optional PlanRanker for strategy ordering (#55).
                When provided, use ordered_ladder() per pensioner.
        """
        self._ranker = ranker

    def ordered_ladder(self, ctx: SearchContext | None = None) -> list:
        """Return ladder, reordered by ranker if available (#55).

        When no ranker is set, returns the default fixed-order ladder.
        When ranker is set, ranks strategy names by expected utility
        for this pensioner's context.
        """
        if self._ranker is None:
            return list(self.ladder)
        if ctx is None:
            return list(self.ladder)
        names = [s.name for s in self.ladder]
        context = {
            "regiment": ctx.extra("regiment", ""),
            "first": ctx.first,
            "last": ctx.last,
            "birth_year": ctx.birth_year,
            "death_year": ctx.death_year,
            "state": ctx.state,
        }
        try:
            ranked_names = self._ranker.rank_strategies(names, pensioner_context=context)
        except Exception:
            return list(self.ladder)
        # Build ordered list preserving original strategy objects
        name_to_strat = {s.name: s for s in self.ladder}
        return [name_to_strat[n] for n in ranked_names if n in name_to_strat]

    def build_url(self, params: dict) -> str:
        """Compose the FaG search URL from a params dict.

        FaG uses standard URL query params (?firstname=...&lastname=...).
        The order of params doesn't matter; the runner doesn't
        care about the resulting URL except for audit logging.
        """
        return self.base_url + "?" + _urlparse.urlencode(params)

    def parse_results_page(self, page, url: str) -> list[dict]:
        """Parse a FaG results page into candidate dicts.

        Each candidate has at minimum: id (memorial_id), slug,
        name, snippet, details, plus optional backlink/iiif_url.

        Wraps scripts.fag.parser.parse_results_page. The
        page is a live Playwright page; the URL is recorded
        for the audit trail.
        """
        from scripts.fag.parser import parse_results_page
        _total, candidates = parse_results_page(page)
        # Some parser paths (older runs, error fallbacks) omit
        # `iiif_url`; v2 view needs it for candidate thumbnails.
        # Build it from memorial_id if missing. Issue #62 close.
        for c in candidates:
            if not c.get("iiif_url") and c.get("memorial_id"):
                c["iiif_url"] = (
                    f"https://www.findagrave.com/iiif/2/"
                    f"memorial:{c['memorial_id']}/full/full/0/default.jpg"
                )
        return candidates

    def score(
        self, ctx: SearchContext, candidate: dict,
    ) -> tuple[float, dict]:
        """Score a FaG candidate against the local context.

        Builds the local-dict shape scripts.fag.scoring expects
        (first_name / middle_name / last_name / _state_abbr) and
        delegates to score_candidate. Returns (score, breakdown).
        """
        # Bridge: SearchContext → FaG's local-dict shape.
        # We pull _state_abbr from ctx.extras; the
        # from_pensioner helper (when used) maps
        # fag_state_filter / pensioner_state into "state".
        local = {
            "first_name": ctx.first,
            "middle_name": ctx.middle,
            "last_name": ctx.last,
            "_state_abbr": ctx.state,
            "_death_year": ctx.death_year,
            "_birth_year": ctx.birth_year,
        }
        return score_candidate(local, candidate)

    def classify_response(self, page) -> Classification:
        """Classify a FaG response page.

        Wraps scripts.fag.response_classifier.ResponseClassifier.
        Returns a thin Classification that bridges to the engine
        Protocol's boolean is_blocking property.
        """
        try:
            title = page.title() if hasattr(page, "title") else ""
        except Exception:
            title = ""
        cls = ResponseClassifier.classify(title=title)
        return _FaGClassificationAdapter(cls)

    def apply_filters(
        self, params: dict, ctx: SearchContext,
    ) -> dict:
        """Apply FaG-specific filters: locationId, ACW date
        window, linkedToName (spouse cross-search).

        Reads state from ctx.state; reads spouse name from
        ctx.extras (caller is responsible for putting the
        right keys there via from_pensioner).
        """
        spouse_first = ctx.extra("spouse_first_name", "") or ""
        spouse_last = ctx.extra("spouse_last_name", "") or ""
        spouse_middle = ctx.extra("spouse_middle_name", "") or ""
        return apply_location_filter(
            params, ctx.state or "",
            spouse_first=spouse_first,
            spouse_last=spouse_last,
            spouse_middle=spouse_middle,
        )

    def throttle_seconds(self) -> float:
        """FaG inter-request throttle (seconds).

        2.5s is the law from CONTEXT.md: bypassing causes a
        30-minute Cloudflare backoff. The default; the engine
        reads from the request_gate constant for tunability.
        """
        try:
            from scripts.fag.request_gate import THROTTLE_SECONDS
            return THROTTLE_SECONDS
        except ImportError:
            return 2.5

    def follow_up_search(self, page, ctx: SearchContext) -> dict:
        """Run follow-up search (F4) for needs-research pensioners.

        Uses broadened parameters: no state filter, surname-only,
        wider year window (±10), fuzzy spelling. Returns the same
        shape as search_one.
        """
        from scripts.search.engine import default_search_one
        return default_search_one(self, page, ctx, strategy_name="F4-follow-up")

    def to_common_candidate(self, candidate: dict) -> dict:
        """Convert a FaG candidate to the common shape.

        FaG-specific fields (memorial_id, backlink, iiif_url) are
        mapped to the common id/url/media fields. Evidence is
        wrapped in the standard score_breakdown + raw envelope.
        """
        details = candidate.get("details") or {}
        evidence = candidate.get("score_evidence") or {}
        score_breakdown = evidence.get("score_breakdown", {})
        common_bd = {}
        if score_breakdown:
            common_bd = {
                "last_name": score_breakdown.get("last", 0),
                "first_name": score_breakdown.get("first", 0),
                "middle_name": score_breakdown.get("middle", 0),
                "year_window": score_breakdown.get("death", 0),
                "state": score_breakdown.get("state", 0),
                "ok_burial": score_breakdown.get("ok_burial", 0),
                "veteran": score_breakdown.get("veteran", 0),
            }
        return {
            "id": str(candidate.get("memorial_id", "")),
            "title": candidate.get("name", ""),
            "url": candidate.get("backlink", ""),
            "score": candidate.get("score", 0),
            "attributes": {
                "birth_year": details.get("birth_year", ""),
                "death_year": details.get("death_year", ""),
                "state": details.get("state", ""),
            },
            "media": {
                "image_url": candidate.get("iiif_url", ""),
            },
            "evidence": {
                "score_breakdown": common_bd,
                "raw": candidate,
            },
        }


# ============================================================
# Classification adapter: FaG's enum → Protocol's Classification
# ============================================================


class _FaGClassificationAdapter(Classification):
    """Adapts scripts.fag.response_classifier.Classification
    (a str-Enum) to the SearchEngine Protocol's Classification
    (a base class with is_blocking / is_normal / value).

    FaG's classification is a rich enum:
      - NormalPage → is_normal=True
      - CloudflareChallenge, CloudflareBlocked,
        RateLimit1015, ErrorPage → is_blocking=True

    Future engines with their own enum can ship a similar
    adapter (or inherit Classification directly).
    """

    def __init__(self, fag_cls: FaGClassification):
        self._cls = fag_cls

    @property
    def is_blocking(self) -> bool:
        return ResponseClassifier.is_blocking(self._cls)

    @property
    def is_normal(self) -> bool:
        return self._cls == FaGClassification.NormalPage

    @property
    def value(self) -> str:
        return self._cls.value
