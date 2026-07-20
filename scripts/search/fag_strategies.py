"""FaG-specific strategies that need extras beyond the core
SearchContext (regiment, nickname, maiden name).

These were F2-regiment-bio and F3-nickname in the original
ladder. They live separately from scripts/search/strategies.py
because the canonical 10-strategy ladder is engine-agnostic;
F2/F3 read FaG-specific fields from ctx.extras.

Both are wrapped as FunctionStrategy and added to the F2/F3
slot in the run_ladder integration. Strategies.py and this
file together form the complete FaG ladder.
"""
from __future__ import annotations

from scripts.search.context import SearchContext
from scripts.search.strategy import FunctionStrategy

from scripts.matching.regiment_keyword import strategy_regiment_bio
from scripts.matching.nickname_match import strategy_with_nickname


# ============================================================
# Context-form wrappers
# ============================================================


def f2_regiment_bio(ctx: SearchContext):
    """F2: regiment-bio search.

    Reads `regiment` from ctx.extras. Falls back to "" when
    absent (which makes the underlying strategy_regiment_bio
    return None).
    """
    return strategy_regiment_bio(
        ctx.first, ctx.middle, ctx.last,
        ctx.extra("regiment", ""),
        ctx.death_year,
    )


def f3_nickname(ctx: SearchContext):
    """F3: nickname + maiden-name expansion.

    Reads `spouse_last_name` from ctx.extras. The original
    `strategy_with_nickname` accepts a full pensioner dict;
    we pass ctx.extras (or a derived dict) so it can read
    maiden-name and any other future fields it needs.
    """
    return strategy_with_nickname(
        ctx.first, ctx.middle, ctx.last,
        ctx.birth_year, ctx.death_year,
        pensioner=dict(ctx.extras),
    )


# ============================================================
# Ladder entries (registered as Strategy objects)
# ============================================================

F2_REGIMENT_BIO = FunctionStrategy("F2-regiment-bio", f2_regiment_bio)
F3_NICKNAME = FunctionStrategy("F3-nickname", f3_nickname)


def f4_follow_up(ctx: SearchContext):
    """F4: follow-up search for needs-research pensioners.

    Broadened parameters designed as a last-attempt pass:
      - No state filter (US-wide search)
      - Surname-only (drops first name for fuzzy matching)
      - Wider year window: ±10 instead of ±5
      - Fuzzy spelling enabled

    Returns None when last name is missing (can't search surname-only).
    """
    if not ctx.last:
        return None
    params: dict = {
        "lastname": ctx.last,
        "fuzzy": "true",
    }
    # Wider year window: ±10
    by = int(ctx.birth_year) if (ctx.birth_year and ctx.birth_year.isdigit()) else None
    dy = int(ctx.death_year) if (ctx.death_year and ctx.death_year.isdigit()) else None
    if by is not None:
        params["birthyear"] = str(by - 10)
        params["birthyear_range"] = "20"
    if dy is not None:
        params["deathyear"] = str(dy - 10)
        params["deathyear_range"] = "20"
    return params


F4_FOLLOW_UP = FunctionStrategy("F4-follow-up", f4_follow_up)
