"""POST_PASSES registry — Slice 7.

The full list of post-passes that run after the main scheduler
loop closes. Each entry is `(callable, factory)` where `factory`
takes the runner config + per-run context and returns the
frozen config dataclass the callable expects.

Adding a new post-pass = append one tuple here. No new code in
`run_unified.py` (only one loop that calls each entry).

Per the design's Q2 decision, each pass owns its config dataclass;
the factory extracts pass-specific fields from the runner config
or environment. Passes that need per-run context (browser session,
results path, view.html source, out_dir) get those via the factory
closure that the runner builds.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from scripts.post_pass import (
    dd,
    labels,
    observation_enrichment,
    pensioncard_pages,
    spouse,
    state_schema,
    view_copy,
)
from scripts.post_pass.types import BasePassConfig, PostPassStats


# Type alias for the factory signature. Each factory returns a
# (BasePassConfig, dict) where the dict is passed via **kwargs
# to the callable (for non-config arguments like browser_session).
PassFactory = Callable[[Any], tuple[BasePassConfig, dict[str, Any]]]
PassCallable = Callable[..., PostPassStats]


# Per-run context the runner needs to thread through factories.
# Populated once at the start of `run_post_passes()`.
class _RunContext:
    def __init__(
        self,
        *,
        config: Any,
        run_id: str,
        log: Any,
        out_dir: Path,
        state_repo: Any,
        store: Any,
        browser_session: Any,
        view_html_source: Path | None,
    ) -> None:
        self.config = config
        self.run_id = run_id
        self.log = log
        self.out_dir = out_dir
        self.state_repo = state_repo
        self.store = store
        self.browser_session = browser_session
        self.view_html_source = view_html_source


# Each entry: (name, callable, factory)
# The factory returns (pass_config, kwargs) where kwargs are
# extra non-config arguments the callable expects (e.g. browser_session).
POST_PASSES: list[tuple[str, PassCallable, PassFactory]] = [
    # 1. DixieData match (env-gated)
    (
        "dd",
        dd.run,
        lambda ctx: (
            dd.config_from(ctx.config),
            {
                "state_repo": ctx.state_repo,
                "store": ctx.store,
                "run_id": ctx.run_id,
                "log": ctx.log,
            },
        ),
    ),
    # 2. Spouse cross-reference (env-gated via FAG_SCRAPE_SPOUSE)
    (
        "spouse",
        spouse.run,
        lambda ctx: (
            spouse.config_from(
                ctx.config,
                browser_session=ctx.browser_session,
                results_path=ctx.state_repo.path,
            ),
            {
                "store": ctx.store,
                "run_id": ctx.run_id,
                "log": ctx.log,
            },
        ),
    ),
    # 3. Observation enrichment (writes CGR/DD/Spouse into state rows)
    (
        "observation_enrichment",
        observation_enrichment.run,
        lambda ctx: (
            observation_enrichment.config_from(ctx.config),
            {
                "state_repo": ctx.state_repo,
                "store": ctx.store,
                "run_id": ctx.run_id,
                "log": ctx.log,
            },
        ),
    ),
    # 4. Pensioncard pages annotation
    (
        "pensioncard_pages",
        pensioncard_pages.run,
        lambda ctx: (
            pensioncard_pages.config_from(ctx.config),
            {
                "results_path": ctx.state_repo.path,
                "out_dir": ctx.out_dir,
                "log": ctx.log,
            },
        ),
    ),
    # 5. View.html copy + embed
    (
        "view_copy",
        view_copy.run,
        lambda ctx: (
            view_copy.config_from(
                ctx.config,
                dest_dir=ctx.out_dir,
                results_path=ctx.state_repo.path,
                source=ctx.view_html_source,
            ),
            {"log": ctx.log},
        ),
    ),
    # 6. Label collection (recipe-gated)
    (
        "labels",
        labels.run,
        lambda ctx: (
            labels.config_from(ctx.config, out_dir=ctx.out_dir),
            {"log": ctx.log},
        ),
    ),
    # 7. Projection schema (issue #98). Writes state.schema.json
    #    next to state.jsonl so view.html can detect shape drift.
    (
        "state_schema",
        state_schema.run,
        lambda ctx: (
            state_schema.config_from(
                ctx.config, results_path=ctx.state_repo.path
            ),
            {"log": ctx.log},
        ),
    ),
]


def run_post_passes(
    *,
    config: Any,
    run_id: str,
    log: Any,
    out_dir: Path,
    state_repo: Any,
    store: Any,
    browser_session: Any,
    view_html_source: Path | None,
) -> list[PostPassStats]:
    """Run every registered post-pass in order.

    Each pass gets its config + kwargs from the registry's factory.
    A pass that raises or returns an error does NOT abort the loop
    (per the inline behavior in run_unified.py where each block was
    individually try/except'd). The individual passes already
    handle their own exceptions and report via PostPassStats.

    Args:
        config: The runner's UnifiedRunnerConfig (or equivalent).
        run_id: Run identifier for observability.
        log: Logger.
        out_dir: Output directory.
        state_repo: State repository.
        store: Blackboard store.
        browser_session: Browser session (or None).
        view_html_source: Resolved view.html source path (or None).

    Returns:
        List of PostPassStats, one per registered pass, in execution order.
    """
    ctx = _RunContext(
        config=config,
        run_id=run_id,
        log=log,
        out_dir=out_dir,
        state_repo=state_repo,
        store=store,
        browser_session=browser_session,
        view_html_source=view_html_source,
    )

    results: list[PostPassStats] = []
    for name, fn, factory in POST_PASSES:
        pass_config, kwargs = factory(ctx)
        try:
            stats = fn(config=pass_config, **kwargs)
        except Exception as exc:
            log.warning("Post-pass %s raised (continuing): %s", name, exc)
            results.append(
                PostPassStats(
                    name=name,
                    skipped=True,
                    errors=1,
                    notes=f"exception: {exc}",
                )
            )
            continue
        results.append(stats)
        if stats.errors:
            log.warning(
                "Post-pass %s reported %d error(s): %s",
                stats.name,
                stats.errors,
                stats.notes,
            )
    return results


__all__ = ["POST_PASSES", "run_post_passes"]