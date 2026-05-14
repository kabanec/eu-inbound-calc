"""Avalara getQuote adapter tests + Flask API smoke tests."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app import create_app
from app.services.avalara_adapter import from_avalara_getquote


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# Adapter -----------------------------------------------------------------
class TestAvalaraAdapter:
    def test_minimal_legacy_payload(self):
        """Pure legacy getQuote with no euReform2026 namespaces."""
        payload = {
            "addresses": {"shipTo": {"country": "DE"}},
            "date": "2026-08-01",
            "lines": [
                {"hsCode": "610910", "description": "Cotton t-shirt",
                 "countryOfOrigin": "CN", "quantity": 2, "amount": 24}
            ]
        }
        c = from_avalara_getquote(payload)
        assert c.destination_ms == "DE"
        assert len(c.items) == 1
        assert c.items[0].hs6 == "610910"
        assert c.items[0].origin == "CN"
        assert c.items[0].unit_value_eur == Decimal("12")
        assert c.b2b is None  # Adapter passes None; defaults engine will resolve
        assert c.ioss_registered is None  # Defaults engine will resolve

    def test_full_eu_extension_payload(self):
        payload = {
            "addresses": {"shipTo": {"country": "FR"}},
            "date": "2026-09-01",
            "shippingTerms": "DDP",
            "euReform2026": {
                "iossNumber": "IM3720000123",
                "buyerAgent": False,
                "postalDesignatedOperator": False,
                "shipmentChannel": "express",
            },
            "customer": {
                "euReform2026": {"isBusinessBuyer": False}
            },
            "lines": [
                {
                    "hsCode": "640399",
                    "description": "Leather shoe",
                    "countryOfOrigin": "GB",
                    "quantity": 1,
                    "amount": 35,
                    "euReform2026": {
                        "ftaProofType": "REX",
                        "productIdentifiers": {
                            "merchantId": "SHOE-001",
                            "gtin": "8901234567890"
                        }
                    }
                }
            ]
        }
        c = from_avalara_getquote(payload)
        assert c.ioss_registered is True
        assert c.items[0].fta_proof_held is True
        assert c.items[0].gtin == "8901234567890"
        assert c.items[0].merchant_id == "SHOE-001"

    def test_vat_number_implies_b2b(self):
        payload = {
            "addresses": {"shipTo": {"country": "DE"}},
            "lines": [{"hsCode": "610910", "quantity": 1, "amount": 100}],
            "customer": {"euReform2026": {"vatNumber": "DE123456789"}}
        }
        c = from_avalara_getquote(payload)
        assert c.b2b is True
        assert c.customer_vat_number == "DE123456789"

    def test_missing_destination_raises(self):
        with pytest.raises(ValueError, match="destination"):
            from_avalara_getquote({"lines": [{"hsCode": "610910",
                                              "quantity": 1, "amount": 20}]})

    def test_missing_lines_raises(self):
        with pytest.raises(ValueError, match="lines"):
            from_avalara_getquote(
                {"addresses": {"shipTo": {"country": "DE"}}, "lines": []}
            )

    def test_coo_defaults_to_ship_from_when_omitted(self):
        """If line has no countryOfOrigin, fall back to consignment shipFrom."""
        payload = {
            "addresses": {"shipTo": {"country": "DE"}, "shipFrom": {"country": "CN"}},
            "date": "2026-08-01",
            "lines": [{"hsCode": "610910", "quantity": 1, "amount": 20}],
        }
        c = from_avalara_getquote(payload)
        assert c.items[0].origin == "CN"

    def test_coo_unknown_when_neither_line_coo_nor_ship_from(self):
        """If both shipFrom and line countryOfOrigin are missing, falls back to UNKNOWN."""
        payload = {
            "addresses": {"shipTo": {"country": "DE"}},
            "date": "2026-08-01",
            "lines": [{"hsCode": "610910", "quantity": 1, "amount": 20}],
        }
        c = from_avalara_getquote(payload)
        assert c.items[0].origin == "UNKNOWN"

    def test_explicit_line_coo_wins_over_ship_from(self):
        payload = {
            "addresses": {"shipTo": {"country": "DE"}, "shipFrom": {"country": "CN"}},
            "date": "2026-08-01",
            "lines": [{"hsCode": "610910", "quantity": 1, "amount": 20,
                       "countryOfOrigin": "GB"}],
        }
        c = from_avalara_getquote(payload)
        assert c.items[0].origin == "GB"

    def test_shipping_cost_override_passes_through(self):
        """User-supplied shipping_cost_eur on the payload flows to Consignment."""
        payload = {
            "addresses": {"shipTo": {"country": "DE"}, "shipFrom": {"country": "GB"}},
            "date": "2026-08-01",
            "lines": [{"hsCode": "610910", "quantity": 1, "amount": 40}],
            "shipping_cost_eur": 22.50,
        }
        from decimal import Decimal
        c = from_avalara_getquote(payload)
        assert c.shipping_cost_eur == Decimal("22.5")

    def test_shipping_cost_omitted_stays_none(self):
        """Without the field, shipping_cost_eur remains None — defaults engine fills it."""
        payload = {
            "addresses": {"shipTo": {"country": "DE"}, "shipFrom": {"country": "GB"}},
            "date": "2026-08-01",
            "lines": [{"hsCode": "610910", "quantity": 1, "amount": 40}],
        }
        c = from_avalara_getquote(payload)
        assert c.shipping_cost_eur is None

    def test_shipping_cost_negative_or_garbage_ignored(self):
        """Malformed values silently default to None rather than crashing."""
        for bad in (-5, "not-a-number", None):
            payload = {
                "addresses": {"shipTo": {"country": "DE"}, "shipFrom": {"country": "GB"}},
                "date": "2026-08-01",
                "lines": [{"hsCode": "610910", "quantity": 1, "amount": 40}],
                "shipping_cost_eur": bad,
            }
            c = from_avalara_getquote(payload)
            assert c.shipping_cost_eur is None, f"Bad input {bad!r} must yield None"


# API endpoints -----------------------------------------------------------
class TestAPI:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.get_json()["status"] == "ok"

    def test_calculate_legacy_payload(self, client):
        payload = {
            "addresses": {"shipTo": {"country": "DE"}},
            "date": "2026-08-01",
            "lines": [
                {"hsCode": "610910", "description": "Cotton t-shirt",
                 "countryOfOrigin": "CN", "quantity": 2, "amount": 24,
                 "standard_duty_rate": 0.12}
            ]
        }
        r = client.post("/api/calculate", json=payload)
        assert r.status_code == 200
        data = r.get_json()
        assert data["duty_total_eur"] == 3.0  # IOSS-default → €3
        assert "defaults_applied" in data
        # ioss_registered must have been defaulted (since payload didn't supply it)
        fields_defaulted = [d["field"] for d in data["defaults_applied"]]
        assert "ioss_registered" in fields_defaulted

    def test_calculate_full_extension(self, client):
        payload = {
            # iossNumber present → path (a) IOSS fires for BOTH lines, regardless
            # of FTA proof on the GB shoe. Asymmetric reading of DA Art. 1(1)(a)
            # revised def (24): FTA exclusion is scoped to path (b) postal only.
            "addresses": {"shipFrom": {"country": "GB"}, "shipTo": {"country": "FR"}},
            "date": "2026-08-01",
            "euReform2026": {"iossNumber": "IM3720000123"},
            "lines": [
                {"hsCode": "610910", "description": "tee",
                 "countryOfOrigin": "CN", "quantity": 1, "amount": 20,
                 "standard_duty_rate": 0.12},
                {"hsCode": "640399", "description": "shoe",
                 "countryOfOrigin": "GB", "quantity": 1, "amount": 35,
                 "standard_duty_rate": 0.08, "fta_duty_rate": 0,
                 "euReform2026": {"ftaProofType": "REX"}}
            ]
        }
        r = client.post("/api/calculate", json=payload)
        assert r.status_code == 200
        data = r.get_json()
        # Both lines fire path (a) IOSS → €3 each = €6 total.
        assert data["duty_total_eur"] == 6.0
        # France national fee: 2 distinct HS6 × €2 = €4
        assert data["fees"]["national_fee_eur"] == 4.0

    def test_strategy_endpoint(self, client):
        payload = {
            "addresses": {"shipTo": {"country": "DE"}},
            "date": "2026-08-01",
            "lines": [
                {"hsCode": "610910", "description": "tee",
                 "countryOfOrigin": "CN", "quantity": 1, "amount": 20,
                 "standard_duty_rate": 0.12}
            ]
        }
        r = client.post("/api/strategy", json=payload)
        assert r.status_code == 200
        strategies = r.get_json()["strategies"]
        assert len(strategies) >= 3
        # Sorted by landed cost ascending
        costs = [s["result"]["landed_cost_eur"] for s in strategies]
        assert costs == sorted(costs)

    def test_calculate_400_on_missing_destination(self, client):
        r = client.post("/api/calculate", json={
            "lines": [{"hsCode": "610910", "quantity": 1, "amount": 20}]
        })
        assert r.status_code == 400
