"""Tests for scripts/fag/response_classifier.py — Phase 4 Slice 4.3."""

from scripts.fag.response_classifier import (
    Classification,
    ResponseClassifier,
)


def test_normal_page():
    """Normal FaG search results page."""
    result = ResponseClassifier.classify(
        title="Find a Grave Memorial Search",
    )
    assert result == Classification.NormalPage
    assert not ResponseClassifier.is_blocking(result)


def test_just_a_moment_title():
    """'Just a moment...' title -> CloudflareChallenge."""
    result = ResponseClassifier.classify(
        title="Just a moment...",
    )
    assert result == Classification.CloudflareChallenge
    assert ResponseClassifier.is_blocking(result)


def test_attention_required_title():
    """'Attention Required! | Cloudflare' title -> CloudflareBlocked."""
    result = ResponseClassifier.classify(
        title="Attention Required! | Cloudflare",
    )
    assert result == Classification.CloudflareBlocked


def test_rate_limit_1015_title():
    """'Error 1015 (Rate Limited)' title -> RateLimit1015."""
    result = ResponseClassifier.classify(
        title="Error 1015 (Rate Limited) - www.findagrave.com",
    )
    assert result == Classification.RateLimit1015
    assert ResponseClassifier.cooldown_seconds(result) == 120


def test_rate_limit_body_fallback():
    """Rate limit detected in body when title is ambiguous."""
    result = ResponseClassifier.classify(
        title="Find a Grave",
        body_hint="<html>Error 1015: You are being rate limited</html>",
    )
    assert result == Classification.RateLimit1015


def test_challenge_body_fallback():
    """Challenge detected in body with normal title."""
    result = ResponseClassifier.classify(
        title="Loading...",
        body_hint="Just a moment while we verify your browser",
    )
    assert result == Classification.CloudflareChallenge


def test_url_challenge_detection():
    """Challenge detected from URL fragment."""
    result = ResponseClassifier.classify(
        title="",
        url="https://www.findagrave.com/cdn-cgi/challenge-platform/...",
    )
    assert result == Classification.CloudflareChallenge


def test_empty_all():
    """Empty inputs -> NormalPage."""
    result = ResponseClassifier.classify()
    assert result == Classification.NormalPage


def test_rate_limit_takes_priority():
    """RateLimit1015 takes priority over challenge/blocked markers."""
    result = ResponseClassifier.classify(
        title="Error 1015 Rate Limited - Just a moment...",
    )
    assert result == Classification.RateLimit1015


def test_cooldown_defaults():
    """Normal pages have zero cooldown."""
    assert ResponseClassifier.cooldown_seconds(Classification.NormalPage) == 0
    assert ResponseClassifier.cooldown_seconds(Classification.CloudflareChallenge) == 30
    assert ResponseClassifier.cooldown_seconds(Classification.CloudflareBlocked) == 60
