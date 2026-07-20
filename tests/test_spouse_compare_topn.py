"""Tests for the top-N logic in scripts/cgr/spouse_compare.py.

Issue #14: allow top_n > 1 so a name-collision candidate ranked
first doesn't suppress a later ACW-era match.

The annotate_records function is too entangled with playwright
to call directly. We patch playwright.sync_api.sync_playwright
+ playwright_stealth.Stealth + scripts.fag.spouse_scrape.scrape_and_compare
so annotate_records can run against a stub page.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.cgr.spouse_compare import annotate_records
from scripts.fag.spouse_scrape import parse_spouse_from_html


# A canonical Mitchell Ward Slemp page fixture that the parser
# recognizes. Mirrors SAMPLE_HTML_MARGARET (memorial 42943220)
# but for memorial 12345678 (the rank-2 candidate in our
# tests). Local expected spouse is "Mitchell Ward Slemp".
SAMPLE_HTML_MITCHELL_12345678 = """\
<!DOCTYPE html><html><body>
<h1>Some Wrong Veteran</h1>
<h2>Family Members</h2>

<div><b id="spouseLabel" class="label-relation">Spouse</b>
<ul class="member-family" aria-labelledby="spouseLabel">
  <li itemscope itemtype="https://schema.org/Person">
    <a class="d-block text-decoration-none" href="/memorial/12345678/mitchell_ward-slemp" itemprop="url">
      <div class="member-item d-flex mb-2">
        <span itemprop="name">Mitchell Ward Slemp</span>
        <span>1845-1904</span>
      </div>
    </a>
    (m. 1874)
  </li>
</ul></div>

