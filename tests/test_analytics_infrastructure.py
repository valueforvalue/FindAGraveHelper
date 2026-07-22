"""Tests for analytics infrastructure (issue #84).

Covers:
  - BlackboardObserver protocol compliance of RunAuditLog
  - BlackboardObserver protocol compliance of AnalyticsAggregator
  - Observer notification from store operations
  - AnalyticsAggregator metric accumulation
  - analytics_from_audit() reconstruction
"""

import json
import time

import pytest

from scripts.blackboard.schema import (
    Kind,
    Observation,
    WorkItem,
    WorkState,
)
from scripts.blackboard.store import SqliteBlackboardStore
from scripts.analysis.run_analytics import (
    AnalyticsAggregator,
    AnalyticsSnapshot,
    KnowledgeSourceMetrics,
    analytics_from_audit,
)
from scripts.pipeline.audit_log import RunAuditLog


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def sqlite_store(tmp_path):
    """Open a SQLite store in a temp directory."""
    store = SqliteBlackboardStore(tmp_path / "blackboard.db")
    store.open()
    yield store
    store.close()


@pytest.fixture
def audit_log_path(tmp_path):
    """Return a temp path for audit log JSONL."""
    return tmp_path / "run_audit.jsonl"


def _obs(
    oid: str,
    pid: int = 1,
    kind: Kind = Kind.FaGCandidateFetch,
    payload: dict | None = None,
    source: str = "test",
) -> Observation:
    return Observation(
        observation_id=oid,
        pensioner_id=pid,
        kind=kind,
        source=source,
        source_version="1",
        run_id="run-test",
        pass_id="1",
        payload=payload or {},
    )


def _work(
    wid: str,
    pid: int = 1,
    ks: str = "FaGScraper",
    state: WorkState = WorkState.READY,
) -> WorkItem:
    return WorkItem(
        work_id=wid,
        pensioner_id=pid,
        knowledge_source=ks,
        state=state,
    )


# ============================================================
# RunAuditLog as BlackboardObserver
# ============================================================


class TestRunAuditLogObserver:
    """Verify RunAuditLog implements BlackboardObserver correctly."""

    def test_on_observation_appended_writes_event(self, audit_log_path):
        audit = RunAuditLog.open(audit_log_path)
        obs = _obs("obs-1", pid=42, kind=Kind.CGRCorroboration, source="cgr_fetcher")
        audit.on_observation_appended(obs)
        audit.close()

        events = _read_audit_events(audit_log_path)
        appends = [e for e in events if e["event"] == "observation_appended"]
        assert len(appends) == 1
        assert appends[0]["observation_id"] == "obs-1"
        assert appends[0]["pensioner_id"] == 42
        assert appends[0]["kind"] == "CGRCorroboration"
        assert appends[0]["source"] == "cgr_fetcher"

    def test_on_work_claimed_writes_event(self, audit_log_path):
        audit = RunAuditLog.open(audit_log_path)
        item = _work("work-1", pid=7, ks="RegionalPlannerKS")
        item.attempt = 2
        audit.on_work_claimed(item, "RegionalPlannerKS")
        audit.close()

        events = _read_audit_events(audit_log_path)
        claims = [e for e in events if e["event"] == "work_claimed"]
        assert len(claims) == 1
        assert claims[0]["work_id"] == "work-1"
        assert claims[0]["pensioner_id"] == 7
        assert claims[0]["knowledge_source"] == "RegionalPlannerKS"
        assert claims[0]["attempt"] == 2

    def test_on_work_completed_writes_event(self, audit_log_path):
        audit = RunAuditLog.open(audit_log_path)
        audit.on_work_completed(
            work_id="work-2",
            pensioner_id=3,
            knowledge_source="FaGScraperKS",
            old_state="leased",
            new_state=WorkState.SUCCEEDED,
            observation_ids=["obs-a", "obs-b"],
        )
        audit.close()

        events = _read_audit_events(audit_log_path)
        completions = [e for e in events if e["event"] == "work_completed"]
        assert len(completions) == 1
        assert completions[0]["work_id"] == "work-2"
        assert completions[0]["old_state"] == "leased"
        assert completions[0]["new_state"] == "succeeded"
        assert completions[0]["observation_count"] == 2

    def test_on_cooldown_set_writes_event(self, audit_log_path):
        audit = RunAuditLog.open(audit_log_path)
        audit.on_cooldown_set("findagrave.com", "2026-07-22T12:00:00Z")
        audit.close()

        events = _read_audit_events(audit_log_path)
        cooldowns = [e for e in events if e["event"] == "cooldown_set"]
        assert len(cooldowns) == 1
        assert cooldowns[0]["provider"] == "findagrave.com"


