"""Уточнение границ найденного ФИО: инициалы и отчество рядом с именем.

Детекторы находят ядро ФИО («Иван Петрович», «Иванов И»), а соседние части остаются
открытыми: «И. Иван Петрович», «Иван Иванов Петрович», «Иван Петрович И.». Функция
расширяет интервал на такие части. Регистр не важен.
"""

from __future__ import annotations

import re

from app.core.detectors.names_data import PATRONYMIC_RE

# Инициал слева: «И. Иван», «И.Иван» (перед буквой инициала — не буква).
_LEFT_INITIAL_RE = re.compile(r"(?<![A-Za-zА-ЯЁа-яё.])([A-Za-zА-ЯЁа-яё])\.\s?$")
# Инициалы справа: « И.», « И. П.», « И.П.» (после точки не должна идти буква того же слова).
_RIGHT_INITIALS_RE = re.compile(r"\s{1,2}([А-ЯЁа-яёA-Z]\.(?:\s?[А-ЯЁа-яёA-Z]\.)?)(?![А-ЯЁа-яёA-Za-z])")
_RIGHT_WORD_RE = re.compile(r"\s{1,2}([А-ЯЁа-яё]+)(?![А-ЯЁа-яё\-])")
# Ядро заканчивается одиночной буквой-инициалом без точки: «Иванов И» + «.».
_TRAILING_INITIAL_RE = re.compile(r"(?:^|\s)[А-ЯЁа-яёA-Za-z]$")

_MAX_STEPS = 3


def _extend_right(text: str, end: int) -> int:
    for _ in range(_MAX_STEPS):
        m = _RIGHT_INITIALS_RE.match(text, end)
        if m:
            end = m.end(1)
            continue
        w = _RIGHT_WORD_RE.match(text, end)
        if w and PATRONYMIC_RE.match(w.group(1).lower()):
            end = w.end(1)
            continue
        break
    return end


def extend_person_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Расширяет интервал ФИО на соседние инициалы и отчество."""
    left = _LEFT_INITIAL_RE.search(text, max(0, start - 4), start)
    if left and left.end() == start:
        start = left.start(1)
    if end < len(text) and text[end] == "." and _TRAILING_INITIAL_RE.search(text, start, end):
        end += 1
    return start, _extend_right(text, end)
