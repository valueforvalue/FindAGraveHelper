"""Strategy protocol: domain-agnostic interface for search strategies.

A Strategy is a named, callable unit that converts a SearchContext
into a dict of search-engine URL params. The protocol is engine-
agnostic: the same Strategy could feed FaG, Ancestry, FamilySearch,
or Newspapers.com, as long as the params dict is shaped right for
that engine.

Two ways to build a Strategy:

1. **Function form** — write a plain function and wrap it:

       def my_strategy(ctx: SearchContext) -> dict | None:
           if not ctx.has("first", "last"):
               return None
           return {"firstname": ctx.first, "lastname": ctx.last}

       MY_STRATEGY = FunctionStrategy("B1-exact", my_strategy)

2. **Template form** — describe it in YAML / dict and let the
   template engine build it (see scripts/search/template.py):

       spec = {
           "name": "B1-exact",
           "params": {
               "firstname": "{first}",
               "lastname": "{last}",
               "exactspelling": "true",
           },
       }
       B1 = TemplateStrategy.from_spec(spec)

The ladder only cares about the protocol surface; both forms are
interchangeable.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable, Callable

from scripts.search.context import SearchContext


# A strategy returns either a dict of URL params, or None to
# signal "not applicable" (the runner will try the next one).
StrategyResult = dict | None


@runtime_checkable
class Strategy(Protocol):
    """A single search strategy.

    Attributes:
        name: Short identifier used in stats / debugging. Should
              be stable across versions (it's the audit trail).
    """
    name: str

    def params(self, ctx: SearchContext) -> StrategyResult:
        """Build URL params for this strategy, or None if not
        applicable for the given context.

        MUST be pure: same input → same output. MUST NOT mutate
        the context. MUST NOT perform I/O.
        """
        ...


class FunctionStrategy:
    """Wrap a plain function as a Strategy.

    The function takes a SearchContext and returns dict | None.
    Used for strategies that need real logic (regex, multi-step
    computation, conditional logic the template DSL can't express).
    """
    __slots__ = ("name", "_fn", "alias")

    def __init__(self, name: str, fn: Callable[[SearchContext], StrategyResult], alias: str = ""):
        self.name = name
        self._fn = fn
        self.alias = alias or name

    def params(self, ctx: SearchContext) -> StrategyResult:
        return self._fn(ctx)

    def __repr__(self) -> str:
        return f"FunctionStrategy({self.name!r})"


def as_strategy(name: str, fn: Callable[[SearchContext], StrategyResult], alias: str = "") -> Strategy:
    """Convenience: wrap a function as a Strategy. Equivalent to
    `FunctionStrategy(name, fn)` but reads more naturally at the
    point of definition:

        STRATEGIES = [
            as_strategy("B1-exact", lambda ctx: ..., "Exact name match"),
            ...
        ]
    """
    return FunctionStrategy(name, fn, alias=alias)
