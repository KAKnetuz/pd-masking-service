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

from app.core.engine import DetectionEngine
from app.core.masking import Masker
from app.core.policy import load_policies
from app.core.processor import Processor
from app.storage.codec import RecordCodec
from app.storage.memory import MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / "span_audit_report.txt"
AUDIT_TTL_SECONDS = 60

# (номер, название, текст)
EXAMPLES: list[tuple[int, str, str]] = [
    (1, "ФИО", "Клиент Иванов Иван Иванович обратился в банк."),
    (2, "ФИО верхний регистр", "КЛИЕНТ ПЕТРОВА АННА СЕРГЕЕВНА ПРОСИТ ПЕРЕЗВОНИТЬ."),
    (3, "ФИО нижний регистр", "звонил иванов иван иванович по поводу вклада."),
    (4, "Дата дд.мм.гггг", "Дата рождения: 12.03.1990."),
    (5, "Дата мм.дд.гггг", "Дата рождения 03.25.1990."),
    (6, "Дата гггг.дд.мм", "Дата рождения 1990.25.03."),
    (7, "Дата текстом", "Она родилась 12 марта 1990 года в Москве."),
    (8, "Место рождения", "Место рождения: г. Краснодар."),
    (9, "Паспорт", "Паспорт 4509 123456."),
    (10, "Паспорт серия номер", "Паспорт серия 4510 номер 654321."),
    (11, "Паспорт серии №", "Паспорт серии 45 09 № 123456."),
    (12, "Гражданство", "Гражданство: Российская Федерация."),
    (13, "Орган выдачи", "Паспорт выдан ОУФМС России по г. Москве."),
    (14, "Код подразделения", "Код подразделения 770-001."),
    (15, "Дата выдачи", "Дата выдачи паспорта 15.06.2015."),
    (16, "ВУ", "Водительское удостоверение 77 АВ 123456."),
    (17, "ВУ цифрами", "Водительское удостоверение 9901 123456."),
    (18, "Адрес", "Проживает по адресу: 350000, Россия, г. Краснодар, ул. Красная, д. 10, кв. 5."),
    (19, "Email", "Пишите на ivan.petrov@mail.ru."),
    (20, "Телефон 1", "Телефон +7 (916) 123-45-67."),
    (21, "Телефон 2", "Мой номер 89161234567."),
    (22, "ИНН", "ИНН 500100732259."),
    (23, "Карта", "Номер карты 2200 1234 5678 9019."),
    (24, "CVV", "CVV 123."),
    (25, "PIN один", "Пин-код 4321."),
    (26, "Карта полностью", "Карта 2200 1234 5678 9019, держатель IVAN IVANOV, CVV 123, пин-код 4321."),
    (27, "Ловушка Пушкин", "Александр Пушкин написал «Евгения Онегина»."),
    (28, "Ловушка отделение", "Отделение банка находится по адресу: г. Москва, ул. Каланчевская, д. 27."),
    (29, "Без ПД", "Какие документы нужны для открытия вклада?"),
    (
        30,
        "Сложное предложение",
        "Клиент Сидоров Пётр Алексеевич, 05.11.1985 г.р., паспорт серия 4511 номер 987654 "
        "выдан ОУФМС России по г. Краснодару 20.01.2010, код подразделения 230-001, проживает: "
        "г. Краснодар, ул. Северная, д. 5, кв. 12, тел. +7 918 555-44-33, email sidorov@yandex.ru, "
        "ИНН 500100732259, просит перевыпустить карту 2200 1234 5678 9019.",
    ),
]


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
    for number, title, text in EXAMPLES:
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
