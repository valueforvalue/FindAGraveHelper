# ADR 0001 — Playwright + stealth over `requests` for FaG scraping

## Status

`Accepted` (2026-07-08). Earned by Phase 1 research; cited
again in Run #1 when a one-off `requests` "speed" test got
blocked in 5 seconds. See
[`CONTEXT.md` §L8](../../CONTEXT.md#l8-fag-requests-go-through-playwright--stealth-never-requests).

## Context

Find a Grave uses Cloudflare Turnstile to gate scrapers.
Three observed behaviors:

1. Plain `requests.get()` against `findagrave.com/memorial/*`
   returns 200 OK but the body is the Turnstile challenge
   page ("Just a moment..."). The script thinks the search
   succeeded.
2. Playwright with `headless=True` and no stealth is blocked
   in <5 seconds.
3. Playwright with `headless=True` + `playwright-stealth` is
   blocked in <30 seconds (Cloudflare's headless fingerprint
   detection catches the stealth bypass).

What works:

- **Playwright** with **playwright-stealth** (Python or Node)
- Browser launched with `headless=False` (Cloudflare detects
   headless mode; even with stealth, headless=True is blocked)
- **Warmup**: visit `https://www.findagrave.com/` before any
   search to establish a Cloudflare session cookie
- **30s backoff** on any CAPTCHA before retrying

The forces in tension:

- **Throughput vs. stealth**: headless is faster but blocked.
  Headful with stealth is the only path.
- **Operational simplicity vs. real-data quality**: a `requests`
  path would be simpler to maintain, but the data quality is
  zero (every request returns the Turnstile page).
- **Run reliability vs. dependency surface**: Playwright +
  Chromium adds ~500MB RSS + a heavy install. The simpler
  stack is rejected.

## Decision

All FaG requests go through Playwright + `playwright-stealth`
with `headless=False`. The `scripts/fag/fag_browser.py` module is
the only sanctioned path. `requests.get()` against any FaG URL
is a bug.

CI runs without a browser sandbox; the live FaG tests
(`tests/test_real_fag_memory.py`) are gated behind a manual
trigger and skip in CI.

### Alternatives rejected

- **`requests` + HTML parsing** — rejected, returns Turnstile
  page as 200 OK.
- **`requests-html` (PyQt5-backed)** — rejected, same Turnstile
  block; PyQt5 install footprint larger than Playwright.
- **`httpx` async + stealth** — rejected, fingerprint detection
  is browser-side, not request-side.
- **Headless Playwright without stealth** — rejected, blocked
  in <30s.
- **Headless Playwright + stealth (different config)** —
  rejected, blocked in <60s.

## Consequences

**Positive:**

- The data quality is real (matches the user's browser).
- The Cloudflare warmup dance establishes a session cookie
  that survives throttled re-use.
- The harness can recover from closed-target errors via the
  browser reset loop.

**Negative:**

- Playwright + Chromium adds ~500MB RSS minimum.
- `headless=False` requires a display (or `xvfb-run` on Linux).
- The Cloudflare challenge can escalate; manual fallback to a
  user-driven browser is the recovery.

**When to revisit:**

- Cloudflare deprecates Turnstile (unlikely in 2026-2027).
- FaG opens an official API (unlikely; they actively block
  scrapers).
- A cheaper browser fingerprint becomes available (e.g.
  Firefox + stealth parity with Chromium).

**Related:**

- [`CONTEXT.md` §L8](../../CONTEXT.md#l8-fag-requests-go-through-playwright--stealth-never-requests)
- [`bug-catalog.md` §"Playwright layer" §"Closed-target detection"](bug-catalog.md)
- [`addenda/python-playwright-userscript.md` §"Playwright"](addenda/python-playwright-userscript.md)
- Commit `2580c36` (Apply Playwright Python memory-leak fix)