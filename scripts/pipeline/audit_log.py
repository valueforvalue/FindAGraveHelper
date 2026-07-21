"""Structured run audit log (issue #71).

Writes per-pensioner and per-strategy events to a JSON-lines file
in the output directory. Supplement to the Python logging module;
this captures machine-parseable structured events for post-run
analysis without needing to regex the log output.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional


class RunAuditLog:
    """JSON-lines audit log for one pipeline run.

    Usage::

        audit = RunAuditLog.open(out_dir / "run_audit.jsonl")
        audit.pensioner_start(pensioner_id="272", name="Eads, James")
        audit.strategy_ran(strategy="B1-exact", candidates=33, state="OK")
        audit.strategy_skipped(strategy="B2-middle-initial", reason="no middle")
        audit.pensioner_end(pensioner_id="272", total_candidates=33, status="auto_accept")
        audit.summary(total_pensioners=7758, total_requests=12345,
                       cloudflare_events=3, errors_by_type={"nav_timeout": 12})
        audit.close()
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._f = open(str(self._path), "w", encoding="utf-8")
        self._started_at: float = time.time()
        self._stats: dict[str, int] = {}
        self._pensioner_start: dict[str, float] = {}
        self._request_count: int = 0
        self._cloudflare_count: int = 0

    @classmethod
    def open(cls, path: Path) -> "RunAuditLog":
        return cls(path)

    def close(self) -> None:
        self._f.close()

    # ── per-pensioner ──

    def pensioner_start(self, pensioner_id: str, name: str, **fields: Any) -> None:
        self._pensioner_start[pensioner_id] = time.time()
        self._emit("pensioner_start", pensioner_id=pensioner_id, name=name, **fields)

    def pensioner_end(
        self,
        pensioner_id: str,
        total_candidates: int,
        status: str,
        best_score: float = 0.0,
        auto_relaxed: bool = False,
        **fields: Any,
    ) -> None:
        elapsed = 0.0
        if pensioner_id in self._pensioner_start:
            elapsed = time.time() - self._pensioner_start.pop(pensioner_id)
        self._emit(
            "pensioner_end",
            pensioner_id=pensioner_id,
            total_candidates=total_candidates,
            status=status,
            best_score=best_score,
            auto_relaxed=auto_relaxed,
            elapsed_s=round(elapsed, 3),
            **fields,
        )

    # ── per-strategy ──

    def strategy_ran(
        self,
        pensioner_id: str,
        strategy: str,
        candidates: int,
        state: str = "",
        url: str = "",
        response_classification: str = "",
        parse_time_s: float = 0.0,
        **fields: Any,
    ) -> None:
        self._request_count += 1
        if response_classification in ("challenge", "blocked", "rate_limit"):
            self._cloudflare_count += 1
        self._emit(
            "strategy_ran",
            pensioner_id=pensioner_id,
            strategy=strategy,
            candidates=candidates,
            state=state,
            url=url,
            classification=response_classification,
            parse_time_s=round(parse_time_s, 4),
            **fields,
        )

    def strategy_skipped(
        self, pensioner_id: str, strategy: str, reason: str = ""
    ) -> None:
        self._emit(
            "strategy_skipped",
            pensioner_id=pensioner_id,
            strategy=strategy,
            reason=reason,
        )

    def strategy_error(
        self,
        pensioner_id: str,
        strategy: str,
        error: str,
        **fields: Any,
    ) -> None:
        key = f"error:{error}"
        self._stats[key] = self._stats.get(key, 0) + 1
        self._emit(
            "strategy_error",
            pensioner_id=pensioner_id,
            strategy=strategy,
            error=error,
            **fields,
        )

    # ── summary ──

    def summary(
        self,
        total_pensioners: int,
        total_requests: int = 0,
        cloudflare_events: int = 0,
        errors_by_type: Optional[dict[str, int]] = None,
        **fields: Any,
    ) -> None:
        elapsed = time.time() - self._started_at
        self._emit(
            "run_summary",
            total_pensioners=total_pensioners,
            total_requests=total_requests or self._request_count,
            cloudflare_events=cloudflare_events or self._cloudflare_count,
            errors_by_type=errors_by_type or self._stats,
            elapsed_s=round(elapsed, 1),
            **fields,
        )

    # ── internal ──

    def _emit(self, event: str, **fields: Any) -> None:
        record = {"ts": time.time(), "event": event, **fields}
        self._f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._f.flush()