<h2>Inscription</h2>
</body></html>"""


# Empty memorial pages (no Family Members > Spouse section).
HTML_NO_SPOUSE_A = "<html><body>No family members here</body></html>"
HTML_NO_SPOUSE_B = "<html><body>Another no-spouse page</body></html>"
HTML_NO_SPOUSE_C = "<html><body>Third no-spouse page</body></html>"


class _StubPage:
    """Fake playwright Page that returns canned HTML based on the
    URL it navigates to."""

    def __init__(self, html_by_id: dict[str, str]):
        self._html = html_by_id
        self.visits: list[str] = []

    def goto(self, url: str, **kwargs):
        self.visits.append(url)

    def content(self) -> str:
        for mem_id, html in self._html.items():
            if f"/memorial/{mem_id}/" in self.visits[-1]:
                return html
        return ""

    def wait_for_selector(self, *args, **kwargs):
        pass

    def wait_for_timeout(self, *args, **kwargs):
        pass


class _StubContext:
    def __init__(self, page):
        self._page = page

    def new_page(self):
        return self._page

    def close(self):
        pass


class _StubBrowser:
    """Stand-in for pw.chromium - the .launch() returns a browser
    that responds to .new_context()."""

    def __init__(self, page):
        self._page = page

    def new_context(self, **kwargs):
        return _StubContext(self._page)

    def close(self):
        pass


def _stub_pw_factory(page):
    """Returns a fake sync_playwright() context manager that
    yields a pw whose .chromium.launch() returns a browser wired
    to the given stub page."""

    class _StubPW:
        def __init__(self, page):
            self._page = page

        def __enter__(self):
            self.chromium = _StubBrowserLauncher(self._page)
            self.chromium.launch = self.chromium.launch
            return self

        def __exit__(self, *a):
            return False

    return _StubPW(page)


class _StubBrowserLauncher:
    def __init__(self, page):
        self._page = page

    def launch(self, headless=True):
        return _StubBrowser(self._page)


class _NoOpStealth:
    """Fake Stealth class; apply_stealth_sync is a no-op."""

    def apply_stealth_sync(self, ctx):
        pass


@pytest.fixture
def patch_playwright(monkeypatch):
    """Patch playwright + stealth + scrape_and_compare so
    annotate_records can run against a stub page. Returns a
    state dict the test can poke at."""

    state: dict = {"page": None, "html_map": {}}

    from scripts.fag import spouse_scrape

    def make_fake_scrape(html_map):
        def fake(page, cand, local, throttle_seconds=0.0):
            mid = str(cand.get("memorial_id") or cand.get("id") or "")
            slug = cand.get("slug") or ""
            # Mirror real scrape_and_compare: navigate first, so
            # the stub page records the URL.
            try:
                page.goto(f"https://www.findagrave.com/memorial/{mid}/{slug}")
            except Exception:
                pass
            html = html_map.get(mid, "")
            captured = parse_spouse_from_html(html)
            if captured is None:
                return None
            return spouse_scrape.compare_spouses(local, captured)
        return fake

    def install_fake(html_map):
        # The function is locally imported inside annotate_records,
        # so we patch the source module: scripts.fag.spouse_scrape
        fake = make_fake_scrape(html_map)
        spouse_scrape.scrape_and_compare = fake
        # Also patch in spouse_compare.py's namespace as a
        # belt-and-suspenders in case the import resolves to the
        # module-level attribute.
        import scripts.cgr.spouse_compare as sc
        sc.scrape_and_compare = fake

    # Patch playwright.sync_api.sync_playwright at the source
    # module level. This is what scripts/cgr/spouse_compare.py
    # imports lazily.
    import playwright.sync_api as pw_sync_api
    monkeypatch.setattr(pw_sync_api, "sync_playwright", lambda: _stub_pw_factory(state["page"]))

    # Patch playwright_stealth.Stealth similarly.
    try:
        import playwright_stealth as pw_stealth
        monkeypatch.setattr(pw_stealth, "Stealth", _NoOpStealth)
    except ImportError:
        pass

    # Patch scrape_and_compare.
    monkeypatch.setattr(spouse_scrape, "scrape_and_compare", make_fake_scrape(state["html_map"]))

    return state, install_fake


def _make_results_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _read_first(path: Path) -> dict:
    out = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l]
    return out[0]


def test_top_n_1_default_skips_non_top_candidate(tmp_path, patch_playwright):
    """When top_n=1, a match at rank > 1 is NOT found."""
    state, install_fake = patch_playwright
    html_map = {
        "12345678": SAMPLE_HTML_MITCHELL_12345678,
        "9999": HTML_NO_SPOUSE_A,
        "8888": HTML_NO_SPOUSE_B,
    }
    state["page"] = _StubPage(html_map)
    state["html_map"] = html_map
    install_fake(html_map)

    results = tmp_path / "results.jsonl"
    rec = {
        "pensioner_id": 1,
        "pensioner_spouse_first": "Mitchell",
        "pensioner_spouse_middle": "Ward",
        "pensioner_spouse_last": "Slemp",
        "fag_records": [
            {"memorial_id": 9999, "slug": "wrong-1"},
            {"memorial_id": 12345678, "slug": "mitchell_ward-slemp"},
            {"memorial_id": 8888, "slug": "wrong-2"},
        ],
    }
    _make_results_jsonl(results, [rec])

    stats = annotate_records(results, top_n=1, throttle_seconds=0, headless=True)

    assert stats["matched"] == 0
    assert stats["total_with_spouse"] == 1
    assert any("/9999/" in v for v in state["page"].visits), \
        f"rank-1 candidate 9999 should be visited; got: {state['page'].visits}"
    assert not any("/12345678/" in v for v in state["page"].visits), \
        f"rank-2 should NOT be visited at top_n=1; got: {state['page'].visits}"


def test_top_n_3_finds_rank_2_match(tmp_path, patch_playwright):
    """top_n=3 finds the rank-2 match; rank 3 is skipped after the match."""
    state, install_fake = patch_playwright
    html_map = {
        "12345678": SAMPLE_HTML_MITCHELL_12345678,
        "9999": HTML_NO_SPOUSE_A,
        "8888": HTML_NO_SPOUSE_B,
    }
    state["page"] = _StubPage(html_map)
    state["html_map"] = html_map
    install_fake(html_map)

    results = tmp_path / "results.jsonl"
    rec = {
        "pensioner_id": 1,
        "pensioner_spouse_first": "Mitchell",
        "pensioner_spouse_middle": "Ward",
        "pensioner_spouse_last": "Slemp",
        "fag_records": [
            {"memorial_id": 9999, "slug": "wrong-1"},
            {"memorial_id": 12345678, "slug": "mitchell_ward-slemp"},
            {"memorial_id": 8888, "slug": "wrong-2"},
        ],
    }
    _make_results_jsonl(results, [rec])

    stats = annotate_records(results, top_n=3, throttle_seconds=0, headless=True)

    assert stats["matched"] == 1
    assert stats["matched_rank_histogram"].get("2") == 1

    written = _read_first(results)
    assert written["spouse_match"] is not None
    assert written["spouse_match"]["matched_via_rank"] == 2
    assert len(written["spouse_candidates"]) == 3

    cands = written["spouse_candidates"]
    assert cands[0]["rank"] == 1
    assert cands[0]["match"] is None  # rank-1 had no spouse section
    assert cands[1]["rank"] == 2
    assert cands[1]["match"] is not None
    assert cands[1]["match"]["matched"] is True
    assert cands[1]["match"]["matched_via_rank"] == 2
    assert cands[1]["match"]["match_strength"] == "strong"
    # Rank-3 was skipped after we found the match at rank 2.
    assert cands[2]["rank"] == 3
    assert cands[2]["match"]["skipped"] is True


def test_top_n_3_no_match_writes_three_candidates(tmp_path, patch_playwright):
    """When no candidate matches, spouse_match is None but all
    candidates are recorded (audit trail)."""
    state, install_fake = patch_playwright
    html_map = {
        "9999": HTML_NO_SPOUSE_A,
        "8888": HTML_NO_SPOUSE_B,
        "7777": HTML_NO_SPOUSE_C,
    }
    state["page"] = _StubPage(html_map)
    state["html_map"] = html_map
    install_fake(html_map)

    results = tmp_path / "results.jsonl"
    rec = {
        "pensioner_id": 1,
        "pensioner_spouse_first": "Mitchell",
        "pensioner_spouse_middle": "Ward",
        "pensioner_spouse_last": "Slemp",
        "fag_records": [
            {"memorial_id": 9999, "slug": "wrong-1"},
            {"memorial_id": 8888, "slug": "wrong-2"},
            {"memorial_id": 7777, "slug": "wrong-3"},
        ],
    }
    _make_results_jsonl(results, [rec])

    stats = annotate_records(results, top_n=3, throttle_seconds=0, headless=True)

    assert stats["matched"] == 0
    assert stats["total_with_spouse"] == 3

    written = _read_first(results)
    assert written["spouse_match"] is None
    assert len(written["spouse_candidates"]) == 3
    for c in written["spouse_candidates"]:
        assert c["match"] is None  # no captures matched the local spouse


def test_top_n_caps_at_fag_records_length(tmp_path, patch_playwright):
    """top_n=5 with only 2 candidates writes 2 candidate entries."""
    state, install_fake = patch_playwright
    html_map = {
        "9999": HTML_NO_SPOUSE_A,
        "8888": HTML_NO_SPOUSE_B,
    }
    state["page"] = _StubPage(html_map)
    state["html_map"] = html_map
    install_fake(html_map)

    results = tmp_path / "results.jsonl"
    rec = {
        "pensioner_id": 1,
        "pensioner_spouse_first": "Mitchell",
        "pensioner_spouse_middle": "Ward",
        "pensioner_spouse_last": "Slemp",
        "fag_records": [
            {"memorial_id": 9999, "slug": "wrong-1"},
            {"memorial_id": 8888, "slug": "wrong-2"},
        ],
    }
    _make_results_jsonl(results, [rec])

    annotate_records(results, top_n=5, throttle_seconds=0, headless=True)

    written = _read_first(results)
    assert len(written["spouse_candidates"]) == 2


def test_no_spouse_data_writes_empty_candidates(tmp_path, patch_playwright):
    """Records without pensioner_spouse_* get empty candidates."""
    state, install_fake = patch_playwright
    state["page"] = _StubPage({})
    state["html_map"] = {}
    install_fake({})

    results = tmp_path / "results.jsonl"
    rec = {
        "pensioner_id": 1,
        "pensioner_spouse_first": "",
        "pensioner_spouse_middle": "",
        "pensioner_spouse_last": "",
        "fag_records": [{"memorial_id": 9999, "slug": "x"}],
    }
    _make_results_jsonl(results, [rec])

    stats = annotate_records(results, top_n=3, throttle_seconds=0, headless=True)

    assert stats["matched"] == 0
    assert stats["total_with_spouse"] == 0
    written = _read_first(results)
    assert written["spouse_match"] is None
    assert written["spouse_candidates"] == []


def test_view_html_rank_note_in_badge_when_match_at_rank_2():
    """view.html renderSpouseMatchBadge surfaces rank>1 in the title
    and badge text. Regression test for #14."""
    src = Path("scripts/view.html").read_text(encoding="utf-8")
    m = re.search(
        r"function\s+renderSpouseMatchBadge\s*\(\s*p\s*\)[\s\S]{0,2200}?\n\s*\}\s*\n",
        src,
    )
    assert m, "renderSpouseMatchBadge body not found"
    body = m.group(0)
    assert "matched_via_rank" in body, \
        "badge must read m.matched_via_rank (issue #14 top-N match position)"
    assert "rank" in body.lower()
    assert "rank > 1" in body or "rankNote" in body

