"""Fellegi-Sunter probabilistic record linkage — Phase 3 Slice 3.5.

Proper Fellegi-Sunter m/u estimation from labeled pairs. Replaces
the LogisticRegression fallback with actual m/u probabilities
computed from match/non-match training pairs.

Produces versioned MatchModel artifacts with:
  - model_version, feature_schema, trained_at, feature_count
  - m_probabilities, u_probabilities per feature
  - predict() returning (probability, evidence)
  - load() restricted to operator-owned local paths
"""
from __future__ import annotations

import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.matching.name_evidence import NameEvidence


@dataclass
class MatchModel:
    """Versioned Fellegi-Sunter model artifact."""

    model_version: str = "1"
    feature_schema: list[str] = field(default_factory=list)
    trained_at: str = ""
    feature_count: int = 0
    training_pair_count: int = 0

    # Per-feature m and u probabilities
    m_probs: dict[str, float] = field(default_factory=dict)
    u_probs: dict[str, float] = field(default_factory=dict)

    def predict(
        self, features: dict[str, float]
    ) -> tuple[float, dict[str, Any]]:
        """Compute match probability and per-feature evidence.

        Returns (probability, evidence_dict).
        """
        if not self.m_probs:
            return 0.5, {"reason": "untrained"}

        total_weight = 0.0
        evidence: dict[str, Any] = {}

        for name in self.feature_schema:
            m = self.m_probs.get(name, 0.5)
            u = self.u_probs.get(name, 0.1)

            # Clamp to avoid log(0)
            m = max(0.001, min(0.999, m))
            u = max(0.001, min(0.999, u))

            value = features.get(name, 0.0)
            # Treat continuous features: agreement weight scaled by value
            agree_weight = math.log2(m / u)
            disagree_weight = math.log2((1 - m) / (1 - u))
            weight = agree_weight * value + disagree_weight * (1 - value)
            total_weight += weight
            evidence[name] = {
                "value": value,
                "m": round(m, 4),
                "u": round(u, 4),
                "weight": round(weight, 4),
            }

        # Convert log-likelihood ratio to probability via sigmoid
        probability = 1.0 / (1.0 + math.exp(-total_weight))
        evidence["total_weight"] = round(total_weight, 4)
        evidence["probability"] = round(probability, 4)

        return probability, evidence

    def save(self, path: Path) -> None:
        """Persist model to a local file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump(self, f)

    @classmethod
    def load(cls, path: Path) -> "MatchModel":
        """Load model from an operator-owned local path.

        Restriction: path must be an absolute local filesystem path.
        Network/UNC/remote paths are rejected.
        """
        resolved = path.resolve()
        # Reject remote/UNC paths
        if str(resolved).startswith("\\\\"):
            raise ValueError(
                f"Model path {resolved} appears to be a network path. "
                "Models must be operator-owned local files."
            )
        with path.open("rb") as f:
            return pickle.load(f)


class FellegiSunterMatcher:
    """Trains Fellegi-Sunter m/u probabilities from labeled pairs.

    Features (per pair):
      - name_similarity: NameEvidence.fuzzy_match() score
      - birth_year_match: ±2 years
      - unit_state_match: state codes in unit strings
      - first_initial_match: first-name first char matches
      - metaphone_last: metaphone match on last name
    """

    FEATURE_NAMES = [
        "name_similarity",
        "birth_year_match",
        "unit_state_match",
        "first_initial_match",
        "metaphone_last",
    ]

    def __init__(self) -> None:
        self._match_features: list[dict[str, float]] = []
        self._nonmatch_features: list[dict[str, float]] = []
        self._model: MatchModel | None = None

    @property
    def is_trained(self) -> bool:
        return self._model is not None

    def train(
        self,
        pairs: list[tuple[dict, dict, bool]],
    ) -> MatchModel:
        """Train on labeled (pensioner, cgr_vet, is_match) pairs.

        Returns the trained MatchModel.
        """
        import time

        match_features: list[dict[str, float]] = []
        nonmatch_features: list[dict[str, float]] = []

        for pensioner, cgr_vet, is_match in pairs:
            feats = self._extract_features(pensioner, cgr_vet)
            if is_match:
                match_features.append(feats)
            else:
                nonmatch_features.append(feats)

        # Estimate m and u probabilities per feature
        m_probs: dict[str, float] = {}
        u_probs: dict[str, float] = {}

        for name in self.FEATURE_NAMES:
            if match_features:
                m_vals = [f[name] for f in match_features]
                m_probs[name] = sum(m_vals) / len(m_vals)
            else:
                m_probs[name] = 0.5

            if nonmatch_features:
                u_vals = [f[name] for f in nonmatch_features]
                u_probs[name] = sum(u_vals) / len(u_vals)
            else:
                u_probs[name] = 0.1

        self._model = MatchModel(
            model_version="1",
            feature_schema=self.FEATURE_NAMES,
            trained_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            feature_count=len(self.FEATURE_NAMES),
            training_pair_count=len(pairs),
            m_probs=m_probs,
            u_probs=u_probs,
        )
        return self._model

    def predict(
        self, pensioner: dict, cgr_vet: dict
    ) -> tuple[float, dict[str, Any]]:
        """Predict match probability. Returns (probability, evidence)."""
        if not self.is_trained:
            return 0.5, {"reason": "untrained"}

        feats = self._extract_features(pensioner, cgr_vet)
        return self._model.predict(feats)

    def explain(
        self, pensioner: dict, cgr_vet: dict
    ) -> dict[str, Any]:
        """Explain prediction with per-feature breakdown."""
        _prob, evidence = self.predict(pensioner, cgr_vet)
        return evidence

    def save(self, path: Path) -> None:
        if self._model:
            self._model.save(path)

    @classmethod
    def load(cls, path: Path) -> "FellegiSunterMatcher":
        m = cls()
        m._model = MatchModel.load(path)
        return m

    def _extract_features(
        self, pensioner: dict, cgr_vet: dict
    ) -> dict[str, float]:
        """Extract comparison features for a pair."""
        p_name = NameEvidence.from_record(pensioner)
        c_name = NameEvidence.from_record({
            "first_name": cgr_vet.get("first_name", ""),
            "last_name": cgr_vet.get("last_name", ""),
        })

        # Name similarity via fuzzy match
        name_sim = p_name.fuzzy_match(c_name)

        # Birth year match
        p_by = _safe_int(pensioner.get("birth_year"))
        c_by = _safe_int(cgr_vet.get("born"))
        birth_match = 1.0 if (p_by and c_by and abs(p_by - c_by) <= 2) else 0.0

        # Unit state match
        p_unit = str(pensioner.get("regiment", "")).upper()
        c_unit = str(cgr_vet.get("unit", "")).upper()
        p_states = _state_codes_in(p_unit)
        c_states = _state_codes_in(c_unit)
        unit_match = 1.0 if (p_states and c_states and p_states & c_states) else 0.0

        # First initial
        p_first = str(pensioner.get("first_name", ""))
        c_first = str(cgr_vet.get("first_name", ""))
        init_match = 1.0 if (p_first and c_first and p_first[0].upper() == c_first[0].upper()) else 0.0

        # Metaphone last (simple: same first 3 chars)
        p_last = p_name.last_normalized
        c_last = c_name.last_normalized
        meta_match = 1.0 if (p_last[:3] == c_last[:3] and len(p_last) >= 3 and len(c_last) >= 3) else 0.0

        return {
            "name_similarity": name_sim,
            "birth_year_match": birth_match,
            "unit_state_match": unit_match,
            "first_initial_match": init_match,
            "metaphone_last": meta_match,
        }


_STATE_CODES = {
    "AL", "MS", "TN", "TX", "GA", "FL", "AR", "SC", "NC", "VA",
    "LA", "KY", "MO", "MD", "OK", "IN", "IL", "OH", "PA", "NY",
}


def _state_codes_in(text: str) -> set[str]:
    return {s for s in _STATE_CODES if s in text}


def _safe_int(val: Any) -> int | None:
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


# ============================================================
# Convenience scorer (issue #55) — same signature as fag/scoring.py
# ============================================================

def score_candidate(
    local: dict, candidate: dict, *, model: MatchModel | None = None
) -> tuple[float, dict]:
    """Score a candidate against local context using Fellegi-Sunter.

    Matches the signature of scripts.fag.scoring.score_candidate()
    so it can be swapped in via recipe scoring.method.

    Args:
        local: pensioner dict with first_name, last_name, birth_year,
               death_year, regiment
        candidate: FaG candidate dict with name, details, etc.
        model: optional pre-trained MatchModel. When None, returns
               a default score (0.5) with reason="no_model".

    Returns:
        (score, evidence_dict)
    """
    if model is None:
        return 0.5, {"reason": "no_fellegi_sunter_model", "score_breakdown": {}}

    # Build features from local + candidate
    p_name = NameEvidence.from_record({
        "first_name": local.get("first_name", ""),
        "last_name": local.get("last_name", ""),
    })
    c_name = NameEvidence.from_record({
        "first_name": candidate.get("name", "").split()[0] if candidate.get("name") else "",
        "last_name": candidate.get("name", "").split()[-1] if candidate.get("name") else "",
    })
    details = candidate.get("details") or {}

    name_sim = p_name.fuzzy_match(c_name)

    p_by = _safe_int(local.get("birth_year") or local.get("_birth_year"))
    c_by = _safe_int(details.get("birth_year"))
    birth_match = 1.0 if (p_by and c_by and abs(p_by - c_by) <= 2) else 0.0

    p_unit = str(local.get("regiment", "")).upper()
    c_state = str(details.get("state", "")).upper()
    unit_match = 1.0 if (p_unit and c_state and c_state in _STATE_CODES and c_state in p_unit) else 0.0

    p_first = str(local.get("first_name", ""))
    c_name_str = str(candidate.get("name", ""))
    init_match = 1.0 if (p_first and c_name_str and p_first[0].upper() == c_name_str[0].upper()) else 0.0

    p_last = p_name.last_normalized
    c_last = c_name.last_normalized
    meta_match = 1.0 if (p_last[:3] == c_last[:3] and len(p_last) >= 3 and len(c_last) >= 3) else 0.0

    features = {
        "name_similarity": name_sim,
        "birth_year_match": birth_match,
        "unit_state_match": unit_match,
        "first_initial_match": init_match,
        "metaphone_last": meta_match,
    }

    probability, evidence = model.predict(features)
    return probability, evidence
