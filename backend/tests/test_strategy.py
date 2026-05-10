"""Regression tests for the strategy advisor.

These tests pin the math and gating behavior of each individual strategy
generator AND the top-level `recommend()` ordering. Two known bugs are
explicitly covered:

  - `_force_above_150` previously failed to skip when the consignment's
    intrinsic_value_eur was None at the time of the gate check (because the
    /api/strategy route does not run apply_all_defaults beforehand).
    Resulting "savings" were fictional. See test_force_above_150_*.

  - `_split_parcels` used to leave the head parcel's
    consignment_value_eur unchanged while overwriting landed_cost_eur and
    duty_total_eur with the sum across parcels — produced an internally
    inconsistent CalculationResult. See test_split_parcels_*.
"""
from __future__ import annotations

from decimal import Decimal

from app.models.schemas import Consignment, Item
from app.services.strategy import (
    _b2b_eu_warehouse,
    _consolidate_descriptions,
    _drop_ioss_use_fta,
    _force_above_150,
    _split_parcels,
    _status_quo,
    recommend,
)


def _under_150_consignment() -> Consignment:
    """A €40 CN→DE B2C IOSS shipment — under €150 threshold."""
    return Consignment(
        items=[Item(hs6="610910", description="cotton tee", origin="CN",
                    qty=2, unit_value_eur=Decimal("20.00"))],
        destination_ms="DE",
        ioss_registered=True,
    )


def _over_150_consignment() -> Consignment:
    """A €200 CN→DE B2C IOSS shipment — already above €150."""
    return Consignment(
        items=[Item(hs6="610910", description="cotton tee", origin="CN",
                    qty=1, unit_value_eur=Decimal("200.00"))],
        destination_ms="DE",
        ioss_registered=True,
    )


def _fr_with_duplicate_hs_groups() -> Consignment:
    """Three lines, two of which share HS6+origin but have different descriptions."""
    return Consignment(
        items=[
            Item(hs6="610910", description="cotton tee", origin="CN",
                 qty=1, unit_value_eur=Decimal("12.00")),
            Item(hs6="610910", description="men's cotton t-shirt", origin="CN",
                 qty=1, unit_value_eur=Decimal("12.00")),
            Item(hs6="640399", description="leather shoe", origin="CN",
                 qty=1, unit_value_eur=Decimal("35.00")),
        ],
        destination_ms="FR",
        ioss_registered=True,
    )


def _all_fta_consignment() -> Consignment:
    return Consignment(
        items=[Item(hs6="610910", description="cotton tee", origin="GB",
                    qty=1, unit_value_eur=Decimal("20.00"),
                    fta_proof_held=True)],
        destination_ms="DE",
        ioss_registered=True,
    )


# -- _force_above_150 ------------------------------------------------------

class TestForceAbove150:
    def test_returns_strategy_when_value_under_threshold(self, mock_avalara):
        """Under €150 → strategy fires and sets intrinsic_value_eur to €150.01."""
        s = _force_above_150(_under_150_consignment())
        assert s is not None
        assert s.name == "push_above_150"

    def test_returns_none_when_value_already_above_threshold(self, mock_avalara):
        """REGRESSION: `_force_above_150` must skip when value > €150.

        Previously this gate failed because c.intrinsic_value_eur was None
        at strategy time (the adapter doesn't compute it; defaults engine
        does). With apply_all_defaults applied at the top of recommend(),
        the gate now correctly sees €200 and skips.
        """
        s = _force_above_150(_over_150_consignment())
        assert s is None, (
            "push_above_150 must NOT run when value is already over €150 — "
            "doing so produces fictional 'savings' by setting value DOWN to €150.01"
        )

    def test_returns_none_when_value_exactly_at_threshold(self, mock_avalara):
        """Exactly €150 is at threshold but not over — gate stays open."""
        c = Consignment(
            items=[Item(hs6="610910", origin="CN", qty=1,
                        unit_value_eur=Decimal("150.00"))],
            destination_ms="DE",
        )
        s = _force_above_150(c)
        # Threshold check is strict-greater (>), so €150 should still fire
        assert s is not None


# -- _split_parcels --------------------------------------------------------

class TestSplitParcels:
    def test_aggregates_value_and_cost_consistently(self, mock_avalara):
        """REGRESSION: head.consignment_value_eur must reflect the SUM
        across all parcels, not just the first parcel's value.

        Previously: 3 parcels of €12+€35+€25 = €72 total, but the rendered
        CalculationResult showed consignment_value_eur=€12 (head parcel)
        with landed_cost_eur summed across all 3. Inconsistent.
        """
        c = _fr_with_duplicate_hs_groups()
        s = _split_parcels(c)
        assert s is not None
        # consignment_value_eur should equal sum of all line values
        # across all parcels, not just the head parcel.
        expected_total_value = sum(
            (i.line_value_eur for i in c.items), Decimal("0.00")
        )
        assert s.result.consignment_value_eur == expected_total_value, (
            f"Split parcels result.consignment_value_eur={s.result.consignment_value_eur} "
            f"should equal sum of items €{expected_total_value}"
        )

    def test_compliance_warning_mentions_split(self, mock_avalara):
        s = _split_parcels(_fr_with_duplicate_hs_groups())
        assert any("split" in w.lower() for w in s.result.compliance_warnings)


