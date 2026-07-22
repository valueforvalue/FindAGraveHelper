"""Inline run analytics aggregator (issue #84).

BlackboardObserver that tracks per-KS metrics during a run and
produces a JSON report at run end. Complements the cross-run
strategy_stats.py with single-run depth.

Usage (automatic — registered as store observer in run_unified.py):

    from scripts.analysis.run_analytics import AnalyticsAggregator
    aggregator = AnalyticsAggregator()
    store.register_observer(aggregator)
    # ... run ...
    report = aggregator.snapshot()
    aggregator.write_report(out_dir / "run_analytics.json")

Also usable standalone:

    python -m scripts.analysis.run_analytics --audit output/my-run/run_audit.jsonl
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class KnowledgeSourceMetrics:
    """Per-KS aggregate metrics accumulated during a run."""

    name: str = ""
    work_claimed: int = 0
    work_succeeded: int = 0
    work_retryable: int = 0
    work_blocked: int = 0
    work_terminal: int = 0
    total_observations_emitted: int = 0
    observation_kinds: dict[str, int] = field(default_factory=dict)
    # Duration tracking: lease_at → completed_at pairs
    durations_s: list[float] = field(default_factory=list)
    first_claimed_at: float = 0.0
    last_completed_at: float = 0.0

    @property
    def total_work_completed(self) -> int:
        return (
            self.work_succeeded
            + self.work_retryable
            + self.work_blocked
            + self.work_terminal
        )

    @property
    def success_rate(self) -> float:
        total = self.total_work_completed
        if total == 0:
            return 0.0
        return round(self.work_succeeded / total, 4)

    @property
    def avg_duration_s(self) -> float:
        if not self.durations_s:
            return 0.0
        return round(sum(self.durations_s) / len(self.durations_s), 4)

    @property
    def p95_duration_s(self) -> float:
        if not self.durations_s:
            return 0.0
        sorted_d = sorted(self.durations_s)
        idx = int(len(sorted_d) * 0.95)
        return round(sorted_d[min(idx, len(sorted_d) - 1)], 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "work_claimed": self.work_claimed,
            "work_succeeded": self.work_succeeded,
            "work_retryable": self.work_retryable,
            "work_blocked": self.work_blocked,
            "work_terminal": self.work_terminal,
            "total_work_completed": self.total_work_completed,
            "success_rate": self.success_rate,
            "total_observations_emitted": self.total_observations_emitted,
            "observation_kinds": dict(self.observation_kinds),
            "avg_duration_s": self.avg_duration_s,
            "p95_duration_s": self.p95_duration_s,
        }


@dataclass
class AnalyticsSnapshot:
    """Aggregated analytics for one run."""

    started_at: float = 0.0
    finished_at: float = 0.0
    total_observations: int = 0
    observations_by_kind: dict[str, int] = field(default_factory=dict)
    total_work_items: int = 0
    work_by_state: dict[str, int] = field(default_factory=dict)
    ks_metrics: dict[str, KnowledgeSourceMetrics] = field(
        default_factory=dict
    )
    cooldown_events: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_s": (
                round(self.finished_at - self.started_at, 1)
                if self.finished_at and self.started_at
                else 0.0
            ),
            "total_observations": self.total_observations,
            "observations_by_kind": dict(self.observations_by_kind),
            "total_work_items": self.total_work_items,
            "work_by_state": dict(self.work_by_state),
            "knowledge_sources": {
                name: metrics.to_dict()
                for name, metrics in self.ks_metrics.items()
            },
            "cooldown_events": len(self.cooldown_events),
        }


class AnalyticsAggregator:
    """BlackboardObserver that accumulates per-KS metrics during a run.

    Call snapshot() at any point for a point-in-time report.
    Safe to call from multiple threads — counters are CPython
    GIL-protected (dictionary writes are atomic at the interpreter
    level for basic operations).
    """

    def __init__(self) -> None:
        self._snapshot = AnalyticsSnapshot(started_at=time.time())
        # Tracks open leases: work_id -> (ks_name, leased_at)
        self._open_leases: dict[str, tuple[str, float]] = {}

    # ----------------------------------------------------------
    # BlackboardObserver callbacks
    # ----------------------------------------------------------

    def on_observation_appended(self, obs: Any) -> None:
        """Track observation by kind and source KS."""
        self._snapshot.total_observations += 1

        kind_str = (
            obs.kind.value
            if hasattr(obs.kind, "value")
            else str(obs.kind)
        )
        self._snapshot.observations_by_kind[kind_str] = (
            self._snapshot.observations_by_kind.get(kind_str, 0) + 1
        )

        # Also track per-source KS
        ks_name = obs.source or "unknown"
        metrics = self._get_or_create_ks(ks_name)
        metrics.total_observations_emitted += 1
        metrics.observation_kinds[kind_str] = (
            metrics.observation_kinds.get(kind_str, 0) + 1
        )

    def on_work_claimed(self, item: Any, knowledge_source: str) -> None:
        """Track work claim and start duration timer."""
        self._snapshot.total_work_items += 1
        metrics = self._get_or_create_ks(knowledge_source)
        metrics.work_claimed += 1
        if metrics.first_claimed_at == 0.0:
            metrics.first_claimed_at = time.time()

        # Open lease for duration tracking.
        self._open_leases[item.work_id] = (knowledge_source, time.time())

    def on_work_completed(
        self,
        work_id: str,
        pensioner_id: int,
        knowledge_source: str,
        old_state: str,
        new_state: Any,
        observation_ids: list[str] | None,
    ) -> None:
        """Track work completion and close duration timer."""
        new_state_str = (
            new_state.value
            if hasattr(new_state, "value")
            else str(new_state)
        )

        # Track by state.
        self._snapshot.work_by_state[new_state_str] = (
            self._snapshot.work_by_state.get(new_state_str, 0) + 1
        )

        metrics = self._get_or_create_ks(knowledge_source)
        if new_state_str == "succeeded":
            metrics.work_succeeded += 1
        elif new_state_str == "retryable":
            metrics.work_retryable += 1
        elif new_state_str == "blocked":
            metrics.work_blocked += 1
        elif new_state_str == "terminal":
            metrics.work_terminal += 1
        metrics.last_completed_at = time.time()

        # Close duration.
        lease_entry = self._open_leases.pop(work_id, None)
        if lease_entry is not None:
            _, leased_at = lease_entry
            duration = time.time() - leased_at
            metrics.durations_s.append(round(duration, 4))

    def on_cooldown_set(self, provider: str, not_before: str) -> None:
        """Track provider cooldown events."""
        self._snapshot.cooldown_events.append({
            "provider": provider,
            "not_before": not_before,
        })

    # ----------------------------------------------------------
    # Reporting
    # ----------------------------------------------------------

    def snapshot(self) -> AnalyticsSnapshot:
        """Return a copy of the current analytics snapshot."""
        self._snapshot.finished_at = time.time()
        return self._snapshot

    def write_report(self, path: Path) -> None:
        """Write the current snapshot as JSON to *path*."""
        snap = self.snapshot()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(snap.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # ----------------------------------------------------------
    # Internal
    # ----------------------------------------------------------

    def _get_or_create_ks(self, name: str) -> KnowledgeSourceMetrics:
        if name not in self._snapshot.ks_metrics:
            metrics = KnowledgeSourceMetrics(name=name)
            self._snapshot.ks_metrics[name] = metrics
        return self._snapshot.ks_metrics[name]


def analytics_from_audit(audit_path: Path) -> AnalyticsSnapshot:
    """Reconstruct an AnalyticsSnapshot from a run_audit.jsonl file.

    Useful for post-hoc single-run analysis when AnalyticsAggregator
    wasn't registered during the run.
    """
    agg = AnalyticsAggregator()

    if not audit_path.exists():
        return agg.snapshot()

    with open(audit_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("event", "")
            ts = event.get("ts", 0.0)
            if event_type == "observation_appended":
                # Simulate an observation object with necessary fields.
                class _FauxObs:
                    pass

                faux = _FauxObs()
                faux.observation_id = event.get("observation_id", "")
                faux.pensioner_id = event.get("pensioner_id", 0)
                faux.kind = event.get("kind", "")
                faux.source = event.get("source", "")
                agg.on_observation_appended(faux)

            elif event_type == "work_claimed":
                class _FauxItem:
                    pass

                faux = _FauxItem()
                faux.work_id = event.get("work_id", "")
                faux.pensioner_id = event.get("pensioner_id", 0)
                faux.attempt = event.get("attempt", 1)
                ks = event.get("knowledge_source", "unknown")
                agg.on_work_claimed(faux, ks)

            elif event_type == "work_completed":
                agg.on_work_completed(
                    work_id=event.get("work_id", ""),
                    pensioner_id=event.get("pensioner_id", 0),
                    knowledge_source=event.get("knowledge_source", ""),
                    old_state=event.get("old_state", ""),
                    new_state=event.get("new_state", ""),
                    observation_ids=None,
                )

            elif event_type == "cooldown_set":
                agg.on_cooldown_set(
                    provider=event.get("provider", ""),
                    not_before=event.get("not_before", ""),
                )

    # Restore timestamps from audit bounds.
    agg._snapshot.started_at = audit_path.stat().st_ctime
    agg._snapshot.finished_at = audit_path.stat().st_mtime

    return agg.snapshot()


# ============================================================
# CLI
# ============================================================


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Single-run analytics from audit log."
    )
    parser.add_argument(
        "--audit",
        type=Path,
        required=True,
        help="Path to run_audit.jsonl.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output JSON file (default: stdout).",
    )
    args = parser.parse_args(argv)

    snapshot = analytics_from_audit(args.audit)
    report = snapshot.to_dict()

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {args.out}")
    else:
        json.dump(report, __import__("sys").stdout, indent=2, ensure_ascii=False)
        __import__("sys").stdout.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
