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


def _override_channel_shipping(
    new_c: Consignment, target_channel: str, original_channel: str
) -> None:
    """Apply a per-channel shipping override that respects shipping_model.

    Preserves a user-supplied shipping_cost_eur when the strategy keeps the
    SAME channel as the original consignment — the user's number is the
    source of truth for that channel. When the channel actually changes, the
    user's value (which described the original channel) no longer applies:
      flat_per_channel → swap to SHIPPING_COSTS_EUR[target_channel]
      percentage_demo  → clear to None so defaults recompute from value
    """
    if target_channel == original_channel and new_c.shipping_cost_eur is not None:
        return
    if new_c.shipping_model == "percentage_demo":
        new_c.shipping_cost_eur = None
    else:
        new_c.shipping_cost_eur = SHIPPING_COSTS_EUR[target_channel]


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
    # Postal lane → defer to shipping_model:
    #   flat_per_channel → SHIPPING_COSTS_EUR['postal'] (cheaper than express)
    #   percentage_demo  → recomputed from value, channel-agnostic
    _override_channel_shipping(new_c, "postal", c.channel)
    return Strategy(
        "drop_ioss_use_fta",
        "Drop IOSS, ship postal with FTA proof — bypasses €3 via DA Art. 1(1)(a) "
        "revised def (24), which excludes FTA goods from the postal-consignment "
        "definition. IOSS path (a) keeps €3 in play regardless of FTA, so leaving "
        "path (a) is the only way an FTA-eligible seller escapes €3.",
        calculate(new_c), 4,
        [
            "Requires valid proof of preferential origin (REX statement, EUR.1, etc.) "
            "AND direct transport from origin country (or non-alteration declaration).",
            "OPERATIONAL CAVEAT: 'postal' under DA 2015/2446 def (25) = UPU-designated "
            "national operators (Royal Mail, La Poste, Deutsche Post, etc.). The CN22/"
            "CN23 forms have no formal FTA proof field, and the H6 reduced dataset does "
            "not include REX/EUR.1 references. Whether the destination postal operator "
            "transmits an origin statement on the commercial invoice through to customs "
            "via H6 is inconsistent — in practice many postal shipments still get "
            "charged €3 even with FTA-eligible goods. Verify with destination posts "
            "before relying on this path. See _drop_ioss_use_express_fta for the more "
            "operationally reliable variant.",
            "Customer pays VAT on delivery — worse UX than IOSS at checkout.",
            "Special Arrangements regime for postal VAT collection sunsets 1 July 2028.",
        ],
    )


def _drop_ioss_use_express_fta(c: Consignment) -> Optional[Strategy]:
    """Operationally-preferred FTA bypass: drop IOSS, keep express, claim FTA.

    Neither €3 path fires:
      - Path (a) IOSS: not used → doesn't fire.
      - Path (b) postal per def (24): only UPU-designated operators count as
        "postal" under DA 2015/2446 def (25), so express is not path (b).
    Standard tariff applies; FTA preferential rate (often 0%) kicks in via
    the regular H1/H7 declaration, which accepts REX statement in its
    electronic dataset (unlike the postal H6 reduced dataset)."""
    if not all(
        it.origin.upper() in FTA_PARTNERS and it.fta_proof_held
        for it in c.items
    ):
        return None
    new_c = deepcopy(c)
    new_c.ioss_registered = False
    new_c.postal_designated_op = False
    new_c.channel = "express"
    _override_channel_shipping(new_c, "express", c.channel)
    return Strategy(
        "drop_ioss_use_express_fta",
        "Drop IOSS, ship express with REX statement — neither €3 path fires. "
        "Standard tariff at FTA preferential rate (often 0%). The H1/H7 electronic "
        "declaration carries REX/EUR.1 references reliably, unlike the postal H6 "
        "reduced dataset. Operationally the most realistic FTA bypass.",
        calculate(new_c), 4,
        [
            "Requires REX statement on commercial invoice or equivalent FTA proof "
            "for the destination MS customs to grant preference.",
            "Direct-transport requirement: ship_from == origin OR non_alteration "
            "declaration documented in the customs entry.",
            "Customer pays import VAT on delivery via broker — worse UX than IOSS, "
            "and broker fees are additional friction.",
            "Express shipping is typically pricier than postal — model the all-in "
            "landed cost, not just the duty saving.",
        ],
    )


def _drop_ioss_use_mfn(c: Consignment) -> Optional[Strategy]:
    """Drop IOSS, ship express → neither €3 path fires → standard MFN.

    Beats €3 whenever (MFN rate × line value) < €3 per line. Around half of
    EU HS codes have MFN ≤ 6%, so on low-value (≲ €50 / 6%) consignments the
    standard tariff is cheaper than the €3 flat. Gated only on 'currently
    using IOSS' — the calculator + sort decide whether it wins.
    """
    if not c.ioss_registered:
        return None
    new_c = deepcopy(c)
    new_c.ioss_registered = False
    new_c.postal_designated_op = False
    new_c.channel = "express"
    _override_channel_shipping(new_c, "express", c.channel)
    return Strategy(
        "drop_ioss_use_mfn",
        "Drop IOSS, ship express/courier — neither €3 path fires. Standard MFN "
        "tariff applies. Optimal for low-value goods on low-MFN HS codes "
        "(~51% of EU HS codes are ≤ 6%, where MFN × value beats the €3 flat "
        "below the break-even point of €3 / MFN rate).",
        calculate(new_c), 3,
        [
            "Customer pays import VAT on delivery (worse checkout UX vs. IOSS).",
            "Broker fees may apply on the express channel.",
            "Only optimal when standard MFN duty < €3 per line — advisor's "
            "ranking surfaces this automatically when it wins.",
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
    # Bulk import → consolidated freight rate (flat model) or value-based
    # demo cost. Under percentage_demo, the floored €1000 drives shipping.
    _override_channel_shipping(new_c, "general_cargo", c.channel)
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
        _drop_ioss_use_express_fta(c),
        _drop_ioss_use_mfn(c),
        _b2b_eu_warehouse(c),
    ]
    valid = [s for s in candidates if s is not None]
    valid.sort(key=lambda s: s.result.landed_cost_eur)
    return valid
