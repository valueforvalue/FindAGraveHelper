"""Tests for scripts/ingest/scrape_digitalprairie.py.

Pin the URL builders after the digitalprairie.ok.gov migration
(post-2026-07). The /digital/singleitem/ paths now return soft-404
pages; /digital/api/singleitem/ still works (returns JSON).

See issue #13.
"""
from scripts.ingest.scrape_digitalprairie import (
    API_BASE_PENSIONS,
    API_BASE_PENSIONCARD,
    PUBLIC_URL_PENSIONS,
    PUBLIC_URL_PENSIONCARD,
    _format_public_url,
)


def test_public_url_uses_api_path():
    """PUBLIC_URL_PENSIONS/PENSIONCARD must point at the working
    /digital/api/singleitem/... endpoint, not the broken
    /digital/singleitem/... endpoint."""
    assert "/digital/api/singleitem/" in PUBLIC_URL_PENSIONS, (
        "PUBLIC_URL_PENSIONS missing /api/ segment; users clicking "
        "the backlink land on a 404 page"
    )
    assert "/digital/api/singleitem/" in PUBLIC_URL_PENSIONCARD, (
        "PUBLIC_URL_PENSIONCARD missing /api/ segment"
    )


def test_public_url_does_not_have_broken_path():
    """The legacy /digital/singleitem/ (without /api/) must NOT
    appear as a backlink path — it returns a soft-404."""
    # The PUBLIC_URL_* are format strings with {id}; check the prefix
    assert "/digital/singleitem/" not in PUBLIC_URL_PENSIONS, (
        "PUBLIC_URL_PENSIONS still uses the broken /digital/singleitem/ "
        "path; users see a 404 body in the browser"
    )
    assert "/digital/singleitem/" not in PUBLIC_URL_PENSIONCARD


def test_format_public_url_inserts_id():
    """_format_public_url(prefix, id) returns the full URL."""
    u = _format_public_url(PUBLIC_URL_PENSIONS, 3)
    assert u.endswith("/id/3")
    assert "digitalprairie.ok.gov" in u


def test_api_and_public_url_bases_align():
    """After the migration, the public backlink uses the SAME base
    as the API endpoint (both /digital/api/singleitem/...)."""
    # Strip the trailing /id from each and compare
    api_base = API_BASE_PENSIONS  # ends with /id
    public_base = PUBLIC_URL_PENSIONS.replace("{id}", "X")  # ends with /id/X
    # The public URL must start with the API base (when {id} is replaced)
    assert public_base.startswith(api_base), (
        f"public url {public_base!r} does not start with api base {api_base!r}"
    )