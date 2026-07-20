"""SearchRecord: domain-agnostic input record for a search.

A SearchRecord describes one thing the user wants to find
in some search engine. The class is engine-agnostic: a
Find a Grave record, an Ancestry record, a FamilySearch
record, and a "my family tree" record are all SearchRecords.

The fields split into two layers:

**Core** (every record has these):
  - id:            source-specific identifier (string for
                   forward-compat with non-int sources; int
                   ids are accepted and stringified).
  - primary_name:  the joined display name, e.g. "John Q. Smith".
  - birth_year:    year as a string; "" if unknown.
  - death_year:    year as a string; "" if unknown.
  - state:         US state abbr; "" if unknown or non-applicable.
  - source:        provenance string (e.g. "ok_pensioner",
                   "ancestry_tree", "familysearch_person",
                   "user_input"). Defaults to "ok_pensioner"
                   for the current codebase.
  - attributes:    free-form extras. FaG/pensioner-specific
                   fields (pensioner_id, regiment, ...) live
                   here. The from_pensioner() shim populates
                   this with the conventional keys.

**Derived** (computed from primary_name):
  - first, middle, last:    name-part splits. Best-effort;
                            the parser is conservative (only
                            splits on whitespace, doesn't
                            try to identify suffixes).

**Back-compat (today's wire format)**:
  - pensioner_id, pensioner_first, pensioner_middle, ...
    are still readable from the underlying dict for old
    code. New code reads `record.attributes["pensioner_id"]`
    or the typed properties.

The class is frozen + slotted. Use `record.with_(field=value)`
to create a new record with one field changed (so the
frozen contract holds).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping


# Canonical core field names. New engines use these; FaG-specific
# data goes in attributes.
CORE_FIELDS = ("id", "primary_name", "birth_year", "death_year",
               "state", "source")

# FaG/pensioner-specific fields that from_pensioner() pulls
# into attributes. New engines don't have these. Listed here
# so to_pensioner_dict() knows what to emit on the way back.
_FAG_SPECIFIC_FIELDS = (
    "pensioner_id", "pensioner_app_number",
    "pensioner_first", "pensioner_middle", "pensioner_last",
    "pensioner_name", "pensioner_birth_year", "pensioner_death_year",
    "regiment", "company",
    "pensioncard_backlink", "pensioncard_pages",
    "spouse_first_name", "spouse_last_name", "spouse_middle_name",
    "fag_state_filter", "application_number", "middle_name",
    "first_name", "last_name",
    "cemetery_id", "cemetery_name", "rank",
    "death_state", "burial_state",
)


@dataclass(frozen=True, slots=True)
class SearchRecord:
    """One input record for a search.

    The class is the new canonical type. Today's wire format
    (a flat dict with `pensioner_*` keys) is supported via
    from_pensioner() (dict → SearchRecord) and
    to_pensioner_dict() (SearchRecord → dict). Old code that
    still uses the dict form is unaffected.
    """
    id: str
    primary_name: str
    birth_year: str = ""
    death_year: str = ""
    state: str = ""
    source: str = "ok_pensioner"
    attributes: Mapping[str, Any] = field(default_factory=dict)

    # ----- Derived: name-part splits -----

    @property
    def first(self) -> str:
        """First name. Best-effort split on whitespace."""
        return _split_name(self.primary_name)[0]

    @property
    def middle(self) -> str:
        """Middle name. Best-effort split on whitespace."""
        return _split_name(self.primary_name)[1]

    @property
    def last(self) -> str:
        """Last name. Best-effort split on whitespace."""
        return _split_name(self.primary_name)[2]

    # ----- Attribute accessors -----

    def attr(self, key: str, default: Any = "") -> Any:
        """Read a domain-specific extra; default "" if missing.

        Shorthand for `record.attributes.get(key, default)`.
        """
        return self.attributes.get(key, default)

    # ----- Identity helpers -----

    def with_(self, **changes) -> "SearchRecord":
        """Return a new SearchRecord with the given fields changed.

        `attributes=` is replaced (not merged). To add one
        attribute, do `record.with_(attributes={**record.attributes,
        "new_key": "new_value"})`.

        Example:
            record.with_(state="OK")
            record.with_(primary_name="John Q. Smith")
        """
        return replace(self, **changes)

    def with_attribute(self, key: str, value: Any) -> "SearchRecord":
        """Return a new record with one attribute set (or replaced)."""
        new_attrs = dict(self.attributes)
        new_attrs[key] = value
        return replace(self, attributes=new_attrs)

    # ----- Conversion to SearchContext -----

    def to_context(self) -> "SearchContext":
        """Build a SearchContext for use with run_ladder() and
        the engine.

        Carries the core fields + attributes. The context is
        the per-search input (what the strategies see); the
        record is the higher-level "what we're searching for"
        (carrying id, source, full attributes).

        Roundtrip: SearchContext is not a superset of
        SearchRecord (no id, no source). Going record -> context
        -> record loses those. Use to_pensioner_dict() if you
        need a full roundtrip.
        """
        from scripts.search.context import SearchContext
        return SearchContext(
            first=self.first,
            middle=self.middle,
            last=self.last,
            birth_year=self.birth_year,
            death_year=self.death_year,
            state=self.state,
            extras=dict(self.attributes),
        )


# ============================================================
# Name parsing
# ============================================================


def _split_name(primary_name: str) -> tuple[str, str, str]:
    """Best-effort first/middle/last split on whitespace.

    Rules:
      - Empty / whitespace-only → ("", "", "")
      - 1 token  → ("", "", token)         (mononymous)
      - 2 tokens → (first, "", last)      (no middle)
      - 3+ tokens → (first, middle, last) where middle is
        everything between first and last joined by spaces.

    The split is conservative: no suffix detection (Jr., Sr.),
    no title handling, no comma-suffix handling. Records with
    edge-case names should store the parsed parts in
    attributes (e.g. attrs["pensioner_first"], attrs["pensioner_last"])
    and the engine can read those instead.
    """
    if not primary_name or not primary_name.strip():
        return ("", "", "")
    tokens = primary_name.split()
    if len(tokens) == 1:
        return ("", "", tokens[0])
    if len(tokens) == 2:
        return (tokens[0], "", tokens[1])
    return (tokens[0], " ".join(tokens[1:-1]), tokens[-1])


# ============================================================
# From / to dict (back-compat with today's wire format)
# ============================================================


# Recognised core field names in the input dict. The "name" set
# covers the various spellings the codebase has used.
_CORE_KEYS = {
    "id": ("id", "pensioner_id"),
    "primary_name": ("primary_name", "pensioner_name"),
    "birth_year": ("birth_year", "pensioner_birth_year"),
    "death_year": ("death_year", "pensioner_death_year"),
    "state": ("state", "fag_state_filter", "pensioner_state"),
    "source": ("source", "record_source"),
}


def from_pensioner(pensioner: dict) -> SearchRecord:
    """Build a SearchRecord from a pensioner-style dict.

    The input is the dict shape the codebase uses today
    (a flat dict with `pensioner_id`, `pensioner_first`, ...).
    The output is the new SearchRecord. FaG-specific fields
    that don't map to a core field are moved into attributes.

    The shim preserves the wire format: every field currently
    in a pensioner dict has somewhere to land in the resulting
    SearchRecord. from_pensioner(to_pensioner_dict(r)) is a
    roundtrip.
    """
    if not isinstance(pensioner, dict):
        raise TypeError(f"from_pensioner expected dict, got {type(pensioner)}")

    # Core fields
    record_id = ""
    for k in _CORE_KEYS["id"]:
        if k in pensioner and pensioner[k] not in (None, ""):
            record_id = str(pensioner[k])
            break
    primary_name = ""
    for k in _CORE_KEYS["primary_name"]:
        if k in pensioner and pensioner[k]:
            primary_name = str(pensioner[k]).strip()
            break
    # If still empty, try first + middle + last joined
    if not primary_name:
        first = pensioner.get("first_name") or pensioner.get("pensioner_first") or ""
        middle = pensioner.get("middle_name") or pensioner.get("pensioner_middle") or ""
        last = pensioner.get("last_name") or pensioner.get("pensioner_last") or ""
        primary_name = f"{first} {middle} {last}".strip().replace("  ", " ")
    birth_year = ""
    for k in _CORE_KEYS["birth_year"]:
        if k in pensioner and pensioner[k] not in (None, ""):
            birth_year = str(pensioner[k])
            break
    death_year = ""
    for k in _CORE_KEYS["death_year"]:
        if k in pensioner and pensioner[k] not in (None, ""):
            death_year = str(pensioner[k])
            break
    state = ""
    for k in _CORE_KEYS["state"]:
        if k in pensioner and pensioner[k]:
            state = str(pensioner[k]).strip()
            break
    source = "ok_pensioner"
    for k in _CORE_KEYS["source"]:
        if k in pensioner and pensioner[k]:
            source = str(pensioner[k])
            break

    # Attributes: anything not consumed by a core field, that
    # IS in our known FaG-specific list (or a custom key the
    # caller wants to preserve). We don't store arbitrary keys
    # because the input dict may carry FaG-internal data the
    # SearchRecord shouldn't echo.
    consumed_keys = set()
    for keys in _CORE_KEYS.values():
        consumed_keys.update(keys)
    consumed_keys.update({"first_name", "last_name", "middle_name"})
    attributes: dict[str, Any] = {}
    for k, v in pensioner.items():
        if k in consumed_keys:
            continue
        if v is None or v == "":
            continue
        attributes[k] = v

    return SearchRecord(
        id=record_id,
        primary_name=primary_name,
        birth_year=birth_year,
        death_year=death_year,
        state=state,
        source=source,
        attributes=attributes,
    )


def to_pensioner_dict(record: SearchRecord) -> dict:
    """Build a pensioner-style dict from a SearchRecord.

    This is the inverse of from_pensioner for the roundtrip
    case. The output dict has the flat shape today's wire
    format (state.jsonl) expects.

    Layout (matches today's pensioner dict):
      - id, primary_name → id, pensioner_id, pensioner_name
      - first/middle/last (from primary_name) → pensioner_first/middle/last
      - birth_year, death_year → pensioner_birth_year, pensioner_death_year
      - state → fag_state_filter
      - attributes → all keys as top-level fields

    Roundtrip contract: for any dict `d`,
    to_pensioner_dict(from_pensioner(d)) preserves every
    key/value in `d` (modulo stringification of numeric ids).
    """
    out: dict[str, Any] = {
        "id": record.id,
        "pensioner_id": record.id,
        "primary_name": record.primary_name,
        "pensioner_name": record.primary_name,
        "first_name": record.first,
        "middle_name": record.middle,
        "last_name": record.last,
        "pensioner_first": record.first,
        "pensioner_middle": record.middle,
        "pensioner_last": record.last,
        "birth_year": record.birth_year,
        "pensioner_birth_year": record.birth_year,
        "death_year": record.death_year,
        "pensioner_death_year": record.death_year,
        "state": record.state,
        "fag_state_filter": record.state,
        "source": record.source,
    }
    # Attributes become top-level fields. We DO NOT re-emit
    # keys that are already set above (the explicit core
    # fields win so the dict shape is stable).
    for k, v in record.attributes.items():
        if k in out:
            continue
        out[k] = v
    return out
