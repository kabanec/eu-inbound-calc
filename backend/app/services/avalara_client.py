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

_PREFERENTIAL_TARIFF_TYPES = frozenset({"PREFERENTIAL", "FTA", "TCA", "REX"})


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
        "Authorization": os.environ["AVALARA_TOKEN"],
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


def _to_cn8(hs6: str) -> str:
    """Normalise to 8-digit CN8: Avalara requires ≥8 digits when b2b=True."""
    code = hs6.replace(".", "").replace(" ", "")
    return code + "00" if len(code) == 6 else code


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
                        "hscode": _to_cn8(item.hs6),
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
        "type": "QUOTE_ENHANCED10",
        "disableCalculationSummary": False,
        "restrictionsCheck": True,
        "program": "Regular",
    }


def _parse_avalara_response(raw: dict) -> AvalaraResponse:
    """Parse the globalcompliance response.

    Actual response shape:
      raw["globalCompliance"][0]["quote"]["lines"][i]
        .number          — 1-based line number
        .hsCode          — resolved HS code
        .costLines[]     — cost entries; type=="DUTY" entries are the duty figures
        .calculationSummary.dutyCalculationSummary[]  — name/value pairs for rate etc.
        .calculationSummary.dutyGranularity[]         — per-bracket type (MFN/PREFERENTIAL)
    """
    line_results: list[AvalaraLineResult] = []

    gc = raw.get("globalCompliance") or []
    lines = (gc[0].get("quote") or {}).get("lines") or [] if gc else []

    for line in lines:
        line_number = int(line.get("number") or 0)
        cost_lines = line.get("costLines") or []
        calc = line.get("calculationSummary") or {}
        duty_summary = calc.get("dutyCalculationSummary") or []
        duty_granularity = calc.get("dutyGranularity") or []

        duty_eur = Decimal("0.00")
        duty_details: list[dict] = []
        for cl in cost_lines:
            if (cl.get("type") or "").upper() == "DUTY":
                duty_eur += Decimal(str(cl.get("value") or 0))
                duty_details.append(cl)

        duty_rate = Decimal("0.00")
        for entry in duty_summary:
            if entry.get("name") == "RATE":
                duty_rate = Decimal(str(entry.get("value") or 0))
                break

        is_preferential = False
        for entry in duty_summary:
            if entry.get("name") == "TARIFF_TYPE" and (entry.get("value") or "").upper() in _PREFERENTIAL_TARIFF_TYPES:
                is_preferential = True
                break
        if not is_preferential:
            for dg in duty_granularity:
                if (dg.get("type") or "").upper() in _PREFERENTIAL_TARIFF_TYPES:
                    is_preferential = True
                    break

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
        messages=[f"{s['name']}={s['value']}" for s in (raw.get("summary") or [])],
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
