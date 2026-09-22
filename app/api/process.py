"""POST /process — единый контракт маскирования/демаскирования (Приложение A ТЗ)."""

from __future__ import annotations

import hashlib
import logging
import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.responses import json_response
from app.core.policy import SystemNotAllowedError
from app.core.processor import UnmaskForbiddenError
from app.observability.metrics import LATENCY, PD_FOUND, REJECTED, REQUESTS, TOKENS, estimate_tokens
from app.observability.shape import text_shape
from app.storage.base import StoreUnavailableError

log = logging.getLogger("pd.process")
router = APIRouter()


class ProcessRequest(BaseModel):
    payload: str
    payload_id: str = Field(min_length=1)


@router.post("/process")
async def process(body: ProcessRequest, request: Request) -> Response:
    state = request.app.state
    settings = state.settings
    started = time.perf_counter()
    system_id = request.headers.get(settings.system_header)
    request_id = uuid.uuid4().hex[:16]

    if len(body.payload) > settings.max_payload_chars or len(body.payload_id) > settings.max_payload_id_chars:
        REJECTED.labels("too_large").inc()
        return json_response({"detail": "payload слишком большой"}, 413)
    try:
        policy = state.policies.resolve(system_id)
    except SystemNotAllowedError:
        REJECTED.labels("system_not_allowed").inc()
        log.warning("system_not_allowed", extra={"request_id": request_id, "system_id": system_id})
        return json_response({"detail": "система не допущена к сервису"}, 403)

    try:
        outcome = await state.processor.process(body.payload_id, body.payload, policy)
    except UnmaskForbiddenError:
        REJECTED.labels("unmask_forbidden").inc()
        return json_response({"detail": "демаскирование запрещено для системы"}, 403)
    except StoreUnavailableError:
        log.warning("store_unavailable", extra={"request_id": request_id})
        return json_response(
            {"detail": "хранилище временно недоступно, повторите запрос"},
            503,
            headers={"Retry-After": "1"},
        )

    elapsed = time.perf_counter() - started
    direction = outcome.direction.value
    tokens = estimate_tokens(body.payload)
    REQUESTS.labels(direction, "ok").inc()
    LATENCY.labels(direction).observe(elapsed)
    TOKENS.labels(direction).inc(tokens)
    for pd_type, count in outcome.pd_types.items():
        PD_FOUND.labels(pd_type).inc(count)
    log.info(
        "processed",
        extra={
            "request_id": request_id,
            "payload_id_hash": hashlib.sha256(body.payload_id.encode()).hexdigest()[:16],
            "system_id": policy.system_id,
            "direction": direction,
            "latency_ms": round(elapsed * 1000, 2),
            "chars": len(body.payload),
            "tokens": tokens,
            "pd_types": outcome.pd_types,
        },
    )
    if settings.debug_shapes and direction == "mask" and not outcome.pd_types:
        log.info("no_pd_shape", extra={"shape": text_shape(body.payload), "chars": len(body.payload)})
    return json_response({"result": outcome.result})
