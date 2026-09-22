"""FallbackStore: ретрай таймаутов Redis вместо тихого переключения в память.

Без реального Redis: основной store подменяется тестовым классом, который умеет
бросать заданную ошибку заданное число раз, затем работает как обычное хранилище.
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("STORAGE_BACKEND", "memory")

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from app.storage.base import MappingRecord, StoreUnavailableError
from app.storage.codec import RecordCodec
from app.storage.fallback import FallbackStore
from app.storage.memory import MemoryStore

SOURCE = "Клиент Иванов Иван Иванович, паспорт 4509 123456"


def _codec() -> RecordCodec:
    return RecordCodec(b"0" * 32)


def _memory() -> MemoryStore:
    return MemoryStore(_codec(), ttl_seconds=3600)


class FlakyStore:
    """Обёртка над хранилищем: первые `fail_times` вызовов бросают `error`."""

    def __init__(self, inner, error: type[Exception], fail_times: int = 1) -> None:
        self._inner = inner
        self._error = error
        self._fail_times = fail_times
        self.calls = 0

    async def get(self, key: str) -> MappingRecord | None:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._error()
        return await self._inner.get(key)

    async def put_if_absent(self, key: str, record: MappingRecord) -> bool:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._error()
        return await self._inner.put_if_absent(key, record)

    async def put(self, key: str, record: MappingRecord) -> None:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._error()
        await self._inner.put(key, record)

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        await self._inner.close()


def test_timeout_once_then_success_no_memory_fallback() -> None:
    async def scenario() -> None:
        primary = FlakyStore(_memory(), error=TimeoutError, fail_times=1)
        fallback = _memory()
        store = FallbackStore(primary, fallback)

        record = MappingRecord(original=SOURCE, masked="МАСКА")
        # put_if_absent: первый вызов падает по таймауту, повтор успешен.
        assert await store.put_if_absent("k", record) is True
        # Запись попала в primary (Redis), а не в fallback (память).
        assert await store.get("k") == record
        assert await fallback.get("k") is None

    asyncio.run(scenario())


def test_timeout_twice_raises_store_unavailable() -> None:
    async def scenario() -> None:
        primary = FlakyStore(_memory(), error=TimeoutError, fail_times=2)
        store = FallbackStore(primary, _memory())

        record = MappingRecord(original=SOURCE, masked="МАСКА")
        try:
            await store.put_if_absent("k", record)
        except StoreUnavailableError:
            pass
        else:
            raise AssertionError("ожидался StoreUnavailableError после двух таймаутов")

    asyncio.run(scenario())


def test_connection_error_switches_to_memory() -> None:
    async def scenario() -> None:
        primary = FlakyStore(_memory(), error=ConnectionError, fail_times=1)
        fallback = _memory()
        store = FallbackStore(primary, fallback)

        record = MappingRecord(original=SOURCE, masked="МАСКА")
        assert await store.put_if_absent("k", record) is True
        # Запись попала в fallback (память), primary так и не ответил.
        assert await fallback.get("k") == record

    asyncio.run(scenario())


def test_api_returns_503_when_store_unavailable() -> None:
    class UnavailableStore:
        async def get(self, key: str) -> MappingRecord | None:
            raise StoreUnavailableError("timeout", "TimeoutError")

        async def put_if_absent(self, key: str, record: MappingRecord) -> bool:
            raise StoreUnavailableError("timeout", "TimeoutError")

        async def put(self, key: str, record: MappingRecord) -> None:
            raise StoreUnavailableError("timeout", "TimeoutError")

        async def ping(self) -> bool:
            return True

        async def close(self) -> None:
            return None

    with TestClient(create_app(Settings.from_env(), store_override=UnavailableStore())) as client:
        response = client.post("/process", json={"payload": SOURCE, "payload_id": "api-503"})
        assert response.status_code == 503
        assert response.headers.get("Retry-After") == "1"
        assert response.json() == {"detail": "хранилище временно недоступно, повторите запрос"}
        # Исходный текст не должен попасть в ответ.
        assert "Иванов" not in response.text
