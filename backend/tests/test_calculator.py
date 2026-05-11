"""Tests for the core calculator decision tree (PRD §FR-1)."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from app.models.schemas import Consignment, Item
from app.services.calculator import calculate, group_items
from tests.conftest import AVALARA_URL, make_avalara_body


def _set_avalara_duties(mock_avalara, duties: list[float]) -> None:
    """Replace default mock with a response returning specific per-line duties."""
    mock_avalara.reset()
    mock_avalara.add(mock_avalara.POST, AVALARA_URL,
                     json=make_avalara_body(duties), status=200)


def make_item(hs6="610910", desc="cotton t-shirt", origin="CN",
              qty=1, value=20, fta=False, std_rate=0.12, fta_rate=0.0):
    return Item(
        hs6=hs6, description=desc, origin=origin, qty=qty,
        unit_value_eur=Decimal(str(value)),
        fta_proof_held=fta,
        standard_duty_rate=Decimal(str(std_rate)),
        fta_duty_rate=Decimal(str(fta_rate)),
    )


# Item grouping ------------------------------------------------------------
class TestItemGrouping:
    def test_identical_items_group_to_one_line(self):
        groups = group_items([make_item(qty=3), make_item(qty=2)])
        assert len(groups) == 1

    def test_different_hs_codes_split(self):
        groups = group_items([make_item(hs6="610910"), make_item(hs6="640399")])
        assert len(groups) == 2

    def test_different_descriptions_split(self):
        groups = group_items([
            make_item(desc="silk blouse"), make_item(desc="wool blouse"),
        ])
        assert len(groups) == 2

    def test_different_origins_split(self):
        groups = group_items([make_item(origin="CN"), make_item(origin="VN")])
        assert len(groups) == 2

    def test_description_normalization(self):
        groups = group_items([
            make_item(desc="Cotton T-Shirt"),
            make_item(desc="cotton t-shirt"),
            make_item(desc="cotton t-shirt "),
        ])
        assert len(groups) == 1


# €3 trigger paths ---------------------------------------------------------
class TestE3Triggers:
    def test_b2c_ioss_under_150_charges_e3(self):
        c = Consignment(items=[make_item()], destination_ms="DE",
                        ioss_registered=True,
                        transaction_date=date(2026, 8, 1))
        assert calculate(c).duty_total_eur == Decimal("3.00")

    def test_b2c_postal_non_ioss_charges_e3(self):
        c = Consignment(items=[make_item()], destination_ms="DE",
                        ioss_registered=False, postal_designated_op=True,
                        channel="postal", transaction_date=date(2026, 8, 1))
        assert calculate(c).duty_total_eur == Decimal("3.00")

    def test_b2c_non_ioss_non_postal_uses_standard(self, mock_avalara):
        _set_avalara_duties(mock_avalara, [2.40])  # 12% × €20
        c = Consignment(items=[make_item(value=20, std_rate=0.12)],
                        destination_ms="DE", ioss_registered=False,
                        transaction_date=date(2026, 8, 1))
        assert calculate(c).duty_total_eur == Decimal("2.40")

    def test_three_distinct_groups_charges_e9(self):
        c = Consignment(
            items=[
                make_item(hs6="610910", desc="cotton tee"),
                make_item(hs6="640399", desc="leather shoe"),
                make_item(hs6="851712", desc="smartphone"),
            ],
            destination_ms="DE", ioss_registered=True,
            transaction_date=date(2026, 8, 1),
        )
        assert calculate(c).duty_total_eur == Decimal("9.00")

    def test_qty_within_group_does_not_multiply_e3(self):
        c = Consignment(items=[make_item(qty=10, value=5)],
                        destination_ms="DE", ioss_registered=True,
                        transaction_date=date(2026, 8, 1))
        assert calculate(c).duty_total_eur == Decimal("3.00")


# Hard exits ---------------------------------------------------------------
class TestHardExits:
    def test_b2b_skips_e3(self, mock_avalara):
        _set_avalara_duties(mock_avalara, [2.40])  # 12% × €20
        c = Consignment(items=[make_item(value=20, std_rate=0.12)],
                        destination_ms="DE", b2b=True,
                        transaction_date=date(2026, 8, 1))
        r = calculate(c)
        assert r.duty_total_eur == Decimal("2.40")

    def test_buyer_agent_skips_e3(self):
        c = Consignment(items=[make_item()], destination_ms="DE",
                        buyer_agent=True, ioss_registered=True,
                        transaction_date=date(2026, 8, 1))
        assert calculate(c).item_breakdown[0].regime != "e3_simplified"

    def test_value_above_150_skips_e3(self, mock_avalara):
        _set_avalara_duties(mock_avalara, [24.00])  # 12% × €200
        c = Consignment(items=[make_item(value=200, std_rate=0.12)],
                        destination_ms="DE", ioss_registered=True,
                        transaction_date=date(2026, 8, 1))
        assert calculate(c).duty_total_eur == Decimal("24.00")


# FTA exclusion + direct-transport gate (PRD §FR-1 step 3) -----------------
class TestFTAExclusion:
    def test_fta_when_ship_from_equals_origin(self):
        c = Consignment(
            items=[make_item(origin="GB", fta=True, std_rate=0.12, fta_rate=0.0)],
            destination_ms="DE", ioss_registered=True,
            ship_from="GB",
            transaction_date=date(2026, 8, 1),
        )
        r = calculate(c)
        assert r.item_breakdown[0].regime == "standard_tariff_fta"
        assert r.duty_total_eur == Decimal("0.00")

    def test_fta_denied_when_ship_from_differs_no_assertion(self):
        c = Consignment(
            items=[make_item(origin="GB", fta=True, std_rate=0.12, fta_rate=0.0)],
            destination_ms="DE", ioss_registered=True,
            ship_from="CN", non_alteration_confirmed=False,
            transaction_date=date(2026, 8, 1),
        )
        r = calculate(c)
        assert r.item_breakdown[0].regime == "e3_simplified"
        assert r.duty_total_eur == Decimal("3.00")
        assert any(
            "ship_from_vs_origin" in d.field for d in r.defaults_applied
        )

    def test_fta_when_ship_from_differs_with_non_alteration(self):
        c = Consignment(
            items=[make_item(origin="GB", fta=True, std_rate=0.12, fta_rate=0.0)],
            destination_ms="DE", ioss_registered=True,
            ship_from="SG", non_alteration_confirmed=True,
            transaction_date=date(2026, 8, 1),
        )
        r = calculate(c)
        assert r.item_breakdown[0].regime == "standard_tariff_fta"
        assert r.duty_total_eur == Decimal("0.00")

    def test_fta_denied_when_ship_from_unknown(self):
        c = Consignment(
            items=[make_item(origin="GB", fta=True, std_rate=0.12, fta_rate=0.0)],
            destination_ms="DE", ioss_registered=True,
            ship_from=None,
            transaction_date=date(2026, 8, 1),
        )
        r = calculate(c)
        assert r.item_breakdown[0].regime == "e3_simplified"
        assert r.duty_total_eur == Decimal("3.00")
        assert any("ship_from" in d.field for d in r.defaults_applied)

    def test_fta_denied_when_origin_not_in_partners(self):
        # CN has no EU FTA — proof field is irrelevant, €3 applies silently
        c = Consignment(
            items=[make_item(origin="CN", fta=True, std_rate=0.12, fta_rate=0.0)],
            destination_ms="DE", ioss_registered=True,
            ship_from="CN",
            transaction_date=date(2026, 8, 1),
        )
        r = calculate(c)
        assert r.item_breakdown[0].regime == "e3_simplified"
        assert r.duty_total_eur == Decimal("3.00")

    def test_fta_denied_when_no_proof(self):
        # GB is an FTA partner but proof flag is False — €3 applies silently
        c = Consignment(
            items=[make_item(origin="GB", fta=False, std_rate=0.12, fta_rate=0.0)],
            destination_ms="DE", ioss_registered=True,
            ship_from="GB",
            transaction_date=date(2026, 8, 1),
        )
        r = calculate(c)
        assert r.item_breakdown[0].regime == "e3_simplified"
        assert r.duty_total_eur == Decimal("3.00")


# Phase logic --------------------------------------------------------------
class TestPhaseLogic:
    def test_pre_july_2026_uses_legacy_de_minimis(self):
        c = Consignment(items=[make_item(value=20)], destination_ms="DE",
                        ioss_registered=True,
                        transaction_date=date(2026, 6, 30))
        r = calculate(c)
        assert r.duty_total_eur == Decimal("0.00")  # legacy de minimis
        assert r.item_breakdown[0].regime == "pre_e3_de_minimis"

    def test_post_cdh_sunset_uses_standard(self):
        c = Consignment(items=[make_item(value=20, std_rate=0.12)],
                        destination_ms="DE", ioss_registered=True,
                        transaction_date=date(2028, 8, 1))
        assert calculate(c).item_breakdown[0].regime != "e3_simplified"


# VAT ----------------------------------------------------------------------
class TestVAT:
    def test_ioss_excludes_duty_from_base(self):
        c = Consignment(items=[make_item(value=100)], destination_ms="DE",
                        ioss_registered=True,
                        transaction_date=date(2026, 8, 1))
        r = calculate(c)
        assert r.vat.collected_via == "ioss_at_checkout"
        assert r.vat.vat_base_eur == Decimal("100.00")
        assert r.vat.vat_eur == Decimal("19.00")

    def test_special_arrangements_includes_duty(self):
        # Dir 2006/112 Art. 85/86: VAT base for non-IOSS imports =
        # CIF (intrinsic + shipping) + duty. Default postal shipping = €15.
        c = Consignment(items=[make_item(value=100, std_rate=0.10)],
                        destination_ms="DE", ioss_registered=False,
                        postal_designated_op=True,
                        shipping_cost_eur=Decimal("15.00"),
                        transaction_date=date(2026, 8, 1))
        r = calculate(c)
        assert r.vat.collected_via == "special_arrangements"
        # 100 (intrinsic) + 15 (shipping/CIF) + 3 (€3 simplified duty) = 118
        assert r.vat.vat_base_eur == Decimal("118.00")

    def test_standard_import_vat_includes_shipping_cif(self):
        # Standard import >€150, non-IOSS, non-postal. Per Dir 2006/112
        # Art. 85/86: VAT base = customs value (CIF) + duty. CIF includes
        # shipping to EU border, so shipping must be in the VAT base.
        c = Consignment(items=[make_item(value=200, std_rate=0.12)],
                        destination_ms="DE", ioss_registered=False,
                        shipping_cost_eur=Decimal("20.00"),
                        transaction_date=date(2026, 8, 1))
        r = calculate(c)
        assert r.vat.collected_via == "import_clearance"
        # Base = 200 (intrinsic) + 20 (shipping) + duty
        expected_base = Decimal("220.00") + r.duty_total_eur
        assert r.vat.vat_base_eur == expected_base

    def test_ioss_vat_excludes_shipping(self):
        # Reg 282/2011 Art. 5(1): IOSS taxable amount is intrinsic value
        # only — shipping is NOT in the VAT base even though it IS in CIF
        # for duty purposes. Regression for the CIF/VAT split.
        c = Consignment(items=[make_item(value=100)], destination_ms="DE",
                        ioss_registered=True,
                        shipping_cost_eur=Decimal("25.00"),
                        transaction_date=date(2026, 8, 1))
        r = calculate(c)
        assert r.vat.collected_via == "ioss_at_checkout"
        assert r.vat.vat_base_eur == Decimal("100.00")
        assert r.vat.vat_eur == Decimal("19.00")


# National fees ------------------------------------------------------------
class TestNationalFees:
    def test_france_per_hs6_line(self):
        c = Consignment(
            items=[
                make_item(hs6="610910", desc="tee"),
                make_item(hs6="640399", desc="shoe"),
            ],
            destination_ms="FR", ioss_registered=True,
            transaction_date=date(2026, 8, 1),
        )
        assert calculate(c).fees.national_fee_eur == Decimal("4.00")

    def test_italy_suspended_returns_zero_fee(self):
        """IT fee is suspended until 2026-07-01 — no fee before that date."""
        c = Consignment(
            items=[make_item(hs6="610910"), make_item(hs6="640399")],
            destination_ms="IT", ioss_registered=True,
            transaction_date=date(2026, 5, 1),
        )
        assert calculate(c).fees.national_fee_eur == Decimal("0.00")

    def test_italy_active_after_suspension_lift(self):
        """IT fee applies on and after 2026-07-01."""
        c = Consignment(
            items=[make_item(hs6="610910"), make_item(hs6="640399")],
            destination_ms="IT", ioss_registered=True,
            transaction_date=date(2026, 8, 1),
        )
        assert calculate(c).fees.national_fee_eur == Decimal("2.00")

    def test_romania_uses_490_not_5(self):
        """RO fee is €4.90 (25 RON at reference rate), not €5."""
        c = Consignment(
            items=[make_item(hs6="610910")],
            destination_ms="RO", ioss_registered=True,
            transaction_date=date(2026, 8, 1),
        )
        assert calculate(c).fees.national_fee_eur == Decimal("4.90")


# Declarant hierarchy ------------------------------------------------------
class TestDeclarant:
    def test_ioss_seller_is_declarant(self):
        c = Consignment(items=[make_item()], destination_ms="DE",
                        ioss_registered=True,
                        transaction_date=date(2026, 8, 1))
        assert calculate(c).declarant == "seller"

    def test_postal_operator_for_non_ioss_postal(self):
        c = Consignment(items=[make_item()], destination_ms="DE",
                        ioss_registered=False, postal_designated_op=True,
                        channel="postal",
                        transaction_date=date(2026, 8, 1))
        assert calculate(c).declarant == "postal_operator"

    def test_b2b_uses_agent(self):
        c = Consignment(items=[make_item()], destination_ms="DE",
                        b2b=True, transaction_date=date(2026, 8, 1))
        assert calculate(c).declarant == "agent"


# Compliance warnings ------------------------------------------------------
class TestWarnings:
    def test_product_id_warning_post_nov_2026(self):
        c = Consignment(items=[make_item()], destination_ms="DE",
                        ioss_registered=True,
                        transaction_date=date(2026, 12, 1))
        r = calculate(c)
        assert any("MISSING_PRODUCT_IDENTIFIERS" in w
                   for w in r.compliance_warnings)

    def test_product_id_warning_voluntary_period(self):
        c = Consignment(items=[make_item()], destination_ms="DE",
                        ioss_registered=True,
                        transaction_date=date(2026, 8, 1))
        r = calculate(c)
        assert any("voluntary 1 Jul" in w for w in r.compliance_warnings)

    def test_invalidation_warning_for_e3_path(self):
        c = Consignment(items=[make_item()], destination_ms="DE",
                        ioss_registered=True,
                        transaction_date=date(2026, 8, 1))
        r = calculate(c)
        assert any("Article 148(3)" in w for w in r.compliance_warnings)
