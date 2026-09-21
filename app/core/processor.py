"""Логика контракта POST /process: направление по payload_id, идемпотентность.

* Новый payload_id → маскирование, соответствие сохраняется.
* Тот же payload_id и payload == наша маска → демаскирование (исходная строка).
* Тот же payload_id и payload == исходник → ретрай маскирования (та же маска).
* Тот же payload_id и другой текст: если в нём есть наши маски — демаскирование
  по фрагментам (ответ LLM), иначе — это новый текст, маскируем заново.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

from app.core.engine import DetectionEngine
from app.core.masking import Masker, unmask_fragments
from app.core.policy import SystemPolicy
from app.storage.base import MappingRecord, MappingStore


class Direction(str, Enum):
    MASK = "mask"
    MASK_RETRY = "mask_retry"
    UNMASK = "unmask"
    UNMASK_FRAGMENTS = "unmask_fragments"


class UnmaskForbiddenError(Exception):
    """Системе запрещено демаскирование."""


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    result: str
    direction: Direction
    pd_types: dict[str, int] = field(default_factory=dict)


class Processor:
    def __init__(self, engine: DetectionEngine, masker: Masker, store: MappingStore) -> None:
        self._engine = engine
        self._masker = masker
        self._store = store

    async def process(self, payload_id: str, payload: str, policy: SystemPolicy) -> ProcessOutcome:
        record = await self._store.get(payload_id)
        if record is None:
            outcome, record = self._mask(payload, policy)
            if await self._store.put_if_absent(payload_id, record):
                return outcome
            # Параллельный ретрай успел сохранить запись первым — отвечаем по ней.
            stored = await self._store.get(payload_id)
            if stored is None:
                return outcome
            record = stored
        return await self._existing(payload_id, payload, record, policy)

    async def _existing(
        self, payload_id: str, payload: str, record: MappingRecord, policy: SystemPolicy
    ) -> ProcessOutcome:
        if payload == record.masked:
            if record.masked != record.original and not policy.unmask_allowed:
                raise UnmaskForbiddenError(policy.system_id)
            return ProcessOutcome(record.original, Direction.UNMASK)
        if payload == record.original:
            return ProcessOutcome(record.masked, Direction.MASK_RETRY)
        restored, replaced = unmask_fragments(payload, record.fragments)
        if replaced:
            if not policy.unmask_allowed:
                raise UnmaskForbiddenError(policy.system_id)
            return ProcessOutcome(restored, Direction.UNMASK_FRAGMENTS)
        outcome, new_record = self._mask(payload, policy)
        await self._store.put(payload_id, new_record)
        return outcome

    def _mask(self, text: str, policy: SystemPolicy) -> tuple[ProcessOutcome, MappingRecord]:
        entities = self._engine.detect(text, policy.pd_types, policy.combinations)
        masked = self._masker.mask(text, entities, policy.rules)
        counts = Counter(e.pd_type.value for e in entities)
        record = MappingRecord(original=text, masked=masked.text, fragments=masked.fragments)
        return ProcessOutcome(masked.text, Direction.MASK, dict(counts)), record
