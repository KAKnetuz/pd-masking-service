"""In-memory хранилище с TTL и ограничением размера (LRU).

Используется для локального запуска и тестов, а также как резерв при недоступности
Redis. Работает в рамках одного процесса, поэтому с ним запускается один воркер.
"""

from __future__ import annotations

import time
from collections import OrderedDict

from app.storage.base import MappingRecord
from app.storage.codec import RecordCodec


class MemoryStore:
    def __init__(self, codec: RecordCodec, ttl_seconds: int, max_items: int = 500_000) -> None:
        self._codec = codec
        self._ttl = ttl_seconds
        self._max_items = max_items
        self._data: OrderedDict[str, tuple[float, bytes]] = OrderedDict()

    async def get(self, key: str) -> MappingRecord | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires_at, blob = item
        if expires_at < time.monotonic():
            self._data.pop(key, None)
            return None
        return self._codec.decode(key, blob)

    async def put_if_absent(self, key: str, record: MappingRecord) -> bool:
        if await self.get(key) is not None:
            return False
        await self.put(key, record)
        return True

    async def put(self, key: str, record: MappingRecord) -> None:
        self._data[key] = (time.monotonic() + self._ttl, self._codec.encode(key, record))
        self._data.move_to_end(key)
        while len(self._data) > self._max_items:
            self._data.popitem(last=False)

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        self._data.clear()
