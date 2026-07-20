# Search abstraction — adding strategies and engines

> **Tier:** 1 (load when adding a new strategy or a new search
> backend). Token cost: ~3K.

The search layer has three concentric abstractions. From the
inside out:

```
        ┌────────────────────────────────────────┐
        │           SearchContext                │  (input)
        └──────────────┬─────────────────────────┘
                       │ (built from SearchRecord)
        ┌──────────────┴─────────────────────────┐
        │             Strategy                   │  (URL params)
        │     "given a record, build params"      │
        └──────────────┬─────────────────────────┘
                       │ list[Strategy] = ladder
        ┌──────────────┴─────────────────────────┐
        │            SearchEngine                 │  (HTTP + parse)
        │   "build URL, fetch, parse, score"      │
        └──────────────┬─────────────────────────┘
                       │ (orchestrator calls run_one)
        ┌──────────────┴─────────────────────────┐
        │           Pipeline                      │  (compose)
        │   run_one(record, cgr_index, engine)    │
        └──────────────────────────────────────────┘
```

A new strategy changes only the URL-params layer. A new engine
changes only the HTTP-parse-score layer. A new record type
changes only the input. The layers don't leak into each other.

---

## When to add what

| You want to... | Add a... | File |
|---|---|---|
| Search by nickname, by initials, by date, by regiment keyword, with a new URL-param combination | **Strategy** | `scripts/search/strategies.py` or `scripts/search/fag_strategies.py` |
| A new search backend (Ancestry, FamilySearch, Newspapers.com, your local DB, ...) | **SearchEngine** | `scripts/search/<your_engine>.py` |
| A new input source (your own family tree, a CSV import, a JSON dump, ...) | **SearchRecord builder** | `scripts/search/record.py::from_<your_source>` |
| A new strategy that's "I want to write Python for the URL logic" | **Function-form strategy** (this doc §1) |
| A new strategy that's "I just want a dict, no Python" | **Template-form strategy** (this doc §2) |
| A new engine that does text search → ranked results | Use the `SearchEngine` Protocol; 2nd engine already exists as a worked example (this doc §3) |

---

## 1. Adding a function-form strategy

A function-form strategy is a plain Python function that takes
a `SearchContext` and returns either a dict of URL params (or
None to skip). The cleanest form:

```python
# scripts/search/strategies.py (or a domain-specific file)

from scripts.search.context import SearchContext
from scripts.search.strategy import as_strategy


def my_new_strategy(ctx: SearchContext):
    """Short description of what this strategy does.

    Guard: only fire if the context has what we need.
    """
    if not ctx.first and not ctx.last:
        return None
    return {
        "firstname": ctx.first,
        "lastname": ctx.last,
        "middlename": ctx.middle,
        "extra_param": "some_value",
    }


# Add to the ladder:
STRATEGIES.append(as_strategy("X1-my-new-strategy", my_new_strategy))
```

The function can read **any** field on the context (see §5 for
the full list). It MUST NOT mutate the context. It MUST return
either a dict (engine-specific URL params) or `None` (skip).

Test it. The strategy's behavior is a pure function; the test
suite has a `FakeSearchEngine` you can use to test the params
without hitting a real backend.

```python
# tests/test_my_strategies.py

from scripts.search.context import SearchContext
from scripts.search.strategies import my_new_strategy


def test_my_new_strategy_with_full_name():
    ctx = SearchContext(first="John", last="Smith")
    out = my_new_strategy(ctx)
    assert out == {
        "firstname": "John",
        "lastname": "Smith",
        "middlename": "",
        "extra_param": "some_value",
    }


def test_my_new_strategy_skips_when_no_name():
    ctx = SearchContext()
    assert my_new_strategy(ctx) is None
```

---

## 2. Adding a template-form strategy (YAML / dict DSL)

The template DSL is for the 90% of strategies that are "static
dict with a few substitutions + conditionals." No Python
required.

