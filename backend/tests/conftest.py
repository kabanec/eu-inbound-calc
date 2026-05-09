"""Shared test fixtures for EU Inbound Calculator tests."""
from __future__ import annotations

import json

import pytest
import responses as responses_lib

AVALARA_BASE = "https://ns1-quoting-sbx.xbo.avalara.com/api/v2"
AVALARA_COMPANY_ID = "2000099295"
AVALARA_URL = f"{AVALARA_BASE}/companies/{AVALARA_COMPANY_ID}/globalcompliance"


def make_avalara_body(
    duties: list[float],
    rates: list[float] | None = None,
    preferential: list[bool] | None = None,
    request_id: str = "mock-req",
) -> dict:
    """Build a minimal Avalara globalcompliance response body.

    duties: per-line duty amount (len == number of items sent).
    rates/preferential default to 0.12/False for every line.
    """
    rates = rates or [0.12] * len(duties)
    preferential = preferential or [False] * len(duties)

    lines = []
    for i, (duty, rate, pref) in enumerate(zip(duties, rates, preferential)):
        tax_type = "preferentialduty" if pref else "customsduty"
        tax_name = "preferential duty" if pref else "mfn customs duty"
        details = [{"taxType": tax_type, "taxName": tax_name, "tax": duty, "rate": rate}] if duty else []
        lines.append({"lineNumber": i + 1, "hsCode": "610910", "details": details})

    return {"id": request_id, "currency": "EUR", "messages": [], "lines": lines}


@pytest.fixture
def responses():
    """Override pytest-responses fixture: disable 'all requests fired' assertion.

    The autouse mock_avalara registers a callback for all tests, but adapter
    and schema tests don't call Avalara — we don't want teardown to fail.
    """
    with responses_lib.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


@pytest.fixture(autouse=True)
def avalara_env(monkeypatch):
    """Ensure Avalara env vars are present for every test."""
    monkeypatch.setenv("AVALARA_API_BASE", AVALARA_BASE)
    monkeypatch.setenv("AVALARA_TOKEN", "dGVzdDp0ZXN0")
    monkeypatch.setenv("AVALARA_COMPANY_ID", AVALARA_COMPANY_ID)


@pytest.fixture(autouse=True)
def mock_avalara(responses, avalara_env):
    """Intercept Avalara globalcompliance for every test.

    Default: returns 0 duty for each line (count inferred from request body).
    Override: call mock_avalara.reset() then mock_avalara.add(...) in the test.
    """
    def _default_callback(request):
        body = json.loads(request.body)
        n = len(body.get("lines", []))
        body = {
            "id": "mock-req", "currency": "EUR", "messages": [],
            "lines": [{"lineNumber": i + 1, "hsCode": "", "details": []} for i in range(n)],
        }
        return (200, {"Content-Type": "application/json"}, json.dumps(body))

    responses.add_callback(responses.POST, AVALARA_URL, callback=_default_callback)
    return responses