# ============================================================
# Issue #13: per-run memorial-page cache + lower scrape throttle
# ============================================================
class TestSpouseScrapeThrottle:
    """The scrape pass only navigates to one trusted URL pattern
    (/memorial/<id>/<slug>), already warmed up. It doesn't need
    the 1.5s throttle the strategy ladder needs."""

    def test_scrape_throttle_default_is_smaller_than_search(self):
        """Default scrape throttle must be 0.5s, not 1.5s. Pinned
        as a constant (SCRAPE_THROTTLE_SECONDS) so a future bump
        in the search throttle doesn't accidentally double-apply."""
        from scripts.cgr import spouse_compare
        assert hasattr(spouse_compare, "SCRAPE_THROTTLE_SECONDS"), (
            "SCRAPE_THROTTLE_SECONDS constant missing (issue #13)"
        )
        assert spouse_compare.SCRAPE_THROTTLE_SECONDS == 0.5
        # The scrape throttle must be smaller than the search
        # throttle the pipeline uses (2.5s floor per throttle law)
        assert spouse_compare.SCRAPE_THROTTLE_SECONDS < 2.5

    def test_cli_default_throttle_is_scrape_value(self, monkeypatch):
        """CLI's --throttle default must read from the constant,
        not a hardcoded 1.5."""
        from scripts.cgr import spouse_compare
        p = spouse_compare.cli_main(["--results", "/nonexistent/results.jsonl"])
        # We get rc=0 with "nothing to do" stderr because FAG_SCRAPE_SPOUSE
        # isn't set, but the argparse default should already be wired.
        # Test by reading the parser defaults directly.
        import argparse
        # Construct a parser like cli_main does
        parser = argparse.ArgumentParser()
        parser.add_argument("--throttle", type=float,
                            default=spouse_compare.SCRAPE_THROTTLE_SECONDS)
        ns = parser.parse_args([])
        assert ns.throttle == spouse_compare.SCRAPE_THROTTLE_SECONDS


