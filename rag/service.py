"""The desk as an HTTP service. Start it with:  uvicorn service:create_app --factory

POST /v1/messages   header X-API-Key, body {"message": "..."}  ->  reply, case id, citations
GET  /healthz       no data, no key

Order of checks: key, then rate limit, then daily cap, then free capacity, then the desk.
The service holds no database owner login: it runs as desk_service (DATABASE_URL) and refuses to
start without API keys, so a missing setting never means an open door.
"""
import hmac
import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import tracing
from limits import DailyCap, TokenBucket

log = logging.getLogger("desk.service")


def parse_keys(raw: str) -> dict[str, str]:
    """'web=abc,agent=def' -> {'web': 'abc', 'agent': 'def'}. The name is who is calling."""
    keys = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        name, sep, secret = pair.partition("=")
        if not sep or not name.strip() or len(secret.strip()) < 16:
            raise ValueError("SERVICE_API_KEYS must look like name=secret, each secret at least 16 characters")
        keys[name.strip()] = secret.strip()
    return keys


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def create_app(handle=None, keys: dict[str, str] | None = None, limiter: TokenBucket | None = None,
               cap: DailyCap | None = None, max_concurrent: int | None = None,
               on_shutdown=None) -> FastAPI:
    keys = keys if keys is not None else parse_keys(os.environ.get("SERVICE_API_KEYS", ""))
    if not keys:
        raise RuntimeError("SERVICE_API_KEYS is not set: the service will not start without API keys")
    if handle is None:
        from handler import handle_message as handle
    limiter = limiter or TokenBucket(_env_int("RATE_PER_MINUTE", 10), _env_int("RATE_BURST", 5))
    cap = cap or DailyCap(_env_int("DAILY_CAP", 500))
    slots = threading.BoundedSemaphore(max_concurrent or _env_int("MAX_CONCURRENT", 4))

    on_shutdown = on_shutdown or tracing.flush

    @asynccontextmanager
    async def lifespan(_app):
        yield
        try:  # a stop (docker stop sends SIGTERM) must not lose the last traces; never blocks the exit
            on_shutdown()
        except Exception as exc:
            log.warning("shutdown flush failed: %s", type(exc).__name__)

    app = FastAPI(title="Arcaence desk", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid(_request, _exc):
        return JSONResponse({"detail": "invalid request"}, status_code=422)  # never echo the input back

    def who(api_key: str | None) -> str | None:
        found = None
        for name, secret in keys.items():  # compare against every key, so timing does not tell which
            if api_key is not None and hmac.compare_digest(api_key.encode(), secret.encode()):
                found = name
        return found

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/v1/messages")
    def messages(body: MessageIn, x_api_key: str | None = Header(default=None)):
        client = who(x_api_key)
        if client is None:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        allowed, wait = limiter.allow(client)
        if not allowed:
            return JSONResponse({"detail": "too many requests"}, status_code=429, headers={"Retry-After": str(wait)})
        if not cap.take():
            return JSONResponse({"detail": "the service has reached its daily limit"}, status_code=503)
        if not slots.acquire(blocking=False):
            return JSONResponse({"detail": "the service is busy"}, status_code=503, headers={"Retry-After": "5"})
        try:
            result = handle(body.message)
        except Exception as exc:
            log.error("desk failed client=%s error=%s", client, type(exc).__name__)
            return JSONResponse({"detail": "the service could not answer"}, status_code=500)
        finally:
            slots.release()
        citations = [f"{c['doc_id']} {c['clause_id']}".strip() for c in result.get("citations", [])]
        log.info("case=%s client=%s behavior=%s queued=%s", result["case_id"], client, result["behavior"],
                 result["review"]["queued"])  # never the message text: it can hold personal data
        return {"case_id": result["case_id"], "behavior": result["behavior"], "answer": result["answer"],
                "citations": citations, "needs_person": result["review"]["needed"]}

    return app
