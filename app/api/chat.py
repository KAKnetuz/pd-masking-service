"""POST /chat — демо-прокси: маскирование → LLM → демаскирование.

Текст сообщения и ответа никогда не логируется. В лог попадают только
идентификаторы, типы ПД, количество сущностей и время.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.responses import json_response
from app.core.chat_proxy import LeakBlockedError
from app.core.policy import SystemNotAllowedError
from app.llm.client import LLMUnavailableError
from app.observability.metrics import LLM_ERRORS, LLM_LATENCY

log = logging.getLogger("pd.chat")
router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


@router.post("/chat")
async def chat(body: ChatRequest, request: Request) -> Response:
    state = request.app.state
    settings = state.settings
    started = time.perf_counter()
    request_id = uuid.uuid4().hex[:16]
    system_id = request.headers.get(settings.system_header)

    if len(body.message) > settings.max_payload_chars:
        return json_response({"detail": "message слишком большой"}, 413)

    # Заголовок системы обязателен для /chat.
    if not system_id:
        log.warning("system_header_missing", extra={"request_id": request_id})
        return json_response({"detail": "система не допущена к сервису"}, 403)
    try:
        policy = state.policies.resolve(system_id)
    except SystemNotAllowedError:
        log.warning("system_not_allowed", extra={"request_id": request_id, "system_id": system_id})
        return json_response({"detail": "система не допущена к сервису"}, 403)
    if not policy.unmask_allowed:
        log.warning("unmask_forbidden", extra={"request_id": request_id, "system_id": system_id})
        return json_response({"detail": "демаскирование запрещено для системы"}, 403)

    try:
        result = await state.chat_proxy.handle(body.message, policy)
    except LeakBlockedError:
        LLM_ERRORS.labels("leak_blocked").inc()
        log.warning("leak_blocked", extra={"request_id": request_id, "system_id": system_id})
        return json_response(
            {"detail": "Маскирование не гарантировало отсутствие персональных данных, запрос в LLM не отправлен"},
            422,
        )
    except LLMUnavailableError:
        LLM_ERRORS.labels("unavailable").inc()
        log.warning("llm_unavailable", extra={"request_id": request_id, "system_id": system_id})
        return json_response({"detail": "LLM временно недоступна, запрос не выполнен"}, 503)

    elapsed = time.perf_counter() - started
    LLM_LATENCY.observe(result.llm_ms / 1000)
    log.info(
        "chat_processed",
        extra={
            "request_id": request_id,
            "system_id": policy.system_id,
            "pd_types": result.pd_types,
            "entities": sum(result.pd_types.values()),
            "latency_ms": round(elapsed * 1000, 2),
            "llm_ms": round(result.llm_ms, 2),
            "status": "ok",
        },
    )
    return json_response(
        {
            "answer": result.answer,
            "sent_to_llm": result.sent_to_llm,
            "llm_answer": result.llm_answer,
            "pd_types": result.pd_types,
        }
    )
