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


@pytest.mark.asyncio
async def test_duplicate_request_returns_cached_response(client):
    payload = {"amount": 100, "currency": "GHS"}
    key = "key-dup-001"

    first = await client.post(
        "/process-payment", json=payload, headers={"Idempotency-Key": key}
    )
    assert first.status_code == 201

    second = await client.post(
        "/process-payment", json=payload, headers={"Idempotency-Key": key}
    )
    assert second.status_code == 201
    assert second.headers.get("x-cache-hit") == "true"
    assert second.json() == first.json()


@pytest.mark.asyncio
async def test_duplicate_has_no_processing_delay(client):
    payload = {"amount": 50, "currency": "USD"}
    key = "key-timing-001"

    await client.post("/process-payment", json=payload, headers={"Idempotency-Key": key})

    import time
    start = time.time()
    resp = await client.post(
        "/process-payment", json=payload, headers={"Idempotency-Key": key}
    )
    elapsed = time.time() - start

    assert resp.headers.get("x-cache-hit") == "true"
    assert elapsed < 0.5, f"Cached response took too long: {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_same_key_different_body_returns_409(client):
    key = "key-conflict-001"

    await client.post(
        "/process-payment",
        json={"amount": 100, "currency": "GHS"},
        headers={"Idempotency-Key": key},
    )

    resp = await client.post(
        "/process-payment",
        json={"amount": 500, "currency": "GHS"},
        headers={"Idempotency-Key": key},
    )
    assert resp.status_code == 409
    assert "different request body" in resp.json()["detail"]

    
@pytest.mark.asyncio
async def test_concurrent_requests_with_same_key(client):
    """Two identical concurrent requests: only one is processed, both return the same result."""
    key = "key-race-001"
    payload = {"amount": 200, "currency": "RWF"}

    results = await asyncio.gather(
        client.post("/process-payment", json=payload, headers={"Idempotency-Key": key}),
        client.post("/process-payment", json=payload, headers={"Idempotency-Key": key}),
    )


    for r in results:
        assert r.status_code == 201

    bodies = [r.json()["transaction_id"] for r in results]
    
    assert bodies[0] == bodies[1], "Race condition: two different transactions were created!"
