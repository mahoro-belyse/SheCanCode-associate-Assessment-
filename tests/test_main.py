import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app, idempotency_store, in_flight, rate_limit_store


@pytest.fixture(autouse=True)
def clear_stores():
    """Reset all in-memory stores before every test."""
    idempotency_store.clear()
    in_flight.clear()
    rate_limit_store.clear()
    yield


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_first_payment_returns_201(client):
    resp = await client.post(
        "/process-payment",
        json={"amount": 100, "currency": "GHS"},
        headers={"Idempotency-Key": "key-001"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["message"] == "Charged 100.0 GHS"
    assert body["status"] == "success"
    assert "transaction_id" in body


@pytest.mark.asyncio
async def test_missing_idempotency_key_returns_400(client):
    resp = await client.post(
        "/process-payment",
        json={"amount": 100, "currency": "GHS"},
    )
    assert resp.status_code == 400
    assert "Idempotency-Key" in resp.json()["detail"]


