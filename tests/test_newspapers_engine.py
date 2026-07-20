"""Tests for NewspapersComEngine (issue #36).

The 2nd real engine. Validates that the SearchEngine Protocol
+ SearchRecord + run_ladder abstractions are sufficient to
add a new search backend without touching the pipeline.

Tests pin:
  - The parser extracts the right fields from a Newspapers.com
    result block (id, href, title, date, location).
  - Date parsing: "Saturday, August 22, 1896" → "1896-08-22".
  - Score: last name in title gets 0.4; first name 0.2;
    state 0.2; year in window 0.2; total cap 1.0.
  - The engine conforms to the SearchEngine Protocol.
  - End-to-end: with the saved HTML, the engine parses 10
    real results and scores them against a test pensioner.
  - Backward-compat: a NewspaperComEngine run through the
    pipeline produces the right PipelineResult shape.
"""
from __future__ import annotations

import sys
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.search.context import SearchContext
from scripts.search.engine import SearchEngine, engine_supports
from scripts.search.newspapers_engine import (
    NewspapersComEngine,
    _parse_block,
    _parse_date,
    _RESULT_BLOCK_RE,
)


# ============================================================
# HTML fixture: the real saved HTML from the probe
# ============================================================
HTML_FIXTURE = Path("data/probe/newspapers_q_john_smith_broad.html")


@pytest.fixture
def fixture_html() -> str:
    """The full saved HTML from the probe. Skips the test if
    the file is missing (the probe hasn't been run)."""
    if not HTML_FIXTURE.exists():
        pytest.skip(f"{HTML_FIXTURE} not present; run the probe first")
    return HTML_FIXTURE.read_text(encoding="utf-8", errors="ignore")


# ============================================================
# Engine attributes
# ============================================================
class TestNewspapersComEngineAttributes:
    def test_name(self):
        e = NewspapersComEngine()
        assert e.name == "newspapers_com"

    def test_base_url(self):
        e = NewspapersComEngine()
        assert e.base_url == "https://www.newspapers.com/search/"

    def test_ladder_has_3_strategies(self):
        e = NewspapersComEngine()
        assert len(e.ladder) == 3
        names = [s.name for s in e.ladder]
        assert "N1-keyword" in names
        assert "N2-lastname-only" in names
        assert "N3-with-state" in names

    def test_conforms_to_protocol(self):
        e = NewspapersComEngine()
        assert isinstance(e, SearchEngine)
        assert engine_supports(e)


# ============================================================
# Parser
# ============================================================
class TestParser:
    def test_parse_block_extracts_id(self, fixture_html):
        candidates = []
        for m in _RESULT_BLOCK_RE.finditer(fixture_html):
            parsed = _parse_block(m.group(0))
            if parsed is not None:
                candidates.append(parsed)
        assert len(candidates) == 10
        # First candidate id matches the HTML
        assert candidates[0]["id"] == "1113382403"

    def test_parse_block_extracts_href(self, fixture_html):
        m = _RESULT_BLOCK_RE.search(fixture_html)
        parsed = _parse_block(m.group(0))
        assert parsed["href"].startswith("/image/1113382403/")
        assert "match=32" in parsed["href"]
        assert parsed["match_position"] == "32"

    def test_parse_block_extracts_title(self, fixture_html):
        m = _RESULT_BLOCK_RE.search(fixture_html)
        parsed = _parse_block(m.group(0))
        assert "Australasian" in parsed["title"]
        assert "Page 23" in parsed["title"]

    def test_parse_block_extracts_location(self, fixture_html):
        m = _RESULT_BLOCK_RE.search(fixture_html)
        parsed = _parse_block(m.group(0))
        assert "Melbourne" in parsed["location"]
        assert "Australia" in parsed["location"]

    def test_parse_block_extracts_date(self, fixture_html):
        m = _RESULT_BLOCK_RE.search(fixture_html)
        parsed = _parse_block(m.group(0))
        assert "Saturday" in parsed["date"]
        assert "August 22, 1896" in parsed["date"]
        assert parsed["iso_date"] == "1896-08-22"

    def test_parse_block_returns_none_for_invalid(self):
        assert _parse_block("") is None
        assert _parse_block("<div>no id here</div>") is None


