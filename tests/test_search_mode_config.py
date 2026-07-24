"""Tests for the named aggressiveness modes (issue #78).

The named modes (conservative / standard / aggressive) are
implemented in `scripts/batch_config.py::SearchModeConfig` +
`MODE_DEFAULTS`. These tests pin the behavior so the issue
can be closed and the config can evolve without regressions.

The original issue asked for a `modes` field on BatchConfig;
the implementation uses a `mode` field on the more
fine-grained `SearchModeConfig` (which is what the runner
consumes via `config.search_mode`). This is the standard
config shape and what the rest of the codebase already does.
"""

from __future__ import annotations

import pytest

from scripts.batch_config import (
    MODE_DEFAULTS,
    SearchModeConfig,
    VALID_MODES,
    ConfigError,
)


# ============================================================
# Module-level constants
# ============================================================


def test_valid_modes_set():
    """The three named modes are declared."""
    assert VALID_MODES == {"conservative", "standard", "aggressive"}


def test_mode_defaults_cover_all_valid_modes():
    """Every valid mode has a default preset."""
    for mode in VALID_MODES:
        assert mode in MODE_DEFAULTS, (
            f"MODE_DEFAULTS missing entry for {mode!r}"
        )
        # Each preset has the three parameters the runner reads.
        for key in ("max_refinements", "skip_refine_above", "bail_on_auto_accept"):
            assert key in MODE_DEFAULTS[mode], (
                f"MODE_DEFAULTS[{mode!r}] missing {key!r}"
            )


def test_conservative_more_cautious_than_aggressive():
    """Sanity: conservative should be more cautious (lower
    refinements) and aggressive should be more aggressive
    (higher refinements) — per the issue spec.
    """
    assert (
        MODE_DEFAULTS["conservative"]["max_refinements"]
        < MODE_DEFAULTS["standard"]["max_refinements"]
        <= MODE_DEFAULTS["aggressive"]["max_refinements"]
    )


# ============================================================
# from_dict
# ============================================================


def test_from_dict_default_is_standard():
    """No dict → standard mode with the standard preset."""
    cfg = SearchModeConfig.from_dict(None)
    assert cfg.mode == "standard"
    assert cfg.max_refinements == MODE_DEFAULTS["standard"]["max_refinements"]
    assert cfg.skip_refine_above == MODE_DEFAULTS["standard"]["skip_refine_above"]


def test_from_dict_uses_conservative_preset():
    """mode='conservative' applies the conservative preset."""
    cfg = SearchModeConfig.from_dict({"mode": "conservative"})
    assert cfg.mode == "conservative"
    assert cfg.max_refinements == MODE_DEFAULTS["conservative"]["max_refinements"]


def test_from_dict_uses_aggressive_preset():
    """mode='aggressive' applies the aggressive preset."""
    cfg = SearchModeConfig.from_dict({"mode": "aggressive"})
    assert cfg.mode == "aggressive"
    assert cfg.max_refinements == MODE_DEFAULTS["aggressive"]["max_refinements"]


def test_from_dict_operator_override_wins():
    """Operator-supplied fields override the preset's values."""
    cfg = SearchModeConfig.from_dict({
        "mode": "standard",
        "max_refinements": 99,
    })
    assert cfg.mode == "standard"
    assert cfg.max_refinements == 99  # operator override
    # Non-overridden fields still come from the preset.
    assert cfg.skip_refine_above == MODE_DEFAULTS["standard"]["skip_refine_above"]


def test_from_dict_rejects_unknown_mode():
    """Unknown mode names raise ConfigError listing the valid set."""
    with pytest.raises(ConfigError) as excinfo:
        SearchModeConfig.from_dict({"mode": "ultra"})
    msg = str(excinfo.value)
    assert "ultra" in msg
    for m in ("conservative", "standard", "aggressive"):
        assert m in msg


# ============================================================
# to_dict round-trip
# ============================================================


def test_to_dict_round_trip():
    """to_dict + from_dict round-trip preserves the mode + fields."""
    original = SearchModeConfig(
        mode="aggressive",
        max_refinements=8,
        skip_refine_above=0.90,
        bail_on_auto_accept=False,
    )
    rebuilt = SearchModeConfig.from_dict(original.to_dict())
    assert rebuilt.mode == original.mode
    assert rebuilt.max_refinements == original.max_refinements
    assert rebuilt.skip_refine_above == original.skip_refine_above
    assert rebuilt.bail_on_auto_accept == original.bail_on_auto_accept