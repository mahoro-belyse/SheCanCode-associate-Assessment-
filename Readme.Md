# Idempotency Gateway — IgirePay Technologies

A production-grade **Idempotency Layer** built with **FastAPI** that ensures payment requests are processed **exactly once**, even when clients retry due to network timeouts.

---

## Architecture Diagram

```
Client (e-commerce shop)
        │
        │  POST /process-payment
        │  Headers: Idempotency-Key: <uuid>
        │  Body:    {"amount": 100, "currency": "GHS"}
        ▼
┌──────────────────────────────────────────────────────────┐
│                  FastAPI Application                     │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  1. Rate Limiter (Developer's Choice)           │    │
│  │     Sliding window — 10 req / 60s per IP        │    │
│  └──────────────────┬──────────────────────────────┘    │
│                     │                                    │
│  ┌──────────────────▼──────────────────────────────┐    │
│  │  2. Validate Idempotency-Key header present?    │    │
│  │     NO  → 400 Bad Request                       │    │
│  └──────────────────┬──────────────────────────────┘    │
│                     │ YES                                │
│  ┌──────────────────▼──────────────────────────────┐    │
│  │  3. Key exists in idempotency_store?            │    │
│  │     YES → key expired (>24h)?                   │    │
│  │        YES → treat as new (fall through)        │    │
│  │        NO  → same body hash?                    │    │
│  │           YES → return cached response          │    │
│  │                 + X-Cache-Hit: true  (201)      │    │
│  │           NO  → 409 Conflict                    │    │
│  └──────────────────┬──────────────────────────────┘    │
│                     │ Key is NEW                         │
│  ┌──────────────────▼──────────────────────────────┐    │
│  │  4. Key in in_flight dict? (race condition)     │    │
│  │     YES → await Event.wait() until done         │    │
│  │           then return cached response (201)     │    │
│  └──────────────────┬──────────────────────────────┘    │
│                     │ Not in-flight                      │
│  ┌──────────────────▼──────────────────────────────┐    │
│  │  5. Register in_flight[key] = asyncio.Event()   │    │
│  │     Simulate processing (2-second delay)        │    │
│  │     Persist result to idempotency_store         │    │
│  │     event.set() → wake up any waiters           │    │
│  │     Return 201 Created                          │    │
│  └─────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

### Sequence Diagram (Duplicate Request)

```
Client A          Gateway             Store
  │                  │                  │
  │─── POST (key=X) ─►│                  │
  │                  │── lookup key=X ──►│
  │                  │◄── not found ─────│
  │                  │── sleep 2s        │
  │                  │── save result ───►│
  │◄── 201 Created ──│                  │
  │                  │                  │
  │─── POST (key=X) ─►│  (retry)         │
  │                  │── lookup key=X ──►│
  │                  │◄── found ─────────│
  │◄── 201 + X-Cache-Hit: true ──────────│
```

### Sequence Diagram (Race Condition)

```
Client A          Client B          Gateway         Store
  │                  │                  │              │
  │─── POST (key=X) ──────────────────►│              │
  │                  │                  │── sleep 2s   │
  │                  │─── POST (key=X) ─►│              │
  │                  │                  │ (key in-flight)
  │                  │                  │── await event│
  │                  │                  │── event.set()│
  │                  │                  │── save ──────►│
  │◄── 201 Created ──────────────────────              │
  │                  │◄── 201 (cached) ──              │
```

---

## Setup Instructions

### Prerequisites

- Python 3.11+
- pip

### 1. Clone the repository

```bash
git clone https://github.com/<your-username>/idempotency-gateway.git
cd idempotency-gateway
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure your environment

```bash
cp .env.example .env
```

The `.env` file controls all runtime behaviour — no hardcoded values in code:

| Variable                   | Default | Description                          |
|----------------------------|---------|--------------------------------------|
| `APP_ENV`                  | `development` | `development` or `production`  |
| `PORT`                     | `8000`  | Server port                          |
| `PROCESSING_DELAY_SECONDS` | `2.0`   | Simulated payment delay              |
| `KEY_TTL_SECONDS`          | `86400` | How long idempotency keys are stored |
| `RATE_LIMIT_MAX`           | `10`    | Max requests allowed per window      |
| `RATE_LIMIT_WINDOW_SECONDS`| `60`    | Sliding window duration (seconds)    |

> ⚠️ **Never commit `.env` to Git.** It is already listed in `.gitignore`.  
> Only commit `.env.example` (the safe template with no real secrets).

### 5. Start the server

```bash
uvicorn app.main:app --reload --port 8000
```

The server will be live at `http://localhost:8000`.  
Interactive docs (Swagger UI): `http://localhost:8000/docs`

---

## API Documentation

### Base URL

```
http://localhost:8000
```

---

### `GET /`

Health check — confirms the service is running.

**Response `200`**
```json
{
  "service": "IgirePay Idempotency Gateway",
  "status": "running"
}
```

---

### `GET /health`

Returns internal diagnostics.

**Response `200`**
```json
{
  "status": "ok",
  "stored_keys": 3,
  "in_flight_keys": 0,
  "timestamp": "2025-06-15T10:00:00.123456"
}
```

---

### `POST /process-payment`

Process a payment. Protected by idempotency logic.

**Headers**

| Header            | Required | Description                             |
|-------------------|----------|-----------------------------------------|
| `Idempotency-Key` | ✅ Yes   | Unique UUID string generated by client |
| `Content-Type`    | ✅ Yes   | `application/json`                      |

**Request Body**

```json
{
  "amount": 100,
  "currency": "GHS"
}
```