# ============================================================
# Date parser
# ============================================================
class TestDateParser:
    def test_full_date(self):
        assert _parse_date("Saturday, August 22, 1896") == "1896-08-22"

    def test_other_months(self):
        assert _parse_date("Friday, December 13, 1918") == "1918-12-13"
        assert _parse_date("Wednesday, January 1, 1900") == "1900-01-01"

    def test_empty(self):
        assert _parse_date("") == ""

    def test_garbage(self):
        assert _parse_date("not a date") == ""


# ============================================================
# Score
# ============================================================
class TestScore:
    def _ctx(self, **kw) -> SearchContext:
        defaults = dict(
            first="John", last="Smith",
            birth_year="1844", death_year="1932",
            state="OK",
        )
        defaults.update(kw)
        return SearchContext(**defaults)

    def test_last_name_in_title(self):
        e = NewspapersComEngine()
        ctx = self._ctx()
        # Title with "Smith" → 0.4
        score, evidence = e.score(ctx, {
            "title": "Daily Smith Journal",
            "location": "Somewhere",
            "iso_date": "1900-01-01",
        })
        assert score >= 0.4
        assert evidence.get("last_name_in_title") is True

    def test_first_name_in_title(self):
        e = NewspapersComEngine()
        ctx = self._ctx()
        # Title with "John" but not "Smith" → +0.2 (first name).
        # Use a year outside the pensioner lifespan to avoid
        # the year-in-window bonus polluting the assertion.
        score, evidence = e.score(ctx, {
            "title": "Daily John Journal",
            "location": "Somewhere",
            "iso_date": "2000-01-01",  # outside [1839, 1937]
        })
        assert score >= 0.2
        assert score < 0.4
        assert evidence.get("first_name_in_title") is True

    def test_state_in_location(self):
        e = NewspapersComEngine()
        ctx = self._ctx()
        score, evidence = e.score(ctx, {
            "title": "Some Paper",
            "location": "Oklahoma City, OK",
            "iso_date": "1900-01-01",
        })
        assert score >= 0.2
        assert evidence.get("state_in_location") is True

    def test_year_in_window(self):
        e = NewspapersComEngine()
        ctx = self._ctx(birth_year="1844", death_year="1932")
        # 1900 is between 1844-5 and 1932+5 → +0.2
        score, evidence = e.score(ctx, {
            "title": "Some Paper",
            "location": "Somewhere",
            "iso_date": "1900-06-15",
        })
        assert score >= 0.2
        assert "year_in_window" in evidence

    def test_year_out_of_window(self):
        e = NewspapersComEngine()
        ctx = self._ctx(birth_year="1844", death_year="1932")
        # 2020 is outside the window
        score, evidence = e.score(ctx, {
            "title": "Some Paper",
            "location": "Somewhere",
            "iso_date": "2020-01-01",
        })
        assert "year_in_window" not in evidence

    def test_full_match_high_score(self):
        """A candidate that matches name + state + year gets
        a high score (close to 1.0)."""
        e = NewspapersComEngine()
        ctx = self._ctx(first="John", last="Smith", state="OK",
                        birth_year="1844", death_year="1932")
        score, _ = e.score(ctx, {
            "title": "John Smith Obituary",
            "location": "Tulsa, OK",
            "iso_date": "1920-05-10",
        })
        # 0.4 (last) + 0.2 (first) + 0.2 (state) + 0.2 (year) = 1.0
        assert score == 1.0

    def test_no_match_zero_score(self):
        e = NewspapersComEngine()
        ctx = self._ctx(first="John", last="Smith", state="OK",
                        birth_year="1844", death_year="1932")
        score, _ = e.score(ctx, {
            "title": "Something Completely Different",
            "location": "Iceland",
            "iso_date": "2020-01-01",
        })
        assert score == 0.0

    def test_score_caps_at_1(self):
        e = NewspapersComEngine()
        ctx = self._ctx()
        # Pathological case: all features hit
        score, _ = e.score(ctx, {
            "title": "John Smith Obituary",
            "location": "OK, USA",
            "iso_date": "1900-01-01",
        })
        assert score <= 1.0


# ============================================================
# build_url
# ============================================================
class TestBuildUrl:
    def test_basic_url(self):
        e = NewspapersComEngine()
        url = e.build_url({"keyword": "Smith", "date-start": "1850"})
        assert url.startswith("https://www.newspapers.com/search")
        assert "keyword=Smith" in url
        assert "date-start=1850" in url

    def test_url_with_encoded_entities(self):
        e = NewspapersComEngine()
        url = e.build_url({
            "keyword": "John Smith",
            "entity-types": "page,obituary",
        })
        # urlencode encodes the comma as %2C
        assert "entity-types=page%2Cobituary" in url


