"""Tests for FaGEngine (issue #33).

FaGEngine is the concrete SearchEngine implementation that
wraps the existing scripts.fag.* code. These tests pin the
adapter layer (SearchContext ↔ FaG's positional signatures,
FaG classification enum ↔ Protocol's Classification).

What we test:
  - engine.base_url is FaG's search URL
  - engine.ladder is the 10 generic + 2 FaG-specific strategies
  - build_url composes a query string
  - score() bridges SearchContext → FaG's local-dict and
    returns the same score as scripts.fag.scoring.score_candidate
    for identical inputs
  - apply_filters() injects locationId + linkedToName for
    the right inputs
  - throttle_seconds() returns the FaG throttle constant
  - Classification adapter: normal → is_normal; challenge →
    is_blocking
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.search.context import SearchContext
from scripts.search.fag_engine import FaGEngine, _FaGClassificationAdapter
from scripts.search.engine import SearchEngine, engine_supports
from scripts.fag.response_classifier import Classification as FaGCls


# ============================================================
# Engine attributes
# ============================================================
class TestFaGEngineAttributes:
    def test_name(self):
        e = FaGEngine()
        assert e.name == "findagrave"

    def test_base_url_is_fag_search(self):
        e = FaGEngine()
        assert e.base_url == "https://www.findagrave.com/memorial/search"

    def test_ladder_has_12_strategies(self):
        # 10 generic + F2 (regiment-bio) + F3 (nickname)
        e = FaGEngine()
        assert len(e.ladder) == 12

    def test_ladder_contains_fag_specific(self):
        e = FaGEngine()
        names = [s.name for s in e.ladder]
        assert "F2-regiment-bio" in names
        assert "F3-nickname" in names
        # And the generic 10
        for n in ("B1-exact", "B5-apostrophe", "F1c-year-sniper"):
            assert n in names

    def test_conforms_to_protocol(self):
        e = FaGEngine()
        assert isinstance(e, SearchEngine)
        assert engine_supports(e)


# ============================================================
# build_url
# ============================================================
class TestFaGEngineBuildUrl:
    def test_builds_url_with_query_string(self):
        e = FaGEngine()
        url = e.build_url({"firstname": "John", "lastname": "Smith"})
        assert url.startswith("https://www.findagrave.com/memorial/search?")
        assert "firstname=John" in url
        assert "lastname=Smith" in url

    def test_url_encodes_special_chars(self):
        e = FaGEngine()
        url = e.build_url({"bio": "Confederate States America"})
        # Spaces and special chars should be percent-encoded
        assert " " not in url
        assert "Confederate" in _decoded_qs(url)


def _decoded_qs(url: str) -> str:
    """Helper: decode the query string portion for assertion."""
    from urllib.parse import parse_qs, urlparse
    return " ".join(
        f"{k}={v[0]}" for k, v in parse_qs(urlparse(url).query).items()
    )


# ============================================================
# score: SearchContext → FaG local dict
# ============================================================
class TestFaGEngineScore:
    def test_score_with_full_name(self):
        e = FaGEngine()
        ctx = SearchContext(
            first="William", middle="Pickney", last="Looney",
            state="OK",
        )
        candidate = {
            "slug": "william-pickney-looney",
            "snippet": "1844-1932 (Oklahoma)",
        }
        score, evidence = e.score(ctx, candidate)
        assert 0.0 <= score <= 1.0
        # The evidence dict comes from scripts.fag.scoring
        assert isinstance(evidence, dict)

    def test_score_matches_underlying_score_candidate(self):
        """FaGEngine.score must produce the same result as
        calling scripts.fag.scoring.score_candidate directly
        with the same local dict. This is the bridge contract."""
        from scripts.fag.scoring import score_candidate
        e = FaGEngine()
        ctx = SearchContext(
            first="William", middle="Pickney", last="Looney",
            state="OK",
        )
        candidate = {
            "slug": "william-pickney-looney",
            "snippet": "1844-1932 (Oklahoma)",
        }
        score_via_engine, evidence_via_engine = e.score(ctx, candidate)
        # Build the local dict the same way the engine does
        local = {
            "first_name": ctx.first,
            "middle_name": ctx.middle,
            "last_name": ctx.last,
            "_state_abbr": ctx.state,
            "_death_year": ctx.death_year,
            "_birth_year": ctx.birth_year,
        }
        score_direct, _ = score_candidate(local, candidate)
        assert score_via_engine == score_direct

    def test_score_with_empty_context_is_low(self):
        e = FaGEngine()
        ctx = SearchContext()
        candidate = {"slug": "alice", "snippet": ""}
        score, _ = e.score(ctx, candidate)
        # With no name data on the local side, the score is
        # low (the scorer still gives some base weight from
        # slug parsing). The exact value is the underlying
        # scorer's contract; we just assert it's not auto-accept.
        assert score < 0.5


# ============================================================
# apply_filters: location + spouse
# ============================================================
class TestFaGEngineApplyFilters:
    def test_adds_location_id_for_state(self):
        e = FaGEngine()
        ctx = SearchContext(first="John", last="Smith", state="OK")
        out = e.apply_filters({"firstname": "John"}, ctx)
        # OK is state_38
        assert out.get("locationId") == "state_38"

    def test_no_state_means_no_location_filter(self):
        e = FaGEngine()
        ctx = SearchContext(first="John", last="Smith")
        out = e.apply_filters({"firstname": "John"}, ctx)
        # Without state, the filter is not added
        # (the function may still add a country_4 or nothing)
        # The key thing: state_38 must not be present
        assert out.get("locationId") != "state_38"

    def test_adds_linked_to_name_when_spouse_present(self):
        e = FaGEngine()
        ctx = SearchContext(
            first="John", last="Smith",
            extras={
                "spouse_first_name": "Margaret",
                "spouse_last_name": "Slemp",
            },
        )
        out = e.apply_filters({"firstname": "John"}, ctx)
        # FaG's linkedToName filter is a strong signal
        assert "linkedToName" in out

    def test_no_linked_to_name_when_spouse_partial(self):
        e = FaGEngine()
        ctx = SearchContext(
            first="John", last="Smith",
            extras={"spouse_first_name": "Margaret"},  # no last
        )
        out = e.apply_filters({"firstname": "John"}, ctx)
        # A half-name would over-filter; must not be set
        assert "linkedToName" not in out


# ============================================================
# throttle_seconds
# ============================================================
class TestFaGEngineThrottle:
    def test_returns_fag_throttle(self):
        e = FaGEngine()
        v = e.throttle_seconds()
        # Per CONTEXT.md: 2.5s is the law. The actual value
        # may move (THROTTLE_SECONDS constant) but it must
        # always be positive and at least 1.0s (the search
        # floor; lower values trip Cloudflare).
        assert v >= 1.0
        assert v <= 10.0  # sanity upper bound


# ============================================================
# Classification adapter
# ============================================================
class TestFaGClassificationAdapter:
    def test_normal_page_is_not_blocking(self):
        cls = _FaGClassificationAdapter(FaGCls.NormalPage)
        assert cls.is_blocking is False
        assert cls.is_normal is True
        assert cls.value == "NormalPage"

    def test_cloudflare_challenge_is_blocking(self):
        cls = _FaGClassificationAdapter(FaGCls.CloudflareChallenge)
        assert cls.is_blocking is True
        assert cls.is_normal is False
        assert cls.value == "CloudflareChallenge"

    def test_rate_limit_is_blocking(self):
        cls = _FaGClassificationAdapter(FaGCls.RateLimit1015)
        assert cls.is_blocking is True
        assert cls.value == "RateLimit1015"

    def test_error_page_is_blocking(self):
        cls = _FaGClassificationAdapter(FaGCls.ErrorPage)
        assert cls.is_blocking is True
        assert cls.value == "ErrorPage"


# ============================================================
# classify_response: end-to-end with a stub page
# ============================================================
class TestFaGEngineClassifyResponse:
    def test_classify_normal_page_title(self):
        e = FaGEngine()

        class _Page:
            def title(self):
                return "Memorial Search Results"
        cls = e.classify_response(_Page())
        assert cls.is_normal is True
        assert cls.is_blocking is False

    def test_classify_cloudflare_challenge(self):
        e = FaGEngine()

        class _Page:
            def title(self):
                return "Just a moment..."
        cls = e.classify_response(_Page())
        assert cls.is_blocking is True

    def test_classify_handles_page_title_error(self):
        e = FaGEngine()

        class _Page:
            def title(self):
                raise RuntimeError("page closed")
        # Should not raise; default to non-blocking
        cls = e.classify_response(_Page())
        assert cls.is_blocking is False or cls.is_normal is True


# ============================================================
# FaGEngine + default_search_one: end-to-end (smoke)
# ============================================================
class TestFaGEngineEndToEnd:
    """A smoke test that the FaGEngine plugs into the default
    search_one flow and produces a sensible result. We don't
    use a real Playwright page here — the FaG-specific
    orchestration (CAPTCHA waits, 1015 backoff, per-strategy
    throttle) is in scripts/fag/search.py, not in the
    engine's search_one. This test proves the building blocks
    compose correctly."""

    def test_default_search_one_with_fag_engine(self):
        from scripts.search.engine import default_search_one
        from scripts.fag.scoring import score_candidate

        e = FaGEngine()

        # A stub page that records goto() calls. We override
        # build_url/parse/score with fakes so we can run
        # default_search_one without a real browser.
        e.ladder = [__import__(
            "scripts.search.strategy", fromlist=["as_strategy"]
        ).as_strategy("B1", lambda ctx: {
            "firstname": ctx.first, "lastname": ctx.last,
        })]

        class _StubPage:
            def __init__(self):
                self.visited = []
            def goto(self, url, **kw):
                self.visited.append(url)
            def title(self):
                return "Memorial Search Results"
        page = _StubPage()

        # Patch parse_results_page to return canned candidates
        e.parse_results_page = lambda page, url: [
            {"id": "1", "slug": "alice-smith", "snippet": "1844-1932"},
            {"id": "2", "slug": "bob-jones", "snippet": "1845-1930"},
        ]

        ctx = SearchContext(
            first="Alice", last="Smith", state="OK",
        )
        result = default_search_one(e, page, ctx)
        # 1 strategy ran, navigated once
        assert len(page.visited) == 1
        assert "firstname=Alice" in page.visited[0]
        assert "lastname=Smith" in page.visited[0]
        # locationId=state_38 was injected
        assert "locationId=state_38" in page.visited[0]
        # 2 candidates merged, both scored
        assert len(result["candidates"]) == 2
        assert result["best"] is not None
        assert result["best"]["id"] in ("1", "2")
        # The score used the FaG scorer
        for c in result["candidates"]:
            assert 0.0 <= c["score"] <= 1.0
