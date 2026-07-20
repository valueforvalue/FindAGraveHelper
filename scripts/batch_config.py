"""Batch config for the unified runner.

A batch config is a per-run JSON file under output/<runname>/config.json
that captures the parameters of one run. The runner reads it via
load_config() and uses it as the single source of truth for
re-invocation (the resume.sh artifact).

v2 (issue #55): RunRecipe replaces BatchConfig. Config file is a
complete run recipe — engine, pipeline modules, scoring method,
strategy ordering, decision threshold, post-processing. Every
togglable feature is a config key. The config file IS the
reproducibility artifact.

Public surface (the seam):
    RunRecipe                dataclass (v2)
    BatchConfig              dataclass (v1, deprecated — auto-upgraded)
    ConfigError              raised on invalid input
    init_batch(runname)      scaffold output/<runname>/config.json (v2 shape)
    load_config(path)        parse + validate (returns RunRecipe)
    validate_config_against_dir(cfg, out_dir)  assert consistency
    upgrade_v1_to_v2(raw)    convert old config.json shape → RunRecipe
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

from scripts.pipeline.scoring_constants import (
    LOW_SCORE_THRESHOLD,
    AUTO_ACCEPT_THRESHOLD,
)


class ConfigError(ValueError):
    """Raised on any batch-config validation failure."""


# ============================================================
# Slug validation
# ============================================================
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$")


def _is_slug(s: str) -> bool:
    return bool(_SLUG_RE.match(s))


# ============================================================
# Engine config
# ============================================================
@dataclass
class EngineConfig:
    backend: str = "findagrave"   # findagrave | newspapers_com
    throttle: float = 2.5
    state_filter: str = "OK"      # OK | TX | US | ""

    @classmethod
    def from_dict(cls, d: dict | None) -> "EngineConfig":
        if d is None:
            return cls()
        return cls(
            backend=d.get("backend", "findagrave"),
            throttle=float(d.get("throttle", 2.5)),
            state_filter=d.get("state_filter", "OK"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# Scoring config
# ============================================================
@dataclass
class ScoringConfig:
    method: str = "weighted"      # weighted | fellegi_sunter | both

    @classmethod
    def from_dict(cls, d: dict | None) -> "ScoringConfig":
        if d is None:
            return cls()
        return cls(method=d.get("method", "weighted"))

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# Strategy config
# ============================================================
@dataclass
class StrategyConfig:
    order: str = "fixed"          # fixed | ranked
    ranker_priors: str = "default"  # default | path/to/priors.json

    @classmethod
    def from_dict(cls, d: dict | None) -> "StrategyConfig":
        if d is None:
            return cls()
        return cls(
            order=d.get("order", "fixed"),
            ranker_priors=d.get("ranker_priors", "default"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# Decision config
# ============================================================
@dataclass
class DecisionConfig:
    threshold: str = "hardcoded"   # hardcoded | auto
    hardcoded_value: float = AUTO_ACCEPT_THRESHOLD
    classifier_model: str | None = None   # null | path/to/classifier.json
    target_precision: float = 0.95

    @classmethod
    def from_dict(cls, d: dict | None) -> "DecisionConfig":
        if d is None:
            return cls()
        return cls(
            threshold=d.get("threshold", "hardcoded"),
            hardcoded_value=float(d.get("hardcoded_value", AUTO_ACCEPT_THRESHOLD)),
            classifier_model=d.get("classifier_model", None),
            target_precision=float(d.get("target_precision", 0.95)),
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["classifier_model"] is None:
            d["classifier_model"] = None
        return d


# ============================================================
# Post-run config
# ============================================================
@dataclass
class PostConfig:
    collect_labels: bool = True
    labels_path: str = "output/labels/labels_v1.jsonl"
    evaluate: bool = False
    dedup: bool = True
    dd_match: bool = True
    spouse_scrape: bool = False

    @classmethod
    def from_dict(cls, d: dict | None) -> "PostConfig":
        if d is None:
            return cls()
        return cls(
            collect_labels=bool(d.get("collect_labels", True)),
            labels_path=d.get("labels_path", "output/labels/labels_v1.jsonl"),
            evaluate=bool(d.get("evaluate", False)),
            dedup=bool(d.get("dedup", True)),
            dd_match=bool(d.get("dd_match", True)),
            spouse_scrape=bool(d.get("spouse_scrape", False)),
        )

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# Pipeline config (modules list)
# ============================================================
DEFAULT_MODULES = ["regional_planner", "fag_scraper", "candidate_scorer", "deep_refiner"]

VALID_MODULES = {
    "regional_planner",
    "fag_scraper",
    "candidate_scorer",
    "deep_refiner",
    "newspapers_scraper",
    "label_collector",
}


@dataclass
class PipelineConfig:
    modules: list[str] = field(default_factory=lambda: list(DEFAULT_MODULES))
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    strategies: StrategyConfig = field(default_factory=StrategyConfig)
    decision: DecisionConfig = field(default_factory=DecisionConfig)

    @classmethod
    def from_dict(cls, d: dict | None) -> "PipelineConfig":
        if d is None:
            return cls()
        modules = d.get("modules", list(DEFAULT_MODULES))
        for m in modules:
            if m not in VALID_MODULES:
                raise ConfigError(
                    f"invalid pipeline module: {m!r}. Valid: {sorted(VALID_MODULES)}"
                )
        return cls(
            modules=list(modules),
            scoring=ScoringConfig.from_dict(d.get("scoring")),
            strategies=StrategyConfig.from_dict(d.get("strategies")),
            decision=DecisionConfig.from_dict(d.get("decision")),
        )

    def to_dict(self) -> dict:
        return {
            "modules": list(self.modules),
            "scoring": self.scoring.to_dict(),
            "strategies": self.strategies.to_dict(),
            "decision": self.decision.to_dict(),
        }


# ============================================================
# RunRecipe (v2)
# ============================================================
def _build_default_recipe() -> dict:
    """Return the default recipe dict used for init_batch scaffolding."""
    return {
        "version": 2,
        "runname": "",
        "inputs": {
            "pensioners": "docs/research/digitalprairie/ok_pensioners.json",
            "cgr": "docs/research/cgr/ok_vets_enriched.jsonl",
            "start_row": 0,
            "end_row": None,
        },
        "engine": EngineConfig().to_dict(),
        "pipeline": PipelineConfig().to_dict(),
        "post": PostConfig().to_dict(),
    }


@dataclass
class InputsConfig:
    pensioners: Path = Path("docs/research/digitalprairie/ok_pensioners.json")
    cgr: Path = Path("docs/research/cgr/ok_vets_enriched.jsonl")
    start_row: int = 0
    end_row: int | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "InputsConfig":
        return cls(
            pensioners=Path(d.get("pensioners", "docs/research/digitalprairie/ok_pensioners.json")),
            cgr=Path(d.get("cgr", "docs/research/cgr/ok_vets_enriched.jsonl")),
            start_row=int(d.get("start_row", 0)),
            end_row=d.get("end_row", None),
        )

    def to_dict(self) -> dict:
        return {
            "pensioners": str(self.pensioners),
            "cgr": str(self.cgr),
            "start_row": self.start_row,
            "end_row": self.end_row,
        }


@dataclass
class RunRecipe:
    """Complete run recipe (v2, issue #55).

    Backward-compatible: load_config() auto-upgrades v1 BatchConfig
    shape to RunRecipe. Old code that reads BatchConfig fields
    (runname, input_path, cgr_path, etc.) can access them as
    recipe.runname / recipe.inputs.pensioners / recipe.inputs.cgr.
    """
    version: int = 2
    runname: str = ""
    inputs: InputsConfig = field(default_factory=InputsConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    post: PostConfig = field(default_factory=PostConfig)

    # ------------------------------------------------------------------
    # Backward-compat aliases so old callers don't break
    # ------------------------------------------------------------------
    @property
    def input_path(self) -> Path:
        return self.inputs.pensioners

    @property
    def cgr_path(self) -> Path:
        return self.inputs.cgr

    @property
    def start_row(self) -> int:
        return self.inputs.start_row

    @property
    def end_row(self) -> int | None:
        return self.inputs.end_row

    @property
    def throttle(self) -> float:
        return self.engine.throttle

    @property
    def low_score_threshold(self) -> float:
        return LOW_SCORE_THRESHOLD

    @property
    def fag_state_filter(self) -> str:
        return self.engine.state_filter

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def runname_is_slug(self) -> bool:
        return _is_slug(self.runname)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "runname": self.runname,
            "inputs": self.inputs.to_dict(),
            "engine": self.engine.to_dict(),
            "pipeline": self.pipeline.to_dict(),
            "post": self.post.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RunRecipe":
        version = d.get("version", 1)
        if version == 1:
            return upgrade_v1_to_v2(d)
        return cls(
            version=2,
            runname=d.get("runname", ""),
            inputs=InputsConfig.from_dict(d.get("inputs", {})),
            engine=EngineConfig.from_dict(d.get("engine")),
            pipeline=PipelineConfig.from_dict(d.get("pipeline")),
            post=PostConfig.from_dict(d.get("post")),
        )


# ============================================================
# V1 → V2 upgrade
# ============================================================
def upgrade_v1_to_v2(raw: dict) -> RunRecipe:
    """Convert a v1 BatchConfig dict to a v2 RunRecipe."""
    return RunRecipe(
        version=2,
        runname=raw.get("runname", ""),
        inputs=InputsConfig(
            pensioners=Path(raw.get("input", raw.get("input_path", "docs/research/digitalprairie/ok_pensioners.json"))),
            cgr=Path(raw.get("cgr", raw.get("cgr_path", "docs/research/cgr/ok_vets_enriched.jsonl"))),
            start_row=raw.get("start_row", 0),
            end_row=raw.get("end_row", None),
        ),
        engine=EngineConfig(
            backend="findagrave",
            throttle=float(raw.get("throttle", 2.5)),
            state_filter=raw.get("fag_state_filter", "OK"),
        ),
    )


# ============================================================
# BatchConfig (v1, kept for backward compat)
# ============================================================
@dataclass
class BatchConfig:
    """Per-run configuration (v1, deprecated by RunRecipe).

    load_config() auto-upgrades to RunRecipe. This class remains
    for type-annotation backward compat in existing callers.
    """
    runname: str
    input_path: Path
    cgr_path: Path
    start_row: int = 0
    end_row: Optional[int] = None
    throttle: float = 2.5
    low_score_threshold: float = LOW_SCORE_THRESHOLD
    fag_state_filter: str = "OK"

    def runname_is_slug(self) -> bool:
        return _is_slug(self.runname)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["input"] = str(d.pop("input_path"))
        d["cgr"] = str(d.pop("cgr_path"))
        return d


# ============================================================
# Defaults
# ============================================================
REQUIRED_KEYS = ("runname",)
REQUIRED_KEYS_V1 = ("runname", "input", "cgr")
DEFAULT_START_ROW = 0
DEFAULT_END_ROW = None
DEFAULT_THROTTLE = 2.5
DEFAULT_LOW_SCORE_THRESHOLD = LOW_SCORE_THRESHOLD
DEFAULT_FAG_STATE_FILTER = "OK"


# ============================================================
# init-batch (now scaffolds v2 recipe)
# ============================================================
def init_batch(
    runname: str,
    root: Path = Path("output"),
    overwrite: bool = False,
) -> Path:
    """Scaffold output/<runname>/config.json from v2 recipe defaults.

    Creates the directory if missing. Refuses to clobber an existing
    config.json unless overwrite=True.
    """
    if not _is_slug(runname):
        raise ConfigError(
            f"invalid runname {runname!r}: must be lowercase a-z, 0-9, "
            f"hyphens, underscores; no leading/trailing separator"
        )

    run_dir = Path(root) / runname
    config_path = run_dir / "config.json"

    if run_dir.exists() and not overwrite:
        raise ConfigError(
            f"run directory already exists at {run_dir} "
            f"(remove it first, or pass overwrite=True)"
        )
    if run_dir.exists() and not run_dir.is_dir():
        raise ConfigError(f"{run_dir} exists and is not a directory")

    run_dir.mkdir(parents=True, exist_ok=True)

    template = _build_default_recipe()
    template["runname"] = runname

    config_path.write_text(
        json.dumps(template, indent=2) + "\n",
        encoding="utf-8",
    )
    return config_path.resolve()


# ============================================================
# load_config (returns RunRecipe)
# ============================================================
def load_config(path: Path) -> RunRecipe:
    """Parse + validate a config.json file. Returns RunRecipe (v2).

    Auto-detects v1 shape and upgrades. Backward-compatible.
    """
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"invalid JSON in {path}: {e}") from e

    if not isinstance(raw, dict):
        raise ConfigError(
            f"config root must be a JSON object, got {type(raw).__name__}"
        )

    # Detect v1 vs v2
    version = raw.get("version", 1)
    if version == 1:
        # Validate v1 required keys
        missing = [k for k in REQUIRED_KEYS_V1 if k not in raw]
        if missing:
            raise ConfigError(
                f"missing required key(s) in {path.name}: {', '.join(missing)}"
            )
        return upgrade_v1_to_v2(raw)

    # v2 validation
    if "runname" not in raw or not raw["runname"]:
        raise ConfigError(f"missing required key: runname")

    try:
        return RunRecipe.from_dict(raw)
    except (TypeError, ValueError) as e:
        raise ConfigError(f"invalid config in {path}: {e}") from e


# ============================================================
# validate_config_against_dir
# ============================================================
def validate_config_against_dir(cfg: RunRecipe | BatchConfig, out_dir: Path) -> None:
    """Assert that out_dir's basename matches cfg.runname."""
    out_dir = Path(out_dir)
    if out_dir.name != cfg.runname:
        raise ConfigError(
            f"runname mismatch: config.runname={cfg.runname!r} but "
            f"out_dir basename={out_dir.name!r}"
        )


# ============================================================
# build_manifest
# ============================================================
def build_manifest(
    config: RunRecipe | BatchConfig,
    policy_version: str = "1",
    knowledge_source_versions: dict[str, str] | None = None,
) -> "RunManifest":
    """Construct a RunManifest from a config + policy context."""
    import time
    from scripts.blackboard.schema import RunManifest, ManifestBudget

    runname = config.runname

    # Collect source fingerprints from either shape
    if isinstance(config, RunRecipe):
        fingerprints = {
            "input_path": str(config.inputs.pensioners),
            "cgr_path": str(config.inputs.cgr),
            "fag_state_filter": config.engine.state_filter,
            "scoring_method": config.pipeline.scoring.method,
            "strategy_order": config.pipeline.strategies.order,
            "decision_threshold": config.pipeline.decision.threshold,
            "pipeline_modules": ",".join(config.pipeline.modules),
        }
    else:
        fingerprints = {
            "input_path": str(config.input_path),
            "cgr_path": str(config.cgr_path),
            "fag_state_filter": config.fag_state_filter,
        }

    return RunManifest(
        manifest_id=f"manifest-{runname}",
        run_id=runname,
        parent_manifest_id=None,
        policy_version=policy_version,
        knowledge_source_versions=knowledge_source_versions or {},
        scheduler_budget=ManifestBudget(),
        bot_budget=ManifestBudget(
            max_requests=config.end_row if hasattr(config, 'end_row') else None
        ),
        source_fingerprints=fingerprints,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


__all__ = [
    "RunRecipe",
    "BatchConfig",
    "InputsConfig",
    "EngineConfig",
    "PipelineConfig",
    "ScoringConfig",
    "StrategyConfig",
    "DecisionConfig",
    "PostConfig",
    "ConfigError",
    "init_batch",
    "load_config",
    "validate_config_against_dir",
    "build_manifest",
    "upgrade_v1_to_v2",
    "DEFAULT_MODULES",
    "VALID_MODULES",
]