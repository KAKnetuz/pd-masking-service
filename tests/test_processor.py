"""Контракт /process на уровне логики: направление, идемпотентность, права систем."""

import asyncio

import pytest

from app.core.engine import DetectionEngine
from app.core.masking import Masker
from app.core.policy import SystemNotAllowedError, load_policies
from app.core.processor import Direction, Processor, UnmaskForbiddenError
from app.storage.codec import RecordCodec
from app.storage.memory import MemoryStore

POLICIES = load_policies("config/systems.yaml")
SOURCE = "Клиент Иванов Иван Иванович, паспорт 4509 123456"


def _processor() -> Processor:
    return Processor(DetectionEngine(), Masker(b"s" * 32), MemoryStore(RecordCodec(b"k" * 32), 60))


def test_mask_then_unmask_roundtrip() -> None:
    async def scenario() -> None:
        proc, policy = _processor(), POLICIES.resolve(None)
        masked = await proc.process("id-1", SOURCE, policy)
        assert masked.direction is Direction.MASK
        assert masked.result == "Клиент И. И. И., паспорт 45** ****56"
        restored = await proc.process("id-1", masked.result, policy)
        assert restored.direction is Direction.UNMASK
        assert restored.result == SOURCE

    asyncio.run(scenario())


def test_mask_retry_is_idempotent() -> None:
    async def scenario() -> None:
        proc, policy = _processor(), POLICIES.resolve(None)
        first = await proc.process("id-2", SOURCE, policy)
        retry = await proc.process("id-2", SOURCE, policy)
        assert retry.result == first.result
        assert retry.direction is Direction.MASK_RETRY

    asyncio.run(scenario())


def test_text_without_pd_roundtrip() -> None:
    async def scenario() -> None:
        proc, policy = _processor(), POLICIES.resolve(None)
        text = "Какая погода завтра?"
        assert (await proc.process("id-3", text, policy)).result == text
        assert (await proc.process("id-3", text, policy)).result == text

    asyncio.run(scenario())


def test_unmask_forbidden_for_system() -> None:
    async def scenario() -> None:
        proc, policy = _processor(), POLICIES.resolve("analytics")
        masked = await proc.process("id-4", SOURCE, policy)
        with pytest.raises(UnmaskForbiddenError):
            await proc.process("id-4", masked.result, policy)

    asyncio.run(scenario())


def test_disabled_and_unknown_systems() -> None:
    for system_id in ("legacy-crm", "unknown-system"):
        with pytest.raises(SystemNotAllowedError):
            POLICIES.resolve(system_id)