# ============================================================
# Store observer notification
# ============================================================


class TestStoreObserverNotifications:
    """Verify SqliteBlackboardStore notifies registered observers."""

    def test_append_observation_notifies_observer(self, sqlite_store):
        events = []
        agg = AnalyticsAggregator()
        sqlite_store.register_observer(agg)

        obs = _obs("obs-note-1", pid=99, kind=Kind.ScoreObserved, source="CandidateScorerKS")
        sqlite_store.append_observation(obs)

        snap = agg.snapshot()
        assert snap.total_observations == 1
        assert snap.observations_by_kind.get("ScoreObserved") == 1
        assert "CandidateScorerKS" in snap.ks_metrics

    def test_claim_work_notifies_observer(self, sqlite_store):
        item = _work("work-claim-1", pid=5, ks="RegionalPlannerKS")
        sqlite_store.enqueue_work(item)

        agg = AnalyticsAggregator()
        sqlite_store.register_observer(agg)

        claimed = sqlite_store.claim_work("RegionalPlannerKS", lease_seconds=30)
        assert claimed is not None
        assert claimed.state == WorkState.LEASED

        snap = agg.snapshot()
        assert "RegionalPlannerKS" in snap.ks_metrics
        assert snap.ks_metrics["RegionalPlannerKS"].work_claimed == 1

    def test_complete_work_notifies_observer(self, sqlite_store):
        item = _work("work-comp-1", pid=5, ks="FaGScraperKS")
        sqlite_store.enqueue_work(item)
        claimed = sqlite_store.claim_work("FaGScraperKS", lease_seconds=30)
        assert claimed is not None

        agg = AnalyticsAggregator()
        sqlite_store.register_observer(agg)

        sqlite_store.complete_work("work-comp-1", WorkState.SUCCEEDED, ["obs-x"])

        snap = agg.snapshot()
        ks = snap.ks_metrics.get("FaGScraperKS")
        assert ks is not None
        assert ks.work_succeeded == 1
        assert snap.work_by_state.get("succeeded") == 1

    def test_complete_work_tracks_duration(self, sqlite_store):
        agg = AnalyticsAggregator()
        sqlite_store.register_observer(agg)

        item = _work("work-dur-1", pid=5, ks="FaGScraperKS")
        sqlite_store.enqueue_work(item)
        claimed = sqlite_store.claim_work("FaGScraperKS", lease_seconds=30)
        assert claimed is not None

        time.sleep(0.05)
        sqlite_store.complete_work("work-dur-1", WorkState.SUCCEEDED)

        snap = agg.snapshot()
        ks = snap.ks_metrics.get("FaGScraperKS")
        assert ks is not None
        assert len(ks.durations_s) == 1
        assert ks.durations_s[0] >= 0.04


# ============================================================
# AnalyticsAggregator metrics
# ============================================================


