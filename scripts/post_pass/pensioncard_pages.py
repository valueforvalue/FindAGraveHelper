"""Pensioncard pages post-pass (Slice 2 + #101 auto-derive).

Moves the inline `_annotate_pensioncard_pages` helper from
`scripts/pipeline/run_unified.py` into a post-pass module with a
flat `run(results_path, *, config, out_dir, log) -> PostPassStats`
signature. Behavior is preserved byte-for-byte: reads a sidecar
JSON of `{pensioner_id: [page_id, ...]}`, populates each matching
state row's `pensioncard_pages` field, and atomically rewrites
state.jsonl.

Issue #101 (auto-derive): when no sidecar is present, the pass
derives a minimal sidecar from each row's `pensioncard_iiif_url`
field. The IIIF URL pattern is
`https://digitalprairie.ok.gov/iiif/2/pensioncard:{id}/full/.../default.jpg`;
for single-page items, the page_id IS the pensioncard_id (per
`scripts/ingest/fetch_pensioncard_pages.py` docstring — 73% of
pensioncards are single-page). The auto-derive path covers those
73% without operator action. Compound items (2+ sides) still
require a real fetch — a warning fires when the run is > 100
records (operator likely has compound items they don't know
about).

The operator-built sidecar (when present) wins. The auto-derive
path is the fallback for the missed-handshake case.

Note: the pre-loop "load pensioncard_pages cache" block in
`run_unified.py` (lines 852–864) is intentionally NOT part of
this pass. That cache is consumed during per-pensioner row
building (where `row["pensioncard_pages"] = pages` happens inline),
which is the main loop's responsibility, not a post-pass.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from scripts.post_pass.types import BasePassConfig, PostPassStats


# Compound-item threshold: when the run is larger than this AND
# the auto-derive path fires, log a warning that the operator
# may have compound items that the auto-derive missed. 100
# is a deliberately conservative threshold: every smoke test
# and the G10 verification run are well under it.
_COMPOUND_WARN_THRESHOLD = 100

# Regex for extracting the pensioncard_id from the IIIF URL.
# Matches `/iiif/2/pensioncard:{id}/...` and captures {id}.
_IIIF_ID_RE = re.compile(r"/pensioncard:(\d+)/")


def _extract_pensioncard_id(iiif_url: str | None) -> int | None:
    """Return the pensioncard_id from a IIIF URL, or None.

    The URL pattern is
    `https://digitalprairie.ok.gov/iiif/2/pensioncard:{id}/full/.../default.jpg`.
    For single-page items, the page_id IS the pensioncard_id;
    for compound items, the API returns a different pageptr per
    side. The auto-derive path produces `[pensioncard_id]` which
    is correct for single-page; for compound, the operator's
    sidecar (built via `fetch_pensioncard_pages.py`) is the
    correct path.
    """
    if not iiif_url:
        return None
    m = _IIIF_ID_RE.search(iiif_url)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _derive_sidecar_from_results(results_path: Path) -> dict[str, list[int]]:
    """Build a {pensioner_id: [pensioncard_id]} sidecar from
    `pensioncard_iiif_url` fields in results.jsonl.

    Returns an empty dict when results.jsonl is missing or has
    no rows with a parseable IIIF URL.
    """
    out: dict[str, list[int]] = {}
    if not results_path.exists():
        return out
    with results_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            pid = rec.get("pensioner_id")
            if pid is None:
                continue
            pcid = _extract_pensioncard_id(rec.get("pensioncard_iiif_url"))
            if pcid is None:
                continue
            out[str(pid)] = [pcid]
    return out


def _save_sidecar(sidecar_path: Path, data: dict[str, list[int]]) -> None:
    """Persist a derived sidecar. Atomic write via .tmp + replace."""
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = sidecar_path.with_suffix(sidecar_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
    )
    tmp.replace(sidecar_path)


@dataclass(frozen=True)
class PensioncardPagesConfig(BasePassConfig):
    """Configuration for the pensioncard_pages pass.

    `sidecar_path` is the explicit path to the sidecar JSON. When
    None, the pass auto-detects `<out_dir>/pensioncard_pages.json`.

    `fetch_command` (issue #81): an optional callable with the
    signature `(input_path, output_path, throttle_seconds) -> None`
    that builds a real sidecar (including compound items, where
    the auto-derive path produces wrong page lists). The pass
    invokes it when `FETCH_PENSIONCARD_PAGES=1` is set; the
    env var gates the call (opt-in — the auto-derive path
    covers the 73% single-page case by default).
    """

    sidecar_path: Path | None = None
    fetch_command: Any | None = None


class _LoggerLike(Protocol):
    """Subset of logging.Logger used by this pass."""

    def info(self, msg: str, *args: Any) -> None: ...
    def warning(self, msg: str, *args: Any) -> None: ...


def run(
    results_path: Path,
    *,
    config: PensioncardPagesConfig,
    out_dir: Path,
    log: _LoggerLike,
) -> PostPassStats:
    """Annotate state.jsonl rows with pensioncard_pages from a sidecar.

    Resolution order (issue #101):
      1. `config.sidecar_path` (CLI --pensioncard-pages) — wins.
      2. `<out_dir>/pensioncard_pages.json` — auto-detected.
      3. **Auto-derive** from each row's `pensioncard_iiif_url` —
         the IIIF URL pattern has the pensioncard_id baked in
         (single-page items). This is the new fallback path; for
         compound items, the operator's sidecar is still the
         correct path.
      4. None of the above → pass skips.

    On success, rewrites `results_path` atomically (tmp file +
    replace) with each matching row's `pensioncard_pages` field
    populated. When the auto-derive path is used, the derived
    sidecar is written to `<out_dir>/pensioncard_pages.json` so
    subsequent runs that load results.jsonl see the populated
    fields without re-deriving.

    Args:
        results_path: Path to state.jsonl (L5 newline-delimited).
        config: Pass config (sidecar path).
        out_dir: Output directory (used for sidecar auto-detection
            and for the derived-sidecar write-back).
        log: Logger for non-fatal warnings.

    Returns:
        PostPassStats with `name="pensioncard_pages"`, `skipped=True`
        when no sidecar exists AND no row has a parseable
        `pensioncard_iiif_url`, `matched` set to the count of
        rows whose `pensioncard_pages` field was populated.
    """
    started = time.monotonic()

    # Issue #81: opt-in auto-fetch of compound pensioncard pages.
    # When FETCH_PENSIONCARD_PAGES=1 is set AND a fetch_command
    # is supplied, run it before the sidecar-detection chain.
    # Failure is non-fatal: log a warning, fall through to the
    # auto-detect / auto-derive chain.
    if (
        config.fetch_command is not None
        and os.environ.get("FETCH_PENSIONCARD_PAGES", "").strip().lower()
        in ("1", "true", "yes")
    ):
        derived_path = out_dir / "pensioncard_pages.json"
        try:
            log.info(
                "pensioncard_pages: FETCH_PENSIONCARD_PAGES=1; "
                "invoking fetch command → %s",
                derived_path,
            )
            config.fetch_command(
                results_path, derived_path, 0.25
            )
            if derived_path.exists():
                sidecar = derived_path
                log.info(
                    "pensioncard_pages: fetch produced sidecar at %s",
                    derived_path,
                )
            else:
                log.warning(
                    "pensioncard_pages: fetch did not produce a sidecar; "
                    "falling through to auto-detect / auto-derive."
                )
        except Exception as exc:
            log.warning(
                "pensioncard_pages: fetch failed (%s); "
                "falling through to auto-detect / auto-derive.",
                exc,
            )

    sidecar: Path | None = None
    if sidecar is None:
        if config.sidecar_path and config.sidecar_path.exists():
            sidecar = config.sidecar_path
        else:
            candidate = out_dir / "pensioncard_pages.json"
            if candidate.exists():
                sidecar = candidate

    auto_derived = False
    if sidecar is None:
        # Issue #101: auto-derive from existing pensioncard_iiif_url
        # fields in results.jsonl. Covers the 73% single-page case
        # without operator action.
        cache = _derive_sidecar_from_results(results_path)
        if cache:
            auto_derived = True
            derived_path = out_dir / "pensioncard_pages.json"
            _save_sidecar(derived_path, cache)
            sidecar = derived_path
            log.info(
                "pensioncard_pages: auto-derived sidecar with %d entries "
                "from %s (single-page items only; compound items "
                "require scripts/ingest/fetch_pensioncard_pages.py)",
                len(cache),
                results_path,
            )
            if len(cache) > _COMPOUND_WARN_THRESHOLD:
                log.warning(
                    "pensioncard_pages: %d entries auto-derived; if any "
                    "pensioncards are compound (2+ sides), run "
                    "scripts/ingest/fetch_pensioncard_pages.py and "
                    "re-run this post-pass to overwrite the sidecar.",
                    len(cache),
                )
        else:
            return PostPassStats(
                name="pensioncard_pages",
                skipped=True,
                duration_s=time.monotonic() - started,
            )

    try:
        cache = json.loads(sidecar.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("pensioncard_pages annotation load failed: %s", e)
        return PostPassStats(
            name="pensioncard_pages",
            skipped=True,
            errors=1,
            duration_s=time.monotonic() - started,
            notes=f"sidecar load failed: {e}",
        )

    if not cache:
        return PostPassStats(
            name="pensioncard_pages",
            skipped=True,
            duration_s=time.monotonic() - started,
        )

    annotated = 0
    records: list[dict] = []
    if results_path.exists():
        with results_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    records.append({})
                    continue
                pid = str(rec.get("pensioner_id", ""))
                pages = cache.get(pid)
                if pages:
                    rec["pensioncard_pages"] = pages
                    annotated += 1
                records.append(rec)

    if not annotated:
        return PostPassStats(
            name="pensioncard_pages",
            skipped=True,
            duration_s=time.monotonic() - started,
        )

    tmp = results_path.with_suffix(results_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tmp.replace(results_path)

    log.info(
        "Annotated %d records with pensioncard_pages%s from %s",
        annotated,
        " (auto-derived)" if auto_derived else "",
        sidecar,
    )

    return PostPassStats(
        name="pensioncard_pages",
        matched=annotated,
        duration_s=time.monotonic() - started,
        notes=(
            "auto-derived from pensioncard_iiif_url" if auto_derived else ""
        ),
    )


def config_from(parent: Any) -> PensioncardPagesConfig:
    """Build PensioncardPagesConfig from the runner config.

    Pulls `pensioncard_pages_path` (Path | None) from the parent.
    """
    sidecar = getattr(parent, "pensioncard_pages_path", None)
    return PensioncardPagesConfig(sidecar_path=sidecar)