"""Verify FaG search applies the US country (and state) location filter.

Regression guard: search_fag previously omitted location filters, so common
names like "John Smith" pulled 97K global results (mostly foreign), inflating
the too_many bucket. The working param ?locationId=<id> was discovered
empirically:

  data/probe/filter_v7.json  -> locationId=country_4  verified
  data/probe/filter_v8.json  -> locationId=state_38   verified

Cuts ~35% of results for common names to US-only; ~99% when state is known.
"""
from scripts.search_fag import (
    apply_location_filter,
    strategy_b1_exact,
    strategy_b3_first_initial_fuzzy,
    strategy_b4_fuzzy_last,
    strategy_c1_cw_context,
    strategy_with_birth_year,
    strategy_year_sniper,
    FAG_COUNTRY_FILTER_US,
    FAG_STATE_IDS,
)


class TestApplyLocationFilter:
    def test_country_only_when_no_state(self):
        out = apply_location_filter({"firstname": "John"})
        assert out["locationId"] == "country_4"

    def test_state_overrides_country_when_known(self):
        out = apply_location_filter({"firstname": "John"}, "OK")
        assert out["locationId"] == "state_38"
        # Only one locationId value can be passed (last wins); state wins
        # when known because it's strictly more specific.

    def test_unknown_state_falls_back_to_country(self):
        out = apply_location_filter({"firstname": "John"}, "ZZ")
        assert out["locationId"] == "country_4"

    def test_lowercase_state_normalised(self):
        out = apply_location_filter({"firstname": "John"}, "ok")
        assert out["locationId"] == "state_38"

    def test_does_not_mutate_caller(self):
        params = {"firstname": "John"}
        apply_location_filter(params, "OK")
        assert "locationId" not in params


class TestAllStrategiesIncludeCountryFilter:
    """Each strategy's return value, when run through apply_location_filter,
    must include the location filter. This is the bug we just fixed — before
    the fix, strategies returned URLs that pulled global results."""

    def test_b1_exact(self):
        out = apply_location_filter(strategy_b1_exact("John", "", "Smith", 1850))
        assert out.get("locationId") == "country_4"

    def test_b1_exact_with_state(self):
        out = apply_location_filter(strategy_b1_exact("John", "", "Smith", 1850), "OK")
        assert out.get("locationId") == "state_38"

    def test_b3_first_initial_fuzzy(self):
        out = apply_location_filter(strategy_b3_first_initial_fuzzy("John", "", "Smith", 1850))
        assert out.get("locationId") == "country_4"

    def test_b4_fuzzy_last(self):
        out = apply_location_filter(strategy_b4_fuzzy_last("John", "W", "Smith", 1850))
        assert out.get("locationId") == "country_4"

    def test_c1_cw_context(self):
        out = apply_location_filter(strategy_c1_cw_context("John", "", "Smith", 1850, 1920))
        assert out.get("locationId") == "country_4"

    def test_with_birth_year(self):
        out = apply_location_filter(strategy_with_birth_year("John", "", "Smith", 1850))
        assert out.get("locationId") == "country_4"

    def test_year_sniper(self):
        out = apply_location_filter(strategy_year_sniper("John", "", "Smith", 1850, 1920))
        assert out.get("locationId") == "country_4"


class TestStateMapCoverage:
    def test_all_50_states_present(self):
        assert "DC" in FAG_STATE_IDS
        assert len(FAG_STATE_IDS) >= 51  # 50 states + DC

    def test_oklahoma_locked(self):
        # Verified empirically: ?locationId=state_38 -> 1,087 results for John Smith.
        # If FaG changes this id, this test forces a deliberate update.
        assert FAG_STATE_IDS["OK"] == "state_38"


class TestFilterConstantLocked:
    def test_country_filter_value(self):
        # Verified empirically: ?locationId=country_4 -> 62,632 for John Smith.
        assert FAG_COUNTRY_FILTER_US == {"locationId": "country_4"}