"""Аудит маскирования/демаскирования ПД для политики "default".

Загружает политику "default" тем же способом, что и сервис (config/systems.yaml),
для каждого примера выполняет маскирование и демаскирование и пишет отчёт
в span_audit_report.txt в корне репозитория.

Код сервиса (app/) не изменяется — используются его публичные компоненты.

Запуск из корня репозитория: python -m scripts.span_audit
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import yaml

from app.core.engine import DetectionEngine
from app.core.masking import Masker
from app.core.policy import load_policies
from app.core.processor import Processor
from app.storage.codec import RecordCodec
from app.storage.memory import MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / "span_audit_report.txt"
FIXTURES_PATH = REPO_ROOT / "tests" / "fixtures" / "span_reference.yaml"
AUDIT_TTL_SECONDS = 60


def _load_examples() -> list[tuple[int, str, str]]:
    """Читает примеры (id, title, text) из эталонного YAML."""
    cases = yaml.safe_load(FIXTURES_PATH.read_text(encoding="utf-8")) or []
    return [(case["id"], case["title"], case["text"]) for case in cases]


def _found_lines(text: str, entities) -> list[str]:
    """Строки отчёта «НАЙДЕНО»: по строке на сущность в порядке позиции."""
    lines: list[str] = []
    for entity in entities:
        parts = " ".join(
            f"[{start}:{end}] «{text[start:end]}»" for start, end in entity.parts
        )
        lines.append(f"  {entity.pd_type.value} части: {parts}")
    return lines


async def run() -> str:
    policies = load_policies(REPO_ROOT / "config" / "systems.yaml")
    policy = policies.resolve(None)  # политика "default"

    engine = DetectionEngine()
    masker = Masker(os.urandom(32))
    store = MemoryStore(RecordCodec(os.urandom(32)), AUDIT_TTL_SECONDS)
    proc = Processor(engine, masker, store)

    blocks: list[str] = []
    for number, title, text in _load_examples():
        payload_id = f"audit-{number}"

        entities = engine.detect(text, policy.pd_types, policy.combinations)

        start = time.perf_counter()
        masked = await proc.process(payload_id, text, policy)
        elapsed_ms = (time.perf_counter() - start) * 1000

        restored = await proc.process(payload_id, masked.result, policy)
        unmask_ok = restored.result == text

        block = [
            f"=== {number}. {title} ===",
            f"ИСХОДНИК: {text}",
            f"МАСКА:    {masked.result}",
            "НАЙДЕНО:",
        ]
        block.extend(_found_lines(text, entities) or ["  (ничего не найдено)"])
        block.append(f"ДЕМАСКА СОВПАЛА: {'да' if unmask_ok else 'нет'}")
        block.append(f"ВРЕМЯ: {elapsed_ms:.1f}")
        blocks.append("\n".join(block))

    return "\n\n".join(blocks) + "\n"


def main() -> None:
    report = asyncio.run(run())
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Отчёт записан: {REPORT_PATH}")


if __name__ == "__main__":
    main()