```python
# scripts/search/templates.py (or wherever you keep the
# template specs for your domain)

from scripts.search.template import TemplateStrategy


MY_NEW_STRATEGY = TemplateStrategy.from_spec({
    "name": "X1-template",
    "description": "One-line description of what this does.",
    "applies_when": ["first", "last"],   # core fields required
    "params": {
        "firstname": "{first}",
        "lastname": "{last}",
        "middlename?": "{middle}",          # ? = conditional include
        "exactspelling": "true",
        # A transform: drop the apostrophe in last name
        "lastname_clean": {
            "transform": "replace",
            "input": "{last}",
            "args": ["'", ""],
        },
    },
})
```

DSL features:

| Pattern | Meaning |
|---|---|
| `"value"` | Literal string, used as-is |
| `"{first}"` | Substitute `ctx.first` |
| `"{extra.regiment}"` | Substitute `ctx.extra("regiment")` |
| `"key?"` | Conditional: include `key` only if value is truthy |
| `{"transform": "replace", "input": "{last}", "args": ["'", ""]}` | Apply the named transform to the input |
| `{"value": "..."}` | Explicit value (same as just the string) |

Built-in transforms: `replace`, `slice`, `format`, `upper`,
`lower`, `choice`. No user code execution. The DSL is closed;
any logic Python needs that the DSL can't express belongs in
a function-form strategy (see §1).

Test it:

```python
def test_my_template_strategy_runs():
    from scripts.search.context import SearchContext
    from scripts.search.templates import MY_NEW_STRATEGY

    ctx = SearchContext(first="John", last="O'Brien")
    out = MY_NEW_STRATEGY.params(ctx)
    assert out is not None
    assert out["firstname"] == "John"
    # The replace transform ran
    assert out["lastname_clean"] == "OBrien"
    # Empty middle → middlename omitted
    assert "middlename" not in out
```

---

## 3. Adding a 2nd search engine

