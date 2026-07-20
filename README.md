# FindAGraveHelper

A pair of Tampermonkey/Greasemonkey userscripts for working with
[Find a Grave](https://www.findagrave.com) memorials, plus a
research workspace documenting Civil War genealogy patterns that
inform future development.

## Project goal

The current focus is to find **Confederate soldiers associated with
Oklahoma** who are not yet in Find a Grave. The Oklahoma Board of
Pension Commissioners documented every Confederate veteran (or
widow) who applied for an OK state pension under the 1915 act — a
canonical list of OK-associated CW soldiers. See
[`docs/research/digitalprairie/`](./docs/research/digitalprairie/) for
the indexed 7,558-record list, the scraper, and the next-step plan.

## What's in this repo

### Userscripts

| Script | Purpose |
|---|---|
| [`FindaGraveScraper.user.js`](./FindaGraveScraper.user.js) | **Scraper.** Loads Find a Grave memorial pages and exports the data as JSON. For already-found memorials. |
| [`FindaGraveIterativeHelper.user.js`](./FindaGraveIterativeHelper.user.js) | **Search helper.** Iteratively searches Find a Grave for a person who isn't yet in FaG. v4.0, will be replaced by v5.0. |

Both scripts work with Tampermonkey / Greasemonkey / Violentmonkey.

### Research workspace

[`docs/research/`](./docs/research/) contains the research and data
that informs the v5.0 search-helper design:

- [`digitalprairie/`](./docs/research/digitalprairie/) — 7,558
  OK-associated Confederate pensioners from digitalprairie.ok.gov.
  Canonical input list for the next batch FaG search.
- [`local-data/`](./docs/research/local-data/) — analysis of the
  575 CW veterans in the user's dixiedata DB with attached FaG URLs.
  Slug-shape patterns, name matches, date coverage.
- [`findagrave-params/`](./docs/research/findagrave-params/) —
  verified live parameter reference for `/memorial/search`.
- [`cw-tactics/`](./docs/research/cw-tactics/) — practical CW
  genealogy playbook.
- [`phonetic-algorithms/`](./docs/research/phonetic-algorithms/) —
  name-matching algorithm comparison with JS snippets.
- [`naming-conventions/`](./docs/research/naming-conventions/) —
  Southern 1800–1860 naming culture, Confederate Home populations.
- [`broadened-set/`](./docs/research/broadened-set/) — 43,834-soldier
  CW dataset pulled from `freecivilwarrecords.org` (Confederate +
  Union, 11 states).

[`docs/v5-design/`](./docs/v5-design/) contains the proposed v5.0
strategy ladder and design playbook.

### Tools

| Tool | Purpose |
|---|---|
| [`process_ledger.py`](./process_ledger.py) | Converts a JSON export from `FindaGraveScraper` into CSV and per-record Markdown. |
| [`scripts/`](./scripts/) | Analysis scripts for the research workspace (rebuild broadened set, validate strategies, etc.). |
| [`scripts/pipeline/`](./scripts/pipeline/) | Python harness that runs a batch FaG search. Engine-agnostic; today supports Find a Grave (`FaGEngine`) and Newspapers.com (`NewspapersComEngine`). See [Pipeline](#pipeline-python-harness) below. |
| [`scripts/search/`](./scripts/search/) | Search abstractions: `SearchContext`, `Strategy` Protocol, `SearchEngine` Protocol, `SearchRecord`, `run_ladder()`, template DSL. Adding a new strategy or engine is a small addition here. See [Adding a new strategy](#adding-a-new-strategy) and [Adding a new search engine](#adding-a-new-search-engine). |

## Pipeline (Python harness)

The `scripts/pipeline/` module is the engine-agnostic batch
runner. Today it ships with two engines:

- `FaGEngine` (`scripts/search/fag_engine.py`) — the Find a
  Grave search backend, with Cloudflare handling, state filter,
  and the 12-strategy FaG ladder.
- `NewspapersComEngine` (`scripts/search/newspapers_engine.py`)
  — the Newspapers.com search backend, with a 3-strategy
  keyword ladder. Added as a 2nd engine to prove the
  abstraction is real; the pipeline ran it unchanged.

### Quickstart: run a FaG batch

```bash
# Initialize a new batch (creates output/<runname>/config.json)
python scripts/run_unified.py init-batch my-test-run

# Run it (Playwright + stealth; requires a one-time
# `python -m playwright install chromium`)
python scripts/run_unified.py \
    --config output/my-test-run/config.json \
    --limit 25

# Resume after a crash / pause (skips already-done ids)
python scripts/run_unified.py \
    --config output/my-test-run/config.json \
    --resume

# Open the review UI in your browser
open output/my-test-run/view.html
```

### Quickstart: run a Newspapers.com batch

The pipeline is engine-agnostic; `--engine newspapers_com`
swaps the backend:

```bash
python scripts/run_unified.py init-batch my-np-run
python scripts/run_unified.py \
    --config output/my-np-run/config.json \
    --engine newspapers_com \
    --limit 10
```

(Logged-in Newspapers.com session required; cookies persist
in your browser profile.)

### Run the tests

```bash
pytest tests/                                 # full suite
pytest tests/test_<name>.py                   # one file
pytest tests/test_search_engine.py            # abstraction tests
pytest tests/test_newspapers_engine.py        # 2nd engine tests
```

Full architecture diagram (Mermaid, renders in GitHub):
[`docs/agents/pipeline-architecture.md`](./docs/agents/pipeline-architecture.md).

## Adding a new strategy

A "strategy" is a function that takes a `SearchContext` and
returns either a dict of URL params (engine-specific) or
`None` to skip. The cleanest form is one function + one
`FunctionStrategy` registration.

```python
# scripts/search/strategies.py (or a domain-specific file)

from scripts.search.context import SearchContext
from scripts.search.strategy import as_strategy


def my_new_strategy(ctx: SearchContext):
    """One-line description of what this does."""
    if not ctx.first and not ctx.last:
        return None
    return {
        "firstname": ctx.first,
        "lastname": ctx.last,
        "middlename": ctx.middle,
    }


# Add to the ladder (in the right engine's __init__ or
# wherever the engine composes its list):
STRATEGIES.append(as_strategy("X1-my-strategy", my_new_strategy))
```

For the 90% case where the strategy is "static dict with a
few substitutions + conditionals," use the **template DSL**
instead — no Python required:

```python
from scripts.search.template import TemplateStrategy


MY_STRATEGY = TemplateStrategy.from_spec({
    "name": "X1-template",
    "applies_when": ["first", "last"],
    "params": {
        "firstname": "{first}",
        "lastname": "{last}",
        "middlename?": "{middle}",   # ? = conditional
    },
})
```

The DSL features (substitution, conditional include, transforms)
are documented in [`docs/agents/search-abstraction.md`](./docs/agents/search-abstraction.md).

## Adding a new search engine

A `SearchEngine` is the unit that talks to one specific
search backend (Find a Grave, Ancestry, FamilySearch,
Newspapers.com, your local DB). Adding a new one is a 1-2
week project, and the abstraction means the pipeline
doesn't need to change.

The shape:

```python
# scripts/search/<your_engine>.py

from urllib.parse import urlencode
import re

from scripts.search.context import SearchContext
from scripts.search.engine import Classification, SearchEngine
from scripts.search.strategy import FunctionStrategy


BASE_URL = "https://your-engine.example.com/search"


class YourEngine:
    name = "your_engine"
    base_url = BASE_URL
    ladder = []  # list[Strategy]; per-engine

    def build_url(self, params: dict) -> str:
        return BASE_URL + "?" + urlencode(params)

    def parse_results_page(self, page, url: str) -> list[dict]:
        html = page.content()
        return [
            {"id": m.group(1), "title": m.group(2).strip()}
            for m in re.finditer(
                r'<div class="result" id="(\d+)">(.*?)</div>',
                html, re.DOTALL,
            )
        ]

    def score(self, ctx: SearchContext, candidate: dict):
        score, evidence = 0.0, {}
        if ctx.last and ctx.last.lower() in candidate.get("title", "").lower():
            score += 0.4
            evidence["last_name_in_title"] = True
        return min(score, 1.0), evidence

    # See docs/agents/search-abstraction.md for the other
    # 3 building blocks (classify_response, apply_filters,
    # throttle_seconds) and a complete worked example.
```

Plug it into the pipeline:

```python
from scripts.search.your_engine import YourEngine
from scripts.pipeline.core import PipelineConfig, run_one
from scripts.search.record import from_pensioner

config = PipelineConfig(
    engine=YourEngine(),
    page=playwright_page,
)
result = run_one(from_pensioner(pensioner_dict), [], config)
```

The worked example is `scripts/search/newspapers_engine.py` —
~600 lines (3 strategies + parser + scorer + classifier)
plus a complete test file at
`tests/test_newspapers_engine.py`. Use that as your
template.

Full guide: [`docs/agents/search-abstraction.md`](./docs/agents/search-abstraction.md).

## Installing the scraper

1. Install a userscript manager from the links below.
2. Open `FindaGraveScraper.user.js` in a text editor and copy its
   contents.
3. In your userscript manager, choose **Create new script** and paste.
4. Save. Confirm the script is enabled and matches against
   `https://www.findagrave.com/memorial/*`.

### Requirements

- [Tampermonkey](https://www.tampermonkey.net/) (Chrome, Edge, Firefox, Safari)
- [Greasemonkey](https://www.greasespot.net/) (Firefox)
- [Violentmonkey](https://violentmonkey.github.io/) (any modern browser)

## Using the scraper

1. Visit any Find a Grave memorial page (URL of the form
   `https://www.findagrave.com/memorial/<id>/...`).
2. A small dark panel appears in the bottom-right corner labelled
   **▼ Scraper**. Click the toggle to expand it.
3. Click **Scrape Current Page** to capture the current memorial into
   the ledger.
4. Browse to other memorial pages and repeat. Re-visiting a memorial
   updates the existing record instead of duplicating.
5. When ready, click **Export Data (N)**. Your browser will download
   `memorials_archive.json`. A confirmation prompt offers to clear
   the in-script ledger so you can start a fresh batch.

See `process_ledger.py` for processing the export.

## The search helper (v4.0)

The existing `FindaGraveIterativeHelper.user.js` is a working
5-strategy search ladder. See [docs/v5-design/strategy-ladder.md](./docs/v5-design/strategy-ladder.md)
for the proposed v5.0 design that will replace it.

## Output schema (from the scraper)

Each record in `memorials_archive.json` looks like this:

```json
{
  "memorial_id": "12345678",
  "name": "Jane Doe",
  "url": "https://www.findagrave.com/memorial/12345678/jane-doe",
  "birth_date": "12 Jan 1820",
  "birth_location": "Springfield, Illinois, USA",
  "death_date": "3 Mar 1894",
  "death_age": 74,
  "death_location": "Chicago, Illinois, USA",
  "burial_cemetery": "Rosehill Cemetery",
  "burial_location": "Chicago, Cook County, Illinois, USA",
  "biography": "Daughter of ...; wife of ...",
  "family_parents": ["John Doe", "Mary Roe"],
  "family_spouse": "James Smith",
  "family_children": ["Alice Smith", "Bob Smith"],
  "scraped_at": "2026-07-01T14:32:10.000Z"
}
```

Fields may be empty strings (`""`) or `null` when the corresponding
data was not present on the page.

## Processing the export with Python

Once you have `memorials_archive.json`, the example script below
produces both a human-readable CSV summary and per-record Markdown
files suitable for use in a static-site generator or note-taking
workflow.

```bash
python process_ledger.py memorials_archive.json
```

Output:
- `memorials.csv` — flat summary, one row per memorial
- `memorials/` — directory of per-record Markdown files

## Ethical use

- These tools are intended for personal genealogical research and
  archival of memorials you have a legitimate reason to preserve.
- Be courteous to Find a Grave's servers — avoid scraping faster
  than a human browsing pace (1-2 req/sec).
- Respect the wishes of memorial owners: if a memorial has been
  removed or marked private, do not redistribute its content.
- The search helper is intended to find memorials that exist for
  real people. Do not use it to create spurious memorials or
  flood FaG with low-quality submissions.

## License

[MIT](./LICENSE)