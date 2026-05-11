"""Tests for defaults — one test per row of PRD §3.2 table.

This file is the formal verification that the default behavior matches
the PRD. If you add a row to PRD §3.2, add a test here.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.schemas import Consignment, Item
from app.services.calculator import calculate
from app.services.defaults import apply_all_defaults


def make_item(**kw):
    defaults = dict(hs6="610910", description="cotton t-shirt",
                    origin="CN", qty=1, unit_value_eur=Decimal("20.00"),
                    standard_duty_rate=Decimal("0.12"))
    defaults.update(kw)
    return Item(**defaults)


# ---------------------------------------------------------------------------
# §3.2 row: transaction_date
# ---------------------------------------------------------------------------
def test_default_transaction_date_is_today():
    c = Consignment(items=[make_item()], destination_ms="DE",
                    transaction_date=None)
    c, ledger = apply_all_defaults(c)
    assert c.transaction_date == date.today()
    assert any(d.field == "transaction_date" for d in ledger)


# ---------------------------------------------------------------------------
# §3.2 row: consignment_value_eur
# ---------------------------------------------------------------------------
def test_default_consignment_value_summed_from_items():
    c = Consignment(
        items=[
            make_item(qty=2, unit_value_eur=Decimal("12.50")),
            make_item(hs6="640399", qty=1, unit_value_eur=Decimal("35.00")),
        ],
        destination_ms="DE",
        intrinsic_value_eur=None,
    )
    c, _ = apply_all_defaults(c)
    assert c.intrinsic_value_eur == Decimal("60.00")


# ---------------------------------------------------------------------------
# §3.2 row: b2b
# ---------------------------------------------------------------------------
def test_default_b2b_is_false():
    """When b2b is omitted (None), default to False with ledger entry."""
    c = Consignment(items=[make_item()], destination_ms="DE")  # b2b omitted
    c, ledger = apply_all_defaults(c)
    assert c.b2b is False
    assert any(d.field == "b2b" and d.default is False for d in ledger)


# ---------------------------------------------------------------------------
# §3.2 row: ioss_registered (the 93%-accuracy heuristic)
# ---------------------------------------------------------------------------
def test_default_ioss_true_for_b2c_low_value():
    c = Consignment(
        items=[make_item(unit_value_eur=Decimal("20"))],
        destination_ms="DE", ioss_registered=None, b2b=False,
    )
    c, ledger = apply_all_defaults(c)
    assert c.ioss_registered is True
    assert any(
        d.field == "ioss_registered" and "93%" in d.rationale for d in ledger
    )


def test_default_ioss_false_for_b2b():
    c = Consignment(
        items=[make_item(unit_value_eur=Decimal("20"))],
        destination_ms="DE", ioss_registered=None, b2b=True,
    )
    c, _ = apply_all_defaults(c)
    assert c.ioss_registered is False


def test_default_ioss_false_for_high_value():
    c = Consignment(
        items=[make_item(unit_value_eur=Decimal("200"))],
        destination_ms="DE", ioss_registered=None,
    )
    c, _ = apply_all_defaults(c)
    assert c.ioss_registered is False


def test_explicit_ioss_true_overridden_when_b2b():
    """PRD §3.3 edge case: B2B + IOSS=True → forced False with warning."""
    c = Consignment(
        items=[make_item(unit_value_eur=Decimal("20"))],
        destination_ms="DE", ioss_registered=True, b2b=True,
    )
    c, ledger = apply_all_defaults(c)
    assert c.ioss_registered is False
    assert any("OVERRIDE: B2B" in d.rationale for d in ledger)


def test_explicit_ioss_true_overridden_when_buyer_agent():
    c = Consignment(
        items=[make_item(unit_value_eur=Decimal("20"))],
        destination_ms="DE", ioss_registered=True, buyer_agent=True,
    )
    c, ledger = apply_all_defaults(c)
    assert c.ioss_registered is False
    assert any("buyer_agent" in d.rationale for d in ledger)


def test_explicit_ioss_true_overridden_when_value_exceeds_150():
    c = Consignment(
        items=[make_item(unit_value_eur=Decimal("200"))],
        destination_ms="DE", ioss_registered=True,
    )
    c, ledger = apply_all_defaults(c)
    assert c.ioss_registered is False
    assert any("> €150" in d.rationale for d in ledger)


def test_explicit_ioss_false_not_overridden_by_93pct_heuristic():
    """REGRESSION: when the caller explicitly says ioss_registered=False, the
    93% B2C-≤€150 heuristic must NOT flip it back to True.

    Without this, the 'Royal Mail GB→DE postal, no IOSS' scenario silently
    reports VAT (ioss_at_checkout) even though the seller is not IOSS-registered,
    which yields a wrong VAT base (value vs value+duty) and wrong declarant
    (seller vs postal_operator) on the H6 declaration.
    """
    c = Consignment(
        items=[make_item(unit_value_eur=Decimal("35"))],
        destination_ms="DE", ioss_registered=False, b2b=False,
    )
    c, ledger = apply_all_defaults(c)
    assert c.ioss_registered is False
    # The 93% heuristic must NOT have fired (no ledger entry for it).
    assert not any(
        d.field == "ioss_registered" and "93%" in d.rationale for d in ledger
    ), "93% heuristic must not override an explicit False"


def test_adapter_explicit_iossRegistered_false_round_trips():
    """REGRESSION: the avalara_adapter must carry an explicit
    `iossRegistered: false` from the payload through to the Consignment so the
    defaults engine sees `given=False` (not None).
    """
    from app.services.avalara_adapter import from_avalara_getquote
    payload = {
        "addresses": {"shipFrom": {"country": "GB"}, "shipTo": {"country": "DE"}},
        "date": "2026-08-01",
        "euReform2026": {
            "iossNumber": None,
            "iossRegistered": False,   # explicit no
            "shipmentChannel": "postal",
            "postalDesignatedOperator": True,
        },
        "customer": {"euReform2026": {"isBusinessBuyer": False}},
        "lines": [{"hsCode": "610910", "description": "tee", "countryOfOrigin": "GB",
                   "quantity": 1, "amount": 35}],
    }
    c = from_avalara_getquote(payload)
    assert c.ioss_registered is False, (
        "Adapter dropped the explicit iossRegistered=false signal — "
        "defaults engine would now run the 93% heuristic and flip it to True."
    )


def test_adapter_iossNumber_present_still_implies_true():
    """Legacy callers that only send `iossNumber` (no iossRegistered) must
    continue to be interpreted as IOSS-registered."""
    from app.services.avalara_adapter import from_avalara_getquote
    payload = {
        "addresses": {"shipFrom": {"country": "CN"}, "shipTo": {"country": "DE"}},
        "date": "2026-08-01",
        "euReform2026": {"iossNumber": "IM3720000123"},
        "lines": [{"hsCode": "610910", "description": "tee", "countryOfOrigin": "CN",
                   "quantity": 1, "amount": 20}],
    }
    c = from_avalara_getquote(payload)
    assert c.ioss_registered is True


# ---------------------------------------------------------------------------
# §3.2 row: buyer_agent
# ---------------------------------------------------------------------------
def test_default_buyer_agent_is_false():
    c = Consignment(items=[make_item()], destination_ms="DE", buyer_agent=False)
    c, ledger = apply_all_defaults(c)
    assert c.buyer_agent is False


# ---------------------------------------------------------------------------
# §3.2 row: postal_designated_op
# ---------------------------------------------------------------------------
def test_default_postal_designated_op_is_false():
    c = Consignment(items=[make_item()], destination_ms="DE",
                    postal_designated_op=False)
    c, ledger = apply_all_defaults(c)
    assert c.postal_designated_op is False


# ---------------------------------------------------------------------------
# §3.2 row: items[].origin
# ---------------------------------------------------------------------------
def test_default_origin_unknown_is_treated_as_non_fta():
    c = Consignment(
        items=[make_item(origin="UNKNOWN", fta_proof_held=True)],
        destination_ms="DE", ioss_registered=True,
        transaction_date=date(2026, 8, 1),
    )
    r = calculate(c)
    # UNKNOWN origin is not in FTA_PARTNERS → no FTA exclusion → €3 path
    assert r.item_breakdown[0].regime == "e3_simplified"
    assert r.duty_total_eur == Decimal("3.00")


# ---------------------------------------------------------------------------
# §3.2 row: items[].fta_proof_held
# ---------------------------------------------------------------------------
def test_default_fta_proof_held_is_false():
    c = Consignment(
        items=[make_item(origin="GB", fta_proof_held=False)],
        destination_ms="DE", ioss_registered=True,
        transaction_date=date(2026, 8, 1),
    )
    r = calculate(c)
    # GB is FTA partner but no proof held → still pays €3
    assert r.item_breakdown[0].regime == "e3_simplified"


# ---------------------------------------------------------------------------
# §3.2 row: items[].standard_duty_rate
# ---------------------------------------------------------------------------
def test_missing_tariff_rate_emits_warning():
    item = make_item(standard_duty_rate=Decimal("0.00"), fta_proof_held=False)
    c = Consignment(
        items=[item], destination_ms="DE", ioss_registered=False,
        transaction_date=date(2026, 8, 1),
    )
    r = calculate(c)
    assert any(
        d.field.startswith("items[0].standard_duty_rate")
        and "MISSING_TARIFF_RATE" in d.rationale
        for d in r.defaults_applied
    )


# ---------------------------------------------------------------------------
# §3.2 row: items[].description
# ---------------------------------------------------------------------------
def test_default_empty_description_is_unique_grouping_key():
    """Two items with no description should NOT collapse — they're distinct."""
    c = Consignment(
        items=[
            make_item(description="", hs6="610910"),
            make_item(description="", hs6="640399"),  # diff hs
        ],
        destination_ms="DE", ioss_registered=True,
        transaction_date=date(2026, 8, 1),
    )
    r = calculate(c)
    assert len(r.item_breakdown) == 2  # different HS keeps them apart anyway


