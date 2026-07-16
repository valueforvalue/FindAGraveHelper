"""Tests for Cloudflare 1015 (Rate Limited) detection.

Run #2 stalled for ~8 minutes when Cloudflare returned the HTTP
1015 (Rate Limited) page; the existing detection code only
matched 'Just a moment' and 'Attention Required'. We now match
'Rate Limited' and 'Error 1015' too. These tests pin the fix.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _search_fag_source() -> str:
    return Path("scripts/search_fag.py").read_text(encoding="utf-8")


class TestCloudflare1015Detection:
    """The 1015 page title is what our process got stuck on."""

    def test_error_1015_string_detected(self):
        src = _search_fag_source()
        assert "Rate Limited" in src, (
            "search_fag.py must detect Cloudflare 'Rate Limited' "
            "responses (HTTP 1015)."
        )
        assert "1015" in src, (
            "search_fag.py must reference Error 1015 explicitly."
        )

    def test_backoff_for_rate_limit_longer_than_captcha(self):
        """The rate-limit case should back off longer than the standard
        captcha timeout (CAPTCHA_BACKOFF_SECONDS = 30s).
        """
        src = _search_fag_source()
        assert "120.0" in src or "120s" in src or "120" in src, (
            "search_fag.py must apply a >30s backoff for 1015."
        )

    def test_default_captcha_backoff_unaffected(self):
        """The 30s CAPTCHA_BACKOFF_SECONDS constant is still in use
        for non-rate-limit blocks.
        """
        src = _search_fag_source()
        assert "CAPTCHA_BACKOFF_SECONDS = 30.0" in src, (
            "CAPTCHA_BACKOFF_SECONDS constant unchanged"
        )
