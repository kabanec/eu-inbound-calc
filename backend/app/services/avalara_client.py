"""Avalara getQuote client.

Avalara is AUTHORITATIVE for duty figures. This module posts to the
globalcompliance endpoint and returns structured results that the
calculator overlays with EU 2026 regime logic.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import uuid4

import requests

from ..models.schemas import Consignment

DUTY_TYPES = frozenset({
    "customsduty", "mfn", "preferentialduty", "tariff",
    "customs duty", "import duty",
})


class AvalaraError(Exception):
    """Raised on any non-200 response or network failure from Avalara."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Avalara API error {status_code}: {detail}")


@dataclass
class AvalaraLineResult:
    line_number: int
    hs_code: str
    duty_eur: Decimal
    duty_rate: Decimal
    is_preferential: bool
    duty_details: list[dict] = field(default_factory=list)


@dataclass
class AvalaraResponse:
    request_id: str
    currency: str
    line_results: list[AvalaraLineResult]
    total_duty_eur: Decimal
    messages: list[str]
    raw_response: dict


def get_quote(consignment: Consignment) -> AvalaraResponse:
    """POST to Avalara globalcompliance and return parsed results.

    Raises AvalaraError on any HTTP error or network failure.
    """
    company_id = os.environ["AVALARA_COMPANY_ID"]
    url = f"{os.environ['AVALARA_API_BASE']}/companies/{company_id}/globalcompliance"
    headers = {
        "Authorization": f"Basic {os.environ['AVALARA_TOKEN']}",
        "Content-Type": "application/json",
    }
    payload = _build_payload(consignment)
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        raise AvalaraError(exc.response.status_code, exc.response.text) from exc
    except requests.exceptions.RequestException as exc:
        raise AvalaraError(0, str(exc)) from exc

    return _parse_avalara_response(resp.json())


def _build_payload(c: Consignment) -> dict:
    return {
        "id": f"EU-INBOUND-{uuid4().hex[:8]}",
        "companyId": int(os.environ["AVALARA_COMPANY_ID"]),
        "transactionDate": c.transaction_date.isoformat(),
        "currency": "EUR",
        "sellerCode": "EU-INBOUND-POC",
        "b2b": bool(c.b2b),
        "shipFrom": {"country": (c.ship_from or "CN").upper()},
        "destinations": [{
            "shipTo": {"country": c.destination_ms.lower()},
            "parameters": [],
            "taxRegistered": bool(c.b2b),
        }],
        "lines": [
            {
                "lineNumber": i + 1,
                "quantity": item.qty,
                "preferenceProgramApplicable": item.fta_proof_held,
                "item": {
                    "itemCode": f"LINE-{i + 1}",
                    "description": item.description or f"Item {i + 1}",
                    "classifications": [{
                        "country": c.destination_ms.upper(),
                        "hscode": item.hs6.replace(".", "").replace(" ", ""),
                    }],
                    "classificationParameters": [
                        {"name": "price", "value": str(item.unit_value_eur), "unit": "EUR"},
                        {"name": "coo", "value": item.origin.upper()},
                    ],
                    "parameters": [
                        {"name": "weight", "value": "0", "unit": "kg"},
                        {"name": "SHIPPING", "value": "0.00", "unit": "EUR"},
                    ],
                },
                "classificationParameters": [],
            }
            for i, item in enumerate(c.items)
        ],
        "type": "QUOTE_MAXIMUM",
        "disableCalculationSummary": False,
        "restrictionsCheck": True,
        "program": "Regular",
    }


def _parse_avalara_response(raw: dict) -> AvalaraResponse:
    line_results: list[AvalaraLineResult] = []

    for line in raw.get("lines", []):
        line_number = int(line.get("lineNumber") or 0)
        details = line.get("details") or []

        duty_eur = Decimal("0.00")
        duty_rate = Decimal("0.00")
        is_preferential = False
        duty_details: list[dict] = []

        for detail in details:
            tax_type = (detail.get("taxType") or "").lower()
            tax_name = (detail.get("taxName") or "").lower()

            is_duty = (
                tax_type in DUTY_TYPES
                or any(k in tax_name for k in ("customs", "duty", "tariff", "mfn"))
            )
            if not is_duty:
                continue

            duty_eur += Decimal(str(detail.get("tax") or 0))
            if duty_rate == Decimal("0.00"):
                duty_rate = Decimal(str(detail.get("rate") or 0))

            if any(k in tax_type for k in ("preferential", "fta")):
                is_preferential = True
            if any(k in tax_name for k in ("preferential", "fta", "tca")):
                is_preferential = True

            duty_details.append(detail)

        line_results.append(AvalaraLineResult(
            line_number=line_number,
            hs_code=str(line.get("hsCode") or ""),
            duty_eur=duty_eur,
            duty_rate=duty_rate,
            is_preferential=is_preferential,
            duty_details=duty_details,
        ))

    total_duty = sum((lr.duty_eur for lr in line_results), Decimal("0.00"))
    return AvalaraResponse(
        request_id=str(raw.get("id") or ""),
        currency=str(raw.get("currency") or "EUR"),
        line_results=line_results,
        total_duty_eur=total_duty,
        messages=[str(m) for m in (raw.get("messages") or [])],
        raw_response=raw,
    )


def zero_line(line_number: int) -> AvalaraLineResult:
    """Return a zeroed-out line result for items Avalara didn't classify."""
    return AvalaraLineResult(
        line_number=line_number,
        hs_code="",
        duty_eur=Decimal("0.00"),
        duty_rate=Decimal("0.00"),
        is_preferential=False,
        duty_details=[],
    )