def test_two_items_same_hs_empty_descriptions_collapse():
    """Same HS + same (empty) description + same origin → one grouping line."""
    c = Consignment(
        items=[
            make_item(description="", hs6="610910", origin="CN"),
            make_item(description="", hs6="610910", origin="CN"),
        ],
        destination_ms="DE", ioss_registered=True,
        transaction_date=date(2026, 8, 1),
    )
    r = calculate(c)
    assert len(r.item_breakdown) == 1  # collapse to one line, €3 once
    assert r.duty_total_eur == Decimal("3.00")


# ---------------------------------------------------------------------------
# §3.2 row: items[].qty
# ---------------------------------------------------------------------------
def test_default_qty_is_one():
    item = Item(hs6="610910", description="t", origin="CN")
    assert item.qty == 1


# ---------------------------------------------------------------------------
# Required field: destination_ms missing → 400
# ---------------------------------------------------------------------------
def test_missing_destination_raises():
    from app.services.avalara_adapter import from_avalara_getquote
    payload = {"lines": [{"hsCode": "610910", "quantity": 1, "amount": 20}]}
    with pytest.raises(ValueError, match="destination_ms"):
        from_avalara_getquote(payload)


# ---------------------------------------------------------------------------
# Required field: empty items → 400
# ---------------------------------------------------------------------------
def test_empty_items_raises():
    from app.services.avalara_adapter import from_avalara_getquote
    payload = {"addresses": {"shipTo": {"country": "DE"}}, "lines": []}
    with pytest.raises(ValueError, match="lines"):
        from_avalara_getquote(payload)


# ---------------------------------------------------------------------------
# §3.4: defaults_applied appears in response
# ---------------------------------------------------------------------------
def test_defaults_applied_in_response():
    c = Consignment(
        items=[make_item()], destination_ms="DE",
        ioss_registered=None, b2b=False, transaction_date=date(2026, 8, 1),
    )
    r = calculate(c)
    assert len(r.defaults_applied) > 0
    fields = [d.field for d in r.defaults_applied]
    assert "ioss_registered" in fields  # The 93% heuristic was used


def test_no_defaults_applied_when_all_explicit():
    """If caller supplies every field, ledger should be minimal."""
    c = Consignment(
        items=[make_item()], destination_ms="DE",
        ioss_registered=True, b2b=False, buyer_agent=False,
        postal_designated_op=False, transaction_date=date(2026, 8, 1),
        shipping_cost_eur=Decimal("15.00"),
    )
    r = calculate(c)
    # Item-level defaults may still emit (e.g. MISSING_TARIFF_RATE doesn't
    # trigger here because we provided 0.12); description is explicit.
    consignment_level_defaults = [
        d for d in r.defaults_applied
        if not d.field.startswith("items[")
    ]
    assert len(consignment_level_defaults) == 0
