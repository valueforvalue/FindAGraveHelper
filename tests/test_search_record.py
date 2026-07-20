"""Tests for SearchRecord (issue #34).

SearchRecord is the new domain-agnostic input type. The
pensioner-style dict (today's wire format) is supported via
from_pensioner() and to_pensioner_dict(). Tests pin:

  - Construction with all fields.
  - Derived name-part properties (first/middle/last from primary_name).
  - Attribute access via .attr() and .attributes.
  - .with_() and .with_attribute() preserve frozen-ness.
  - from_pensioner() maps every conventional key.
  - to_pensioner_dict() roundtrips.
  - The roundtrip preserves every input key (modulo string
    coercion of numeric ids).
  - SearchRecord integrates with SearchContext (the existing
    from_pensioner() in scripts/search/context.py still
    works on dicts, so consumers can choose either).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.search.record import (
    SearchRecord,
    from_pensioner,
    to_pensioner_dict,
)


# ============================================================
# Construction
# ============================================================
class TestConstruction:
    def test_minimal(self):
        r = SearchRecord(id="1", primary_name="John Smith")
        assert r.id == "1"
        assert r.primary_name == "John Smith"
        assert r.birth_year == ""
        assert r.death_year == ""
        assert r.state == ""
        assert r.source == "ok_pensioner"
        assert dict(r.attributes) == {}

    def test_full(self):
        r = SearchRecord(
            id="42", primary_name="Margaret Ward Slemp",
            birth_year="1845", death_year="1925",
            state="OK", source="ok_pensioner",
            attributes={"regiment": "CSA", "pensioner_app_number": "12345"},
        )
        assert r.birth_year == "1845"
        assert r.attr("regiment") == "CSA"
        assert r.attr("missing", "default") == "default"

    def test_is_frozen(self):
        r = SearchRecord(id="1", primary_name="John Smith")
        with pytest.raises(Exception):  # FrozenInstanceError
            r.id = "2"

    def test_default_source(self):
        r = SearchRecord(id="1", primary_name="John")
        assert r.source == "ok_pensioner"


# ============================================================
# Name parsing: first/middle/last from primary_name
# ============================================================
class TestNameParsing:
    def test_simple_two_part(self):
        r = SearchRecord(id="1", primary_name="John Smith")
        assert r.first == "John"
        assert r.middle == ""
        assert r.last == "Smith"

    def test_three_part(self):
        r = SearchRecord(id="1", primary_name="Margaret Ward Slemp")
        assert r.first == "Margaret"
        assert r.middle == "Ward"
        assert r.last == "Slemp"

    def test_four_part(self):
        # 4+ tokens: middle is everything between first and last
        r = SearchRecord(id="1", primary_name="John Quincy Adams Smith")
        assert r.first == "John"
        assert r.middle == "Quincy Adams"
        assert r.last == "Smith"

    def test_monomymous(self):
        r = SearchRecord(id="1", primary_name="Cher")
        assert r.first == ""
        assert r.middle == ""
        assert r.last == "Cher"

    def test_empty(self):
        r = SearchRecord(id="1", primary_name="")
        assert r.first == ""
        assert r.middle == ""
        assert r.last == ""

    def test_whitespace_only(self):
        r = SearchRecord(id="1", primary_name="   ")
        assert r.first == ""
        assert r.middle == ""
        assert r.last == ""


# ============================================================
# Attribute accessors
# ============================================================
class TestAttributes:
    def test_attr_default(self):
        r = SearchRecord(id="1", primary_name="X",
                         attributes={"k": "v"})
        assert r.attr("k") == "v"
        assert r.attr("missing") == ""
        assert r.attr("missing", "fallback") == "fallback"

    def test_attributes_mapping(self):
        r = SearchRecord(id="1", primary_name="X",
                         attributes={"a": 1, "b": "two"})
        # Mapping[str, Any]; iteration works
        d = dict(r.attributes)
        assert d == {"a": 1, "b": "two"}


# ============================================================
# Frozen + mutation via .with_()
# ============================================================
class TestWith:
    def test_with_changes_one_field(self):
        r = SearchRecord(id="1", primary_name="John", state="")
        r2 = r.with_(state="OK")
        assert r2.state == "OK"
        # Original is unchanged
        assert r.state == ""

    def test_with_attribute_replaces_dict(self):
        r = SearchRecord(id="1", primary_name="X",
                         attributes={"a": 1, "b": 2})
        r2 = r.with_attribute("a", 99)
        assert r2.attr("a") == 99
        assert r2.attr("b") == 2
        # Original unchanged
        assert r.attr("a") == 1

    def test_with_attributes_dict_replaces(self):
        r = SearchRecord(id="1", primary_name="X",
                         attributes={"a": 1})
        r2 = r.with_(attributes={"c": 3})
        # Whole attributes dict replaced
        assert r2.attr("c") == 3
        assert "a" not in r2.attributes


# ============================================================
# from_pensioner: dict → SearchRecord
# ============================================================
class TestFromPensioner:
    def test_minimal_dict(self):
        d = {"pensioner_id": 1, "pensioner_name": "John Smith"}
        r = from_pensioner(d)
        assert r.id == "1"
        assert r.primary_name == "John Smith"

    def test_canonical_keys(self):
        d = {
            "pensioner_id": 2577,
            "pensioner_first": "Margaret",
            "pensioner_middle": "Ward",
            "pensioner_last": "Slemp",
            "pensioner_birth_year": "1845",
            "pensioner_death_year": "1925",
            "fag_state_filter": "OK",
            "regiment": "CSA",
            "pensioner_app_number": "12345",
        }
        r = from_pensioner(d)
        assert r.id == "2577"
        assert r.primary_name == "Margaret Ward Slemp"
        assert r.birth_year == "1845"
        assert r.death_year == "1925"
        assert r.state == "OK"
        assert r.attr("regiment") == "CSA"
        assert r.attr("pensioner_app_number") == "12345"

    def test_unprefixed_keys(self):
        d = {
            "id": "42",
            "first_name": "John",
            "last_name": "Smith",
            "birth_year": "1844",
        }
        r = from_pensioner(d)
        assert r.id == "42"
        assert r.primary_name == "John Smith"
        assert r.birth_year == "1844"

    def test_state_from_state_key(self):
        d = {"id": "1", "primary_name": "X", "state": "TX"}
        r = from_pensioner(d)
        assert r.state == "TX"

    def test_state_from_fag_state_filter(self):
        d = {"id": "1", "primary_name": "X", "fag_state_filter": "OK"}
        r = from_pensioner(d)
        assert r.state == "OK"

    def test_empty_dict(self):
        r = from_pensioner({})
        assert r.id == ""
        assert r.primary_name == ""
        assert dict(r.attributes) == {}

    def test_non_string_id_coerced(self):
        d = {"pensioner_id": 42, "pensioner_name": "X"}
        r = from_pensioner(d)
        assert r.id == "42"  # int -> str

    def test_constructed_primary_name_wins(self):
        # If both primary_name and first/middle/last are set,
        # primary_name wins (the joined form is canonical).
        d = {
            "primary_name": "John Q. Public",
            "first_name": "WRONG",
            "last_name": "WRONG",
        }
        r = from_pensioner(d)
        assert r.primary_name == "John Q. Public"

    def test_falls_back_to_first_middle_last(self):
        d = {"first_name": "John", "middle_name": "Q", "last_name": "Public"}
        r = from_pensioner(d)
        assert r.primary_name == "John Q Public"
        assert r.first == "John"
        assert r.middle == "Q"
        assert r.last == "Public"

    def test_attributes_omit_empty_values(self):
        d = {"id": "1", "primary_name": "X", "regiment": "", "company": None}
        r = from_pensioner(d)
        # Empty / None values are not stored as attributes
        assert "regiment" not in r.attributes
        assert "company" not in r.attributes

    def test_preserves_arbitrary_keys(self):
        d = {
            "id": "1",
            "primary_name": "X",
            "custom_domain_key": "preserved",
            "another": 42,
        }
        r = from_pensioner(d)
        assert r.attr("custom_domain_key") == "preserved"
        assert r.attr("another") == 42

    def test_non_dict_raises(self):
        with pytest.raises(TypeError):
            from_pensioner("not a dict")
        with pytest.raises(TypeError):
            from_pensioner(42)


# ============================================================
# to_pensioner_dict: SearchRecord → dict
# ============================================================
class TestToPensionerDict:
    def test_roundtrip(self):
        d = {
            "pensioner_id": 2577,
            "pensioner_first": "Margaret",
            "pensioner_middle": "Ward",
            "pensioner_last": "Slemp",
            "pensioner_birth_year": "1845",
            "pensioner_death_year": "1925",
            "fag_state_filter": "OK",
            "regiment": "CSA",
            "pensioner_app_number": "12345",
            "pensioncard_backlink": "https://example.com/card",
        }
        r = from_pensioner(d)
        out = to_pensioner_dict(r)
        # Every key in `d` is present in `out`
        for k, v in d.items():
            assert k in out, f"key {k!r} lost in roundtrip"
            # Numeric ids become strings; otherwise values match
            if k == "pensioner_id":
                assert out[k] == "2577"
            else:
                assert out[k] == v, f"key {k!r}: {out[k]!r} != {v!r}"

    def test_outputs_canonical_keys(self):
        r = SearchRecord(
            id="1", primary_name="John Smith",
            birth_year="1844", state="OK",
        )
        out = to_pensioner_dict(r)
        # The output has both prefixed and unprefixed names
        assert out["id"] == "1"
        assert out["pensioner_id"] == "1"
        assert out["primary_name"] == "John Smith"
        assert out["pensioner_name"] == "John Smith"
        assert out["first_name"] == "John"
        assert out["last_name"] == "Smith"
        assert out["birth_year"] == "1844"
        assert out["pensioner_birth_year"] == "1844"
        assert out["state"] == "OK"
        assert out["fag_state_filter"] == "OK"

    def test_attributes_become_top_level(self):
        r = SearchRecord(
            id="1", primary_name="X",
            attributes={"regiment": "CSA", "custom": 99},
        )
        out = to_pensioner_dict(r)
        assert out["regiment"] == "CSA"
        assert out["custom"] == 99

    def test_explicit_core_field_wins_over_attribute(self):
        """If the same key is in both core fields and attributes,
        the explicit core field wins (the dict shape is stable)."""
        r = SearchRecord(
            id="1", primary_name="John Smith",
            attributes={"pensioner_first": "wrong", "regiment": "CSA"},
        )
        out = to_pensioner_dict(r)
        assert out["pensioner_first"] == "John"  # from primary_name
        assert out["regiment"] == "CSA"


# ============================================================
# Interop with SearchContext
# ============================================================
class TestInteropWithContext:
    """A SearchRecord is the higher-level record; a SearchContext
    is the per-search input. The two interoperate: the engine
    can build a SearchContext from a SearchRecord (using
    from_pensioner on the dict form), or from a raw dict."""

    def test_context_from_search_record_dict(self):
        from scripts.search.context import from_pensioner as ctx_from_p
        r = SearchRecord(
            id="1", primary_name="John Q. Smith",
            birth_year="1844", death_year="1932",
        )
        d = to_pensioner_dict(r)
        ctx = ctx_from_p(d)
        # The context picks up the core fields
        assert ctx.first == "John"
        assert ctx.middle == "Q."
        assert ctx.last == "Smith"
        assert ctx.birth_year == "1844"
        assert ctx.death_year == "1932"

    def test_to_context_method(self):
        r = SearchRecord(
            id="1", primary_name="Margaret Ward Slemp",
            birth_year="1845", death_year="1925", state="OK",
            attributes={"regiment": "CSA", "spouse_last_name": "Slemp"},
        )
        ctx = r.to_context()
        assert ctx.first == "Margaret"
        assert ctx.middle == "Ward"
        assert ctx.last == "Slemp"
        assert ctx.birth_year == "1845"
        assert ctx.death_year == "1925"
        assert ctx.state == "OK"
        # Attributes become extras
        assert ctx.extra("regiment") == "CSA"
        assert ctx.extra("spouse_last_name") == "Slemp"


# ============================================================
# Stability
# ============================================================
class TestStability:
    def test_dict_is_a_real_mapping(self):
        """The attributes field is a Mapping (not just a dict)
        so subclasses or read-only views work."""
        r = SearchRecord(id="1", primary_name="X",
                         attributes={"a": 1})
        # Iteration works
        keys = list(r.attributes.keys())
        assert keys == ["a"]


# ============================================================
# Integration: SearchRecord + FaGEngine end-to-end
# ============================================================
class TestRecordEngineIntegration:
    """Proves the engine abstraction works on a SearchRecord,
    not just a raw dict. The integration is a thin adapter
    in scripts/search/record_fag_adapter.py that uses
    SearchRecord.to_context() to feed the engine."""

    def test_search_record_via_engine_produces_attached_result(self):
        from scripts.search.record_fag_adapter import search_record_via_engine
        from scripts.search.fag_engine import FaGEngine

        class _StubPage:
            def __init__(self):
                self.visited = []
            def goto(self, url, **kw):
                self.visited.append(url)
            def title(self):
                return "Memorial Search Results"

        page = _StubPage()
        pensioner = {
            "pensioner_id": 1,
            "pensioner_first": "Alice",
            "pensioner_last": "Smith",
            "fag_state_filter": "OK",
        }
        e = FaGEngine()
        # Use a tiny ladder so the test is fast
        from scripts.search.strategy import as_strategy
        e.ladder = [as_strategy("B1", lambda ctx: {
            "firstname": ctx.first, "lastname": ctx.last,
        })]
        # Stub parse_results_page to return canned candidates
        e.parse_results_page = lambda page, url: [
            {"id": "100", "slug": "alice-smith", "snippet": ""},
            {"id": "200", "slug": "alice-b-smith", "snippet": ""},
        ]

        result_record = search_record_via_engine(page, pensioner, engine=e)
        # Record identity preserved
        assert result_record.id == "1"
        assert result_record.source == "ok_pensioner"
        assert result_record.primary_name == "Alice Smith"
        # Result attached
        result = result_record.attr("result")
        assert result is not None
        assert len(result["candidates"]) == 2
        # The stub page was navigated once with the right URL
        assert len(page.visited) == 1
        assert "firstname=Alice" in page.visited[0]
        assert "lastname=Smith" in page.visited[0]
        # locationId was injected by apply_filters
        assert "locationId=state_38" in page.visited[0]

    def test_to_pensioner_dict_preserves_engine_result(self):
        """to_pensioner_dict() puts engine results back into
        the dict shape today's state.jsonl expects."""
        from scripts.search.record_fag_adapter import search_record_via_engine
        from scripts.search.fag_engine import FaGEngine
        from scripts.search.strategy import as_strategy

        class _StubPage:
            def goto(self, url, **kw):
                pass
            def title(self):
                return "Memorial Search Results"

        e = FaGEngine()
        e.ladder = [as_strategy("B1", lambda ctx: {
            "firstname": ctx.first, "lastname": ctx.last,
        })]
        e.parse_results_page = lambda page, url: [
            {"id": "100", "slug": "alice", "snippet": ""},
        ]

        pensioner = {
            "pensioner_id": 1,
            "pensioner_first": "Alice",
            "pensioner_last": "Smith",
        }
        result_record = search_record_via_engine(_StubPage(), pensioner, engine=e)
        d = to_pensioner_dict(result_record)
        # Today's wire format: pensioner_id + result attributes
        assert d["pensioner_id"] == "1"
        assert d["pensioner_first"] == "Alice"
        assert d["pensioner_last"] == "Smith"
        # Engine result is in attributes
        assert "result" in d
        assert len(d["result"]["candidates"]) == 1