# ============================================================
# apply_filters
# ============================================================
class TestApplyFilters:
    def test_returns_copy(self):
        e = NewspapersComEngine()
        params = {"keyword": "Smith"}
        out = e.apply_filters(params, SearchContext())
        assert out == params
        assert out is not params  # new dict


# ============================================================
# throttle_seconds
# ============================================================
class TestThrottle:
    def test_throttle_is_reasonable(self):
        e = NewspapersComEngine()
        v = e.throttle_seconds()
        # Lower than FaG's 2.5s (Newspapers.com is more lenient)
        # but still positive to avoid burst issues
        assert 0.5 <= v <= 5.0


# ============================================================
# classify_response
# ============================================================
class TestClassifyResponse:
    def test_normal_page(self):
        e = NewspapersComEngine()

        class _Page:
            def title(self):
                return "John Smith - Search - Newspapers.com"
            def content(self):
                return '<div class="SearchResult_SearchResult...">...</div>'
        cls = e.classify_response(_Page())
        assert cls.is_normal is True
        assert cls.is_blocking is False

    def test_cloudflare_challenge(self):
        e = NewspapersComEngine()

        class _Page:
            def title(self):
                return "Just a moment..."
            def content(self):
                return "<html>challenge</html>"
        cls = e.classify_response(_Page())
        assert cls.is_blocking is True
        assert "cloudflare" in cls.value.lower()

    def test_paywall(self):
        e = NewspapersComEngine()

        class _Page:
            def title(self):
                return "Search - Newspapers.com"
            def content(self):
                return '<div class="MarketingResults_...">Start Free Trial</div>'
        cls = e.classify_response(_Page())
        assert cls.value == "paywall"
        # Paywall is not blocking (you can still scrape the
        # skeleton, even if results are gated)
        assert cls.is_blocking is False


# ============================================================
# End-to-end with the saved HTML
# ============================================================
class TestEndToEnd:
    def test_engine_parses_real_results(self, fixture_html):
        """The engine's parse_results_page, called with a
        stub page that returns the saved HTML, should yield
        10 real candidates."""
        e = NewspapersComEngine()

        class _Page:
            def __init__(self, html):
                self._html = html
            def content(self):
                return self._html
        page = _Page(fixture_html)
        cands = e.parse_results_page(page, "https://...")
        assert len(cands) == 10
        # Each has the expected fields
        for c in cands:
            assert "id" in c
            assert "href" in c
            assert "title" in c
            assert "iso_date" in c
            assert "location" in c

    def test_engine_scores_against_a_pensioner(self, fixture_html):
        """Score a real Newspapers.com result against a
        pensioner with a matching name and death year."""
        e = NewspapersComEngine()

        class _Page:
            def __init__(self, html):
                self._html = html
            def content(self):
                return self._html
        page = _Page(fixture_html)
        cands = e.parse_results_page(page, "https://...")

        # Score against a Smith born 1890 died 1950 (matches
        # the 1896 paper)
        ctx = SearchContext(
            first="John", last="Smith",
            birth_year="1890", death_year="1950",
            state="",
        )
        scored = []
        for c in cands:
            score, _ = e.score(ctx, c)
            scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        # At least one result should have a non-zero score
        # (the 1896 newspaper from Melbourne has the year in
        # window and the last name in title)
        max_score = scored[0][0]
        assert max_score > 0


