"""Деградация функционала: при отказе Redis запросы обслуживаются локальным хранилищем.

Сервис продолжает отвечать 200 вместо 5xx. Ограничение режима: пара
«маскирование → демаскирование» должна попасть в тот же процесс, поэтому режим
считается аварийным, отражается в метрике и в /health.
"""

from __future__ import annotations

import logging

from app.observability.metrics import STORE_DEGRADED
from app.storage.base import MappingRecord, MappingStore, StoreUnavailableError

log = logging.getLogger("pd.storage")


class FallbackStore:
    def __init__(self, primary: MappingStore, fallback: MappingStore) -> None:
        self._primary = primary
        self._fallback = fallback

    async def get(self, key: str) -> MappingRecord | None:
        try:
            record = await self._primary.get(key)
        except StoreUnavailableError as exc:
            self._degraded("get", exc)
            return await self._fallback.get(key)
        return record if record is not None else await self._fallback.get(key)

    async def put_if_absent(self, key: str, record: MappingRecord) -> bool:
        try:
            return await self._primary.put_if_absent(key, record)
        except StoreUnavailableError as exc:
            self._degraded("put", exc)
            return await self._fallback.put_if_absent(key, record)

    async def put(self, key: str, record: MappingRecord) -> None:
        try:
            await self._primary.put(key, record)
        except StoreUnavailableError as exc:
            self._degraded("put", exc)
            await self._fallback.put(key, record)

    async def ping(self) -> bool:
        return await self._primary.ping()

    async def close(self) -> None:
        await self._primary.close()
        await self._fallback.close()

    @staticmethod
    def _degraded(operation: str, exc: Exception) -> None:
        STORE_DEGRADED.inc()
        log.warning("store_degraded", extra={"operation": operation, "error": str(exc)})