class TestSpouseMemorialCache:
    """Per-run cache: memorial-page responses are reused across
    pensioners that share the same husband's memorial. Persists
    to output/<runname>/memorial_cache.jsonl so a re-run can
    reuse it; expires by mtime after N days."""

    def test_cache_key_is_memorial_id_plus_slug(self, tmp_path):
        """Cache key: (memorial_id, slug). Two pensioners pointing
        to the same memorial share the cache entry."""
        from scripts.cgr.spouse_compare import _MemorialCache
        cache = _MemorialCache(tmp_path / "memorial_cache.jsonl")
        cache.put("12345", "john-doe", "<html>page A</html>")
        # Same memorial, different cache instance → hits the file.
        cache2 = _MemorialCache(tmp_path / "memorial_cache.jsonl")
        assert cache2.get("12345", "john-doe") == "<html>page A</html>"

    def test_cache_different_slugs_are_separate_entries(self, tmp_path):
        """Same memorial_id with different slug is a separate
        entry. Slug matters for human-readable URLs but the
        HTML body is per-memorial — we use (id, slug) as the
        key to stay conservative."""
        from scripts.cgr.spouse_compare import _MemorialCache
        cache = _MemorialCache(tmp_path / "memorial_cache.jsonl")
        cache.put("12345", "slug-a", "<html>A</html>")
        cache.put("12345", "slug-b", "<html>B</html>")
        assert cache.get("12345", "slug-a") == "<html>A</html>"
        assert cache.get("12345", "slug-b") == "<html>B</html>"

    def test_cache_miss_returns_none(self, tmp_path):
        from scripts.cgr.spouse_compare import _MemorialCache
        cache = _MemorialCache(tmp_path / "memorial_cache.jsonl")
        assert cache.get("99999", "nobody") is None

    def test_cache_expires_after_ttl_days(self, tmp_path):
        """Cache entries older than TTL are invalid. Default TTL
        is 7 days; a file with mtime 30 days ago is treated as
        miss even if it has content."""
        from scripts.cgr.spouse_compare import _MemorialCache
        cache_path = tmp_path / "memorial_cache.jsonl"
        cache = _MemorialCache(cache_path, ttl_days=7)
        cache.put("12345", "john-doe", "<html>stale</html>")
        # Backdate the mtime to 30 days ago
        import os, time
        old_time = time.time() - (30 * 86400)
        os.utime(cache_path, (old_time, old_time))
        # Re-open: should treat as miss
        cache2 = _MemorialCache(cache_path, ttl_days=7)
        assert cache2.get("12345", "john-doe") is None

    def test_annotate_uses_cache_for_shared_memorials(self, tmp_path, patch_playwright):
        """Two pensioners sharing the same husband's memorial: the
        second pensioner should NOT trigger a second navigation.
        The cache hit is recorded in the returned stats."""
        state, install_fake = patch_playwright
        html_map = {
            "42943220": SAMPLE_HTML_MITCHELL_12345678,
        }
        state["page"] = _StubPage(html_map)
        state["html_map"] = html_map
        install_fake(html_map)

        # Pre-seed the cache with the response
        from scripts.cgr.spouse_compare import _MemorialCache
        cache_path = tmp_path / "memorial_cache.jsonl"
        cache = _MemorialCache(cache_path)
        cache.put("42943220", "mitchell_ward-slemp", SAMPLE_HTML_MITCHELL_12345678)

        results = tmp_path / "results.jsonl"
        records = [
            {
                "pensioner_id": 1,
                "pensioner_first": "Margaret",
                "pensioner_last": "Slemp",
                "pensioner_spouse_first": "Mitchell",
                "pensioner_spouse_middle": "Ward",
                "pensioner_spouse_last": "Slemp",
                "fag_records": [
                    {"memorial_id": 42943220, "slug": "mitchell_ward-slemp"},
                ],
            },
            {
                "pensioner_id": 2,
                "pensioner_first": "Sarah",
                "pensioner_last": "Jones",
                "pensioner_spouse_first": "Mitchell",
                "pensioner_spouse_middle": "Ward",
                "pensioner_spouse_last": "Slemp",
                "fag_records": [
                    {"memorial_id": 42943220, "slug": "mitchell_ward-slemp"},
                ],
            },
        ]
        _make_results_jsonl(results, records)

        stats = annotate_records(
            results, top_n=1, throttle_seconds=0, headless=True,
            cache=cache,
        )
        # Both should match
        assert stats["matched"] == 2
        # Neither should have navigated: both hits served from
        # the pre-seeded cache.
        mitchell_visits = [v for v in state["page"].visits if "/42943220/" in v]
        assert len(mitchell_visits) == 0, (
            f"cached responses should not trigger navigation; "
            f"got visits: {state['page'].visits}"
        )
        # Cache hit stat recorded (one hit per candidate; 2 here)
        assert stats.get("cache_hits", 0) >= 2


