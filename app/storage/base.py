"""Контракт хранилища соответствий «payload_id → исходный текст / маска»."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MappingRecord:
    original: str
    masked: str
    fragments: tuple[tuple[str, str], ...] = ()


class StoreUnavailableError(Exception):
    """Хранилище недоступно (сеть, таймаут, отказ Redis)."""


class MappingStore(Protocol):
    async def get(self, key: str) -> MappingRecord | None: ...

    async def put_if_absent(self, key: str, record: MappingRecord) -> bool:
        """Атомарно сохраняет запись. False — запись с таким ключом уже есть (ретрай/гонка)."""
        ...

    async def put(self, key: str, record: MappingRecord) -> None: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...
