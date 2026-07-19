"""Training label extraction — Phase 8 Slice 8.2.

Extracts training labels from projection store + ground-truth CSV +
CGR corroboration + spouse match observations. Produces versioned
LabelSnapshot per pensioner for the prior trainer and classifier.

Temporal split ensures labels created under policy_version N never
train a classifier evaluated against policy N without separation.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class LabelSnapshot:
    """One training label for a pensioner."""

    pensioner_id: int
    ground_truth_memorial_id: str | None = None
    human_review_decision: str = "unreviewed"  # accepted|rejected|ambiguous|unreviewed
    cgr_corroborated: bool = False
    spouse_confirmed: bool = False
    extracted_at: str = ""
    source_policy_version: str = "1"


class LabelExtractor:
    """Reads projections + evidence and emits LabelSnapshots."""

    def extract(
        self,
        projection_rows: list[dict[str, Any]],
        ground_truth: dict[int, str] | None = None,
        cgr_evidence: dict[int, bool] | None = None,
        spouse_evidence: dict[int, bool] | None = None,
    ) -> list[LabelSnapshot]:
        """Extract labels from projection rows + auxiliary evidence."""
        import time

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        labels: list[LabelSnapshot] = []

        for row in projection_rows:
            pid = row.get("pensioner_id", 0)
            if pid == 0:
                continue

            gt_memorial = None
            if ground_truth and pid in ground_truth:
                gt_memorial = ground_truth[pid]

            review = "unreviewed"
            if row.get("human_decision"):
                review = row["human_decision"]

            label = LabelSnapshot(
                pensioner_id=pid,
                ground_truth_memorial_id=gt_memorial,
                human_review_decision=review,
                cgr_corroborated=cgr_evidence.get(pid, False) if cgr_evidence else False,
                spouse_confirmed=spouse_evidence.get(pid, False) if spouse_evidence else False,
                extracted_at=now,
                source_policy_version="1",
            )
            labels.append(label)

        return labels


class LabelStore:
    """SQLite store for LabelSnapshots with temporal split support."""

    def __init__(self, path: Path) -> None:
        self._con = sqlite3.connect(str(path), isolation_level=None)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute(
            """CREATE TABLE IF NOT EXISTS labels (
                pensioner_id INTEGER PRIMARY KEY,
                ground_truth_memorial_id TEXT,
                human_review_decision TEXT NOT NULL DEFAULT 'unreviewed',
                cgr_corroborated INTEGER NOT NULL DEFAULT 0,
                spouse_confirmed INTEGER NOT NULL DEFAULT 0,
                extracted_at TEXT NOT NULL,
                source_policy_version TEXT NOT NULL DEFAULT '1'
            )"""
        )

    def insert_snapshot(self, label: LabelSnapshot) -> None:
        self._con.execute(
            """INSERT OR REPLACE INTO labels
               (pensioner_id, ground_truth_memorial_id,
                human_review_decision, cgr_corroborated,
                spouse_confirmed, extracted_at, source_policy_version)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                label.pensioner_id,
                label.ground_truth_memorial_id,
                label.human_review_decision,
                int(label.cgr_corroborated),
                int(label.spouse_confirmed),
                label.extracted_at,
                label.source_policy_version,
            ),
        )

    def training_split(self, before: str) -> list[LabelSnapshot]:
        """Labels extracted before the given ISO timestamp."""
        rows = self._con.execute(
            "SELECT * FROM labels WHERE extracted_at < ? ORDER BY pensioner_id",
            (before,),
        ).fetchall()
        return [self._row_to_label(r) for r in rows]

    def evaluation_split(self, after: str) -> list[LabelSnapshot]:
        """Labels extracted after the given ISO timestamp."""
        rows = self._con.execute(
            "SELECT * FROM labels WHERE extracted_at >= ? ORDER BY pensioner_id",
            (after,),
        ).fetchall()
        return [self._row_to_label(r) for r in rows]

    def close(self) -> None:
        self._con.close()

    @staticmethod
    def _row_to_label(row: tuple) -> LabelSnapshot:
        return LabelSnapshot(
            pensioner_id=row[0],
            ground_truth_memorial_id=row[1],
            human_review_decision=row[2],
            cgr_corroborated=bool(row[3]),
            spouse_confirmed=bool(row[4]),
            extracted_at=row[5],
            source_policy_version=row[6],
        )