# ============================================================
# Issue #16: separate spouse follow-up pane for deceased husbands
# ============================================================
class TestSpouseFollowupEmission:
    """When spouse_compare finds a match, emit a separate
    follow-up record to <results_dir>/spouse_followups.jsonl.
    NOT a synthetic entry in the main results.jsonl — the
    deceased husband is not a pensioner."""

    def test_emit_writes_followup_jsonl(self, tmp_path, patch_playwright):
        """A widow with a spouse_match generates one followup
        record. Non-widow records generate none."""
        state, install_fake = patch_playwright
        html_map = {
            "12345678": SAMPLE_HTML_MITCHELL_12345678,
        }
        state["page"] = _StubPage(html_map)
        state["html_map"] = html_map
        install_fake(html_map)

        results = tmp_path / "results.jsonl"
        # Widow Margaret Slemp with a husband match
        widow = {
            "pensioner_id": 2577,
            "pensioner_first": "Margaret",
            "pensioner_last": "Slemp",
            "pensioner_spouse_first": "Mitchell",
            "pensioner_spouse_middle": "Ward",
            "pensioner_spouse_last": "Slemp",
            "fag_records": [
                {"memorial_id": 12345678, "slug": "mitchell_ward-slemp"},
            ],
        }
        # Non-widow (no spouse data)
        non_widow = {
            "pensioner_id": 100,
            "pensioner_first": "John",
            "pensioner_last": "Smith",
            "pensioner_spouse_first": "",
            "pensioner_spouse_middle": "",
            "pensioner_spouse_last": "",
            "fag_records": [
                {"memorial_id": 99999, "slug": "john-smith"},
            ],
        }
        _make_results_jsonl(results, [widow, non_widow])

        # Run annotate_records first so spouse_match is populated
        # (the realistic flow). Then emit follow-ups.
        annotate_records(
            results, top_n=1, throttle_seconds=0, headless=True,
        )
        from scripts.cgr.spouse_compare import emit_spouse_followups
        count = emit_spouse_followups(
            results_path=results,
            out_path=tmp_path / "spouse_followups.jsonl",
        )
        assert count == 1
        followup_path = tmp_path / "spouse_followups.jsonl"
        assert followup_path.exists()
        records = [json.loads(l) for l in followup_path.read_text(
            encoding="utf-8").splitlines() if l]
        assert len(records) == 1
        r = records[0]
        assert r["widow_pensioner_id"] == 2577
        assert r["widow_name"] == "Margaret Slemp"
        assert r["from_top_candidate"] == 12345678
        assert r["spouse_captured_first"] == "Mitchell"
        assert r["spouse_captured_middle"] == "Ward"
        assert r["spouse_captured_last"] == "Slemp"
        assert r["spouse_captured_display"] == "Mitchell Ward Slemp"
        assert r["spouse_captured_memorial_id"] == "12345678"
        assert r["spouse_captured_slug"] == "mitchell_ward-slemp"
        assert r["spouse_captured_marriage_year"] == "1874"
        assert "no ACW pension" in r["spouse_role_label"]
        assert r["spouse_research_state"] == "needs_research"
        assert "captured_at" in r

    def test_emit_no_match_writes_nothing(self, tmp_path, patch_playwright):
        """Records without spouse_match generate no followup."""
        state, install_fake = patch_playwright
        html_map = {"9999": HTML_NO_SPOUSE_A}
        state["page"] = _StubPage(html_map)
        state["html_map"] = html_map
        install_fake(html_map)

        results = tmp_path / "results.jsonl"
        rec = {
            "pensioner_id": 1,
            "pensioner_first": "John",
            "pensioner_last": "Smith",
            "pensioner_spouse_first": "Jane",
            "pensioner_spouse_middle": "",
            "pensioner_spouse_last": "Smith",
            "fag_records": [{"memorial_id": 9999, "slug": "nobody"}],
        }
        _make_results_jsonl(results, [rec])

        from scripts.cgr.spouse_compare import emit_spouse_followups
        count = emit_spouse_followups(
            results_path=results,
            out_path=tmp_path / "spouse_followups.jsonl",
        )
        assert count == 0
        assert not (tmp_path / "spouse_followups.jsonl").exists()

    def test_emit_appends_does_not_overwrite(self, tmp_path, patch_playwright):
        """Re-running emit on the same path appends. Useful for
        a resume-friendly flow where the followup file is the
        audit log."""
        state, install_fake = patch_playwright
        html_map = {"12345678": SAMPLE_HTML_MITCHELL_12345678}
        state["page"] = _StubPage(html_map)
        state["html_map"] = html_map
        install_fake(html_map)

        results = tmp_path / "results.jsonl"
        rec = {
            "pensioner_id": 2577,
            "pensioner_first": "Margaret",
            "pensioner_last": "Slemp",
            "pensioner_spouse_first": "Mitchell",
            "pensioner_spouse_middle": "Ward",
            "pensioner_spouse_last": "Slemp",
            "fag_records": [
                {"memorial_id": 12345678, "slug": "mitchell_ward-slemp"},
            ],
        }
        _make_results_jsonl(results, [rec])

        annotate_records(
            results, top_n=1, throttle_seconds=0, headless=True,
        )
        from scripts.cgr.spouse_compare import emit_spouse_followups
        out = tmp_path / "spouse_followups.jsonl"
        emit_spouse_followups(results, out)
        # Second call appends; no dedupe, the file is the log
        emit_spouse_followups(results, out)
        lines = [l for l in out.read_text(encoding="utf-8").splitlines() if l]
        assert len(lines) == 2
