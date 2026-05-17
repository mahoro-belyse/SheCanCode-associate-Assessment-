import asyncio
import hashlib
import json
import time
from datetime import datetime

from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from app.config import settings  # ← all config values come from .env


app = FastAPI(
    title=settings.APP_TITLE,
    description="Ensures payments are processed exactly once, even on retries.",
    version=settings.APP_VERSION,
)


idempotency_store: dict[str, dict] = {}


in_flight: dict[str, asyncio.Event] = {}

rate_limit_store: dict[str, list] = {}


class PaymentRequest(BaseModel):
    amount: float
    currency: str


def body_hash(payload: dict) -> str:
    """Deterministic SHA-256 hash of the request payload."""
    canonical = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def is_key_expired(entry: dict) -> bool:
    """Return True if the stored key is older than KEY_TTL_SECONDS (from .env)."""
    age = time.time() - entry["timestamp"]
    return age > settings.KEY_TTL_SECONDS


def check_rate_limit(client_ip: str) -> None:
    """Sliding-window rate limiter. Values come from .env. Raises 429 if exceeded."""
    now = time.time()
    window_start = now - settings.RATE_LIMIT_WINDOW_SECONDS
    timestamps = rate_limit_store.get(client_ip, [])
    timestamps = [t for t in timestamps if t > window_start]
    if len(timestamps) >= settings.RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded. "
                f"Max {settings.RATE_LIMIT_MAX} requests "
                f"per {settings.RATE_LIMIT_WINDOW_SECONDS}s."
            ),
        )
    timestamps.append(now)
    rate_limit_store[client_ip] = timestamps


@app.get("/", tags=["Health"])
def root():
    return {
        "service": settings.APP_TITLE,
        "version": settings.APP_VERSION,
        "env": settings.APP_ENV,
        "status": "running",
    }


@app.get("/health", tags=["Health"])
def health():
    return {
        "status": "ok",
        "stored_keys": len(idempotency_store),
        "in_flight_keys": len(in_flight),
        "timestamp": datetime.utcnow().isoformat(),
        "config": {
            "processing_delay": settings.PROCESSING_DELAY_SECONDS,
            "key_ttl_seconds": settings.KEY_TTL_SECONDS,
            "rate_limit_max": settings.RATE_LIMIT_MAX,
            "rate_limit_window": settings.RATE_LIMIT_WINDOW_SECONDS,
        },
    }


@app.post("/process-payment", tags=["Payments"])
async def process_payment(
    payment: PaymentRequest,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
   
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)
    if not idempotency_key:
        raise HTTPException(
            status_code=400,
            detail="Missing required header: Idempotency-Key",
        )

    payload = payment.model_dump()
    current_hash = body_hash(payload)

    existing = idempotency_store.get(idempotency_key)
    if existing:
        if is_key_expired(existing):
            del idempotency_store[idempotency_key]
        else:
            if existing["body_hash"] != current_hash:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency key already used for a different request body.",
                )
            return JSONResponse(
                content=existing["response_body"],
                status_code=existing["status_code"],
                headers={"X-Cache-Hit": "true"},
            )

    if idempotency_key in in_flight:
        event = in_flight[idempotency_key]
        await event.wait()
        completed = idempotency_store.get(idempotency_key)
        if completed:
            return JSONResponse(
                content=completed["response_body"],
                status_code=completed["status_code"],
                headers={"X-Cache-Hit": "true"},
            )

    event = asyncio.Event()
    in_flight[idempotency_key] = event

    try:
        await asyncio.sleep(settings.PROCESSING_DELAY_SECONDS)

        response_body = {
            "status": "success",
            "message": f"Charged {payment.amount} {payment.currency}",
            "idempotency_key": idempotency_key,
            "transaction_id": f"txn_{current_hash[:12]}",
            "processed_at": datetime.utcnow().isoformat(),
        }
        status_code = 201
        idempotency_store[idempotency_key] = {
            "body_hash": current_hash,
            "status_code": status_code,
            "response_body": response_body,
            "timestamp": time.time(),
        }

        return JSONResponse(content=response_body, status_code=status_code)

    finally:
        event.set()
        in_flight.pop(idempotency_key, None)