class TestAnalyticsAggregator:
    """Verify AnalyticsAggregator accumulates correctly."""

    def test_empty_snapshot_has_zeroes(self):
        agg = AnalyticsAggregator()
        snap = agg.snapshot()
        assert snap.total_observations == 0
        assert snap.total_work_items == 0
        assert snap.ks_metrics == {}
        d = snap.to_dict()
        assert d["elapsed_s"] >= 0

    def test_multiple_observations_by_kind(self):
        agg = AnalyticsAggregator()
        agg.on_observation_appended(_obs("a", kind=Kind.FaGCandidateFetch, source="FaGScraperKS"))
        agg.on_observation_appended(_obs("b", kind=Kind.FaGCandidateFetch, source="FaGScraperKS"))
        agg.on_observation_appended(_obs("c", kind=Kind.ScoreObserved, source="CandidateScorerKS"))

        snap = agg.snapshot()
        assert snap.total_observations == 3
        assert snap.observations_by_kind["FaGCandidateFetch"] == 2
        assert snap.observations_by_kind["ScoreObserved"] == 1
        assert snap.ks_metrics["FaGScraperKS"].total_observations_emitted == 2
        assert snap.ks_metrics["CandidateScorerKS"].total_observations_emitted == 1

    def test_work_item_state_counts(self):
        agg = AnalyticsAggregator()
        agg.on_work_claimed(_work("w1", ks="KS1"), "KS1")
        agg.on_work_claimed(_work("w2", ks="KS2"), "KS2")
        agg.on_work_claimed(_work("w3", ks="KS1"), "KS1")

        agg.on_work_completed("w1", 1, "KS1", "leased", WorkState.SUCCEEDED, ["o1"])
        agg.on_work_completed("w2", 2, "KS2", "leased", WorkState.BLOCKED, None)
        agg.on_work_completed("w3", 3, "KS1", "leased", WorkState.RETRYABLE, ["o2"])

        snap = agg.snapshot()
        assert snap.total_work_items == 3
        assert snap.work_by_state["succeeded"] == 1
        assert snap.work_by_state["blocked"] == 1
        assert snap.work_by_state["retryable"] == 1

        ks1 = snap.ks_metrics["KS1"]
        assert ks1.work_claimed == 2
        assert ks1.work_succeeded == 1
        assert ks1.work_retryable == 1
        assert ks1.success_rate == 0.5

    def test_duration_stats(self):
        agg = AnalyticsAggregator()
        agg.on_work_claimed(_work("w1", ks="KS1"), "KS1")
        time.sleep(0.02)
        agg.on_work_completed("w1", 1, "KS1", "leased", WorkState.SUCCEEDED, None)

        agg.on_work_claimed(_work("w2", ks="KS1"), "KS1")
        time.sleep(0.04)
        agg.on_work_completed("w2", 2, "KS1", "leased", WorkState.SUCCEEDED, None)

        snap = agg.snapshot()
        ks1 = snap.ks_metrics["KS1"]
        assert len(ks1.durations_s) == 2
        assert ks1.avg_duration_s >= 0.02
        assert ks1.p95_duration_s >= ks1.avg_duration_s

    def test_write_report(self, tmp_path):
        agg = AnalyticsAggregator()
        agg.on_observation_appended(_obs("a", kind=Kind.FaGCandidateFetch, source="FaGScraperKS"))
        agg.on_work_claimed(_work("w1", ks="FaGScraperKS"), "FaGScraperKS")
        agg.on_work_completed("w1", 1, "FaGScraperKS", "leased", WorkState.SUCCEEDED, ["a"])

        report_path = tmp_path / "subdir" / "run_analytics.json"
        agg.write_report(report_path)

        assert report_path.exists()
        data = json.loads(report_path.read_text())
        assert data["total_observations"] == 1
        assert data["total_work_items"] == 1
        assert "FaGScraperKS" in data["knowledge_sources"]


# ============================================================
# analytics_from_audit reconstruction
# ============================================================


class TestAnalyticsFromAudit:
    """Verify reconstruction from run_audit.jsonl."""

    def test_empty_audit_yields_empty_snapshot(self, tmp_path):
        path = tmp_path / "nonexistent.jsonl"
        snap = analytics_from_audit(path)
        assert snap.total_observations == 0
        assert snap.total_work_items == 0

    def test_reconstructs_from_audit_events(self, tmp_path):
        audit_path = tmp_path / "run_audit.jsonl"
        audit = RunAuditLog.open(audit_path)

        obs = _obs("obs-r1", pid=1, kind=Kind.FaGCandidateFetch, source="FaGScraperKS")
        audit.on_observation_appended(obs)
        audit.on_observation_appended(_obs("obs-r2", pid=1, kind=Kind.ScoreObserved, source="CandidateScorerKS"))

        item = _work("work-r1", pid=1, ks="FaGScraperKS")
        audit.on_work_claimed(item, "FaGScraperKS")
        audit.on_work_completed("work-r1", 1, "FaGScraperKS", "leased", WorkState.SUCCEEDED, ["obs-r1", "obs-r2"])

        audit.close()

        snap = analytics_from_audit(audit_path)
        assert snap.total_observations == 2
        assert snap.observations_by_kind["FaGCandidateFetch"] == 1
        assert snap.observations_by_kind["ScoreObserved"] == 1
        assert "FaGScraperKS" in snap.ks_metrics
        assert snap.ks_metrics["FaGScraperKS"].work_succeeded == 1


# ============================================================
# Helpers
# ============================================================


def _read_audit_events(path) -> list[dict]:
    """Parse JSONL audit file into list of event dicts."""
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events
