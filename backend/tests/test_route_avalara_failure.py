"""Integration tests: Avalara failure → route returns 502."""
from __future__ import annotations

import pytest

from app import create_app
from tests.conftest import AVALARA_URL


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


_PAYLOAD = {
    "addresses": {"shipTo": {"country": "DE"}},
    "date": "2026-08-01",
    "lines": [{"hsCode": "610910", "description": "tee",
               "countryOfOrigin": "CN", "quantity": 1, "amount": 20}],
}


class TestAvalaraFailure:
    def test_calculate_returns_502_when_avalara_fails(self, client, mock_avalara):
        mock_avalara.reset()
        mock_avalara.add(mock_avalara.POST, AVALARA_URL,
                         json={"message": "upstream error"}, status=500)

        r = client.post("/api/calculate", json=_PAYLOAD)
        assert r.status_code == 502
        body = r.get_json()
        assert body["type"] == "AvalaraError"
        assert body["avalara_status"] == 500

    def test_strategy_returns_502_when_avalara_fails(self, client, mock_avalara):
        mock_avalara.reset()
        mock_avalara.add(mock_avalara.POST, AVALARA_URL,
                         json={"message": "upstream error"}, status=500)

        r = client.post("/api/strategy", json=_PAYLOAD)
        assert r.status_code == 502
        body = r.get_json()
        assert body["type"] == "AvalaraError"
