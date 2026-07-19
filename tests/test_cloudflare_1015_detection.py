"""Tests for Cloudflare 1015 (Rate Limited) detection.

Run #2 stalled for ~8 minutes when Cloudflare returned the HTTP
1015 (Rate Limited) page; the existing detection code only
matched 'Just a moment' and 'Attention Required'. We now match
'Rate Limited' and 'Error 1015' via ResponseClassifier.

The detection strings live in scripts/fag/response_classifier.py.
search.py imports and uses ResponseClassifier.classify().
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _search_fag_source() -> str:
    return Path("scripts/fag/search.py").read_text(encoding="utf-8")


def _classifier_source() -> str:
    return Path("scripts/fag/response_classifier.py").read_text(
        encoding="utf-8"
    )


class TestCloudflare1015Detection:
    """The 1015 page title is what our process got stuck on."""

    def test_error_1015_string_detected(self):
        src = _classifier_source()
        assert "Rate Limited" in src, (
            "response_classifier.py must detect Cloudflare "
            "'Rate Limited' responses (HTTP 1015)."
        )
        assert "1015" in src, (
            "response_classifier.py must reference Error 1015 explicitly."
        )

    def test_search_fag_uses_classifier(self):
        """search.py imports and uses ResponseClassifier."""
        src = _search_fag_source()
        assert "ResponseClassifier" in src, (
            "search.py must import and use ResponseClassifier."
        )

    def test_backoff_for_rate_limit_longer_than_captcha(self):
        """RateLimit1015 cooldown is longer than CloudflareChallenge."""
        src = _classifier_source()
        # RateLimit1015 returns 120, Challenge returns 30
        assert "Classification.RateLimit1015" in src, (
            "response_classifier must handle RateLimit1015."
        )
        assert "120" in src, (
            "RateLimit1015 cooldown must be >= 120s."
        )

    def test_default_captcha_backoff_unaffected(self):
        """The 30s cooldown for CloudflareChallenge is still present."""
        src = _classifier_source()
        assert "30" in src, (
            "CloudflareChallenge cooldown must be ~30s."
        )
