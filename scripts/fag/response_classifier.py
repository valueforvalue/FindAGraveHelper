"""ResponseClassifier: identify FaG challenge/rate-limit/normal pages.

Pure classifier — no sleeps, no network, no Playwright dependency.
Used by fag_browser and search to route responses through the
RequestGate for cooldown management.

Public surface:
  - Classification (enum)
  - ResponseClassifier.classify(title, body_hint, url) -> Classification
"""
from __future__ import annotations

from enum import Enum
from typing import Optional


class Classification(str, Enum):
    """Outcome of classifying a FaG response page."""

    NormalPage = "NormalPage"
    CloudflareChallenge = "CloudflareChallenge"  # Turnstile / "Just a moment"
    CloudflareBlocked = "CloudflareBlocked"  # "Attention Required! | Cloudflare"
    RateLimit1015 = "RateLimit1015"  # "Error 1015 (Rate Limited)"
    ErrorPage = "ErrorPage"  # other error responses


class ResponseClassifier:
    """Identify FaG response types from page metadata.

    Pure function — no side effects. Callers decide what action
    to take (cooldown, retry, abort) based on the classification.
    """

    # Title substrings that indicate a non-normal page
    _CHALLENGE_TITLES = (
        "Just a moment",
    )
    _BLOCKED_TITLES = (
        "Attention Required",
    )
    _RATE_LIMIT_TITLES = (
        "Rate Limited",
        "Error 1015",
    )

    @classmethod
    def classify(
        cls,
        title: str = "",
        body_hint: str = "",
        url: str = "",
    ) -> Classification:
        """Classify a FaG page response.

        Args:
            title: page.title() result.
            body_hint: first ~500 chars of page body (optional, for
                       additional signal).
            url: current page URL (optional, for redirect detection).

        Returns:
            Classification enum value.
        """
        # Check title patterns (most reliable signal)
        for marker in cls._RATE_LIMIT_TITLES:
            if marker in title:
                return Classification.RateLimit1015

        for marker in cls._BLOCKED_TITLES:
            if marker in title:
                return Classification.CloudflareBlocked

        for marker in cls._CHALLENGE_TITLES:
            if marker in title:
                return Classification.CloudflareChallenge

        # Body hints as fallback
        body_lower = body_hint.lower()
        if "error 1015" in body_lower or "rate limited" in body_lower:
            return Classification.RateLimit1015
        if "just a moment" in body_lower:
            return Classification.CloudflareChallenge
        if "attention required" in body_lower:
            return Classification.CloudflareBlocked

        # URL-based detection (e.g. redirects to challenge pages)
        url_lower = url.lower()
        if "challenge" in url_lower or "turnstile" in url_lower:
            return Classification.CloudflareChallenge

        return Classification.NormalPage

    @classmethod
    def is_blocking(cls, classification: Classification) -> bool:
        """True if this classification means we should NOT parse results."""
        return classification != Classification.NormalPage

    @classmethod
    def cooldown_seconds(cls, classification: Classification) -> int:
        """Recommended cooldown in seconds for each block type."""
        if classification == Classification.RateLimit1015:
            return 120  # 2 min — the ban window is 1-15 min
        if classification == Classification.CloudflareBlocked:
            return 60  # 1 min — shorter than 1015
        if classification == Classification.CloudflareChallenge:
            return 30  # 30s — Turnstile may resolve quickly
        return 0
