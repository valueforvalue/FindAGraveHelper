"""RequestGate: single throttle seam for provider request safety.

Every request to the same provider crosses one deep gate that owns:
  - Minimum spacing between requests (monotonic timer)
  - Provider-wide cooldown after bot-wall events
  - Token-based acquire/release for observability
  - Safe default for FaG (2.5s floor, non-negotiable)

Knowledge Sources propose work; they never sleep or navigate around
the gate. The gate answers "when may one operation happen?"

Usage:
    gate = RequestGate.default_fag()
    with gate.acquire("search") as token:
        page.goto(token.url)
        if token.bot_wall_observed:
            gate.cooldown_for(120)
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class AcquireToken:
    """Token returned by gate.acquire()."""

    provider: str
    kind: str  # "search", "memorial_detail", "cgr_fetch"
    acquired_at: float = 0.0
    url: str = ""
    bot_wall_observed: bool = False


class RequestGate:
    """Monotonic provider request gate.

    Thread-safe only for the owning process. Multi-process
    coordination requires external lock (not needed today).
    """

    def __init__(
        self,
        provider: str,
        min_interval: float = 2.5,
        max_cooldown: float = 3600.0,
    ) -> None:
        self.provider = provider
        self.min_interval = min_interval
        self.max_cooldown = max_cooldown

        self._last_acquire: float = 0.0
        self._not_before: float = 0.0

    @classmethod
    def default_fag(cls, provider: str = "findagrave.com") -> "RequestGate":
        """Factory for FaG with project-mandated 2.5s floor."""
        return cls(provider=provider, min_interval=2.5)

    # ----------------------------------------------------------
    # Public API
    # ----------------------------------------------------------

    def cooldown_for(self, seconds: float) -> None:
        """Set provider-wide cooldown for `seconds` from now.

        Call this when a bot-wall, rate-limit, or challenge page
        is observed. All future acquire() calls will block until
        the cooldown expires.
        """
        until = time.monotonic() + min(seconds, self.max_cooldown)
        self._not_before = max(self._not_before, until)

    def set_not_before_iso(self, until_iso: str) -> None:
        """Set provider cooldown from an ISO 8601 timestamp string.

        If the timestamp is in the past, this is a no-op.
        """
        from datetime import datetime, timezone

        try:
            dt = datetime.fromisoformat(until_iso.replace("Z", "+00:00"))
            now_utc = datetime.now(timezone.utc)
            delay = (dt - now_utc).total_seconds()
            if delay > 0:
                self._not_before = max(
                    self._not_before,
                    time.monotonic() + delay,
                )
        except (ValueError, TypeError):
            pass  # unparseable timestamps are ignored

    @contextmanager
    def acquire(self, kind: str = "search") -> Iterator[AcquireToken]:
        """Block until a request is permitted, return a token.

        The context manager guarantees:
        - min_interval since last acquire across all kinds
        - provider-wide cooldown honored
        - monotonic timing (wall clock skew safe)
        """
        self._wait_until_ready()
        token = AcquireToken(
            provider=self.provider,
            kind=kind,
            acquired_at=time.monotonic(),
        )
        try:
            yield token
        finally:
            self._last_acquire = time.monotonic()

    @property
    def not_before(self) -> float:
        """Earliest monotonic time the next request is permitted."""
        return max(
            self._last_acquire + self.min_interval,
            self._not_before,
        )

    # ----------------------------------------------------------
    # Internal
    # ----------------------------------------------------------

    def _wait_until_ready(self) -> None:
        """Sleep until the gate permits a request."""
        wait = self.not_before - time.monotonic()
        if wait > 0:
            time.sleep(wait)
