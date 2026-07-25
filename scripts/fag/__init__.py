"""scripts.fag: Find a Grave search + browser integration.

Subpackage facade. The canonical implementation lives in:
  - scripts.fag.search           - FaG search engine (T022)
  - scripts.fag.browser_session  - browser lifecycle manager
  - scripts.fag.playwright_leak_fix - Playwright memory hygiene

Back-compat shim at `scripts.search_fag` re-exports everything
for the one release cycle callers migrate.
"""