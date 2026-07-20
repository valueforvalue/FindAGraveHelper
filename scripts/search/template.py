"""Template strategy engine (refactor 2026-07-20, hybrid model).

Lets a strategy be described as a small dict of params instead of
a Python function. Useful for the ~90% of strategies that are
static dicts with a few substitutions and conditionals.

DSL (intentionally tiny — anything more complex belongs in a
function-form strategy):

  name:        <string>          (required)
  description: <string>          (optional)
  applies_when: [<field>, ...]   (optional; "fire only if these
                                  core fields are non-empty")
  params:
    <key>: <value-or-template>

Value shapes for params:

  1. Literal string
        exactspelling: "true"

  2. Field substitution
        firstname: "{first}"
     Reads ctx.first (or any other core field) and substitutes.

  3. Extra-field substitution
        firstname: "{extra.regiment}"
     Reads ctx.extra("regiment").

  4. Conditional inclusion (key ends with "?")
        middlename?:
          value: "{middle}"
     The key is emitted only if the value is truthy after
     substitution. The key in the output is the part before "?".
     (middlename?: → middlename if non-empty, omitted otherwise.)

  5. Transform
        lastname:
          transform: replace
          input:    "{last}"
          args:     ["'", ""]
     The named transform is applied to `input` with `args`.
     Built-in transforms:
       - replace:   str.replace(old, new)
       - slice:     str[start:stop]   (args = [start, stop])
       - format:    "{0:0Nd}".format(value)  (args = [width])
       - upper:     str.upper()
       - lower:     str.lower()
       - choice:    args = [{year_lt: 1930, value: "10"}, ...]
                    returns value from the first matching case
                    (uses ctx.extras for case data)

  6. Conditional transform
        lastname?:
          transform: replace
          input:    "{last}"
          args:     ["'", ""]
     Combine conditional (?) with any value shape.

NO user code execution. The DSL is closed: any logic Python needs
that the DSL can't express belongs in a function-form strategy.
"""
from __future__ import annotations

from typing import Any, Callable

from scripts.search.context import SearchContext
from scripts.search.strategy import Strategy


# ============================================================
# Transforms
# ============================================================
# Each is a function (str, list[str], ctx) -> str. Pure; no I/O.
# Add a new one by adding an entry here and (if it's a conditional
# one) a small doc note in the DSL section above.

_TRANSFORMS: dict[str, Callable[[str, list, SearchContext], str]] = {}


def _register_transform(name: str):
    def deco(fn):
        _TRANSFORMS[name] = fn
        return fn
    return deco


@_register_transform("replace")
def _t_replace(value: str, args: list, ctx: SearchContext) -> str:
    if len(args) < 2:
        raise ValueError("replace transform needs [old, new] args")
    return value.replace(args[0], args[1])


@_register_transform("slice")
def _t_slice(value: str, args: list, ctx: SearchContext) -> str:
    if len(args) < 2:
        raise ValueError("slice transform needs [start, stop] args")
    return value[args[0]:args[1]]


@_register_transform("format")
def _t_format(value: str, args: list, ctx: SearchContext) -> str:
    if len(args) < 1:
        raise ValueError("format transform needs [width] args")
    return f"{int(value):0{args[0]}d}"


@_register_transform("upper")
def _t_upper(value: str, args: list, ctx: SearchContext) -> str:
    return value.upper()


@_register_transform("lower")
def _t_lower(value: str, args: list, ctx: SearchContext) -> str:
    return value.lower()


@_register_transform("choice")
def _t_choice(value: str, args: list, ctx: SearchContext) -> str:
    """args = [{"when": {field: <value>}, "then": <value>}, ...]
    Returns the `then` of the first case whose `when` matches
    the context. Used for year-window choice and similar.
    """
    for case in args:
        when = case.get("when", {})
        then = case.get("then")
        if all(str(ctx.extra(k, "")) == str(v) for k, v in when.items()):
            return str(then)
    return ""


# ============================================================
# Substitution
# ============================================================

#: Match `{field}` (core field) or `{extra.key}` (extras).
import re as _re
_FIELD_RE = _re.compile(r"\{(\w+)(?:\.(\w+))?\}")


