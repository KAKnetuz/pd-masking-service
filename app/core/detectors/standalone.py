"""Детектор «голых значений»: весь текст — одно значение ПД без слов-подсказок.

Срабатывает только когда весь текст (без пробелов по краям и конечной пунктуации
`. , ; !`) совпадает с одним форматом ПД. Контрольные суммы не проверяются — в
датасете значения часто записаны с неверными суммами (синтетика), а пропуск ПД
штрафуется сильнее лишней маски. В предложениях правило не применяется.

Идентификация не зависит от регистра (ТЗ): страны, месяцы в датах, буквы серии ВУ,
имена держателя карты сравниваются без учёта регистра.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from app.core.detectors.base import FLAGS, Detector
from app.core.detectors.names_data import (
    CITIES,
    FAMOUS_SURNAME_RE,
    NOT_SURNAMES,
    PATRONYMIC_RE,
    SURNAME_RE,
    is_first_name,
)
from app.core.entities import Entity, PDType, make_entity

# Страны для «голого значения» гражданства (нижний регистр, сравнение через casefold).
_COUNTRIES = frozenset(
    {
        "россия", "рф", "российская федерация", "украина", "беларусь", "республика беларусь",
        "казахстан", "республика казахстан", "узбекистан", "армения", "азербайджан",
        "киргизия", "таджикистан", "молдова", "грузия",
    }
)

_MONTHS = (
    r"январ[яье]|феврал[яье]|март[аеу]?|апрел[яье]|ма[яйе]|июн[яье]|июл[яье]|август[аеу]?"
    r"|сентябр[яье]|октябр[яье]|ноябр[яье]|декабр[яье]"
    r"|янв|фев|мар|апр|июн|июл|авг|сен|сент|окт|ноя|дек"
)

# Форматы «голых значений»: (регэксп, тип). Проверяются по порядку.
# Паспорт с пробелами («4509 123456») обрабатывают обычные детекторы — здесь не дублируем.
_FORMATS: list[tuple[re.Pattern[str], PDType]] = [
    (re.compile(r"^\d{3}$"), PDType.CARD_CVV),
    (re.compile(r"^(0[1-9]|1[0-2])[/.](\d{2}|\d{4})$"), PDType.CARD_EXPIRY),
    (re.compile(r"^\d{2} [А-ЯЁа-яё]{2} \d{6}$"), PDType.DRIVER_LICENSE),
    (re.compile(r"^\d{10}$"), PDType.PASSPORT),
    (re.compile(r"^\d{12}$"), PDType.INN),
    (re.compile(r"^\d{3}-\d{3}$"), PDType.DEPARTMENT_CODE),
    (re.compile(r"^\d{6}$"), PDType.ADDRESS),
]

# Даты: год >= 1900 (исторические даты — не ПД клиента, как в DateDetector).
_DATE_DMY_RE = re.compile(r"^\d{1,2}[./-]\d{1,2}[./-](\d{4})$")
_DATE_YMD_RE = re.compile(r"^(\d{4})[./-]\d{1,2}[./-]\d{1,2}$")
_DATE_TEXT_RE = re.compile(r"^\d{1,2}(?:-?го)?\s+(" + _MONTHS + r")\.?\s+(\d{4})$", FLAGS)

# Номер карты: 16–19 цифр (с пробелами/дефисами).
_CARD_NUMBER_RE = re.compile(r"^[\d \-]{16,19}$")
# Телефон.
_PHONE_RE = re.compile(r"^(\+7\d{10}|8 \d{3} \d{3} \d{2} \d{2})$")
# Email.
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._%+-]{0,62}[A-Za-z0-9_%+-])?@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$"
)
# Орган выдачи без слова «выдан»: «ГУ МВД России по г. Москве».
_ISSUER_RE = re.compile(
    r"^(?:ГУ\s+)?(?:МВД|ФМС|ОВД|УВД|УФМС|ОУФМС|ОМВД|ГИБДД|РЭО|ТП|отдел\w*|управлени\w*|паспортн\w*)\b"
    r"(?:\s+России(?:\s+по\s+.+)?|\s+по\s+.+)$",
    FLAGS,
)
# Две-три латинские слова в любом регистре — имя держателя карты.
_CARD_HOLDER_RE = re.compile(r"^[A-Za-z]{2,}(?: [A-Za-z]{2,}){1,2}$")
_LATIN_STOPWORDS = frozenset(
    {
        "cvv", "cvc", "pin", "visa", "mastercard", "mir", "maestro", "valid", "thru", "exp",
        "card", "bank", "number", "holder", "name", "unionpay", "amex", "code", "date",
    }
)


def _strip(text: str) -> str:
    return text.strip().rstrip(".,;!")


class StandaloneValueDetector(Detector):
    """«Голое значение»: весь текст — одно значение ПД."""

    types = frozenset(
        {
            PDType.CARD_CVV, PDType.CARD_PIN, PDType.CARD_EXPIRY, PDType.DATE,
            PDType.PASSPORT, PDType.DRIVER_LICENSE, PDType.DEPARTMENT_CODE, PDType.ADDRESS,
            PDType.INN, PDType.CARD_NUMBER, PDType.CARD_HOLDER, PDType.CITIZENSHIP,
            PDType.PASSPORT_ISSUER, PDType.PHONE, PDType.EMAIL, PDType.FIO,
        }
    )

    def detect(self, text: str) -> Iterator[Entity | None]:
        stripped = _strip(text)
        if not stripped:
            return
        start = text.find(stripped)
        end = start + len(stripped)
        pd_type = self._classify(stripped)
        if pd_type is None:
            return
        yield make_entity(pd_type, [(start, end)], priority=90)

    @classmethod
    def _classify(cls, value: str) -> PDType | None:
        # 4 цифры → pin, кроме годов 1900–2099 (год — не ПД).
        if re.fullmatch(r"\d{4}", value):
            year = int(value)
            if not 1900 <= year <= 2099:
                return PDType.CARD_PIN
            return None
        for pattern, pd_type in _FORMATS:
            if pattern.fullmatch(value):
                return pd_type
        # Даты: год >= 1900.
        date_type = cls._classify_date(value)
        if date_type is not None:
            return date_type
        if _CARD_NUMBER_RE.fullmatch(value):
            digits = "".join(ch for ch in value if ch.isdigit())
            if 16 <= len(digits) <= 19:
                return PDType.CARD_NUMBER
        if _PHONE_RE.fullmatch(value):
            return PDType.PHONE
        if _EMAIL_RE.fullmatch(value):
            return PDType.EMAIL
        if _ISSUER_RE.fullmatch(value):
            return PDType.PASSPORT_ISSUER
        if _CARD_HOLDER_RE.fullmatch(value):
            words = value.casefold().split()
            if not any(w in _LATIN_STOPWORDS for w in words):
                return PDType.CARD_HOLDER
        if value.casefold() in _COUNTRIES:
            return PDType.CITIZENSHIP
        # Одиночное слово: имя/фамилия/отчество или город.
        if " " not in value:
            return cls._classify_single_word(value)
        return None

    @staticmethod
    def _classify_date(value: str) -> PDType | None:
        m = _DATE_DMY_RE.fullmatch(value)
        if m:
            return PDType.DATE if int(m.group(1)) >= 1900 else None
        m = _DATE_YMD_RE.fullmatch(value)
        if m:
            return PDType.DATE if int(m.group(1)) >= 1900 else None
        m = _DATE_TEXT_RE.fullmatch(value)
        if m:
            return PDType.DATE if int(m.group(2)) >= 1900 else None
        return None

    @staticmethod
    def _classify_single_word(value: str) -> PDType | None:
        lower = value.casefold()
        # Город.
        if lower in CITIES:
            return PDType.ADDRESS
        # Имя/фамилия/отчество. Известные люди и слова-не-фамилии не маскируются.
        if lower in NOT_SURNAMES:
            return None
        if FAMOUS_SURNAME_RE.match(lower):
            return None
        if SURNAME_RE.match(lower) or is_first_name(lower) or PATRONYMIC_RE.match(lower):
            return PDType.FIO
        return None
