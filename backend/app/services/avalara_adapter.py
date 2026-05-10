"""Avalara getQuote payload adapter.

Maps an Avalara cross-border `getQuote`-style request to the internal
`Consignment` model. Accepts both:

  - Pure legacy getQuote (no `euReform2026` namespaces)
  - Extended payload with surgical EU-2026 fields per BRD §3

See docs/samples/ for example payloads.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from ..models.schemas import Consignment, Item


def from_avalara_getquote(payload: dict[str, Any]) -> Consignment:
    """Translate Avalara getQuote payload → internal Consignment.

    Robustness: missing fields fall back to empty strings / None / [] so
    the defaults engine in services/defaults.py can apply business rules
    in one place.
    """
    addresses = payload.get("addresses", {})
    if not isinstance(addresses, dict):
        addresses = {}
    ship_to = addresses.get("shipTo", {}) or {}
    ship_from_raw = (addresses.get("shipFrom", {}) or {}).get("country")
    destination = (ship_to.get("country") or payload.get("destination_ms") or "").upper()
    if not destination:
        raise ValueError("destination_ms (or addresses.shipTo.country) is required")

    txn_date_raw = payload.get("date") or payload.get("transaction_date")
    txn_date = date.fromisoformat(txn_date_raw) if txn_date_raw else date.today()

    eu_ext = payload.get("euReform2026", {}) or {}
    customer = payload.get("customer", {}) or {}
    customer_eu_ext = customer.get("euReform2026", {}) or {}

    # B2B inference: explicit isBusinessBuyer wins; otherwise vatNumber presence
    is_business = customer_eu_ext.get("isBusinessBuyer")
    vat_number = customer_eu_ext.get("vatNumber")
    if is_business is None and vat_number:
        is_business = True

    # IOSS inference: explicit iossNumber presence implies IOSS-registered
    ioss_number = eu_ext.get("iossNumber") or eu_ext.get("platformIossNumber")
    ioss_registered = True if ioss_number else None  # None lets defaults engine decide

    default_origin = ship_from_raw.upper() if ship_from_raw else None
    items = [_item_from_line(line, default_origin=default_origin)
             for line in payload.get("lines", [])]
    if not items:
        raise ValueError("lines[] must contain at least one line item")

    # Pass None for omitted boolean flags so the defaults engine can log them.
    # Only assign explicit True/False if the payload actually contained the field.
    return Consignment(
        items=items,
        destination_ms=destination,
        b2b=bool(is_business) if is_business is not None else None,
        ioss_registered=ioss_registered,
        buyer_agent=eu_ext["buyerAgent"] if "buyerAgent" in eu_ext else None,
        incoterm=payload.get("shippingTerms"),
        channel=eu_ext.get("shipmentChannel", "express"),
        postal_designated_op=(
            eu_ext["postalDesignatedOperator"]
            if "postalDesignatedOperator" in eu_ext else None
        ),
        ship_from=ship_from_raw.upper() if ship_from_raw else None,
        non_alteration_confirmed=bool(eu_ext.get("nonAlterationConfirmed", False)),
        transaction_date=txn_date if txn_date_raw else None,
        avalara_doc_code=payload.get("code"),
        customer_vat_number=vat_number,
    )


def _item_from_line(line: dict[str, Any], *, default_origin: str | None = None) -> Item:
    eu_ext = line.get("euReform2026", {}) or {}
    pid = eu_ext.get("productIdentifiers", {}) or {}

    # Avalara uses `hsCode`; we normalize to 6 digits
    hs_code = str(line.get("hsCode") or line.get("hs6") or "").replace(".", "")
    hs6 = hs_code[:6] if hs_code else ""

    qty = int(line.get("quantity") or line.get("qty") or 1)
    amount = line.get("amount")
    if amount is not None:
        unit_value = Decimal(str(amount)) / Decimal(qty) if qty else Decimal("0.00")
    else:
        unit_value = Decimal(str(line.get("unit_value_eur", 0)))

    fta_proof = bool(eu_ext.get("ftaProofType"))

    # COO defaults to consignment's shipFrom when the line omits it.
    # This avoids "country UNKNOWN" errors from Avalara when the parent
    # caller (e.g., embed URL) only supplies a ship-from country.
    raw_coo = line.get("countryOfOrigin") or line.get("origin")
    origin = (
        str(raw_coo).upper() if raw_coo
        else (default_origin.upper() if default_origin else "UNKNOWN")
    )

    return Item(
        hs6=hs6,
        description=str(line.get("description", "")),
        origin=origin,
        qty=qty,
        unit_value_eur=unit_value,
        fta_proof_held=fta_proof,
        standard_duty_rate=Decimal(str(line.get("standard_duty_rate", 0))),
        fta_duty_rate=Decimal(str(line.get("fta_duty_rate", 0))),
        merchant_id=pid.get("merchantId"),
        manufacturer_id=pid.get("manufacturerId"),
        gtin=pid.get("gtin"),
    )
