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