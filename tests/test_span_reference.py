"""Регрессионные тесты границ фрагментов ПД по эталону span_reference.yaml.

Проверяют три свойства для каждого из 30 эталонных примеров:
1. Найденные сущности (тип + подстроки частей) в порядке позиции точно равны expected.
2. Маскирование → демаскирование той же маской возвращает исходный текст.
3. Ни одна подстрока из expected.parts не встречается в замаскированном тексте целиком.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

import pytest
import yaml

from app.core.engine import DetectionEngine
from app.core.masking import Masker
from app.core.policy import load_policies
from app.core.processor import Processor
from app.storage.codec import RecordCodec
from app.storage.memory import MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "span_reference.yaml"

POLICIES = load_policies(REPO_ROOT / "config" / "systems.yaml")
POLICY = POLICIES.resolve(None)  # политика "default"

CASES = yaml.safe_load(FIXTURES.read_text(encoding="utf-8")) or []


def _ids() -> list[str]:
    return [f"{case['id']}-{case['title']}" for case in CASES]


def _processor() -> Processor:
    return Processor(
        DetectionEngine(),
        Masker(os.urandom(32)),
        MemoryStore(RecordCodec(os.urandom(32)), 60),
    )


def _found(text: str) -> list[tuple[str, list[str]]]:
    engine = DetectionEngine()
    entities = engine.detect(text, POLICY.pd_types, POLICY.combinations)
    return [(e.pd_type.value, [text[s:e] for s, e in e.parts]) for e in entities]


@pytest.mark.parametrize("case", CASES, ids=_ids())
def test_span_boundaries(case: dict) -> None:
    expected = [(item["type"], list(item["parts"])) for item in case["expected"]]
    assert _found(case["text"]) == expected


@pytest.mark.parametrize("case", CASES, ids=_ids())
def test_mask_unmask_roundtrip(case: dict) -> None:
    async def scenario() -> None:
        proc = _processor()
        payload_id = f"ref-{case['id']}"
        masked = await proc.process(payload_id, case["text"], POLICY)
        restored = await proc.process(payload_id, masked.result, POLICY)
        assert restored.result == case["text"]

    asyncio.run(scenario())


@pytest.mark.parametrize("case", CASES, ids=_ids())
def test_no_leak_of_parts_in_masked(case: dict) -> None:
    async def scenario() -> None:
        proc = _processor()
        masked = (await proc.process(f"ref-{case['id']}", case["text"], POLICY)).result
        for item in case["expected"]:
            for part in item["parts"]:
                # Подстрока не должна остаться открытой как самостоятельный фрагмент
                # (граница слова), чтобы короткие части не давали ложных срабатываний
                # из-за совпадения с другими замаскированными значениями.
                assert not re.search(rf"\b{re.escape(part)}\b", masked), (
                    f"утечка подстроки {part!r} в маске: {masked!r}"
                )

    asyncio.run(scenario())
