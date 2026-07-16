"""scripts.fag: Find a Grave search + browser integration.

Subpackage facade. The canonical implementation lives in:
  - scripts.fag.search           - FaG search engine (T022)
  - scripts.fag.fag_browser      - browser wrapper for the runner
  - scripts.fag.playwright_leak_fix - Playwright memory hygiene
  - scripts.fag.pw_session       - Playwright session wrapper
  - scripts.fag.rss_watchdog     - Win32 RSS watchdog

The deep-module-engineer facade is `scripts.fag.search.search_one_pensioner`.
Back-compat shim at `scripts.search_fag` re-exports everything
for the one release cycle callers migrate.
"""