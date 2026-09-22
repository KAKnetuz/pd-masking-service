"""Детектор дат: дата рождения, дата выдачи документа, прочие даты рядом с ПД.

Форматы (ТЗ 4.2): дд.мм.гггг, мм.дд.гггг, дд/мм/гг, гггг.мм.дд, гггг.дд.мм, ISO,
«12 марта 1990», «12 мар. 1990 г.», «12-го марта 1990 года», «март 1990».
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date

from app.core.detectors.base import FLAGS, Detector, cue_before
from app.core.entities import Entity, PDType, make_entity

_MONTHS = (
    r"январ[яье]|феврал[яье]|март[аеу]?|апрел[яье]|ма[яйе]|июн[яье]|июл[яье]|август[аеу]?"
    r"|сентябр[яье]|октябр[яье]|ноябр[яье]|декабр[яье]"
    r"|янв|фев|мар|апр|июн|июл|авг|сен|сент|окт|ноя|дек"
    r"|january|february|march|april|may|june|july|august|september|october|november|december"
)

_NUMERIC_DMY_RE = re.compile(r"(?<![\d.\-/])(\d{1,2})([./\-])(\d{1,2})\2(\d{4}|\d{2})(?![\d.\-/]\d|\d)")
_NUMERIC_YMD_RE = re.compile(r"(?<![\d.\-/])(\d{4})([./\-])(\d{1,2})\2(\d{1,2})(?![\d.\-/]\d|\d)")
_TEXT_DATE_RE = re.compile(
    r"(?<!\d)(\d{1,2})(?:-?го)?\s+(" + _MONTHS + r")\.?\s+(\d{4})",
    FLAGS,
)
_MONTH_YEAR_RE = re.compile(
    r"(?<![\dА-Яа-яЁё])(" + _MONTHS + r")\.?\s+(\d{4})", FLAGS
)

_BIRTH_CUE_RE = re.compile(
    r"рожд|родил|\bд\.\s?р\.?|\bдр\b|\bг\.\s?р\.|date\s+of\s+birth|\bdob\b|birth", FLAGS
)
_BIRTH_AFTER_RE = re.compile(r"\s*(?:г\.\s?р\.|года\s+рождения|г\.\s?рожд)", FLAGS)
_ISSUE_CUE_RE = re.compile(r"выда[нчв]|выдачи|issued|date\s+of\s+issue", FLAGS)

# Дата без контекста маскируется, только если в тексте есть ПД конкретного человека.
_PERSON_TYPES = frozenset(
    {PDType.FIO, PDType.PASSPORT, PDType.DRIVER_LICENSE, PDType.BIRTH_PLACE, PDType.INN}
)


def _valid_numeric(a: int, b: int, year: int) -> bool:
    """Дата корректна при любом порядке дня и месяца (дд.мм или мм.дд)."""
    if not 1 <= year <= 2100:
        return False
    return (1 <= a <= 31 and 1 <= b <= 12) or (1 <= a <= 12 and 1 <= b <= 31)


def _normalize_year(raw: str) -> int:
    year = int(raw)
    if len(raw) == 2:
        year += 1900 if year > date.today().year % 100 else 2000
    return year


def _classify(text: str, start: int, end: int, year: int, shift: int = 0) -> Entity | None:
    parts = [(start, end)]
    if cue_before(text, start, _BIRTH_CUE_RE, window=35) or _BIRTH_AFTER_RE.match(text, end):
        return make_entity(PDType.BIRTH_DATE, parts, priority=64 + shift)
    # Орган выдачи может быть длинным: «выдан ОВД района ... г. Москвы 12.03.2010».
    if cue_before(text, start, _ISSUE_CUE_RE, window=90):
        return make_entity(PDType.PASSPORT_ISSUE_DATE, parts, priority=64 + shift)
    if 1900 <= year <= date.today().year:
        return make_entity(PDType.DATE, parts, priority=35 + shift, requires_any=_PERSON_TYPES)
    return None


class DateDetector(Detector):
    types = frozenset({PDType.BIRTH_DATE, PDType.PASSPORT_ISSUE_DATE, PDType.DATE})
    needs_digits = True

    def detect(self, text: str) -> Iterator[Entity | None]:
        for m in _NUMERIC_DMY_RE.finditer(text):
            year = _normalize_year(m.group(4))
            if _valid_numeric(int(m.group(1)), int(m.group(3)), year):
                yield _classify(text, m.start(), m.end(), year)
        for m in _NUMERIC_YMD_RE.finditer(text):
            year = int(m.group(1))
            if _valid_numeric(int(m.group(3)), int(m.group(4)), year):
                yield _classify(text, m.start(), m.end(), year)
        for m in _TEXT_DATE_RE.finditer(text):
            if 1 <= int(m.group(1)) <= 31:
                yield _classify(text, m.start(), m.end(), int(m.group(3)))
        for m in _MONTH_YEAR_RE.finditer(text):
            yield _classify(text, m.start(), m.end(), int(m.group(2)), shift=-5)
