"""Значения ПД после меток и формы записи из датасета проверяющей системы.

Детектор дополняет остальные и заполняет их пробелы:
* паспорт/ВУ, где серия и номер разделены словами и знаками («Серия: 4509; номер: 123456»,
  «номер 123456 серия 4509», «сер. 4509 № 123456»);
* даты после меток «дата рождения» / «дата выдачи» со вставкой слов до двоеточия,
  с месяцем словом или сокращением, двузначным годом или без года;
* ФИО после меток «имя», «отчество», «ФИО», «на имя» и после слова «клиент»;
* ФИО как весь текст: двойные имена, инициалы, смешанный регистр, иностранные имена;
* гражданство после метки — значение из нескольких слов до конца предложения.

Приоритет сущностей ниже, чем у основных детекторов: при пересечении побеждает
основной детектор, этот только заполняет пропуски. Поиск не зависит от регистра.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from app.core.detectors.base import FLAGS, Detector
from app.core.detectors.names_data import (
    FAMOUS_SURNAME_RE,
    NOT_SURNAMES,
    PATRONYMIC_RE,
    SURNAME_RE,
    is_first_name,
)
from app.core.entities import Entity, PDType, make_entity

_PRIORITY = 45
# Правило «весь текст — имя» применяется только к коротким текстам.
_MAX_WHOLE_NAME_CHARS = 80

# --- Паспорт / ВУ ------------------------------------------------------------
_SERIES = r"(?:серия|серии|серией|сер\.)"
_NUMBER = r"(?:номер|номером|№)"
_SEP = r"\s*[:—–-]?\s*"
_SERIES_VALUE = r"(\d{2}\s?\d{2})(?!\d)"
_NUMBER_VALUE = r"(\d{6})(?!\d)"
_GAP = r"[^\d\n]{0,25}?"

_SERIES_FIRST_RE = re.compile(_SERIES + _SEP + _SERIES_VALUE + _GAP + _NUMBER + _SEP + _NUMBER_VALUE, FLAGS)
_NUMBER_FIRST_RE = re.compile(_NUMBER + _SEP + _NUMBER_VALUE + _GAP + _SERIES + _SEP + _SERIES_VALUE, FLAGS)
_LICENSE_CUE_RE = re.compile(r"удостоверени|\bву\b|\bправа\b|водительск", FLAGS)

# --- Даты после метки ---------------------------------------------------------
_MONTH = (
    r"(?:январ[яье]|феврал[яье]|март[аеу]?|апрел[яье]|ма[яйе]|июн[яье]|июл[яье]|август[аеу]?"
    r"|сентябр[яье]|октябр[яье]|ноябр[яье]|декабр[яье]"
    r"|янв|фев|мар|апр|июн|июл|авг|сент|сен|окт|ноя|дек)"
)
_DATE_LABEL_RE = re.compile(r"дата\s+(рождения|выдачи)[^:\n.]{0,60}?:\s*", FLAGS)
_MONTH_WORD = r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
# Дата прописью: «пятнадцатое марта тысяча девятьсот девяностого года».
_DATE_IN_WORDS = r"[а-яё]+(?:\s+[а-яё]+)?\s+" + _MONTH_WORD + r"(?:\s+[а-яё]+){1,5}?\s+года"
_LABELLED_DATE_RE = re.compile(
    r"(\d{1,2}[\s-]" + _MONTH + r"(?:\.?[\s-](\d{4}|\d{2}))?|\d{1,2}\s\d{2}\s(\d{2}|\d{4})"
    r"|\d{1,2}[/\s]\d{2}(?![\d/])|" + _DATE_IN_WORDS + r")(?![\d\w])",
    FLAGS,
)

# --- Имена --------------------------------------------------------------------
_WORD = r"[А-ЯЁа-яё]+(?:['’][А-ЯЁа-яё]+)?"
_NAME_TOKEN = _WORD + r"(?:[-/]" + _WORD + r")*"
_INITIAL = r"[А-ЯЁа-яё]\."
_NAME_VALUE = r"(?:" + _NAME_TOKEN + r"|" + _INITIAL + r")(?:\s+(?:" + _NAME_TOKEN + r"|" + _INITIAL + r")){0,3}"
_WHOLE_NAME_RE = re.compile(_NAME_VALUE)
_TOKEN_SPLIT_RE = re.compile(r"[\s/-]+")
_INITIAL_RE = re.compile(r"^[А-ЯЁа-яё]\.$")
_TRAILING_NOTE_RE = re.compile(r"\s*\([^()]*\)\s*$")
_NAME_LABEL_RE = re.compile(r"(?:\bотчество|\bимя|\bфио|\bна\s+имя)\b[^:\n]{0,40}?:\s*", FLAGS)
_CLIENT_NAME_RE = re.compile(
    r"\b(?:клиент|клиентка|гражданин|гражданка)\s+(" + _WORD + r"(?:\s+[А-ЯЁа-яё]\.)?)",
    FLAGS,
)
_NOT_NAME_WORDS = frozenset(
    """
    спасибо добрый доброе добрая день утро вечер здравствуйте привет карта карты заблокирована
    банк банка альфа альфа-банк сбербанк клиент клиентка счёт счет вклад кредит перевод
    """.split()
)

# --- Гражданство ----------------------------------------------------------------
_CITIZENSHIP_LABEL_RE = re.compile(r"гражданств\w*[^:\n]{0,40}?:\s*", FLAGS)
_CITIZENSHIP_VALUE_RE = re.compile(r"[А-ЯЁ][А-ЯЁа-яё-]*(?:[\s/]+[А-ЯЁ][А-ЯЁа-яё-]*){0,3}")


def _is_initial(token: str) -> bool:
    return _INITIAL_RE.match(token) is not None


def _is_name_word(word: str) -> bool:
    lower = word.casefold().strip(".")
    if lower in NOT_SURNAMES or lower in _NOT_NAME_WORDS:
        return False
    return bool(SURNAME_RE.match(lower) or is_first_name(lower) or PATRONYMIC_RE.match(lower))


def _has_apostrophe(token: str) -> bool:
    return "'" in token or "’" in token


def _token_is_strong(token: str) -> bool:
    """Токен точно указывает на имя: инициал, имя/фамилия/отчество, иностранное имя с апострофом."""
    if _is_initial(token) or _has_apostrophe(token):
        return True
    return any(_is_name_word(part) for part in _TOKEN_SPLIT_RE.split(token) if part)


def _token_is_allowed(token: str) -> bool:
    """Токен допустим в имени: сильный или написан с заглавной буквы («Шмидт»)."""
    return _token_is_strong(token) or token[:1].isupper()


def _looks_like_name(value: str) -> bool:
    """Все слова похожи на части имени и хотя бы одно — точно имя, фамилия, отчество или инициал."""
    tokens = value.split()
    parts = [p.casefold() for p in _TOKEN_SPLIT_RE.split(value) if p]
    if any(p.strip(".") in _NOT_NAME_WORDS for p in parts):
        return False
    if any(FAMOUS_SURNAME_RE.match(p) for p in parts):
        return False
    if not all(_token_is_allowed(t) for t in tokens):
        return False
    return any(_token_is_strong(t) for t in tokens)


class LabelledValueDetector(Detector):
    """Значения после меток и формы записи из датасета."""

    types = frozenset(
        {
            PDType.PASSPORT,
            PDType.DRIVER_LICENSE,
            PDType.BIRTH_DATE,
            PDType.PASSPORT_ISSUE_DATE,
            PDType.FIO,
            PDType.CITIZENSHIP,
        }
    )

    def detect(self, text: str) -> Iterator[Entity | None]:
        yield from self._documents(text)
        yield from self._dates(text)
        yield from self._labelled_names(text)
        yield from self._client_names(text)
        yield from self._whole_name(text)
        yield from self._citizenship(text)

    # --- паспорт / ВУ ---
    @staticmethod
    def _document_type(text: str, start: int) -> PDType:
        window = text[max(0, start - 60) : start]
        return PDType.DRIVER_LICENSE if _LICENSE_CUE_RE.search(window) else PDType.PASSPORT

    def _documents(self, text: str) -> Iterator[Entity | None]:
        for m in _SERIES_FIRST_RE.finditer(text):
            pd_type = self._document_type(text, m.start())
            yield make_entity(pd_type, [m.span(1), m.span(2)], priority=_PRIORITY)
        for m in _NUMBER_FIRST_RE.finditer(text):
            pd_type = self._document_type(text, m.start())
            yield make_entity(pd_type, [m.span(1), m.span(2)], priority=_PRIORITY)

    # --- даты ---
    @staticmethod
    def _dates(text: str) -> Iterator[Entity | None]:
        for label in _DATE_LABEL_RE.finditer(text):
            m = _LABELLED_DATE_RE.match(text, label.end())
            if m is None:
                continue
            year = m.group(2) or m.group(3)
            if year and len(year) == 4 and int(year) < 1900:
                continue
            pd_type = PDType.BIRTH_DATE if label.group(1).lower() == "рождения" else PDType.PASSPORT_ISSUE_DATE
            yield make_entity(pd_type, [m.span(1)], priority=_PRIORITY)

    # --- имена ---
    @staticmethod
    def _labelled_names(text: str) -> Iterator[Entity | None]:
        for label in _NAME_LABEL_RE.finditer(text):
            m = _WHOLE_NAME_RE.match(text, label.end())
            if m is None or not m.group(0)[:1].isupper():
                continue
            if not _looks_like_name(m.group(0)):
                continue
            yield make_entity(PDType.FIO, [m.span(0)], priority=_PRIORITY)

    @staticmethod
    def _client_names(text: str) -> Iterator[Entity | None]:
        for m in _CLIENT_NAME_RE.finditer(text):
            first_word = m.group(1).split()[0]
            if is_first_name(first_word.casefold()) and first_word.casefold() not in _NOT_NAME_WORDS:
                yield make_entity(PDType.FIO, [m.span(1)], priority=_PRIORITY)

    @staticmethod
    def _whole_name(text: str) -> Iterator[Entity | None]:
        stripped = text.strip()
        if len(stripped) > _MAX_WHOLE_NAME_CHARS:
            return
        note = _TRAILING_NOTE_RE.search(stripped)
        value = stripped[: note.start()] if note else stripped
        value = value.rstrip(",;!")
        if not value or _WHOLE_NAME_RE.fullmatch(value) is None:
            return
        if not _looks_like_name(value):
            return
        start = text.find(value)
        yield make_entity(PDType.FIO, [(start, start + len(value))], priority=_PRIORITY)

    # --- гражданство ---
    @staticmethod
    def _citizenship(text: str) -> Iterator[Entity | None]:
        for label in _CITIZENSHIP_LABEL_RE.finditer(text):
            m = _CITIZENSHIP_VALUE_RE.match(text, label.end())
            if m is not None:
                yield make_entity(PDType.CITIZENSHIP, [m.span(0)], priority=_PRIORITY)
