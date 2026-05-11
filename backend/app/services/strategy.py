"""Shipping strategy advisor — ranks alternatives by landed cost."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ..models.schemas import CalculationResult, Consignment
from ..reference.data import (
    FTA_PARTNERS, LOW_VALUE_THRESHOLD_EUR, SHIPPING_COSTS_EUR,
)
from .calculator import calculate, group_items
from .defaults import apply_all_defaults


@dataclass
class Strategy:
    name: str
    description: str
    result: CalculationResult
    complexity: int
    risk_notes: list[str]


def _status_quo(c: Consignment) -> Strategy:
    return Strategy(
        "status_quo", "Ship as currently configured.",
        calculate(deepcopy(c)), 1, [],
    )


def _force_above_150(c: Consignment) -> Optional[Strategy]:
    # Defensive: if intrinsic_value_eur is None (i.e. defaults haven't been
    # applied), compute it from line items so the gate still works.
    actual_value = c.intrinsic_value_eur
    if actual_value is None:
        actual_value = sum((i.line_value_eur for i in c.items), Decimal("0"))
    if actual_value > LOW_VALUE_THRESHOLD_EUR:
        return None
    new_c = deepcopy(c)
    new_c.intrinsic_value_eur = LOW_VALUE_THRESHOLD_EUR + Decimal("0.01")
    return Strategy(
        "push_above_150",
        "Push consignment value above €150 to use standard tariff instead of €3 per item.",
        calculate(new_c), 3,
        [
            "Requires merchandising change (filler item or upsell).",
            "Triggers H1 declaration with full data requirements.",
            "Loses H7 simplification.",
        ],
    )


def _split_parcels(c: Consignment) -> Strategy:
    groups = group_items(c.items)
    sub_results = []
    total_landed = Decimal("0.00")
    total_duty = Decimal("0.00")
    total_shipping = Decimal("0.00")
    for _, items in groups.items():
        sub = deepcopy(c)
        sub.items = deepcopy(items)
        sub.intrinsic_value_eur = sum(
            (i.line_value_eur for i in items), Decimal("0.00")
        )
        # Force per-parcel modeled shipping (don't carry parent's bundled cost).
        sub.shipping_cost_eur = None
        r = calculate(sub)
        sub_results.append(r)
        total_landed += r.landed_cost_eur
        total_duty += r.duty_total_eur
        total_shipping += r.shipping_cost_eur

    n_parcels = len(sub_results)
    head = sub_results[0]
    head.duty_total_eur = total_duty
    head.landed_cost_eur = total_landed
    head.shipping_cost_eur = total_shipping
    # Replace head's per-parcel single-line value with the SUM across all parcels
    # so the rendered "consignment value" matches the rendered total cost.
    head.consignment_value_eur = sum(
        (r.consignment_value_eur for r in sub_results), Decimal("0.00")
    )
    head.compliance_warnings.append(
        f"Split into {n_parcels} parcels — values, duties, shipping and totals are summed across parcels."
    )
    return Strategy(
        "split_parcels",
        "One parcel per HS6+description+origin group. Almost always worse than consolidation.",
        head, 4,
        [
            "Multiplies handling fees and Union handling fee.",
            "Higher fulfillment cost.",
            "Included for comparison; rarely optimal.",
        ],
    )


def _consolidate_descriptions(c: Consignment) -> Strategy:
    new_c = deepcopy(c)
    by_hs_origin: dict[tuple, str] = {}
    for it in new_c.items:
        key = (it.hs6, it.origin.upper())
        if key not in by_hs_origin:
            by_hs_origin[key] = it.description
        else:
            it.description = by_hs_origin[key]
    return Strategy(
        "consolidate_descriptions",
        "Normalize descriptions so items sharing HS6+origin collapse to one grouping line.",
        calculate(new_c), 2,
        [
            "Description must remain ACCURATE — no over-genericization.",
            "EU customs may challenge an inadequate description.",
            "Best applied at catalog/PIM layer pre-shipment.",
        ],
    )


def _drop_ioss_use_fta(c: Consignment) -> Optional[Strategy]:
    if not all(
        it.origin.upper() in FTA_PARTNERS and it.fta_proof_held
        for it in c.items
    ):
        return None
    new_c = deepcopy(c)
    new_c.ioss_registered = False
    new_c.postal_designated_op = True
    new_c.channel = "postal"
    # Postal lane → re-derive shipping from postal table (cheaper than express).
    new_c.shipping_cost_eur = SHIPPING_COSTS_EUR["postal"]
    return Strategy(
        "drop_ioss_use_fta",
        "Postal non-IOSS with FTA preference — €3 bypassed; standard tariff (often 0%).",
        calculate(new_c), 4,
        [
            "Requires valid proof of preferential origin (REX, EUR.1, etc.).",
            "Customer pays VAT on delivery — worse UX than IOSS at checkout.",
            "Special arrangements regime sunsets 1 July 2028.",
        ],
    )


def _b2b_eu_warehouse(c: Consignment) -> Strategy:
    new_c = deepcopy(c)
    new_c.b2b = True
    new_c.ioss_registered = False
    new_c.channel = "general_cargo"
    new_c.intrinsic_value_eur = max(
        new_c.intrinsic_value_eur or Decimal("0.00"), Decimal("1000.00")
    )
    # Bulk import → consolidated freight rate, not per-parcel express.
    new_c.shipping_cost_eur = SHIPPING_COSTS_EUR["general_cargo"]
    return Strategy(
        "b2b_eu_warehouse",
        "Bulk B2B import + EU domestic fulfillment. €3 fully out; standard tariff once at scale.",
        calculate(new_c), 5,
        [
            "Requires EU warehouse capacity (currently constrained).",
            "Working capital tied up in inventory.",
            "Shifts to OSS VAT for intra-EU distance sales.",
            "EU policy direction explicitly favors this model.",
        ],
    )


def recommend(c: Consignment) -> list[Strategy]:
    # Apply defaults first so every strategy gate sees a populated
    # intrinsic_value_eur. Otherwise gates like `_force_above_150` that
    # check `c.intrinsic_value_eur > 150` silently fail on None.
    c, _ = apply_all_defaults(c)
    candidates = [
        _status_quo(c),
        _consolidate_descriptions(c),
        _split_parcels(c),
        _force_above_150(c),
        _drop_ioss_use_fta(c),
        _b2b_eu_warehouse(c),
    ]
    valid = [s for s in candidates if s is not None]
    valid.sort(key=lambda s: s.result.landed_cost_eur)
    return valid
