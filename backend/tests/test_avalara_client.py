"""Unit tests for the Avalara globalcompliance HTTP client."""
from __future__ import annotations

from decimal import Decimal

import pytest
import requests.exceptions

from app.models.schemas import Consignment, Item
from app.services.avalara_client import AvalaraError, get_quote, zero_line
from app.services.defaults import apply_all_defaults
from tests.conftest import AVALARA_URL


def _ready_consignment(**kwargs) -> Consignment:
    """Return a Consignment with defaults already applied."""
    c = Consignment(
        items=[Item(hs6="610910", description="cotton tee", origin="CN",
                    qty=1, unit_value_eur=Decimal("20.00"))],
        destination_ms="DE",
        ioss_registered=True,
        **kwargs,
    )
    c, _ = apply_all_defaults(c)
    return c


class TestPayloadStructure:
    def test_one_line_per_item(self, mock_avalara):
        """Payload contains exactly one line per item in the consignment."""
        from app.services.avalara_client import _build_payload
        c = _ready_consignment()
        payload = _build_payload(c)

        assert len(payload["lines"]) == 1
        line = payload["lines"][0]
        assert line["lineNumber"] == 1
        assert line["quantity"] == 1
        item_node = line["item"]
        assert item_node["classifications"][0]["hscode"] == "610910"
        price_param = next(p for p in item_node["classificationParameters"] if p["name"] == "price")
        assert price_param["value"] == "20.00"
        coo_param = next(p for p in item_node["classificationParameters"] if p["name"] == "coo")
        assert coo_param["value"] == "CN"

    def test_currency_and_type_fixed(self, mock_avalara):
        from app.services.avalara_client import _build_payload
        c = _ready_consignment()
        payload = _build_payload(c)
        assert payload["currency"] == "EUR"
        assert payload["type"] == "QUOTE_MAXIMUM"


class TestResponseParsing:
    def test_duty_summed_from_multiple_detail_entries(self, mock_avalara):
        """Two separate duty detail rows for the same line are summed."""
        mock_avalara.reset()
        mock_avalara.add(mock_avalara.POST, AVALARA_URL, json={
            "id": "req-001", "currency": "EUR", "messages": [],
            "lines": [{
                "lineNumber": 1, "hsCode": "610910",
                "details": [
                    {"taxType": "customsduty", "taxName": "mfn", "tax": 1.50, "rate": 0.08},
                    {"taxType": "tariff", "taxName": "additional tariff", "tax": 0.50, "rate": 0.02},
                ],
            }],
        }, status=200)

        resp = get_quote(_ready_consignment())
        assert resp.request_id == "req-001"
        assert len(resp.line_results) == 1
        assert resp.line_results[0].duty_eur == Decimal("2.00")
        assert resp.total_duty_eur == Decimal("2.00")

    def test_vat_details_excluded_from_duty(self, mock_avalara):
        """Non-duty detail entries (VAT, fees) do not contribute to duty_eur."""
        mock_avalara.reset()
        mock_avalara.add(mock_avalara.POST, AVALARA_URL, json={
            "id": "req-002", "currency": "EUR", "messages": [],
            "lines": [{
                "lineNumber": 1, "hsCode": "610910",
                "details": [
                    {"taxType": "customsduty", "taxName": "mfn customs duty", "tax": 3.00, "rate": 0.15},
                    {"taxType": "vat", "taxName": "import vat", "tax": 4.00, "rate": 0.20},
                ],
            }],
        }, status=200)

        resp = get_quote(_ready_consignment())
        assert resp.line_results[0].duty_eur == Decimal("3.00")

    def test_preferential_detected_from_tax_type(self, mock_avalara):
        """is_preferential=True when taxType contains 'preferential'."""
        mock_avalara.reset()
        mock_avalara.add(mock_avalara.POST, AVALARA_URL, json={
            "id": "req-003", "currency": "EUR", "messages": [],
            "lines": [{
                "lineNumber": 1, "hsCode": "640399",
                "details": [
                    {"taxType": "preferentialduty", "taxName": "tca duty", "tax": 0.0, "rate": 0.0},
                ],
            }],
        }, status=200)

        resp = get_quote(_ready_consignment())
        assert resp.line_results[0].is_preferential is True
        assert resp.line_results[0].duty_eur == Decimal("0.00")


class TestErrorHandling:
    def test_http_500_raises_avalara_error_with_status(self, mock_avalara):
        mock_avalara.reset()
        mock_avalara.add(mock_avalara.POST, AVALARA_URL,
                         json={"message": "server error"}, status=500)

        with pytest.raises(AvalaraError) as exc_info:
            get_quote(_ready_consignment())
        assert exc_info.value.status_code == 500

    def test_http_401_raises_avalara_error_with_status(self, mock_avalara):
        mock_avalara.reset()
        mock_avalara.add(mock_avalara.POST, AVALARA_URL,
                         json={"message": "Unauthorized"}, status=401)

        with pytest.raises(AvalaraError) as exc_info:
            get_quote(_ready_consignment())
        assert exc_info.value.status_code == 401

    def test_network_failure_raises_avalara_error_status_zero(self, mock_avalara):
        mock_avalara.reset()
        mock_avalara.add(mock_avalara.POST, AVALARA_URL,
                         body=requests.exceptions.ConnectionError("unreachable"))

        with pytest.raises(AvalaraError) as exc_info:
            get_quote(_ready_consignment())
        assert exc_info.value.status_code == 0


class TestZeroLine:
    def test_zero_line_fields(self):
        lr = zero_line(7)
        assert lr.line_number == 7
        assert lr.duty_eur == Decimal("0.00")
        assert lr.duty_rate == Decimal("0.00")
        assert lr.is_preferential is False
        assert lr.duty_details == []
