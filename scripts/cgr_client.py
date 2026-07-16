"""CGR HTTP client.

Thin wrapper over urllib.request that handles:
  - Building search URLs with the right field names
  - GET requests to results.php and the detail pages
  - Throttling between requests
  - Returning parsed data, not raw HTML

The site has no bot detection (we confirmed this with several
manual fetches in 2026-07-16). It uses standard HTTP, no JS,
no auth. We still throttle to be polite.

We send a User-Agent so we're identifiable as our project. The
site doesn't care, but it's good citizenship.

This client does NOT match records to local data — that's the
matcher's job (cgr_matcher.py). It just fetches and parses.
"""
import time
import urllib.parse
import urllib.request


_BASE_URL = "https://cgr.scv.org"
_USER_AGENT = "FindAGraveHelper/0.1 (research; contact: jeremy@example.com)"


class CGRClient:
    """Client for the Confederate Graves Registry site."""

    def __init__(self, throttle_seconds: float = 0.0):
        self.throttle_seconds = throttle_seconds
        self._request_count = 0  # first request is "free" (warmup)

    def _get(self, url: str) -> str:
        """GET a URL with our user-agent and throttle. Returns raw HTML."""
        if self._request_count > 0 and self.throttle_seconds > 0:
            time.sleep(self.throttle_seconds)
        self._request_count += 1
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        # CGR pages are latin-1 / iso-8859-1. Try that first; fall back.
        try:
            return data.decode("iso-8859-1")
        except UnicodeDecodeError:
            return data.decode("utf-8", errors="replace")

    def search_by_name(
        self,
        fname: str = "",
        lname: str = "",
        ordinal: str = "",
        unit_state: str = "",
        unit_type: str = "",
        unit_aka: str = "",
        born_county: str = "",
        cem_state: str = "",
        cem_country: str = "",
    ) -> list[dict]:
        """Search CGR for veterans matching the given parameters.

        Returns a list of {id, name, unit, born} dicts. Empty list
        if no matches.
        """
        # Import here to avoid circular dependency at module load.
        from scripts.cgr_results import parse_cgr_results
        params = {
            "fname": fname,
            "lname": lname,
            "ordinal": ordinal,
            "unit_state": unit_state,
            "unit_type": unit_type,
            "unit_aka": unit_aka,
            "born_county": born_county,
            "cem_state": cem_state,
            "cem_country": cem_country,
        }
        # Drop empty values so the URL stays clean
        params = {k: v for k, v in params.items() if v}
        url = f"{_BASE_URL}/results.php?" + urllib.parse.urlencode(params)
        html = self._get(url)
        return parse_cgr_results(html)

    def get_vet_details(self, vet_id: int) -> dict:
        """Fetch and parse a vet details page. Returns a dict (possibly empty)."""
        from scripts.cgr_vet import parse_cgr_vet
        url = f"{_BASE_URL}/vetDetails.php?id={vet_id}"
        html = self._get(url)
        return parse_cgr_vet(html)

    def get_cemetery_details(self, vet_id: int) -> dict:
        """Fetch and parse a cemetery details page.

        Note: the cemetery id is in the same URL as the vet (the
        search uses vet id; the cemetery is associated). CGR's
        cemDetails.php?id=X expects the vet id, not a separate
        cemetery id.
        """
        from scripts.cgr_cem import parse_cgr_cem
        url = f"{_BASE_URL}/cemDetails.php?id={vet_id}"
        html = self._get(url)
        return parse_cgr_cem(html)