A `SearchEngine` is the unit that talks to one specific search
backend. Adding a new engine is a 1-2 week project (per the
estimate in the 2nd-engine planning issue, #36). The shape:

```python
# scripts/search/<your_engine>.py

from typing import Any
from urllib.parse import urlencode
import re

from scripts.search.context import SearchContext
from scripts.search.engine import Classification, SearchEngine
from scripts.search.strategy import FunctionStrategy


BASE_URL = "https://your-engine.example.com/search"


# ----- A few small strategies (URL-shape for this engine) -----

def _strategy_keyword(ctx: SearchContext):
    if not ctx.first and not ctx.last:
        return None
    return {
        "q": " ".join(filter(None, (ctx.first, ctx.middle, ctx.last))),
        "year_start": ctx.birth_year or "",
    }


# ----- The engine itself -----

class YourEngine:
    """A new search backend.

    Implements the 6 SearchEngine building blocks:
    build_url, parse_results_page, score, classify_response,
    apply_filters, throttle_seconds.
    """

    name = "your_engine"
    base_url = BASE_URL
    ladder = [FunctionStrategy("Y1-keyword", _strategy_keyword)]

    def build_url(self, params: dict) -> str:
        return BASE_URL + "?" + urlencode(params)

    def parse_results_page(self, page, url: str) -> list[dict]:
        """Parse the engine's HTML into a list of candidates.
        Each candidate has at minimum: id, title (or whatever
        your engine surfaces). The score() function decides
        what fields to weight."""
        html = page.content()
        results = []
        for m in re.finditer(
            r'<div class="result" id="(\d+)">(.*?)</div>',
            html, re.DOTALL,
        ):
            results.append({
                "id": m.group(1),
                "title": m.group(2).strip(),
            })
        return results

    def score(
        self, ctx: SearchContext, candidate: dict,
    ) -> tuple[float, dict]:
        """Score a candidate against the local context.
        Returns (score, evidence). Score in [0, 1]."""
        score = 0.0
        evidence = {}
        if ctx.last and ctx.last.lower() in candidate.get("title", "").lower():
            score += 0.4
            evidence["last_name_in_title"] = True
        return min(score, 1.0), evidence

    def classify_response(self, page) -> Classification:
        """Classify the response: normal, paywall, captcha, etc.
        Override Classification and set is_blocking=True for
        pages the runner should back off from."""
        # Default: assume normal; override per engine
        class _N(Classification):
            @property
            def is_blocking(self): return False
            @property
            def is_normal(self): return True
            @property
            def value(self): return "normal"
        return _N()

    def apply_filters(
        self, params: dict, ctx: SearchContext,
    ) -> dict:
        """Apply engine-specific URL-param filters (location,
        year window, etc.). Return a NEW params dict."""
        return dict(params)

    def throttle_seconds(self) -> float:
        """Inter-request throttle. Default: 1.0s (lenient).
        Engines with stricter rate limits (e.g. FaG) override
        to 2.5s+."""
        return 1.0
```

The engine is now usable anywhere a `SearchEngine` is expected.
Plug it into the pipeline via `config.engine`:

```python
from scripts.search.your_engine import YourEngine
from scripts.pipeline.core import PipelineConfig, run_one
from scripts.search.record import from_pensioner

config = PipelineConfig(
    engine=YourEngine(),
    page=playwright_page,  # or a stub for tests
)
record = from_pensioner(pensioner_dict)
result = run_one(record, [], config)
```

A worked example lives in `scripts/search/newspapers_engine.py`
(2nd engine, ~600 lines including 3 strategies + parser +
scorer + classifier). The engine's test file
`tests/test_newspapers_engine.py` is a complete reference for
how to test a new engine.

---

## 4. Where the abstractions live

| Module | Purpose |
|---|---|
| `scripts/search/context.py` | `SearchContext` dataclass + `from_pensioner` |
| `scripts/search/strategy.py` | `Strategy` Protocol + `FunctionStrategy` |
| `scripts/search/ladder.py` | `run_ladder()` (mode="first" or mode="all") |
| `scripts/search/strategies.py` | 10 generic FaG-shape strategies + positional shims |
| `scripts/search/fag_strategies.py` | F2/F3 (regiment, nickname) + F4 (follow-up) for FaG |
| `scripts/search/templates.py` | Sample template-form strategies |
| `scripts/search/template.py` | `TemplateStrategy` + the DSL |
| `scripts/search/record.py` | `SearchRecord` + `from_pensioner` / `to_pensioner_dict` |
| `scripts/search/engine.py` | `SearchEngine` Protocol + `default_search_one` + `to_common_candidate` |
| `scripts/search/fag_engine.py` | `FaGEngine` (1st implementation; 13 strategies) |
| `scripts/search/newspapers_engine.py` | `NewspapersComEngine` (2nd implementation; 3 strategies) |
| `scripts/search/record_fag_adapter.py` | Bridge: pensioner dict → SearchRecord → engine |

The Blackboard layer (`scripts/blackboard/`) wraps the
abstractions: `FaGScraperKS` consumes an engine, emits
`FaGSearchExecuted` observations. `RegionalPlannerKS` emits
`QueryPlan` work items the engine consumes via
`engine.ordered_ladder(ctx)` (when a `PlanRanker` is
registered; otherwise the static ladder order applies).

FaG-specific orchestration (CAPTCHA waits, 1015 backoff,
per-strategy throttle) lives in `BrowserSession` +
`RequestGate` + `ResponseClassifier` under
`scripts/blackboard/` (provider safety layer). The engine
path itself uses the simpler `default_search_one` flow.

---

## 5. `SearchContext` reference

The context is what strategies see. Core fields:

| Field | Type | Example |
|---|---|---|
| `first` | str | "Margaret" |
| `middle` | str | "Ward" |
| `last` | str | "Slemp" |
| `birth_year` | str | "1845" ("" if unknown) |
| `death_year` | str | "1925" ("" if unknown) |
| `state` | str | "OK" ("" if unknown) |
| `extras` | Mapping | `{"regiment": "CSA", "pensioner_app_number": "12345"}` |

Helpers:
- `ctx.has("first", "last")` — True iff all named fields are non-empty.
- `ctx.extra("regiment", "")` — read a domain-specific extra.
- `ctx.first / middle / last` — derived from `primary_name` on `SearchRecord`.

For function-form strategies, prefer `ctx.has("first", "last")`
at the top as a guard. For template-form strategies, use
`applies_when: ["first", "last"]` for the same effect.

---

## 6. Quick check: did my new strategy run?

The orchestrator's `result.engine_result` carries the run
summary:

```python
result = run_one(record, [], config)
# result.engine_result["candidates"] — list of scored candidates
# result.engine_result["strategies_run"] — list of strategy names that fired
# result.engine_result["classification"] — "normal" / "paywall" / etc.
# result.engine_result["error"] — non-None if any strategy raised
```

If your strategy didn't run, check:
- Is it in the ladder? (`engine.ladder` should include it.)
- Did `applies_when` filter it out? (For template-form.)
- Did the guard `if not ctx.first` reject it? (For function-form.)
- Did `build_url` raise? (Check the engine's URL builder.)

---

## 7. Quick check: did my new engine run?

If `result.engine_result["candidates"]` is empty:
- `parse_results_page` returned an empty list. Check the DOM
  selectors. Save the HTML to `data/probe/<engine>_q_<label>.html`
  and parse it offline.
- `classify_response` returned "paywall" or "challenge". Your
  account isn't logged in, or the engine has anti-bot. Check
  the page title in the browser.
- The orchestrator caught an exception. Check
  `result.engine_result["error"]`.

---

## 8. Engine-agnostic common shape

Every engine that wants to play with the v2 view, the
Blackboard Projector, or the scraper export must implement
`to_common_candidate(native_candidate) -> CommonCandidate`.
The `CommonCandidate` dataclass is defined in
`scripts/search/engine.py` and has these fields:

| Field | Type | Meaning |
|---|---|---|
| `id` | str | Engine-native identifier (`memorial_id` for FaG; record id for Newspapers.com). |
| `url` | str | Canonical page URL. |
| `name` | str | Display name. |
| `score` | float | In `[0, 1]`. The engine's `score()` output. |
| `evidence` | dict | Engine-specific evidence (match_strength, dates, locations, IIIF links). |
| `engine` | str | Engine name (`findagrave`, `newspapers_com`, ...). |
| `media` | str | Optional. IIIF thumbnail URL or image. |

The ProjectionBuilder writes one `common` array per record
alongside the legacy `ranked_candidates`. v2 reads `common`
directly via `normalizeRecordV2()`; the legacy FaG fields
stay alongside for back-compat with v1 `view.html`.

### Implementing `to_common_candidate`

```python
def to_common_candidate(self, native: dict) -> CommonCandidate:
    return CommonCandidate(
        id=native["memorial_id"],
        url=f"https://www.findagrave.com/memorial/{native['memorial_id']}/{native['slug']}",
        name=native["name"],
        score=native["score"],
        evidence={
            "match_strength": native.get("match_strength"),
            "burial_location": native.get("burial_location"),
            "death_date": native.get("death_date"),
        },
        engine="findagrave",
        media=native.get("iiif_url"),
    )
```

### Test it

```python
def test_fag_to_common_candidate_roundtrip():
    native = {
        "memorial_id": "50923719",
        "slug": "william-pickney-looney",
        "name": "William Pickney Looney",
        "score": 0.92,
        "match_strength": "high",
        "burial_location": "Rose Hill Cemetery, OK",
        "death_date": "1907",
        "iiif_url": "https://www.findagrave.com/iiif/2/50923719/...",
    }
    engine = FaGEngine()
    common = engine.to_common_candidate(native)
    assert common.id == "50923719"
    assert common.url.endswith("/william-pickney-looney")
    assert common.engine == "findagrave"
    assert common.media is not None
    assert 0 <= common.score <= 1
```