| Field      | Type   | Required | Description              |
|------------|--------|----------|--------------------------|
| `amount`   | number | ✅ Yes   | Payment amount           |
| `currency` | string | ✅ Yes   | ISO 4217 currency code   |

---

#### Scenario 1 — First Request (Happy Path)

```bash
curl -X POST http://localhost:8000/process-payment \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000" \
  -d '{"amount": 100, "currency": "GHS"}'
```

**Response `201 Created`**
```json
{
  "status": "success",
  "message": "Charged 100.0 GHS",
  "idempotency_key": "550e8400-e29b-41d4-a716-446655440000",
  "transaction_id": "txn_a3f2c1d4e5b6",
  "processed_at": "2025-06-15T10:00:02.000000"
}
```

---

#### Scenario 2 — Duplicate Request (Idempotency Replay)

Send the **exact same request** again:

```bash
curl -X POST http://localhost:8000/process-payment \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000" \
  -d '{"amount": 100, "currency": "GHS"}'
```

**Response `201 Created`** (instant, no delay)

```
X-Cache-Hit: true
```
```json
{
  "status": "success",
  "message": "Charged 100.0 GHS",
  "idempotency_key": "550e8400-e29b-41d4-a716-446655440000",
  "transaction_id": "txn_a3f2c1d4e5b6",
  "processed_at": "2025-06-15T10:00:02.000000"
}
```

The body is **identical** to the first response.

---

#### Scenario 3 — Same Key, Different Body (Fraud Check)

```bash
curl -X POST http://localhost:8000/process-payment \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000" \
  -d '{"amount": 500, "currency": "GHS"}'
```

**Response `409 Conflict`**
```json
{
  "detail": "Idempotency key already used for a different request body."
}
```

---

#### Scenario 4 — Missing Idempotency-Key

```bash
curl -X POST http://localhost:8000/process-payment \
  -H "Content-Type: application/json" \
  -d '{"amount": 100, "currency": "GHS"}'
```

**Response `400 Bad Request`**
```json
{
  "detail": "Missing required header: Idempotency-Key"
}
```

---

#### Scenario 5 — Rate Limit Exceeded (Developer's Choice)

After 10 requests in 60 seconds:

**Response `429 Too Many Requests`**
```json
{
  "detail": "Rate limit exceeded. Max 10 requests per 60s."
}
```

---

## Running Tests

```bash
pytest tests/test_main.py -v
```

Expected output:

```
tests/test_main.py::test_first_payment_returns_201              PASSED
tests/test_main.py::test_missing_idempotency_key_returns_400    PASSED
tests/test_main.py::test_duplicate_request_returns_cached_response PASSED
tests/test_main.py::test_duplicate_has_no_processing_delay      PASSED
tests/test_main.py::test_same_key_different_body_returns_409    PASSED
tests/test_main.py::test_concurrent_requests_with_same_key      PASSED
tests/test_main.py::test_rate_limit_enforced                    PASSED
tests/test_main.py::test_health_endpoint                        PASSED
```

---

## Design Decisions

### Why FastAPI?
FastAPI is built on Starlette and uses Python's `asyncio` natively. This makes it ideal for this challenge because:
- `async/await` lets us use `asyncio.Event` to block duplicate in-flight requests without spawning threads.
- Auto-generated Swagger docs at `/docs` make testing easy.
- Pydantic v2 validates request bodies with zero boilerplate.

### Why In-Memory Store?
For this challenge an in-memory `dict` is sufficient and keeps the setup dependency-free. In production this would be replaced with **Redis** using atomic `SET NX` + `EXPIRE` to support multi-instance deployments.

### Body Hashing
Rather than storing the raw payload, we store a **SHA-256 hash** of the canonically serialised JSON. This:
- Saves memory on large payloads.
- Prevents timing attacks based on string comparison.
- Is deterministic regardless of key insertion order.

### `asyncio.Event` for Race Conditions
When two identical requests arrive simultaneously, the second one calls `await event.wait()`. This suspends the coroutine (non-blocking) until the first finishes and calls `event.set()`. The second then reads from the store and returns the same result — no double processing, no 409.

---

## Developer's Choice — Rate Limiting + Key TTL

### Rate Limiting
**Why:** A real Fintech API must protect against abuse and DDoS. Without rate limiting, a client could flood the gateway and exhaust server resources.

**Implementation:** A sliding-window rate limiter per client IP address. The window is 60 seconds with a maximum of 10 requests. Old timestamps outside the window are pruned on each request. Returns `429 Too Many Requests` when exceeded.

**Production upgrade:** Replace with Redis + Lua scripting for atomic, distributed rate limiting.

### Key TTL (24-hour expiry)
**Why:** Idempotency keys should not be stored forever. If a key is more than 24 hours old, the original transaction has cleared and the risk of accidental duplication is gone. This also prevents unbounded memory growth.

**Implementation:** Every stored entry includes a `timestamp`. On lookup, if `now - timestamp > 86400s`, the entry is deleted and the request is treated as new.

---

## Project Structure

```
idempotency-gateway/
├── app/
│   ├── __init__.py
│   └── main.py          # All application logic
├── tests/
│   ├── __init__.py
│   └── test_main.py     # Full test suite
├── requirements.txt
├── pytest.ini
└── README.md
```

---

## Suggested Git Commit History

```
feat: initial project scaffold with FastAPI
feat: implement User Story 1 - first payment processing
feat: implement User Story 2 - idempotency cache replay
feat: implement User Story 3 - conflict detection on body mismatch
feat: implement Bonus - race condition guard with asyncio.Event
feat: implement Developer's Choice - rate limiting and key TTL
test: add full pytest suite covering all user stories
docs: complete README with architecture diagram and API docs
```
