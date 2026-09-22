"""Хранилище в Redis: общее для всех воркеров и инстансов (горизонтальное масштабирование)."""

from __future__ import annotations

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.storage.base import MappingRecord, StoreUnavailableError
from app.storage.codec import RecordCodec

_PREFIX = "pd:map:"


def _unavailable(exc: RedisError) -> StoreUnavailableError:
    if isinstance(exc, RedisTimeoutError):
        return StoreUnavailableError("timeout", type(exc).__name__)
    if isinstance(exc, RedisConnectionError):
        return StoreUnavailableError("connection", type(exc).__name__)
    return StoreUnavailableError("connection", type(exc).__name__)


class RedisStore:
    def __init__(
        self,
        url: str,
        codec: RecordCodec,
        ttl_seconds: int,
        timeout_seconds: float = 2.0,
        max_connections: int = 64,
    ) -> None:
        self._redis = Redis.from_url(
            url,
            socket_timeout=timeout_seconds,
            socket_connect_timeout=timeout_seconds,
            max_connections=max_connections,
            health_check_interval=30,
        )
        self._codec = codec
        self._ttl = ttl_seconds

    async def get(self, key: str) -> MappingRecord | None:
        try:
            blob = await self._redis.get(_PREFIX + key)
        except RedisError as exc:
            raise _unavailable(exc) from exc
        return None if blob is None else self._codec.decode(key, blob)

    async def put_if_absent(self, key: str, record: MappingRecord) -> bool:
        try:
            created = await self._redis.set(_PREFIX + key, self._codec.encode(key, record), ex=self._ttl, nx=True)
        except RedisError as exc:
            raise _unavailable(exc) from exc
        return bool(created)

    async def put(self, key: str, record: MappingRecord) -> None:
        try:
            await self._redis.set(_PREFIX + key, self._codec.encode(key, record), ex=self._ttl)
        except RedisError as exc:
            raise _unavailable(exc) from exc

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except RedisError:
            return False

    async def close(self) -> None:
        await self._redis.aclose()
