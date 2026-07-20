"""Search context: domain-agnostic inputs for strategy functions.

A SearchContext carries the inputs a strategy might need to build
its search-URL params. The core fields (first/middle/last/years)
cover the common case for genealogy searches. Domain-specific
extras (regiment, cemetery_id, maiden_name, unit, ...) live in
`extras`, a free-form mapping that strategies read from as needed.

The dataclass is frozen + slotted so it can be hashed and cheaply
copied. Strategies MUST NOT mutate the context; build a new one
if you need a transformation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class SearchContext:
    """Inputs for one strategy invocation.

    Attributes:
        first:       First name (may be empty string if unknown).
        middle:      Middle name or initial (may be empty).
        last:        Last name (may be empty for mononymous).
        birth_year:  Birth year as a string (e.g. "1844"); "" if
                     unknown. Stored as str to match FaG URL params;
                     strategies that need an int can convert.
        death_year:  Death year as a string; "" if unknown.
        state:       US state abbreviation (e.g. "OK"); "" if unknown
                     or non-applicable. Used by state-filtered
                     strategies; ignored by name-only ones.
        extras:      Domain-specific extras. Read with
                     `ctx.extras.get("regiment", "")`. Strategy
                     authors should document which keys they read.
    """
    first: str = ""
    middle: str = ""
    last: str = ""
    birth_year: str = ""
    death_year: str = ""
    state: str = ""
    extras: Mapping[str, Any] = field(default_factory=dict)

    def has(self, *fields: str) -> bool:
        """True iff every named core field is non-empty.

        Example: ctx.has("first", "last") is True iff both names
        are populated. Useful as a guard at the top of a strategy:

            def strategy_xxx(ctx):
                if not ctx.has("first", "last"):
                    return None
                ...
        """
        for f in fields:
            if not getattr(self, f, ""):
                return False
        return True

    def extra(self, key: str, default: Any = "") -> Any:
        """Read a domain-specific extra; default "" if missing.

        Shorthand for `ctx.extras.get(key, default)`.
        """
        return self.extras.get(key, default)


def from_pensioner(pensioner: dict) -> SearchContext:
    """Build a SearchContext from a pensioner-style dict.

    Recognised keys: first_name / pensioner_first → first,
    middle_name / pensioner_middle → middle, last_name /
    pensioner_last → last, birth_year / pensioner_birth_year →
    birth_year, death_year / pensioner_death_year → death_year,
    state / fag_state_filter → state.

    Anything else in the dict lands in `extras` (stringified) so
    strategies can pull regiment, cemetery_id, etc. without us
    having to enumerate every possible key here.
    """
    first = str(pensioner.get("first_name")
                or pensioner.get("pensioner_first")
                or pensioner.get("first") or "").strip()
    middle = str(pensioner.get("middle_name")
                 or pensioner.get("pensioner_middle")
                 or pensioner.get("middle") or "").strip()
    last = str(pensioner.get("last_name")
               or pensioner.get("pensioner_last")
               or pensioner.get("last") or "").strip()
    birth_year = str(pensioner.get("birth_year")
                     or pensioner.get("pensioner_birth_year") or "").strip()
    death_year = str(pensioner.get("death_year")
                     or pensioner.get("pensioner_death_year") or "").strip()
    state = str(pensioner.get("state")
                or pensioner.get("fag_state_filter")
                or pensioner.get("pensioner_state") or "").strip()
    # Extras: anything not consumed above. Stringify non-str values
    # so the Mapping is JSON-friendly (matters for future
    # serialisation of strategies/results).
    consumed = {
        "first_name", "pensioner_first", "first",
        "middle_name", "pensioner_middle", "middle",
        "last_name", "pensioner_last", "last",
        "birth_year", "pensioner_birth_year",
        "death_year", "pensioner_death_year",
        "state", "fag_state_filter", "pensioner_state",
    }
    extras: dict[str, Any] = {}
    for k, v in pensioner.items():
        if k in consumed:
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            extras[k] = v if v is not None else ""
    return SearchContext(
        first=first,
        middle=middle,
        last=last,
        birth_year=birth_year,
        death_year=death_year,
        state=state,
        extras=extras,
    )