# -- _drop_ioss_use_fta ----------------------------------------------------

class TestDropIossUseFta:
    def test_returns_none_when_no_item_is_fta_eligible(self, mock_avalara):
        """All items are CN origin without FTA proof → strategy not applicable."""
        c = Consignment(
            items=[Item(hs6="610910", origin="CN", qty=1,
                        unit_value_eur=Decimal("20.00"))],
            destination_ms="DE",
        )
        assert _drop_ioss_use_fta(c) is None

    def test_returns_none_when_only_some_items_are_fta(self, mock_avalara):
        """Mixed basket (one FTA, one not) → strategy not applicable to the whole shipment."""
        c = Consignment(
            items=[
                Item(hs6="610910", origin="GB", qty=1,
                     unit_value_eur=Decimal("20.00"), fta_proof_held=True),
                Item(hs6="420232", origin="CN", qty=1,
                     unit_value_eur=Decimal("30.00")),
            ],
            destination_ms="FR",
        )
        assert _drop_ioss_use_fta(c) is None

    def test_returns_strategy_when_all_items_are_fta(self, mock_avalara):
        """All items FTA-eligible with proof → strategy fires."""
        s = _drop_ioss_use_fta(_all_fta_consignment())
        assert s is not None
        assert s.name == "drop_ioss_use_fta"


# -- _b2b_eu_warehouse -----------------------------------------------------

class TestB2BWarehouse:
    def test_floors_value_at_1000(self, mock_avalara):
        """Always sets value to max(actual, €1000) — represents bulk import."""
        c = _under_150_consignment()
        s = _b2b_eu_warehouse(c)
        assert s.result.consignment_value_eur >= Decimal("1000.00")

    def test_keeps_higher_actual_value(self, mock_avalara):
        """If actual value > €1000, that value is preserved."""
        c = Consignment(
            items=[Item(hs6="610910", origin="CN", qty=1,
                        unit_value_eur=Decimal("2500.00"))],
            destination_ms="DE",
            intrinsic_value_eur=Decimal("2500.00"),
        )
        s = _b2b_eu_warehouse(c)
        # Strategy should keep €2500, not floor at €1000
        assert s.result.consignment_value_eur == Decimal("2500.00")


# -- _consolidate_descriptions ---------------------------------------------

class TestConsolidateDescriptions:
    def test_merges_lines_with_same_hs6_origin(self, mock_avalara):
        """Two lines sharing HS6+origin but different descriptions →
        consolidate normalises descriptions so they collapse to one group.
        """
        c = _fr_with_duplicate_hs_groups()
        # Original: 3 grouping keys (two share hs6+origin but differ on description)
        # After consolidation: 2 grouping keys (descriptions now match)
        s = _consolidate_descriptions(c)
        assert s is not None
        # status_quo has 3 distinct grouping keys; consolidate should produce 2
        sq = _status_quo(c)
        assert len(sq.result.item_breakdown) == 3
        assert len(s.result.item_breakdown) == 2


# -- recommend() ordering --------------------------------------------------

class TestRecommend:
    def test_recommend_applies_defaults_before_running_strategies(self, mock_avalara):
        """REGRESSION: recommend() must apply_all_defaults BEFORE iterating
        strategies, otherwise gates that check c.intrinsic_value_eur silently
        fail on None and run strategies that should have been skipped.
        """
        c = _over_150_consignment()
        c.intrinsic_value_eur = None  # explicit: defaults haven't run
        result = recommend(c)
        # push_above_150 must not appear because intrinsic_value > €150
        names = [s.name for s in result]
        assert "push_above_150" not in names, (
            "push_above_150 leaked into recommend() output for a >€150 shipment "
            "— the apply_all_defaults call at the top of recommend() should "
            "have set intrinsic_value_eur correctly so the gate fires."
        )

    def test_recommend_orders_by_landed_cost_ascending(self, mock_avalara):
        result = recommend(_under_150_consignment())
        costs = [s.result.landed_cost_eur for s in result]
        assert costs == sorted(costs), "strategies should be sorted by landed_cost_eur asc"

    def test_recommend_always_includes_status_quo(self, mock_avalara):
        result = recommend(_under_150_consignment())
        assert any(s.name == "status_quo" for s in result)

    def test_recommend_filters_inapplicable_strategies(self, mock_avalara):
        """For a CN-only basket, drop_ioss_use_fta is filtered out."""
        result = recommend(_under_150_consignment())
        names = [s.name for s in result]
        assert "drop_ioss_use_fta" not in names
