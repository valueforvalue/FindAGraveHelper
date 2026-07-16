"""Batch config for the unified runner.

A batch config is a per-run JSON file under output/<runname>/config.json
that captures the parameters of one run. The runner reads it via
`load_config()` and uses it as the single source of truth for
re-invocation (the resume.sh artifact).

Public surface (the seam):
    BatchConfig              dataclass
    ConfigError              raised on invalid input
    init_batch(runname)      scaffold output/<runname>/config.json
    load_config(path)        parse + validate a config.json
    validate_config_against_dir(cfg, out_dir)  assert consistency
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ============================================================
# Errors
# ============================================================
class ConfigError(ValueError):
    """Raised on any batch-config validation failure."""


# ============================================================
# Slug validation
# ============================================================
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$")


def _is_slug(s: str) -> bool:
    """True iff s is a valid runname slug.

    Rules: lowercase a-z, 0-9, hyphen, underscore.
    Must not start or end with a separator.
    Single-char names must be [a-z0-9].
    """
    return bool(_SLUG_RE.match(s))


# ============================================================
# Dataclass
# ============================================================
@dataclass
class BatchConfig:
    """Per-run configuration loaded from output/<runname>/config.json.

    Field names mirror the JSON keys (snake_case). Paths are stored
    as Path objects so callers don't need to re-parse strings.
    """
    runname: str
    input_path: Path
    cgr_path: Path
    start_row: int = 0
    end_row: Optional[int] = None
    throttle: float = 2.5
    low_score_threshold: float = 0.40

    def runname_is_slug(self) -> bool:
        """True iff self.runname is a valid runname slug."""
        return _is_slug(self.runname)

    def to_dict(self) -> dict:
        """Serialize back to a dict (Path objects → str for JSON friendliness)."""
        d = asdict(self)
        # Path → str so json.dumps works without a custom encoder
        d["input"] = str(d.pop("input_path"))
        d["cgr"] = str(d.pop("cgr_path"))
        return d


# ============================================================
# Defaults
# ============================================================
REQUIRED_KEYS = ("runname", "input", "cgr")
DEFAULT_START_ROW = 0
DEFAULT_END_ROW = None
DEFAULT_THROTTLE = 2.5
DEFAULT_LOW_SCORE_THRESHOLD = 0.40


# ============================================================
# init-batch
# ============================================================
def init_batch(
    runname: str,
    root: Path = Path("output"),
    overwrite: bool = False,
) -> Path:
    """Scaffold `root/<runname>/config.json` from defaults.

    Creates the directory if missing. Refuses to clobber an existing
    config.json unless `overwrite=True`.

    Args:
        runname: The slug identifying the run. Must be a valid slug
                 (lowercase a-z, 0-9, hyphens, underscores).
        root:    Parent directory. Defaults to "output/" relative to cwd.
        overwrite: Allow replacing an existing config.json. Off by default.

    Returns:
        Absolute path to the created config.json.

    Raises:
        ConfigError: invalid runname, dir exists, or write fails.
    """
    if not _is_slug(runname):
        raise ConfigError(
            f"invalid runname {runname!r}: must be lowercase a-z, 0-9, "
            f"hyphens, underscores; no leading/trailing separator"
        )

    run_dir = Path(root) / runname
    config_path = run_dir / "config.json"

    # Refuse to clobber an existing run dir unless overwrite=True.
    # This protects in-progress runs from accidental re-init.
    if run_dir.exists() and not overwrite:
        raise ConfigError(
            f"run directory already exists at {run_dir} "
            f"(remove it first, or pass overwrite=True)"
        )
    if run_dir.exists() and not run_dir.is_dir():
        raise ConfigError(f"{run_dir} exists and is not a directory")

    run_dir.mkdir(parents=True, exist_ok=True)

    template = {
        "runname": runname,
        "input": "docs/research/digitalprairie/ok_pensioners.json",
        "cgr": "docs/research/cgr/ok_vets_enriched.jsonl",
        "start_row": DEFAULT_START_ROW,
        "end_row": DEFAULT_END_ROW,
        "throttle": DEFAULT_THROTTLE,
        "low_score_threshold": DEFAULT_LOW_SCORE_THRESHOLD,
    }
    config_path.write_text(
        json.dumps(template, indent=2) + "\n",
        encoding="utf-8",
    )
    return config_path.resolve()


# ============================================================
# load_config
# ============================================================
def load_config(path: Path) -> BatchConfig:
    """Parse + validate a config.json file.

    Required keys: runname, input, cgr.
    Optional keys (with defaults): start_row, end_row, throttle,
    low_score_threshold.

    Args:
        path: Path to a JSON file.

    Returns:
        A populated BatchConfig.

    Raises:
        ConfigError: file missing, JSON invalid, required key missing,
                     or field has the wrong type.
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

    # Required keys
    missing = [k for k in REQUIRED_KEYS if k not in raw]
    if missing:
        raise ConfigError(
            f"missing required key(s) in {path.name}: {', '.join(missing)}"
        )

    # Type checks (strict — no coercion)
    for key, expected in (
        ("runname", str),
        ("input", str),
        ("cgr", str),
        ("start_row", int),
        ("throttle", (int, float)),
        ("low_score_threshold", (int, float)),
    ):
        if key in raw and not isinstance(raw[key], expected):
            raise ConfigError(
                f"{key} must be {expected}, got {type(raw[key]).__name__}"
            )
    if "end_row" in raw and raw["end_row"] is not None \
            and not isinstance(raw["end_row"], int):
        raise ConfigError(
            f"end_row must be int or null, got {type(raw['end_row']).__name__}"
        )

    return BatchConfig(
        runname=raw["runname"],
        input_path=Path(raw["input"]),
        cgr_path=Path(raw["cgr"]),
        start_row=raw.get("start_row", DEFAULT_START_ROW),
        end_row=raw.get("end_row", DEFAULT_END_ROW),
        throttle=float(raw.get("throttle", DEFAULT_THROTTLE)),
        low_score_threshold=float(
            raw.get("low_score_threshold", DEFAULT_LOW_SCORE_THRESHOLD)
        ),
    )


# ============================================================
# validate_config_against_dir
# ============================================================
def validate_config_against_dir(cfg: BatchConfig, out_dir: Path) -> None:
    """Assert that out_dir's basename matches cfg.runname.

    Raises:
        ConfigError: on mismatch.
    """
    out_dir = Path(out_dir)
    if out_dir.name != cfg.runname:
        raise ConfigError(
            f"runname mismatch: config.runname={cfg.runname!r} but "
            f"out_dir basename={out_dir.name!r}"
        )


__all__ = [
    "BatchConfig",
    "ConfigError",
    "init_batch",
    "load_config",
    "validate_config_against_dir",
]