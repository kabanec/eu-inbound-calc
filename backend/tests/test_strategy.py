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
from app.reference.data import SHIPPING_COSTS_EUR
from app.services.strategy import (
    _b2b_eu_warehouse,
    _consolidate_descriptions,
    _drop_ioss_use_express_fta,
    _drop_ioss_use_fta,
    _drop_ioss_use_mfn,
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


# -- _drop_ioss_use_mfn ----------------------------------------------------

class TestDropIossUseMfn:
    def test_returns_none_when_not_using_ioss(self, mock_avalara):
        """Strategy only applies when caller is currently using IOSS."""
        c = Consignment(
            items=[Item(hs6="610910", origin="CN", qty=1,
                        unit_value_eur=Decimal("20.00"))],
            destination_ms="DE",
            ioss_registered=False,
        )
        assert _drop_ioss_use_mfn(c) is None

    def test_returns_strategy_for_non_fta_ioss_consignment(self, mock_avalara):
        """CN-origin IOSS consignment (no FTA available) → strategy fires."""
        s = _drop_ioss_use_mfn(_under_150_consignment())
        assert s is not None
        assert s.name == "drop_ioss_use_mfn"

    def test_flips_ioss_off_and_uses_express_channel(self, mock_avalara):
        """Result must have ioss off, no postal designation, express channel —
        otherwise either €3 path could still fire."""
        s = _drop_ioss_use_mfn(_under_150_consignment())
        assert s is not None
        # Resulting consignment configuration should disengage both €3 triggers.
        # The recalc's regime per line should be standard_tariff (not e3_simplified).
        regimes = {ib.regime for ib in s.result.item_breakdown}
        assert "e3_simplified" not in regimes, (
            "drop_ioss_use_mfn must produce standard_tariff lines; "
            "if e3_simplified appears, either ioss wasn't flipped or postal trigger fired"
        )

    def test_fires_alongside_fta_strategies_when_fta_eligible(self, mock_avalara):
        """For FTA-eligible IOSS consignments, the MFN strategy still fires
        (no FTA gate). The ranking decides which wins — typically FTA wins
        because FTA preferential rate ≤ MFN."""
        s = _drop_ioss_use_mfn(_all_fta_consignment())
        assert s is not None  # gateless beyond 'currently IOSS'

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

    def test_recommend_includes_drop_ioss_use_mfn_for_ioss_basket(self, mock_avalara):
        """drop_ioss_use_mfn must surface for any IOSS consignment, regardless
        of FTA eligibility — its gate is just 'currently using IOSS'."""
        result = recommend(_under_150_consignment())
        names = [s.name for s in result]
        assert "drop_ioss_use_mfn" in names

    def test_recommend_drops_drop_ioss_use_mfn_when_not_using_ioss(self, mock_avalara):
        """When the caller is already on the standard-tariff path (ioss off),
        the strategy is redundant and should not appear."""
        c = Consignment(
            items=[Item(hs6="610910", origin="CN", qty=1,
                        unit_value_eur=Decimal("20.00"))],
            destination_ms="DE",
            ioss_registered=False,
        )
        result = recommend(c)
        names = [s.name for s in result]
        assert "drop_ioss_use_mfn" not in names


# -- shipping cost modeling ------------------------------------------------

class TestShippingCost:
    def test_status_quo_uses_modeled_express_shipping(self, mock_avalara):
        """status_quo on a default-channel ('express') consignment carries
        the express shipping rate from SHIPPING_COSTS_EUR."""
        s = _status_quo(_under_150_consignment())
        assert s.result.shipping_cost_eur == SHIPPING_COSTS_EUR["express"]

    def test_drop_ioss_use_fta_switches_to_postal_shipping(self, mock_avalara):
        """drop_ioss_use_fta switches channel to postal → cheaper shipping."""
        s = _drop_ioss_use_fta(_all_fta_consignment())
        assert s is not None
        assert s.result.shipping_cost_eur == SHIPPING_COSTS_EUR["postal"]
        # Sanity: postal must be cheaper than express, otherwise the strategy
        # makes no sense vs. status_quo.
        assert SHIPPING_COSTS_EUR["postal"] < SHIPPING_COSTS_EUR["express"]

    def test_b2b_warehouse_uses_general_cargo_shipping(self, mock_avalara):
        """B2B EU warehouse uses bulk freight rate, not per-parcel express."""
        s = _b2b_eu_warehouse(_under_150_consignment())
        assert s.result.shipping_cost_eur == SHIPPING_COSTS_EUR["general_cargo"]

    def test_split_parcels_multiplies_shipping(self, mock_avalara):
        """N parcels → shipping summed across all sub-parcels."""
        c = _fr_with_duplicate_hs_groups()
        # 3 distinct (hs6, description, origin) groups → 3 parcels
        s = _split_parcels(c)
        assert s is not None
        # Each sub-parcel ships at express rate; total should be 3 × express.
        expected_min = SHIPPING_COSTS_EUR["express"] * Decimal("3")
        assert s.result.shipping_cost_eur >= expected_min

    def test_landed_cost_includes_shipping(self, mock_avalara):
        """landed_cost_eur must include shipping — otherwise strategy
        comparisons that change shipping (postal, freight) would be wrong."""
        s = _status_quo(_under_150_consignment())
        # landed = value + duty + fees + vat + shipping
        # status_quo has €40 value, 0 duty (mock), default IOSS VAT.
        # Shipping must be > 0 and reflected.
        assert s.result.shipping_cost_eur > Decimal("0.00")
        # crude check — landed cost is at least value + shipping
        assert s.result.landed_cost_eur >= (
            s.result.consignment_value_eur + s.result.shipping_cost_eur
        )


# -- shipping_model: percentage_demo --------------------------------------

class TestPercentageDemoShippingModel:
    """The 'percentage_demo' shipping_model replaces channel-flat shipping
    with max(€10, 10% × value), uniform across channels. Legacy callers
    that don't set the field must continue to see flat-per-channel."""

    def _pct_consignment(self, **kw) -> Consignment:
        defaults = dict(
            items=[Item(hs6="610910", description="cotton tee", origin="CN",
                        qty=1, unit_value_eur=Decimal("40.00"))],
            destination_ms="DE",
            ioss_registered=True,
            shipping_model="percentage_demo",
        )
        defaults.update(kw)
        return Consignment(**defaults)

    def test_floor_kicks_in_for_low_value(self, mock_avalara):
        """€40 goods × 10% = €4, below floor → €10 applies."""
        c = self._pct_consignment()  # €40 single line
        s = _status_quo(c)
        assert s.result.shipping_cost_eur == Decimal("10.00")

    def test_percentage_applies_above_floor(self, mock_avalara):
        """€500 goods × 10% = €50, above €10 floor → €50."""
        c = self._pct_consignment(items=[
            Item(hs6="610910", description="tee", origin="CN",
                 qty=1, unit_value_eur=Decimal("500.00")),
        ])
        s = _status_quo(c)
        assert s.result.shipping_cost_eur == Decimal("50.00")

    def test_legacy_default_unchanged_when_field_omitted(self, mock_avalara):
        """Callers that don't send shipping_model must still see flat
        per-channel behavior so the production / page isn't affected."""
        c = Consignment(
            items=[Item(hs6="610910", description="tee", origin="CN",
                        qty=1, unit_value_eur=Decimal("40.00"))],
            destination_ms="DE",
            ioss_registered=True,
        )
        s = _status_quo(c)
        # Legacy: express channel = €15 flat
        assert s.result.shipping_cost_eur == SHIPPING_COSTS_EUR["express"]

    def test_drop_ioss_use_fta_channel_agnostic_under_demo_model(self, mock_avalara):
        """Under percentage_demo, the channel switch to postal no longer
        produces a shipping discount — both routes pay the same value-based
        cost. drop_ioss_use_fta's case rests on the €3 bypass, not shipping."""
        c = Consignment(
            items=[Item(hs6="610910", description="cotton tee", origin="GB",
                        qty=1, unit_value_eur=Decimal("60.00"),
                        fta_proof_held=True)],
            destination_ms="DE",
            ioss_registered=True,
            shipping_model="percentage_demo",
        )
        sq = _status_quo(c)
        ds = _drop_ioss_use_fta(c)
        assert ds is not None
        # Both legs use max(€10, 10% × €60) = €10 — shipping unchanged.
        assert sq.result.shipping_cost_eur == Decimal("10.00")
        assert ds.result.shipping_cost_eur == Decimal("10.00")

    def test_b2b_warehouse_floors_shipping_at_100_under_demo_model(self, mock_avalara):
        """b2b_eu_warehouse floors value at €1000 → shipping = 10% × €1000 = €100
        under percentage_demo, replacing the €50 flat freight rate."""
        c = self._pct_consignment()  # €40 actual value
        s = _b2b_eu_warehouse(c)
        # Value floored at €1000 → 10% = €100, well above €10 floor
        assert s.result.shipping_cost_eur == Decimal("100.00")
        assert s.result.consignment_value_eur >= Decimal("1000.00")

    def test_split_parcels_uses_per_sub_parcel_percentage(self, mock_avalara):
        """Splitting €12 + €12 + €35 = €72 across 3 parcels:
        each sub-parcel × 10% is below €10 floor → 3 × €10 = €30 total."""
        c = Consignment(
            items=[
                Item(hs6="610910", description="cotton tee", origin="CN",
                     qty=1, unit_value_eur=Decimal("12.00")),
                Item(hs6="640399", description="leather shoe", origin="CN",
                     qty=1, unit_value_eur=Decimal("35.00")),
                Item(hs6="420232", description="leather wallet", origin="CN",
                     qty=1, unit_value_eur=Decimal("25.00")),
            ],
            destination_ms="FR",
            ioss_registered=True,
            shipping_model="percentage_demo",
        )
        s = _split_parcels(c)
        assert s is not None
        # 3 parcels × €10 floor each (all values × 10% < €10)
        assert s.result.shipping_cost_eur == Decimal("30.00")

    def test_split_parcels_floor_vs_percentage_per_sub_parcel(self, mock_avalara):
        """One small parcel (floor applies) + one large parcel (% applies):
        €40 × 10% = €4 → floor €10. €500 × 10% = €50 → no floor.
        Total split shipping = €10 + €50 = €60."""
        c = Consignment(
            items=[
                Item(hs6="610910", description="tee", origin="CN",
                     qty=1, unit_value_eur=Decimal("40.00")),
                Item(hs6="640399", description="shoe", origin="CN",
                     qty=1, unit_value_eur=Decimal("500.00")),
            ],
            destination_ms="DE",
            ioss_registered=True,
            shipping_model="percentage_demo",
        )
        s = _split_parcels(c)
        assert s is not None
        assert s.result.shipping_cost_eur == Decimal("60.00")


# -- user-supplied shipping override --------------------------------------

class TestUserShippingOverride:
    """The UI surfaces an editable per-parcel shipping+handling field. The
    user's value must:
      - flow through to status_quo, consolidate_descriptions, force_above_150
        (same shipment, no channel change)
      - be PRESERVED for same-channel strategies (drop_ioss_use_express_fta,
        drop_ioss_use_mfn — both keep express)
      - be REPLACED by the new channel's flat rate when a strategy changes
        channel (drop_ioss_use_fta → postal, b2b_eu_warehouse → general_cargo)
    """

    def _express_with_override(self, override_eur: str = "22.50") -> Consignment:
        """Default express consignment with a user-typed shipping override."""
        return Consignment(
            items=[Item(hs6="610910", description="cotton tee", origin="GB",
                        qty=1, unit_value_eur=Decimal("40.00"),
                        fta_proof_held=True)],
            destination_ms="DE",
            ioss_registered=True,
            channel="express",
            shipping_cost_eur=Decimal(override_eur),
        )

    def test_status_quo_preserves_user_override(self, mock_avalara):
        """status_quo never changes channel → user value must survive."""
        s = _status_quo(self._express_with_override())
        assert s.result.shipping_cost_eur == Decimal("22.50")

    def test_force_above_150_preserves_user_override(self, mock_avalara):
        """Pushing value above €150 doesn't change channel → preserve."""
        s = _force_above_150(self._express_with_override())
        assert s is not None
        assert s.result.shipping_cost_eur == Decimal("22.50")

    def test_consolidate_descriptions_preserves_user_override(self, mock_avalara):
        """Description normalization is a metadata change only — preserve."""
        s = _consolidate_descriptions(self._express_with_override())
        assert s.result.shipping_cost_eur == Decimal("22.50")

    def test_drop_ioss_use_express_fta_preserves_user_override(self, mock_avalara):
        """express → express (same channel) — user value MUST be preserved.
        REGRESSION: previously _override_channel_shipping clobbered the user
        value with SHIPPING_COSTS_EUR['express'] (€15) even though the channel
        didn't change."""
        s = _drop_ioss_use_express_fta(self._express_with_override())
        assert s is not None
        assert s.result.shipping_cost_eur == Decimal("22.50"), (
            "Same-channel strategy must preserve user override, not swap to flat rate"
        )

    def test_drop_ioss_use_mfn_preserves_user_override(self, mock_avalara):
        """express → express (same channel) — user value preserved."""
        s = _drop_ioss_use_mfn(self._express_with_override())
        assert s is not None
        assert s.result.shipping_cost_eur == Decimal("22.50")

    def test_drop_ioss_use_fta_replaces_override_on_channel_switch(self, mock_avalara):
        """express → postal (channel change) — user value no longer applies;
        strategy uses the postal channel's flat rate."""
        s = _drop_ioss_use_fta(self._express_with_override())
        assert s is not None
        assert s.result.shipping_cost_eur == SHIPPING_COSTS_EUR["postal"]

    def test_b2b_warehouse_replaces_override_on_channel_switch(self, mock_avalara):
        """express → general_cargo — user value replaced with freight rate."""
        s = _b2b_eu_warehouse(self._express_with_override())
        assert s.result.shipping_cost_eur == SHIPPING_COSTS_EUR["general_cargo"]

    def test_postal_origin_preserves_user_override_when_strategy_keeps_postal(
        self, mock_avalara
    ):
        """If user is already on postal with a custom rate, drop_ioss_use_fta
        keeps postal — must preserve the user value, not reset to €5 flat."""
        c = Consignment(
            items=[Item(hs6="610910", description="cotton tee", origin="GB",
                        qty=1, unit_value_eur=Decimal("40.00"),
                        fta_proof_held=True)],
            destination_ms="DE",
            ioss_registered=True,
            channel="postal",
            postal_designated_op=True,
            shipping_cost_eur=Decimal("8.00"),
        )
        s = _drop_ioss_use_fta(c)
        assert s is not None
        assert s.result.shipping_cost_eur == Decimal("8.00"), (
            "Postal → postal must preserve user-supplied €8, not reset to €5 default"
        )
