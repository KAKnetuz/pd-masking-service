"""Форма текста без содержимого — для отладки распознавания (DEBUG_SHAPES).

Буквы и цифры заменяются классом символа, поэтому значения ПД по форме не восстановить.
Как есть остаются только служебные слова из фиксированного словаря ниже (это словарь
сервиса, а не данные клиента), пробелы и знаки препинания.
"""

from __future__ import annotations

import re

MAX_SHAPE_CHARS = 120

SERVICE_WORDS: frozenset[str] = frozenset(
    """
    паспорт паспорта серия номер выдан выдана дата рождения место код подразделения
    гражданство гражданин гражданка тел телефон моб email e-mail почта адрес индекс
    г город ул улица д дом кв квартира корп стр обл область край район р-н респ
    карта карты срок действия до cvv cvc cvc2 cvv2 pin пин пин-код держатель инн снилс
    ву водительское удостоверение права фио клиент клиентка имя фамилия отчество страна
    """.split()
)

_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+(?:-[0-9A-Za-zА-Яа-яЁё]+)*")


def _char_class(ch: str) -> str:
    if ch.isdigit():
        return "9"
    if "a" <= ch.lower() <= "z":
        return "X" if ch.isupper() else "x"
    if ch.isalpha():
        return "А" if ch.isupper() else "а"
    return ch


def _token_shape(token: str) -> str:
    lowered = token.lower()
    if lowered in SERVICE_WORDS:
        return lowered
    return "".join(_char_class(ch) for ch in token)


def text_shape(text: str) -> str:
    """Возвращает форму текста: «Срок действия: 12/27» → «срок действия: 99/99»."""
    shaped = _TOKEN_RE.sub(lambda m: _token_shape(m.group(0)), text)
    return shaped[:MAX_SHAPE_CHARS]
