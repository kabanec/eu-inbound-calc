"""Core duty + VAT + fees calculator.

Implements PRD §FR-1 decision tree:

  1. Phase: date >= 2028-07-01 → standard tariff (CDH live)
  2. Hard exits to standard tariff: value > €150, b2b, buyer_agent
  3. Per item: FTA exclusion (origin ∈ FTA partners + fta_proof_held)
  4. €3 trigger: ioss_registered OR postal_designated_op
  5. Else: standard tariff with special-arrangements VAT
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from ..models.schemas import (
    CalculationResult, Consignment, DeclarationType, Declarant,
    FeeBreakdown, Item, ItemBreakdown, Regime, VATBreakdown,
)
from ..reference.data import (
    DATE_E3_START, DATE_E3_SUNSET, DATE_PRODUCT_ID_MANDATORY,
    DATE_UNION_HANDLING_FEE, E3_PER_ITEM_EUR, FTA_PARTNERS,
    LOW_VALUE_THRESHOLD_EUR, NATIONAL_FEES, UNION_HANDLING_FEE_EUR, VAT_RATES,
)
from .defaults import apply_all_defaults

CENT = Decimal("0.01")


def _round(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def group_items(items: list[Item]) -> dict[tuple, list[Item]]:
    groups: dict[tuple, list[Item]] = defaultdict(list)
    for item in items:
        groups[item.grouping_key].append(item)
    return dict(groups)


def _resolve_item_regime(
    item: Item, *, consignment_low_value: bool, b2b: bool,
    buyer_agent: bool, ioss: bool, postal: bool, e3_active: bool,
) -> Regime:
    if not e3_active:
        return _standard_or_fta(item)
    if not consignment_low_value or b2b or buyer_agent:
        return _standard_or_fta(item)
    if item.fta_proof_held and item.origin.upper() in FTA_PARTNERS:
        return "standard_tariff_fta"
    if ioss or postal:
        return "e3_simplified"
    return _standard_or_fta(item)


def _standard_or_fta(item: Item) -> Regime:
    if item.fta_proof_held and item.origin.upper() in FTA_PARTNERS:
        return "standard_tariff_fta"
    if item.standard_duty_rate == 0:
        return "no_duty"
    return "standard_tariff"


def _item_duty(item: Item, regime: Regime) -> Decimal:
    if regime == "e3_simplified":
        return E3_PER_ITEM_EUR
    if regime == "standard_tariff_fta":
        return _round(item.line_value_eur * item.fta_duty_rate)
    if regime == "standard_tariff":
        return _round(item.line_value_eur * item.standard_duty_rate)
    return Decimal("0.00")


def _resolve_declarant(c: Consignment) -> Declarant:
    if c.b2b or c.buyer_agent:
        return "agent"
    if c.ioss_registered:
        return "seller"
    if c.postal_designated_op:
        return "postal_operator"
    if c.channel == "express":
        return "carrier"
    return "consumer"


def _resolve_declaration_type(c: Consignment) -> DeclarationType:
    if c.intrinsic_value_eur > LOW_VALUE_THRESHOLD_EUR:
        return "H1"
    if c.postal_designated_op:
        return "H6"
    return "H7"


def _calculate_fees(c: Consignment, distinct_groups: int) -> FeeBreakdown:
    fees = FeeBreakdown()
    if c.transaction_date >= DATE_UNION_HANDLING_FEE:
        fees.union_handling_fee_eur = UNION_HANDLING_FEE_EUR

    nf = NATIONAL_FEES.get(c.destination_ms)
    if nf and c.transaction_date >= nf["since"]:
        if nf["basis"] == "per_hs6_line":
            fees.national_fee_eur = nf["amount_eur"] * Decimal(distinct_groups)
        else:
            fees.national_fee_eur = nf["amount_eur"]
        fees.national_fee_source = nf["source"]

    return fees


def _calculate_vat(
    c: Consignment, duty_total: Decimal, fees: FeeBreakdown,
) -> VATBreakdown:
    rate = VAT_RATES.get(c.destination_ms, Decimal("0.20"))
    if c.b2b:
        return VATBreakdown(
            vat_rate=rate, vat_base_eur=Decimal("0.00"),
            vat_eur=Decimal("0.00"), collected_via="oss_b2b",
        )
    if c.ioss_registered:
        base = c.intrinsic_value_eur
        return VATBreakdown(
            vat_rate=rate, vat_base_eur=_round(base),
            vat_eur=_round(base * rate), collected_via="ioss_at_checkout",
        )
    base = c.intrinsic_value_eur + duty_total
    if c.postal_designated_op:
        return VATBreakdown(
            vat_rate=rate, vat_base_eur=_round(base),
            vat_eur=_round(base * rate), collected_via="special_arrangements",
        )
    return VATBreakdown(
        vat_rate=rate, vat_base_eur=_round(base),
        vat_eur=_round(base * rate), collected_via="import_clearance",
    )


def _compliance_warnings(c: Consignment, regimes: list[Regime]) -> list[str]:
    w: list[str] = []
    if c.transaction_date < DATE_E3_START:
        w.append(
            "Pre-€3 regime: standard tariff with €150 de minimis still applicable. "
            "EU 2026 reform fields ignored."
        )
    if c.transaction_date >= DATE_PRODUCT_ID_MANDATORY:
        # Check if any item is missing identifiers
        if any(
            (it.merchant_id is None and it.manufacturer_id is None and it.gtin is None)
            for it in c.items
        ):
            w.append(
                "MISSING_PRODUCT_IDENTIFIERS — DA C(2026)2760 requires merchant ID, "
                "manufacturer ID, or GTIN per item from 1 Nov 2026."
            )
    elif c.transaction_date >= DATE_E3_START:
        w.append(
            "Product identifiers voluntary 1 Jul – 31 Oct 2026, mandatory from 1 Nov 2026."
        )
    if "e3_simplified" in regimes and c.intrinsic_value_eur <= LOW_VALUE_THRESHOLD_EUR:
        w.append(
            "Article 148(3) invalidation facilitation does NOT apply to distance "
            "sales ≤ €150 (DA point 12) — returns require standard customs procedure."
        )
    return w


def calculate(c: Consignment) -> CalculationResult:
    """Compute landed cost. Applies defaults first, then runs decision tree."""
    c, ledger = apply_all_defaults(c)

    e3_active = DATE_E3_START <= c.transaction_date < DATE_E3_SUNSET
    pre_e3 = c.transaction_date < DATE_E3_START

    groups = group_items(c.items)
    breakdown: list[ItemBreakdown] = []
    duty_total = Decimal("0.00")
    regimes_seen: list[Regime] = []

    for key, group_items_list in groups.items():
        rep = group_items_list[0]
        qty_total = sum(i.qty for i in group_items_list)
        line_value = sum(
            (i.line_value_eur for i in group_items_list), Decimal("0.00")
        )
        agg = Item(
            hs6=rep.hs6, description=rep.description, origin=rep.origin,
            qty=qty_total,
            unit_value_eur=line_value / qty_total if qty_total else Decimal("0.00"),
            fta_proof_held=rep.fta_proof_held,
            standard_duty_rate=rep.standard_duty_rate,
            fta_duty_rate=rep.fta_duty_rate,
        )

        if pre_e3:
            # Pre-July 2026: legacy de minimis still in force for ≤ €150
            if c.intrinsic_value_eur <= LOW_VALUE_THRESHOLD_EUR:
                regime: Regime = "pre_e3_de_minimis"
                duty = Decimal("0.00")
            else:
                regime = "standard_tariff"
                duty = _round(line_value * agg.standard_duty_rate)
        else:
            regime = _resolve_item_regime(
                agg, consignment_low_value=(c.intrinsic_value_eur <= LOW_VALUE_THRESHOLD_EUR),
                b2b=c.b2b, buyer_agent=c.buyer_agent,
                ioss=c.ioss_registered, postal=c.postal_designated_op,
                e3_active=e3_active,
            )
            duty = _item_duty(agg, regime)

        duty_total += duty
        regimes_seen.append(regime)

        notes: list[str] = []
        if regime == "standard_tariff_fta":
            notes.append(
                f"FTA preference applied (origin {agg.origin}); "
                f"€3 EXCLUDED per DA Art. 1(1)(a)."
            )
        if regime == "e3_simplified" and qty_total > 1:
            notes.append(
                f"€3 charged once for {qty_total} units sharing identical "
                f"(HS, desc, origin) tuple."
            )

        breakdown.append(ItemBreakdown(
            grouping_key=key, qty_total=qty_total,
            line_value_eur=_round(line_value), regime=regime,
            duty_eur=duty, notes=notes,
        ))

    fees = _calculate_fees(c, distinct_groups=len(groups))
    vat = _calculate_vat(c, duty_total, fees)

    landed = (
        c.intrinsic_value_eur + duty_total
        + fees.union_handling_fee_eur + fees.national_fee_eur
        + vat.vat_eur
    )

    return CalculationResult(
        consignment_value_eur=_round(c.intrinsic_value_eur),
        duty_total_eur=_round(duty_total),
        item_breakdown=breakdown,
        fees=fees, vat=vat,
        declaration_type=_resolve_declaration_type(c),
        declarant=_resolve_declarant(c),
        landed_cost_eur=_round(landed),
        defaults_applied=ledger,
        compliance_warnings=_compliance_warnings(c, regimes_seen),
        legal_references=[
            "Council Regulation (EU) 2026/382 of 11 February 2026",
            "Commission Delegated Regulation C(2026)2760 of 30 April 2026",
            "Council Directive 2006/112/EC, Articles 14(4), 85, 143(1)(ca)",
            "UCC Regulation (EU) 952/2013, Article 77",
        ],
    )
