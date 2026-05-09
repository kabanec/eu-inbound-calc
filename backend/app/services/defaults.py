"""Centralized default-resolution logic.

This module is the SINGLE SOURCE OF TRUTH for fallback behavior. Every
rule in PRD §3.2 lives here. Changes to defaults MUST be made here and
nowhere else.

Each `apply_*` function:
  1. Takes the partial input
  2. Returns the resolved value
  3. Appends to a `defaults_applied` ledger so the response can audit
     which defaults were used

Tests in tests/test_defaults.py cover each rule explicitly.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from ..models.schemas import Consignment, DefaultApplied, Item
from ..reference.data import LOW_VALUE_THRESHOLD_EUR


# ---------------------------------------------------------------------------
# Consignment-level defaults
# ---------------------------------------------------------------------------
def resolve_transaction_date(
    given: Optional[date], ledger: list[DefaultApplied],
) -> date:
    if given is not None:
        return given
    today = date.today()
    ledger.append(DefaultApplied(
        field="transaction_date",
        default=today.isoformat(),
        rationale="Server clock — caller did not specify a date",
    ))
    return today


def resolve_b2b(given: Optional[bool], ledger: list[DefaultApplied]) -> bool:
    if given is not None:
        return given
    ledger.append(DefaultApplied(
        field="b2b",
        default=False,
        rationale="Default to B2C distance sale (~85% of getQuote inbound EU population)",
    ))
    return False


def resolve_ioss_registered(
    given: Optional[bool], *, b2b: bool, value_eur: Decimal,
    buyer_agent: bool, ledger: list[DefaultApplied],
) -> bool:
    """93%-accuracy heuristic for the IOSS flag.

    Hard overrides:
    - B2B → IOSS impossible (VAT Directive Art. 369l is B2C-only)
    - Value > €150 → IOSS cap exceeded
    - Buyer agent → distance-sale construct broken
    """
    if b2b:
        if given is True:
            ledger.append(DefaultApplied(
                field="ioss_registered",
                default=False,
                rationale="OVERRIDE: B2B set → IOSS impossible (VAT Dir Art. 369l)",
            ))
        return False
    if buyer_agent:
        if given is True:
            ledger.append(DefaultApplied(
                field="ioss_registered",
                default=False,
                rationale="OVERRIDE: buyer_agent breaks distance-sale construct",
            ))
        return False
    if value_eur > LOW_VALUE_THRESHOLD_EUR:
        if given is True:
            ledger.append(DefaultApplied(
                field="ioss_registered",
                default=False,
                rationale="OVERRIDE: value > €150 → IOSS cap exceeded",
            ))
        return False

    if given is not None:
        return given
    # Council 93% statistic for B2C low-value
    ledger.append(DefaultApplied(
        field="ioss_registered",
        default=True,
        rationale="93% of B2C ≤€150 EU imports are IOSS-registered (Council 2025-12-12)",
    ))
    return True


def resolve_buyer_agent(
    given: Optional[bool], ledger: list[DefaultApplied],
) -> bool:
    if given is not None:
        return given
    ledger.append(DefaultApplied(
        field="buyer_agent",
        default=False,
        rationale="Default to direct distance sale (forwarders <2% of e-commerce)",
    ))
    return False


def resolve_postal_designated_op(
    given: Optional[bool], ledger: list[DefaultApplied],
) -> bool:
    if given is not None:
        return given
    ledger.append(DefaultApplied(
        field="postal_designated_op",
        default=False,
        rationale="Default to commercial channel (postal share ~25% and decreasing)",
    ))
    return False


# ---------------------------------------------------------------------------
# Item-level defaults
# ---------------------------------------------------------------------------
def resolve_item(
    item: Item, *, line_index: int, ledger: list[DefaultApplied],
) -> Item:
    """Apply line-level defaults in place; return the same item.

    Each missing field appends a `DefaultApplied` entry indexed by line.
    """
    if item.origin == "UNKNOWN" or not item.origin:
        item.origin = "UNKNOWN"
        ledger.append(DefaultApplied(
            field=f"items[{line_index}].origin",
            default="UNKNOWN",
            rationale="Unknown origin treated as non-FTA (conservative)",
        ))

    if item.fta_proof_held is False and item.origin == "UNKNOWN":
        # No proof + unknown origin = no FTA path possible. No ledger entry
        # needed since there's nothing to default.
        pass

    if item.standard_duty_rate == Decimal("0.00") and not item.fta_proof_held:
        ledger.append(DefaultApplied(
            field=f"items[{line_index}].standard_duty_rate",
            default=0.00,
            rationale=(
                "MISSING_TARIFF_RATE — caller did not supply MFN rate. "
                "Result is unreliable for non-€3 path."
            ),
        ))

    if not item.description:
        ledger.append(DefaultApplied(
            field=f"items[{line_index}].description",
            default="",
            rationale="Empty description — line will be its own grouping key",
        ))

    return item


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------
def apply_all_defaults(c: Consignment) -> tuple[Consignment, list[DefaultApplied]]:
    """Return (consignment_with_defaults, ledger).

    Order matters: B2B must be resolved before IOSS, since IOSS depends on B2B.
    """
    ledger: list[DefaultApplied] = []

    # Date first — phase logic depends on it
    c.transaction_date = resolve_transaction_date(
        c.transaction_date if c.transaction_date else None, ledger,
    )

    # B2B before IOSS
    c.b2b = resolve_b2b(c.b2b, ledger)
    c.buyer_agent = resolve_buyer_agent(c.buyer_agent, ledger)
    c.postal_designated_op = resolve_postal_designated_op(
        c.postal_designated_op, ledger,
    )

    # Items before IOSS (need value)
    for idx, item in enumerate(c.items):
        resolve_item(item, line_index=idx, ledger=ledger)

    # Recompute intrinsic value after item defaults
    if c.intrinsic_value_eur is None:
        c.intrinsic_value_eur = sum(
            (it.line_value_eur for it in c.items), Decimal("0.00")
        )

    # IOSS last — depends on B2B, value, buyer_agent
    c.ioss_registered = resolve_ioss_registered(
        c.ioss_registered, b2b=c.b2b, value_eur=c.intrinsic_value_eur,
        buyer_agent=c.buyer_agent, ledger=ledger,
    )

    return c, ledger
