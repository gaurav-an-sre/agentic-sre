"""storefront is the edge: X-Request-ID starts here and must reach the checkout call unchanged."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "system" / "storefront"))
import main as sf


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(sf, "get_products", lambda: [{"id": 1, "name": "Rice 5kg", "price_cents": 19900}])
    return TestClient(sf.app)


def test_healthz(client):
    assert client.get("/healthz").json()["status"] == "ok"


def test_request_id_generated_at_edge_and_forwarded(client, monkeypatch):
    seen = {}
    def fake_post(payload, rid):
        seen["rid"] = rid
        class R:
            status_code = 200
            def json(self): return {"status": "succeeded", "order_id": 7}
        return R()
    monkeypatch.setattr(sf, "post_checkout", fake_post)
    resp = client.post("/api/checkout", json={"items": [{"product_id": 1, "quantity": 1}]})
    assert resp.status_code == 200
    assert seen["rid"].startswith("req_")
    assert resp.headers["X-Request-ID"] == seen["rid"]


def test_inbound_request_id_is_propagated(client, monkeypatch):
    seen = {}
    def fake_post(payload, rid):
        seen["rid"] = rid
        class R:
            status_code = 200
            def json(self): return {"status": "succeeded", "order_id": 8}
        return R()
    monkeypatch.setattr(sf, "post_checkout", fake_post)
    client.post("/api/checkout", json={"items": [{"product_id": 1, "quantity": 1}]},
                headers={"X-Request-ID": "req_customer1"})
    assert seen["rid"] == "req_customer1"


def test_upstream_down_is_a_502_not_a_traceback(client, monkeypatch):
    import httpx
    def boom(payload, rid):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(sf, "post_checkout", boom)
    resp = client.post("/api/checkout", json={"items": [{"product_id": 1, "quantity": 1}]})
    assert resp.status_code == 502
    assert resp.json()["reason"] == "checkout_unreachable"


def test_homepage_lists_products(client):
    page = client.get("/")
    assert "Rice 5kg" in page.text and "request id" in page.text
