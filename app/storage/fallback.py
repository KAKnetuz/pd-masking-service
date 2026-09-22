"""Деградация функционала: при отказе Redis запросы обслуживаются локальным хранилищем.

Сервис продолжает отвечать 200 вместо 5xx. Ограничение режима: пара
«маскирование → демаскирование» должна попасть в тот же процесс, поэтому режим
считается аварийным, отражается в метрике и в /health.

Различаем два вида ошибок Redis:
* TimeoutError — Redis жив, но не успел ответить за таймаут (воркер загружен CPU).
  Повторяем операцию один раз; если повтор успешен — продолжаем с Redis, в память
  не переключаемся. Если и повтор упал по таймауту — бросаем StoreUnavailableError.
* Ошибка соединения (ConnectionError, OSError и т.п.) — Redis недоступен.
  Переключаемся в память (store_degraded), как раньше.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.observability.metrics import STORE_DEGRADED, STORE_ERRORS
from app.storage.base import MappingRecord, MappingStore, StoreUnavailableError

log = logging.getLogger("pd.storage")

T = TypeVar("T")

# Ошибки, которые FallbackStore обрабатывает: StoreUnavailableError (обёртка из
# RedisStore) и сырые OSError-подобные (TimeoutError, ConnectionError) из тестовых
# и сторонних хранилищ.
_HANDLED = (StoreUnavailableError, OSError)


def _classify(exc: Exception) -> str:
    """Возвращает "timeout" или "connection" для ошибки хранилища."""
    if isinstance(exc, StoreUnavailableError):
        return exc.reason
    if isinstance(exc, TimeoutError):
        return "timeout"
    return "connection"


class FallbackStore:
    def __init__(self, primary: MappingStore, fallback: MappingStore) -> None:
        self._primary = primary
        self._fallback = fallback

    async def get(self, key: str) -> MappingRecord | None:
        try:
            record = await self._primary.get(key)
        except _HANDLED as exc:
            return await self._handle_error(
                "get", exc, lambda: self._primary.get(key), lambda: self._fallback.get(key)
            )
        return record if record is not None else await self._fallback.get(key)

    async def put_if_absent(self, key: str, record: MappingRecord) -> bool:
        try:
            return await self._primary.put_if_absent(key, record)
        except _HANDLED as exc:
            return await self._handle_error(
                "put",
                exc,
                lambda: self._primary.put_if_absent(key, record),
                lambda: self._fallback.put_if_absent(key, record),
            )

    async def put(self, key: str, record: MappingRecord) -> None:
        try:
            await self._primary.put(key, record)
        except _HANDLED as exc:
            await self._handle_error(
                "put", exc, lambda: self._primary.put(key, record), lambda: self._fallback.put(key, record)
            )

    async def ping(self) -> bool:
        return await self._primary.ping()

    async def close(self) -> None:
        await self._primary.close()
        await self._fallback.close()

    async def _handle_error(
        self,
        operation: str,
        exc: Exception,
        primary_call: Callable[[], Awaitable[T]],
        fallback_call: Callable[[], Awaitable[T]],
    ) -> T:
        if _classify(exc) == "timeout":
            STORE_ERRORS.labels("timeout_retry").inc()
            log.warning("store_retry", extra={"operation": operation, "error": type(exc).__name__})
            try:
                return await primary_call()
            except _HANDLED as retry_exc:
                if _classify(retry_exc) == "timeout":
                    STORE_ERRORS.labels("unavailable").inc()
                    raise StoreUnavailableError("timeout", type(retry_exc).__name__) from retry_exc
                self._degraded(operation, retry_exc)
                return await fallback_call()
        self._degraded(operation, exc)
        return await fallback_call()

    @staticmethod
    def _degraded(operation: str, exc: Exception) -> None:
        STORE_DEGRADED.inc()
        log.warning("store_degraded", extra={"operation": operation, "error": str(exc)})
