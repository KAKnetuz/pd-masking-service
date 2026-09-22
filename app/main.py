"""Точка входа FastAPI: сборка компонентов и обработчики ошибок."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response

from app.api import chat as chat_api
from app.api import process as process_api
from app.api import service as service_api
from app.api.limiter import InflightLimitMiddleware
from app.core.chat_proxy import ChatProxy
from app.core.engine import DetectionEngine
from app.core.masking import Masker
from app.core.policy import load_policies
from app.core.processor import Processor
from app.llm.client import build_llm_client
from app.observability.logging import setup_logging
from app.settings import Settings
from app.storage.base import MappingStore
from app.storage.codec import RecordCodec, decode_key
from app.storage.memory import MemoryStore

log = logging.getLogger("pd.app")


def _secret(raw: str, name: str) -> bytes:
    if raw:
        return decode_key(raw)
    log.warning("secret_not_set_generated_ephemeral", extra={"operation": name})
    return os.urandom(32)


def build_store(settings: Settings, codec: RecordCodec) -> MappingStore:
    memory = MemoryStore(codec, settings.mapping_ttl_seconds)
    if settings.storage_backend != "redis":
        return memory
    from app.storage.fallback import FallbackStore
    from app.storage.redis_store import RedisStore

    return FallbackStore(RedisStore(settings.redis_url, codec, settings.mapping_ttl_seconds), memory)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        codec = RecordCodec(_secret(settings.encryption_key, "ENCRYPTION_KEY"))
        store = build_store(settings, codec)
        llm_client = build_llm_client(settings)
        app.state.settings = settings
        app.state.policies = load_policies(settings.systems_config)
        app.state.store = store
        app.state.processor = Processor(
            DetectionEngine(), Masker(_secret(settings.token_secret, "TOKEN_SECRET")), store
        )
        app.state.chat_proxy = ChatProxy(
            DetectionEngine(), Masker(_secret(settings.token_secret, "TOKEN_SECRET")), llm_client
        )
        log.info("started", extra={"storage": settings.storage_backend})
        yield
        await llm_client.aclose()
        await store.close()

    app = FastAPI(title="PD Security Module", version="1.0.0", lifespan=lifespan, docs_url="/docs")
    app.include_router(process_api.router)
    app.include_router(chat_api.router)
    app.include_router(service_api.router)
    app.add_middleware(InflightLimitMiddleware, max_inflight=settings.max_inflight)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> Response:
        # Стандартный ответ FastAPI возвращает входные данные — с ПД. Отдаём только поля.
        fields = sorted({".".join(str(p) for p in err.get("loc", ())) for err in exc.errors()})
        return process_api.json_response({"detail": "некорректный запрос", "fields": fields}, 400)

    @app.exception_handler(Exception)
    async def unhandled_error(_: Request, exc: Exception) -> Response:
        log.error("unhandled_error", extra={"error": type(exc).__name__})
        return process_api.json_response({"detail": "внутренняя ошибка сервиса"}, 500)

    return app


app = create_app()
