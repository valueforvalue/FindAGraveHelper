"""View.html copy post-pass (Slice 3).

Moves the inline `copy_view_html_if_missing` helper and the four
`EMBEDDED_*_PLACEHOLDER` constants from `scripts/pipeline/run_unified.py`
into a post-pass module. The low-level `copy_view_html_if_missing()`
helper is preserved verbatim (same signature, same return value) so
existing direct callers in tests and CLI scripts keep working.

The post-pass `run(config, log) -> PostPassStats` wrapper translates
the bool return into the standard PostPassStats shape.

Back-compat (per Slice 3's design decision):
  - `scripts.pipeline.run_unified.copy_view_html_if_missing` is
    re-exported (shim).
  - `scripts.pipeline.run_unified.EMBEDDED_*_PLACEHOLDER` constants
    stay accessible via re-export.
  - External tests (test_view_ux_j9, test_unified_config_externalization)
    import `copy_view_html_if_missing` directly; the shim keeps them
    green without modification.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol

from scripts.post_pass.types import BasePassConfig, PostPassStats

EMBEDDED_DATA_PLACEHOLDER = "<!--EMBEDDED_RESULTS_JSONL-->"
EMBEDDED_DD_MATCH_PLACEHOLDER = "<!--EMBEDDED_DD_MATCH_JSON-->"
EMBEDDED_SPOUSE_MATCH_PLACEHOLDER = "<!--EMBEDDED_SPOUSE_MATCH_JSON-->"
EMBEDDED_SPOUSE_FOLLOWUPS_PLACEHOLDER = "<!--EMBEDDED_SPOUSE_FOLLOWUPS_JSON-->"


@dataclass(frozen=True)
class ViewCopyConfig(BasePassConfig):
    """Configuration for the view_copy pass.

    `source` is the canonical view.html path (or None to skip).
    `dest_dir` is the run output directory.
    `dest_filename` is the per-run filename (default "view.html").
    `results_path`, `dd_match_path`, `spouse_match_path`, and
    `spouse_followups_path` are optional sidecars to embed as
    `<script type="application/json">` blocks.
    """

    source: Path | None
    dest_dir: Path
    dest_filename: str = "view.html"
    results_path: Path | None = None
    dd_match_path: Path | None = None


class _LoggerLike(Protocol):
    """Subset of logging.Logger used by this pass."""

    def info(self, msg: str, *args: Any) -> None: ...
    def warning(self, msg: str, *args: Any) -> None: ...


def copy_view_html_if_missing(
    source: Optional[Path],
    dest_dir: Path,
    dest_filename: str = "view.html",
    results_path: Optional[Path] = None,
    dd_match_path: Optional[Path] = None,
) -> bool:
    """Copy source -> dest_dir/dest_filename iff dest doesn't exist.

    If `results_path` is provided AND the source view.html contains
    the EMBEDDED_DATA_PLACEHOLDER, the matching JSONL content is
    injected as a <script type="application/json"> block so the
    page works from file:// without needing a server.

    If `dd_match_path` is provided AND the source contains the
    EMBEDDED_DD_MATCH_PLACEHOLDER, the matching JSON sidecar is
    similarly embedded (J14).

    Returns True if a copy happened, False otherwise (skipped because
    dest exists, or source missing, or source/dest identical path).
    Never raises on missing source — the run proceeds without a
    per-run view.html.
    """
    if source is None:
        return False
    source = Path(source)
    dest_dir = Path(dest_dir)
    dest = dest_dir / dest_filename
    if dest.exists():
        return False
    if not source.exists():
        return False
    dest_dir.mkdir(parents=True, exist_ok=True)

    text = source.read_text(encoding="utf-8")
    # Embed the results.jsonl as a JSON script block (J9).
    if results_path is not None and EMBEDDED_DATA_PLACEHOLDER in text:
        if results_path.exists():
            embedded = results_path.read_text(encoding="utf-8")
            # Escape </script> inside the JSON to keep the script
            # block well-formed (the JSON itself shouldn't contain
            # it, but defense in depth).
            safe = embedded.replace("</script>", "<\\/script>")
            block = (
                f'<script type="application/json" id="embedded-results-jsonl">\n'
                f'{safe}\n'
                f'</script>\n'
            )
            text = text.replace(EMBEDDED_DATA_PLACEHOLDER, block)
        else:
            # No results yet; drop the placeholder so the page
            # still loads (the user can pick a file manually).
            text = text.replace(EMBEDDED_DATA_PLACEHOLDER, "")

    # J14: same embed pattern for the dd_match sidecar.
    if dd_match_path is not None and EMBEDDED_DD_MATCH_PLACEHOLDER in text:
        if dd_match_path.exists():
            sidecar = dd_match_path.read_text(encoding="utf-8")
            safe = sidecar.replace("</script>", "<\\/script>")
            block = (
                f'<script type="application/json" id="embedded-dd-match">\n'
                f'{safe}\n'
                f'</script>\n'
            )
            text = text.replace(EMBEDDED_DD_MATCH_PLACEHOLDER, block)
        else:
            # No DD sidecar yet (e.g. no DD source configured).
            text = text.replace(EMBEDDED_DD_MATCH_PLACEHOLDER, "")

    # J15-S2: spouse_match sidecar (gold 'Spouse match' badge data).
    spouse_match_path = dest_dir / "spouse_match.json"
    if spouse_match_path is not None and EMBEDDED_SPOUSE_MATCH_PLACEHOLDER in text:
        if spouse_match_path.exists():
            sidecar = spouse_match_path.read_text(encoding="utf-8")
            safe = sidecar.replace("</script>", "<\\/script>")
            block = (
                f'<script type="application/json" id="embedded-spouse-match">\n'
                f'{safe}\n'
                f'</script>\n'
            )
            text = text.replace(EMBEDDED_SPOUSE_MATCH_PLACEHOLDER, block)
        else:
            text = text.replace(EMBEDDED_SPOUSE_MATCH_PLACEHOLDER, "")

    # J16: spouse_followups sidecar (deceased husbands; not
    # pensioners). JSONL (one record per line), so we read it
    # as text and embed as a single <script> block.
    spouse_followups_path = dest_dir / "spouse_followups.jsonl"
    if EMBEDDED_SPOUSE_FOLLOWUPS_PLACEHOLDER in text:
        if spouse_followups_path.exists():
            sidecar = spouse_followups_path.read_text(encoding="utf-8")
            safe = sidecar.replace("</script>", "<\\/script>")
            block = (
                f'<script type="application/json" id="embedded-spouse-followups">\n'
                f'{safe}\n'
                f'</script>\n'
            )
            text = text.replace(EMBEDDED_SPOUSE_FOLLOWUPS_PLACEHOLDER, block)
        else:
            text = text.replace(EMBEDDED_SPOUSE_FOLLOWUPS_PLACEHOLDER, "")

    dest.write_text(text, encoding="utf-8")
    return True


def run(
    *,
    config: ViewCopyConfig,
    log: _LoggerLike,
) -> PostPassStats:
    """Post-pass wrapper around `copy_view_html_if_missing`.

    Translates the bool return into PostPassStats:
      - True  → matched=1, skipped=False
      - False → matched=0, skipped=True

    Args:
        config: Pass config (source, dest_dir, optional sidecars).
        log: Logger (currently unused; the underlying helper logs
            via the same logger interface).

    Returns:
        PostPassStats with `name="view_copy"`.
    """
    del log  # low-level helper handles its own logging
    started = time.monotonic()
    copied = copy_view_html_if_missing(
        source=config.source,
        dest_dir=config.dest_dir,
        dest_filename=config.dest_filename,
        results_path=config.results_path,
        dd_match_path=config.dd_match_path,
    )
    return PostPassStats(
        name="view_copy",
        skipped=not copied,
        matched=1 if copied else 0,
        duration_s=time.monotonic() - started,
    )


def config_from(parent: Any, *, dest_dir: Path, **overrides: Any) -> ViewCopyConfig:
    """Build ViewCopyConfig from the runner config + run context.

    Pulls `view_html_source` from the parent by default. Callers can
    pass `source=...` via overrides to supply a pre-resolved path
    (e.g. one that has already had the runner's default applied).
    The dest filename is ALWAYS `"view.html"` regardless of
    `results_filename` (state.jsonl vs view.html are separate
    concerns). `dest_dir` is passed by the runner (per-run, not a
    config field). Additional sidecars can be supplied via `overrides`.
    """
    source = overrides.pop("source", None)
    if source is None:
        source = getattr(parent, "view_html_source", None)
    return ViewCopyConfig(
        source=source,
        dest_dir=dest_dir,
        dest_filename="view.html",
        **overrides,
    )