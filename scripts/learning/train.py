"""Train priors and classifier from accumulated reviewer labels (#54).

Reads labels from output/labels/labels_v1.jsonl, computes strategy
success stats, updates PriorRegistry, retrains CalibratedClassifier,
and writes updated model files to output/models/.

Usage:
    python scripts/learning/train.py --labels output/labels/labels_v1.jsonl
    python scripts/learning/train.py --labels output/labels/ --out output/models/
"""
from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path

# Project root for imports
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))


def load_labels(path: Path) -> list[dict]:
    """Load labels from a JSONL file or directory of JSONL files."""
    labels: list[dict] = []
    if path.is_dir():
        for f in sorted(path.glob("*.jsonl")):
            labels.extend(_read_jsonl(f))
    elif path.suffix == ".jsonl":
        labels.extend(_read_jsonl(path))
    elif path.suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            labels.extend(raw)
    return labels


def _read_jsonl(path: Path) -> list[dict]:
    labels: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            labels.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return labels


def compute_strategy_stats(labels: list[dict]) -> dict[str, dict[str, int]]:
    """Aggregate per-strategy acceptance statistics from labels.

    Each label dict may carry:
      - _winning_strategy: the strategy that found the picked candidate
      - _picked_rank: position in scorer ranking (1-indexed)
      - human_review_decision: accepted | rejected | ambiguous | unreviewed
    """
    stats: dict[str, dict[str, int]] = {}
    for label in labels:
        strategy = label.get("_winning_strategy") or label.get("_source_strategy") or ""
        if not strategy:
            continue
        if strategy not in stats:
            stats[strategy] = {"total": 0, "accepted": 0, "top1": 0}
        stats[strategy]["total"] += 1
        decision = label.get("human_review_decision", "unreviewed")
        if decision == "accepted":
            stats[strategy]["accepted"] += 1
            rank = label.get("_picked_rank", 1)
            if rank == 1:
                stats[strategy]["top1"] += 1
    return stats


def compute_label_features(labels: list[dict]) -> list[dict]:
    """Extract feature dicts from labels for classifier training."""
    features: list[dict] = []
    for label in labels:
        decision = label.get("human_review_decision", "unreviewed")
        features.append({
            "best_score": float(label.get("_picked_score", label.get("_top_score", 0.0))),
            "accepted": decision == "accepted",
            "winning_strategy": label.get("_winning_strategy", ""),
            "picked_rank": label.get("_picked_rank", 0),
            "score_gap_to_top": label.get("_score_gap_to_top", 0.0),
        })
    return features


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description="Train priors from reviewer labels")
    parser.add_argument("--labels", type=Path, required=True,
                        help="Path to labels JSONL file or directory")
    parser.add_argument("--out", type=Path, default=Path("output/models"),
                        help="Output directory for model files")
    args = parser.parse_args(argv)

    labels_path: Path = args.labels
    if not labels_path.exists():
        print(f"error: labels path not found: {labels_path}", file=sys.stderr)
        return 1

    labels = load_labels(labels_path)
    if not labels:
        print("No labels found. Nothing to train on.")
        return 0

    print(f"Loaded {len(labels)} labels from {labels_path}")

    # Strategy stats
    strategy_stats = compute_strategy_stats(labels)
    if strategy_stats:
        print("\nStrategy success rates:")
        for name in sorted(strategy_stats):
            s = strategy_stats[name]
            rate = s["accepted"] / max(s["total"], 1)
            top1_rate = s["top1"] / max(s["accepted"], 1)
            print(f"  {name}: {s['accepted']}/{s['total']} accepted ({rate:.0%}), "
                  f"top1={s['top1']}/{s['accepted']} ({top1_rate:.0%})")

    # Update priors
    from scripts.learning.priors import PriorRegistry
    priors = PriorRegistry.default()
    label_features = compute_label_features(labels)
    priors.update_from_labels(labels, label_features=label_features,
                              strategy_stats=strategy_stats)
    priors.policy_version = "2"
    priors.source_labels = [str(labels_path)]

    args.out.mkdir(parents=True, exist_ok=True)
    priors_path = args.out / "priors_v2.json"
    priors.save(priors_path)
    print(f"\nPriors saved to {priors_path}")
    print(f"  training_label_count: {priors.training_label_count}")
    if priors._strategy_utility:
        print(f"  strategy_utility: {len(priors._strategy_utility)} entries")
    if priors._match_calibration:
        print(f"  match_calibration: {len(priors._match_calibration)} points")

    # Train classifier
    accepted_labels = [l for l in labels
                       if l.get("human_review_decision") == "accepted"]
    if len(accepted_labels) >= 10:
        from scripts.learning.calibrated_classifier import CalibratedClassifier
        from scripts.learning.label_extractor import LabelSnapshot

        snapshots = []
        for l in labels:
            snapshots.append(LabelSnapshot(
                pensioner_id=l.get("pensioner_id", l.get("_source_pensioner_id", 0)),
                human_review_decision=l.get("human_review_decision", "unreviewed"),
            ))

        classifier = CalibratedClassifier(classifier_version="2")
        classifier.train(snapshots, label_features)
        classifier_path = args.out / "classifier_v2.json"
        classifier.save(classifier_path)
        print(f"Classifier saved to {classifier_path}")
        print(f"  coeffs: {classifier._coeffs}")
    else:
        print(f"\nSkipping classifier: need >=10 accepted labels, have {len(accepted_labels)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
