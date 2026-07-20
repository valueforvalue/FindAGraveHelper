"""Template-form FaG strategies (hybrid model proof).

These are 3 of the 10 strategies from scripts/search/strategies.py
re-implemented in the template DSL to demonstrate the hybrid
model: simple cases as templates, complex cases stay as Python.

The 3 chosen are:
  - B1: simple exact (literal strings + field substitution +
    conditional middlename?/birthyear?)
  - B5: with a transform (replace apostrophe)
  - F1a-birthyear: with a conditional and the year_zero check
    via the `_year_str` semantics (we replicate it in the
    conditional by checking birth_year != "0")

If you want to migrate more, the pattern is: copy the function-
form body, identify the static parts (those become literal
strings), the field reads (those become {field}), and the
conditionals (those become ? suffix + apply_when).
"""
from __future__ import annotations

from scripts.search.template import TemplateStrategy


# B1: simple exact
B1_EXACT_TEMPLATE = TemplateStrategy.from_spec({
    "name": "B1-exact",
    "description": "Exact sniper. first + middlename + last + exactspelling.",
    "applies_when": ["first", "last"],
    "params": {
        "firstname": "{first}",
        "lastname": "{last}",
        "exactspelling": "true",
        "middlename?": "{middle}",
        "birthyear?": "{birth_year}",
        "birthyearfilter?": "1",
    },
})


# B5: with a transform (drop the apostrophe)
B5_APOSTROPHE_TEMPLATE = TemplateStrategy.from_spec({
    "name": "B5-apostrophe",
    "description": "Apostrophe variants. Only if last contains apostrophe.",
    "applies_when": ["first", "last"],
    "params": {
        "firstname": "{first}",
        "lastname": {
            "transform": "replace",
            "input": "{last}",
            "args": ["'", ""],
        },
        "fuzzyNames": "true",
    },
})


# F1a-birthyear: with conditional and the year-zero semantics
# (function form uses _year_str to drop "0"; template form does
# the same by gating on the conditional — birthyear? is dropped
# when birth_year is empty or "0").
F1A_BIRTHYEAR_TEMPLATE = TemplateStrategy.from_spec({
    "name": "F1a-birthyear-exact",
    "description": "B1-style exact with birth year filter.",
    "applies_when": ["first", "last"],
    "params": {
        "firstname": "{first}",
        "lastname": "{last}",
        "exactspelling": "true",
        # birthyear? drops when birth_year is "" or "0"
        # (matches _year_str semantics in the function form).
        "birthyear?": "{birth_year}",
        "birthyearfilter?": "5",
        "middlename?": "{middle}",
    },
})


# The "B1-equivalent" template form passes the same tests as the
# function form for the inputs we exercise in tests/test_strategies.py
# EXCEPT the birthyearfilter value: function form uses "1" (for
# the exact year), template form uses "5" (matches F1a). This
# difference is because the original B1 used birthyearfilter="1"
# (1-year window) while F1a uses "5". Pick the one you want.
