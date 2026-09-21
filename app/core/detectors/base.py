"""Базовый класс детектора и общие утилиты."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable

from app.core.entities import Entity, PDType

_DIGIT_RE = re.compile(r"\d")

# Поиск не зависит от регистра (требование ТЗ 4.1).
FLAGS = re.IGNORECASE | re.UNICODE


class Detector(ABC):
    """Детектор одного или нескольких близких типов ПД.

    Чтобы добавить новый тип ПД, достаточно реализовать ``detect`` и
    зарегистрировать детектор в ``registry.py`` — остальной сервис не меняется.
    """

    #: Типы, которые может вернуть детектор (для фильтрации по настройкам системы).
    types: frozenset[PDType] = frozenset()
    #: Нужны ли цифры в тексте. Позволяет дёшево пропустить детектор.
    needs_digits: bool = False

    def applicable(self, has_digits: bool, enabled: frozenset[PDType]) -> bool:
        if not self.types & enabled:
            return False
        return has_digits or not self.needs_digits

    @abstractmethod
    def detect(self, text: str) -> Iterable[Entity | None]:
        """Возвращает кандидатов. Пересечения разрешает движок."""


def text_has_digits(text: str) -> bool:
    return _DIGIT_RE.search(text) is not None


def cue_before(text: str, pos: int, cue: re.Pattern[str], window: int = 40) -> bool:
    """Есть ли контекстное слово в окне ``window`` символов перед позицией."""
    return cue.search(text, max(0, pos - window), pos) is not None


def digits_only(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def luhn_valid(number: str) -> bool:
    """Контрольная сумма Луна для номеров банковских карт."""
    total = 0
    for idx, ch in enumerate(reversed(number)):
        digit = ord(ch) - 48
        if idx % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def inn_valid(inn: str) -> bool:
    """Контрольные разряды ИНН (10 цифр — юрлицо, 12 — физлицо)."""

    def checksum(digits: str, coeffs: tuple[int, ...]) -> int:
        return sum(int(d) * c for d, c in zip(digits, coeffs, strict=False)) % 11 % 10

    if len(inn) == 10:
        return checksum(inn, (2, 4, 10, 3, 5, 9, 4, 6, 8)) == int(inn[9])
    if len(inn) == 12:
        n11 = checksum(inn, (7, 2, 4, 10, 3, 5, 9, 4, 6, 8))
        n12 = checksum(inn, (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8))
        return n11 == int(inn[10]) and n12 == int(inn[11])
    return False


def snils_valid(snils: str) -> bool:
    if len(snils) != 11:
        return False
    body, control = snils[:9], int(snils[9:])
    total = sum(int(d) * (9 - i) for i, d in enumerate(body))
    if total > 101:
        total %= 101
    expected = 0 if total in (100, 101) else total
    return expected == control