def _substitute(value: str, ctx: SearchContext) -> str:
    """Replace {field} / {extra.key} with ctx values. The
    substitution is a single pass; literal braces in the
    surrounding text pass through."""

    def _replace(m):
        head, sub = m.group(1), m.group(2)
        if head == "extra" and sub is not None:
            return str(ctx.extra(sub, ""))
        # core field
        v = getattr(ctx, head, "")
        return str(v) if v is not None else ""

    return _FIELD_RE.sub(_replace, value)


# ============================================================
# Param resolution
# ============================================================


def _resolve_value(node: Any, ctx: SearchContext) -> str | None:
    """Resolve a single param value spec to a string (or None if
    conditional + falsy)."""
    if isinstance(node, str):
        return _substitute(node, ctx)
    if isinstance(node, dict):
        if "transform" in node:
            tf_name = node["transform"]
            if tf_name not in _TRANSFORMS:
                raise ValueError(f"Unknown transform: {tf_name!r}")
            input_spec = node.get("input", "")
            if isinstance(input_spec, str):
                value = _substitute(input_spec, ctx)
            else:
                value = str(input_spec)
            return _TRANSFORMS[tf_name](value, node.get("args", []), ctx)
        if "value" in node:
            v = node["value"]
            if isinstance(v, str):
                return _substitute(v, ctx)
            return str(v)
        # Unknown dict shape; treat as None so the param is dropped.
        return None
    if node is None:
        return None
    return str(node)


def resolve_params(
    spec: dict[str, Any],
    ctx: SearchContext,
) -> dict[str, str] | None:
    """Resolve a full params spec against a context. Returns
    None if any of `applies_when` is empty (strategy not
    applicable); otherwise returns the resolved dict.

    Keys ending in "?" are emitted without the "?" and only
    if their resolved value is truthy.
    """
    # applies_when guard
    for f in spec.get("applies_when", []):
        if not getattr(ctx, f, ""):
            return None
    params_spec = spec.get("params", {})
    out: dict[str, str] = {}
    for raw_key, node in params_spec.items():
        conditional = raw_key.endswith("?")
        key = raw_key.rstrip("?")
        value = _resolve_value(node, ctx)
        if value is None:
            continue
        if conditional and not value:
            continue
        out[key] = value
    return out


# ============================================================
# TemplateStrategy
# ============================================================


class TemplateStrategy:
    """A Strategy whose params are built from a template spec.

    Two construction paths:
      - TemplateStrategy.from_spec({"name": ..., "params": ...})
      - TemplateStrategy.from_yaml(yaml_string_or_path)

    The spec is resolved at params() time (not at construction
    time) so the same TemplateStrategy can be reused across many
    contexts.
    """

    __slots__ = ("name", "_spec", "_description")

    def __init__(self, name: str, spec: dict, description: str = ""):
        self.name = name
        self._spec = spec
        self._description = description

    def params(self, ctx: SearchContext):
        return resolve_params(self._spec, ctx)

    def __repr__(self) -> str:
        return f"TemplateStrategy({self.name!r})"

    @classmethod
    def from_spec(cls, spec: dict) -> "TemplateStrategy":
        """Build from a dict. The dict MUST have a 'name' key.
        A 'description' key is optional. A 'params' key is
        required."""
        if "name" not in spec:
            raise ValueError("Template spec must have a 'name' key")
        if "params" not in spec:
            raise ValueError("Template spec must have a 'params' key")
        return cls(
            name=spec["name"],
            spec=spec,
            description=spec.get("description", ""),
        )

    @classmethod
    def from_yaml(cls, text_or_path: str) -> "TemplateStrategy":
        """Build from a YAML string or path to a YAML file.
        Requires PyYAML; raises ImportError if not installed."""
        try:
            import yaml
        except ImportError as e:
            raise ImportError(
                "TemplateStrategy.from_yaml requires PyYAML; "
                "use from_spec() for the dict form (no dep)."
            ) from e
        # Path or string?
        from pathlib import Path
        p = Path(text_or_path)
        if p.exists() and p.is_file():
            text = p.read_text(encoding="utf-8")
        else:
            text = text_or_path
        spec = yaml.safe_load(text)
        if not isinstance(spec, dict):
            raise ValueError("YAML must decode to a dict")
        return cls.from_spec(spec)
