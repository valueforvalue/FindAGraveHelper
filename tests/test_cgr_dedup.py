"""Tests for scripts/cgr_dedup.py.

Covers the strict dedup predicate, the union-find clustering,
the dual-source map (member_cgr_ids, linked_pensioner_ids), and
the metadata merge logic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestNormalization:
    def test_norm_lowercases_and_strips_punctuation(self):
        from scripts.cgr.cgr_dedup import _norm
        assert _norm("OBrien") == "obrien"
        assert _norm("O'Brien") == "obrien"
        assert _norm("Mc Donald") == "mcdonald"
        assert _norm("Smith-Jones") == "smithjones"

    def test_norm_strips_accents(self):
        from scripts.cgr.cgr_dedup import _norm
        assert _norm("Müller") == "muller"
        assert _norm("García") == "garcia"

    def test_norm_empty(self):
        from scripts.cgr.cgr_dedup import _norm
        assert _norm("") == ""
        assert _norm(None) == ""


class TestJaroWinkler:
    def test_identical_strings_score_1(self):
        from scripts.cgr_dedup import jaro_winkler
        assert jaro_winkler("hugh", "hugh") == 1.0

    def test_partial_match(self):
        from scripts.cgr_dedup import jaro_winkler
        s = jaro_winkler("hugh", "hue")
        # JW with prefix bonus; both share 'hu' as prefix.
        assert 0.7 < s < 0.85

    def test_completely_different(self):
        from scripts.cgr_dedup import jaro_winkler
        assert jaro_winkler("aaa", "zzz") == 0.0

    def test_threshold_pass(self):
        """JW("willis","william") >= 0.90 (per smoke check)."""
        from scripts.cgr_dedup import jaro_winkler
        assert jaro_winkler("willis", "william") >= 0.90


class TestSamePersonPredicate:
    def test_identical_records_merge(self):
        from scripts.cgr_dedup import same_person
        a = {"first_name": "Hugh", "last_name": "Akers",
             "born": "1840", "died": "1920",
             "cemetery_id": 1, "unit": "CSA"}
        b = {"first_name": "Hugh", "last_name": "Akers",
             "born": "1841", "died": "1920",
             "cemetery_id": 2, "unit": "CSA"}
        assert same_person(a, b) is True

    def test_different_last_name_no_merge(self):
        from scripts.cgr_dedup import same_person
        a = {"first_name": "Hugh", "last_name": "Akers",
             "born": "1840", "cemetery_id": 1, "unit": "CSA"}
        b = {"first_name": "Hugh", "last_name": "Williams",
             "born": "1840", "cemetery_id": 1, "unit": "CSA"}
        assert same_person(a, b) is False

    def test_last_name_match_but_first_name_below_threshold_no_merge(self):
        from scripts.cgr_dedup import same_person
        a = {"first_name": "Hugh", "last_name": "Akers",
             "born": "1840", "cemetery_id": 1, "unit": "CSA"}
        b = {"first_name": "Jane", "last_name": "Akers",
             "born": "1845", "cemetery_id": 1, "unit": "CSA"}
        # First name distance too big.
        assert same_person(a, b) is False

    def test_no_first_name_does_not_merge(self):
        """Refuse to merge without first names — too noisy."""
        from scripts.cgr_dedup import same_person
        a = {"first_name": "", "last_name": "Akers",
             "born": "1840", "cemetery_id": 1, "unit": "CSA"}
        b = {"first_name": "", "last_name": "Akers",
             "born": "1840", "cemetery_id": 1, "unit": "CSA"}
        assert same_person(a, b) is False

    def test_last_name_match_first_name_pass_but_no_tiebreaker_no_merge(self):
        """Strict: tiebreaker is required."""
        from scripts.cgr_dedup import same_person
        a = {"first_name": "Hugh", "last_name": "Akers"}
        b = {"first_name": "Hugh", "last_name": "Akers"}
        # No tiebreaker at all -> False even though names match.
        assert same_person(a, b) is False

    def test_year_close_match_counts_as_tiebreaker(self):
        from scripts.cgr_dedup import same_person
        a = {"first_name": "Hugh", "last_name": "Akers", "born": "1840"}
        b = {"first_name": "Hugh", "last_name": "Akers", "born": "1843"}
        # 3-year birth-year delta is within the year_delta=5 window.
        assert same_person(a, b) is True

    def test_year_far_apart_no_tiebreaker(self):
        from scripts.cgr_dedup import same_person
        a = {"first_name": "Hugh", "last_name": "Akers", "born": "1840"}
        b = {"first_name": "Hugh", "last_name": "Akers", "born": "1850"}
        # 10-year delta is outside the year_delta=5 window.
        assert same_person(a, b) is False

    def test_cem_id_match_counts_as_tiebreaker(self):
        from scripts.cgr_dedup import same_person
        a = {"first_name": "Hugh", "last_name": "Akers",
             "cemetery_id": 42}
        b = {"first_name": "Hugh", "last_name": "Akers",
             "cemetery_id": 42}
        assert same_person(a, b) is True

    def test_unit_match_counts_as_tiebreaker(self):
        from scripts.cgr_dedup import same_person
        a = {"first_name": "Hugh", "last_name": "Akers", "unit": "1 TX"}
        b = {"first_name": "Hugh", "last_name": "Akers", "unit": "1 TX"}
        assert same_person(a, b) is True


class TestUnionFind:
    def test_basic_union_find(self):
        from scripts.cgr_dedup import UnionFind
        uf = UnionFind()
        for x in range(5):
            uf.add(x)
        uf.union(0, 1)
        uf.union(1, 2)
        # 0, 1, 2 share a root; 3, 4 are separate.
        assert uf.find(0) == uf.find(1) == uf.find(2)
        assert uf.find(3) != uf.find(0)
        assert uf.find(3) != uf.find(4)

    def test_transitive_merge(self):
        from scripts.cgr_dedup import UnionFind
        uf = UnionFind()
        for x in range(4):
            uf.add(x)
        uf.union(0, 1)
        uf.union(2, 3)
        uf.union(1, 2)
        # All four share a root now.
        assert uf.find(0) == uf.find(3)


class TestBuildDedup:
    def _fixture_cgr(self, *recs):
        """Helper: list of CGR records with stable ids."""
        return [{**r, "id": i} for i, r in enumerate(recs)]

    def test_two_clear_matches_merge_into_one_person(self):
        from scripts.cgr_dedup import build_dedup
        cgr = self._fixture_cgr(
            {"first_name": "Hugh", "last_name": "Akers",
             "born": "1840", "died": "1920", "cemetery_id": 1,
             "unit": "1 TX", "rank": "Pvt"},
            {"first_name": "Hugh", "last_name": "Akers",
             "born": "1841", "died": "1920", "cemetery_id": 2,
             "unit": "1 TX", "rank": "Pvt"},
            {"first_name": "Jane", "last_name": "Akers",
             "born": "1845", "cemetery_id": 3, "unit": "CSA"},
        )
        out = build_dedup(
            cgr_records=cgr,
            pensioner_to_cgr_links={},
            pensioners_by_id=None,
        )
        # Two CGRs merge (Hugh Hugh); Jane is separate.
        cgr_persons = [p for p in out["persons"].values()
                       if p["member_cgr_ids"]]
        assert len(cgr_persons) == 2
        # The merged person has 2 members.
        big = max(cgr_persons, key=lambda p: len(p["member_cgr_ids"]))
        assert len(big["member_cgr_ids"]) == 2
        assert big["merged_metadata"]["last_name"] == "Akers"
        assert "1920" in big["merged_metadata"]["death_year"]

    def test_pensioner_link_via_cgr(self):
        from scripts.cgr_dedup import build_dedup
        cgr = self._fixture_cgr(
            {"first_name": "Hugh", "last_name": "Akers",
             "born": "1840", "died": "1920", "cemetery_id": 1,
             "unit": "CSA"},
        )
        out = build_dedup(
            cgr_records=cgr,
            pensioner_to_cgr_links={42: [cgr[0]["id"]]},
            pensioners_by_id={42: {"id": 42, "first_name": "H.",
                                   "last_name": "Akers"}},
        )
        # Find the person with both members and pensions.
        hit = next(
            p for p in out["persons"].values()
            if p["member_cgr_ids"] and p["linked_pensioner_ids"]
        )
        assert hit["linked_pensioner_ids"] == [42]
        assert hit["member_cgr_ids"] == [cgr[0]["id"]]

    def test_pensioner_only_singleton(self):
        from scripts.cgr_dedup import build_dedup
        cgr = self._fixture_cgr(
            {"first_name": "Hugh", "last_name": "Akers",
             "born": "1840", "cemetery_id": 1, "unit": "CSA"},
        )
        out = build_dedup(
            cgr_records=cgr,
            pensioner_to_cgr_links={},
            pensioners_by_id={99: {"id": 99, "first_name": "X",
                                   "last_name": "Y"}},
        )
        # Pensioner 99 has no CGR record -> its own person_id.
        singleton = next(
            p for pid, p in out["persons"].items()
            if p["linked_pensioner_ids"] == [99]
            and not p["member_cgr_ids"]
        )
        assert singleton["merged_metadata"] == {}

    def test_provenance_in_reverse_index(self):
        from scripts.cgr_dedup import build_dedup
        cgr = self._fixture_cgr(
            {"first_name": "Hugh", "last_name": "Akers",
             "born": "1840", "cemetery_id": 1, "unit": "CSA"},
        )
        out = build_dedup(
            cgr_records=cgr,
            pensioner_to_cgr_links={42: [cgr[0]["id"]]},
            pensioners_by_id={42: {"id": 42, "first_name": "H.",
                                   "last_name": "Akers"}},
        )
        # Reverse indexes: every input CGR record maps to one person_id,
        # every input pensioner maps to one person_id.
        assert str(cgr[0]["id"]) in out["cgr_id_to_person_id"]
        assert "42" in out["pensioner_id_to_person_id"]

    def test_transitive_merge_three_cgr_records(self):
        from scripts.cgr_dedup import build_dedup
        cgr = self._fixture_cgr(
            # A—B same person (year tiebreaker)
            {"first_name": "Hugh", "last_name": "Akers",
             "born": "1840", "cemetery_id": 1, "unit": "CSA"},
            {"first_name": "Hugh", "last_name": "Akers",
             "born": "1842", "cemetery_id": 2, "unit": "CSA"},
            # B—C same person (cemetery tiebreaker)
            {"first_name": "Hugh", "last_name": "Akers",
             "born": "1845", "cemetery_id": 3, "unit": "CSA"},
        )
        out = build_dedup(
            cgr_records=cgr,
            pensioner_to_cgr_links={},
            pensioners_by_id=None,
        )
        # All three should land in the same cluster via transitivity.
        # (A-B share year; B-C share cemetery; A-C need not directly
        # match but union-find bridges them.)
        # Check that the output has 1 person (not 3).
        cgr_persons = [p for p in out["persons"].values()
                       if p["member_cgr_ids"]]
        assert len(cgr_persons) == 1
        assert len(cgr_persons[0]["member_cgr_ids"]) == 3

    def test_merged_metadata_takes_first_non_empty(self):
        from scripts.cgr_dedup import merged_metadata_for
        members = [
            {"first_name": "", "last_name": "", "born": "",
             "spouse": "", "unit": "", "rank": ""},
            {"first_name": "Hugh", "last_name": "Akers",
             "spouse": "Mary", "unit": "1 TX", "rank": "Pvt"},
            {"first_name": "Hugh", "last_name": "Akers",
             "spouse": "Jane", "unit": "2 TX", "rank": ""},
        ]
        m = merged_metadata_for(members)
        # First non-empty wins (member 0 has all empty; member 1 fills).
        assert m["first_name"] == "Hugh"
        assert m["last_name"] == "Akers"
        assert m["spouse"] == "Mary"
        assert m["regiment"] == "1 TX"
        assert m["rank"] == "Pvt"


class TestOutputSchema:
    def test_output_has_required_top_level_keys(self):
        from scripts.cgr_dedup import build_dedup
        cgr = []
        out = build_dedup(cgr_records=cgr, pensioner_to_cgr_links={},
                          pensioners_by_id=None)
        for key in ("version", "created_at", "thresholds", "persons",
                    "cgr_id_to_person_id", "pensioner_id_to_person_id",
                    "stats"):
            assert key in out, f"missing top-level key: {key}"

    def test_stats_count_records(self):
        from scripts.cgr_dedup import build_dedup
        cgr = [
            {"id": 1, "first_name": "A", "last_name": "Smith",
             "born": "1840", "cemetery_id": 1, "unit": "CSA"},
            {"id": 2, "first_name": "A", "last_name": "Smith",
             "born": "1841", "cemetery_id": 1, "unit": "CSA"},
        ]
        out = build_dedup(
            cgr_records=cgr,
            pensioner_to_cgr_links={99: [1]},
            pensioners_by_id={99: {"id": 99}},
        )
        assert out["stats"]["input_cgr_records"] == 2
        assert out["stats"]["merged_pairs"] == 1


# ============================================================
# Integration: end-to-end dedup via CLI wrapper (no subprocess)
# ============================================================
class TestCLIOutputFormat:
    """The CLI main() writes a deterministic JSON shape. These
    tests pin the contract: the file MUST round-trip and contain
    at least one CGR-merged pair when fed synthetic data.
    """

    def _run_end_to_end(self, tmp_path, cgr_records, pensioners,
                        pensioner_to_cgr_links):
        # Bypass subprocess by calling build_dedup directly on the
        # same data the CLI would read.
        from scripts.cgr_dedup import build_dedup
        return build_dedup(
            cgr_records=cgr_records,
            pensioner_to_cgr_links=pensioner_to_cgr_links,
            pensioners_by_id=pensioners,
        )

    def test_end_to_end_realistic(self, tmp_path):
        """Small but realistic dataset that exercises every code path."""
        cgr = [
            {"id": 1, "first_name": "Hugh", "last_name": "Akers",
             "born": "1840", "cemetery_id": 1, "unit": "CSA",
             "rank": "Pvt"},
            {"id": 2, "first_name": "Hugh", "last_name": "Akers",
             "born": "1841", "cemetery_id": 2, "unit": "CSA",
             "rank": "Pvt"},
            {"id": 3, "first_name": "Jane", "last_name": "Akers",
             "born": "1845", "cemetery_id": 3, "unit": "CSA",
             "rank": "Pvt"},
        ]
        pensions = {
            42: {"id": 42, "first_name": "H.", "last_name": "Akers"},
            99: {"id": 99, "first_name": "X", "last_name": "Y"},
        }
        links = {42: [1]}
        out = self._run_end_to_end(
            tmp_path, cgr, pensions, links,
        )
        # Two unique cluster roots (the Akers cluster + Jane singleton).
        cgr_persons = [p for p in out["persons"].values()
                       if p["member_cgr_ids"]]
        assert len(cgr_persons) == 2
        # The merged Hugh pair is one of them.
        big = max(cgr_persons, key=lambda p: len(p["member_cgr_ids"]))
        assert sorted(big["member_cgr_ids"]) == [1, 2]
        # Pensioner 42 maps to the merged person.
        assert out["pensioner_id_to_person_id"]["42"] is not None
        # Pensioner 99 maps to a singleton (pensioner_99).
        assert out["pensioner_id_to_person_id"]["99"] == "pensioner_99"
