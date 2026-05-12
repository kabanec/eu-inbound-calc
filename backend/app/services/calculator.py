"""Core duty + VAT + fees calculator.

Implements PRD §FR-1 decision tree:

  1. Phase: date >= 2028-07-01 → standard tariff (CDH live)
  2. Hard exits to standard tariff: value > €150, b2b, buyer_agent
  3. Per-item FTA exclusion (DA Art. 1(1)(a)) + direct-transport gate:
       fta_proof_held AND origin ∈ FTA partners
       AND (ship_from == origin OR non_alteration_confirmed)
       → standard_tariff_fta; otherwise fall through.
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
from .avalara_client import get_quote, zero_line
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
    ship_from: str | None = None, non_alteration_confirmed: bool = False,
) -> Regime:
    if not e3_active:
        return _standard_or_fta(item, ship_from=ship_from, non_alteration_confirmed=non_alteration_confirmed)
    if not consignment_low_value or b2b or buyer_agent:
        return _standard_or_fta(item, ship_from=ship_from, non_alteration_confirmed=non_alteration_confirmed)
    if item.fta_proof_held and item.origin.upper() in FTA_PARTNERS:
        # Direct-transport gate: importer-burden default is denial.
        # FTA granted only when ship_from == origin OR non_alteration_confirmed.
        if ship_from is not None and (
            ship_from.upper() == item.origin.upper() or non_alteration_confirmed
        ):
            return "standard_tariff_fta"
        # Gate failed — fall through to €3 trigger below.
    if ioss or postal:
        return "e3_simplified"
    return _standard_or_fta(item, ship_from=ship_from, non_alteration_confirmed=non_alteration_confirmed)


def _standard_or_fta(
    item: Item,
    *,
    ship_from: str | None = None,
    non_alteration_confirmed: bool = False,
) -> Regime:
    if item.fta_proof_held and item.origin.upper() in FTA_PARTNERS:
        if ship_from is not None and (
            ship_from.upper() == item.origin.upper() or non_alteration_confirmed
        ):
            return "standard_tariff_fta"
    if item.standard_duty_rate == 0:
        return "no_duty"
    return "standard_tariff"



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
        if nf.get("suspended_until") and c.transaction_date < nf["suspended_until"]:
            return fees
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
        # IOSS taxable amount is intrinsic-only per Reg 282/2011 Art. 5(1)
        # and Dir 2006/112 Art. 369y. Shipping is NOT in the VAT base even
        # though it IS in the customs (CIF) value for duty purposes.
        base = c.intrinsic_value_eur
        return VATBreakdown(
            vat_rate=rate, vat_base_eur=_round(base),
            vat_eur=_round(base * rate), collected_via="ioss_at_checkout",
        )
    # Non-IOSS: Dir 2006/112 Art. 85/86 — VAT base = customs value (CIF) + duty
    # + incidental expenses up to first destination. CIF already includes
    # shipping to the EU border, so we add shipping_cost_eur explicitly here.
    shipping = c.shipping_cost_eur or Decimal("0.00")
    base = c.intrinsic_value_eur + shipping + duty_total
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
    """Compute landed cost. Applies defaults first, then runs decision tree.

    Avalara getQuote is called for every consignment and is authoritative for
    duty figures. The €3 simplified regime overrides Avalara when triggered.
    Raises AvalaraError (propagates to route → 502) on API failure.
    """
    c, ledger = apply_all_defaults(c)

    ava_resp = get_quote(c)
    line_map = {lr.line_number: lr for lr in ava_resp.line_results}

    # Map each item's 0-based position to its grouping key so we can sum
    # Avalara duty across all individual lines that belong to the same group.
    group_indices: dict[tuple, list[int]] = defaultdict(list)
    for idx, item in enumerate(c.items):
        group_indices[item.grouping_key].append(idx)

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

        # Avalara duty for the whole group (sum of individual item lines).
        indices = group_indices[key]
        ava_lines = [line_map.get(idx + 1, zero_line(idx + 1)) for idx in indices]
        ava_group_duty = sum((l.duty_eur for l in ava_lines), Decimal("0.00"))
        ava_rep = ava_lines[0]

        agg = Item(
            hs6=rep.hs6, description=rep.description, origin=rep.origin,
            qty=qty_total,
            unit_value_eur=line_value / qty_total if qty_total else Decimal("0.00"),
            fta_proof_held=rep.fta_proof_held,
            standard_duty_rate=rep.standard_duty_rate,
            fta_duty_rate=rep.fta_duty_rate,
        )

        if pre_e3:
            if c.intrinsic_value_eur <= LOW_VALUE_THRESHOLD_EUR:
                regime: Regime = "pre_e3_de_minimis"
                duty = Decimal("0.00")
            else:
                regime = "standard_tariff"
                duty = ava_group_duty
        else:
            regime = _resolve_item_regime(
                agg, consignment_low_value=(c.intrinsic_value_eur <= LOW_VALUE_THRESHOLD_EUR),
                b2b=c.b2b, buyer_agent=c.buyer_agent,
                ioss=c.ioss_registered, postal=c.postal_designated_op,
                e3_active=e3_active,
                ship_from=c.ship_from,
                non_alteration_confirmed=c.non_alteration_confirmed,
            )
            if regime == "e3_simplified":
                duty = E3_PER_ITEM_EUR
            elif regime in ("standard_tariff", "standard_tariff_fta"):
                duty = ava_group_duty
            else:
                duty = Decimal("0.00")

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
            avalara_rate=ava_rep.duty_rate,
            avalara_is_preferential=ava_rep.is_preferential,
            avalara_details=ava_rep.duty_details,
        ))

    fees = _calculate_fees(c, distinct_groups=len(groups))

    # If Avalara returned a CCF (administrative fee), use it as the national fee
    # — it is more accurate than our lookup table for FR/IT/RO.
    # IT suspension guard: only override when the fee is actually live.
    if ava_resp.national_fee_eur > Decimal("0.00"):
        nf_data = NATIONAL_FEES.get(c.destination_ms)
        suspended = (
            nf_data is not None
            and nf_data.get("suspended_until") is not None
            and c.transaction_date < nf_data["suspended_until"]
        )
        if not suspended:
            fees.national_fee_eur = ava_resp.national_fee_eur
            fees.national_fee_source = "Customs administrative fee"

    vat = _calculate_vat(c, duty_total, fees)

    shipping = c.shipping_cost_eur or Decimal("0.00")
    landed = (
        c.intrinsic_value_eur + duty_total
        + fees.union_handling_fee_eur + fees.national_fee_eur
        + vat.vat_eur + shipping
    )

    return CalculationResult(
        consignment_value_eur=_round(c.intrinsic_value_eur),
        duty_total_eur=_round(duty_total),
        item_breakdown=breakdown,
        fees=fees, vat=vat,
        declaration_type=_resolve_declaration_type(c),
        declarant=_resolve_declarant(c),
        shipping_cost_eur=_round(shipping),
        landed_cost_eur=_round(landed),
        defaults_applied=ledger,
        compliance_warnings=_compliance_warnings(c, regimes_seen),
        legal_references=[
            "Council Regulation (EU) 2026/382 of 11 February 2026",
            "Commission Delegated Regulation C(2026)2760 of 30 April 2026",
            "Council Directive 2006/112/EC, Articles 14(4), 85, 143(1)(ca)",
            "UCC Regulation (EU) 952/2013, Article 77",
        ],
        avalara_request_id=ava_resp.request_id,
        avalara_total_eur=ava_resp.total_duty_eur,
        avalara_national_fee_eur=ava_resp.national_fee_eur,
        avalara_messages=ava_resp.messages,
    )