# ============================================================
# End-to-end: NewspapersComEngine through the pipeline
# ============================================================
class TestEngineInPipeline:
    """The acceptance test for issue #36: a 2nd real engine
    runs through the pipeline unchanged. The orchestrator
    consumes the engine via config.engine; the result
    populates engine_result + fag_records (back-compat
    wire-format field)."""

    def test_newspapers_engine_runs_through_run_one(self, fixture_html):
        from scripts.pipeline.core import (
            PipelineConfig, run_one,
        )
        from scripts.search.record import from_pensioner
        from scripts.search.newspapers_engine import NewspapersComEngine

        class _StubPage:
            def __init__(self, html):
                self._html = html
            def goto(self, url, **kw):
                pass
            def title(self):
                return "John Smith - Search - Newspapers.com"
            def content(self):
                return self._html

        e = NewspapersComEngine()
        page = _StubPage(fixture_html)

        pensioner = {
            "id": 1,
            "first_name": "John",
            "last_name": "Smith",
            "birth_year": "1890",
            "death_year": "1950",
        }
        record = from_pensioner(pensioner)
        config = PipelineConfig(engine=e, page=page)
        result = run_one(record, [], config)

        # Pipeline ran the engine; results were captured
        assert result.engine_result is not None
        assert len(result.engine_result["candidates"]) == 10
        # fag_records is the back-compat field for the wire format
        assert len(result.fag_records) == 10
        # At least one candidate scored > 0 (last name match)
        scored = [c for c in result.fag_records if c.get("score", 0) > 0]
        assert len(scored) > 0

    def test_fake_newspapers_engine_in_test_search_engine(self):
        """A FakeNewspapersComEngine exists for the search
        engine protocol tests."""
        from scripts.search.engine import default_search_one

        from scripts.search.strategy import as_strategy as _as_strategy

        class FakeNewspapersComEngine:
            name = "newspapers_com_fake"
            base_url = "https://fake.example.com/"

            def __init__(self, candidates=None):
                self.ladder = [_as_strategy(
                    "FN1", lambda ctx: {"keyword": ctx.first or "x"},
                )]
                self._candidates = candidates or []

            def build_url(self, params):
                return self.base_url + "?" + str(params)
            def parse_results_page(self, page, url):
                return list(self._candidates)
            def score(self, ctx, candidate):
                return (0.5, {"fake": True})
            def classify_response(self, page):
                from scripts.search.engine import Classification
                class _N(Classification):
                    @property
                    def is_blocking(self): return False
                    @property
                    def is_normal(self): return True
                    @property
                    def value(self): return "normal"
                return _N()
            def apply_filters(self, params, ctx):
                return dict(params)
            def throttle_seconds(self):
                return 0.0

        e = FakeNewspapersComEngine(candidates=[{"id": "1", "title": "X"}])
        class _Page:
            def goto(self, url, **kw): pass
            def title(self): return ""
        ctx = SearchContext(first="John", last="Smith")
        result = default_search_one(e, _Page(), ctx)
        assert result["candidates"][0]["id"] == "1"


# ============================================================
# to_common_candidate (issue #39)
# ============================================================
class TestNewspapersToCommonCandidate:
    """NewspapersComEngine.to_common_candidate maps fields to common shape."""

    def test_basic_conversion(self):
        """Newspapers candidate fields map to common keys."""
        from scripts.search.newspapers_engine import NewspapersComEngine
        e = NewspapersComEngine()
        candidate = {
            "id": "12345",
            "title": "The Daily Oklahoman \u2022 Page 3",
            "href": "/image/12345/?match=1&terms=smith",
            "score": 0.6,
            "iso_date": "1896-08-22",
            "location": "Oklahoma City, Oklahoma, USA",
            "thumbnail": "/img/thumbnail/12345.jpg",
            "score_evidence": {
                "last_name_in_title": True,
                "state_in_location": True,
                "year_in_window": (1840, 1930),
            },
        }
        result = e.to_common_candidate(candidate)
        assert result["id"] == "12345"
        assert result["title"] == "The Daily Oklahoman \u2022 Page 3"
        assert result["url"] == "https://www.newspapers.com/image/12345/?match=1&terms=smith"
        assert result["score"] == 0.6
        assert result["attributes"]["date"] == "1896-08-22"
        assert result["attributes"]["location"] == "Oklahoma City, Oklahoma, USA"
        assert result["media"]["image_url"] == "/img/thumbnail/12345.jpg"
        assert result["evidence"]["score_breakdown"]["last_name_in_title"] is True
        assert result["evidence"]["raw"] is candidate

    def test_empty_candidate(self):
        """Empty candidate yields safe defaults."""
        from scripts.search.newspapers_engine import NewspapersComEngine
        e = NewspapersComEngine()
        result = e.to_common_candidate({})
        assert result["id"] == ""
        assert result["title"] == ""
        assert result["url"] == ""
        assert result["score"] == 0
        assert result["attributes"]["date"] == ""

    def test_missing_href(self):
        """Candidate without href produces empty url."""
        from scripts.search.newspapers_engine import NewspapersComEngine
        e = NewspapersComEngine()
        result = e.to_common_candidate({"id": "99", "title": "X"})
        assert result["url"] == ""
