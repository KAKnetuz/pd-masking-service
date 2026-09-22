"""Детекторы банковских реквизитов и контактных данных."""

from __future__ import annotations

import re
from collections.abc import Iterator

from app.core.detectors.base import FLAGS, Detector, cue_before, digits_only, inn_valid, luhn_valid
from app.core.entities import Entity, PDType, make_entity

# --- Банковская карта ---------------------------------------------------------
# Номер карты: группы по 4 (16/19 цифр), формат Amex 4-6-5 или 13–19 цифр подряд.
_CARD_RE = re.compile(
    r"(?<![\d\-])(\d{4}(?:[ \-]\d{4}){3}(?:[ \-]\d{3})?|\d{4}[ \-]\d{6}[ \-]\d{5}|\d{13,19})(?![\d])"
)
_CARD_CUE_RE = re.compile(r"карт|card|visa|master|\bмир\b|maestro|\bpan\b", FLAGS)

_CVV_RE = re.compile(
    r"(?:cvv2?|cvc2?|cvn|cav2|код\w*\s+безопасности|(?:трёх|трех)значн\w+\s+код\w*"
    r"|код\w*\s+(?:на|с)\s+(?:обороте|обратной\s+стороне))\s*(?:код\w*)?\s*[:\-–]?\s*(\d{3,4})(?!\d)",
    FLAGS,
)
_PIN_RE = re.compile(
    r"(?:пин[\-\s]?код\w*|\bпин\b|\bpin(?:[\-\s]?code)?\b)\s*(?:от\s+)?(?:карты\s*)?[:\-–]?\s*(\d{4,6})(?!\d)",
    FLAGS,
)
_EXPIRY_VALUE = r"((?:0[1-9]|1[0-2])\s?[/.\-]\s?(?:\d{4}|\d{2}))(?![\d/]|\.\d)"
_EXPIRY_CTX_RE = re.compile(
    r"(?:срок\w*\s+действия(?:\s+карты)?|exp(?:iry|iration)?(?:\s+date)?|valid\s+(?:thru|through|until))"
    r"\s*[:\-–.]?\s*" + _EXPIRY_VALUE,
    FLAGS,
)
# «действует до 12/27» бывает и у скидки — не считаем сроком карты, если рядом слово скидки/акции.
_EXPIRY_WEAK_CTX_RE = re.compile(
    r"(?:действительн\w*\s+до|действует\s+до|годна\s+до)\s*[:\-–.]?\s*" + _EXPIRY_VALUE, FLAGS
)
_DISCOUNT_CUE_RE = re.compile(
    r"скидк\w*|акци\w*|предложени\w*|тариф\w*|цена|цены|цен\w*|стоимост\w*|промо|бонус\w*|купон\w*",
    FLAGS,
)
_EXPIRY_BARE_RE = re.compile(r"(?<![\d/.])((?:0[1-9]|1[0-2])/\d{2})(?![\d/])")

# --- ИНН ----------------------------------------------------------------------
_INN_CTX_RE = re.compile(r"\bинн\b\s*(?:физ\w*\s+лиц\w*\s*)?[:№\-–]?\s*(\d{12}|\d{10})(?!\d)", FLAGS)
_INN_BARE_RE = re.compile(r"(?<!\d)(\d{12})(?!\d)")
# ИНН организации — не ПД: «Организация с ИНН …», «компания ООО …, ИНН …».
_ORG_CUE_RE = re.compile(
    r"организац|компани|контрагент|поставщик|юр\w*\s+лиц|\bооо\b|\bоао\b|\bзао\b|\bпао\b|\bао\b|\bип\b", FLAGS
)

# --- Контакты -----------------------------------------------------------------
_EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Za-z0-9](?:[A-Za-z0-9._%+-]{0,62}[A-Za-z0-9_%+-])?@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}(?![\w-])"
)
_PHONE_RU_RE = re.compile(
    r"(?<![\d+])(?:\+7|8|7)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)"
)
_PHONE_INTL_RE = re.compile(r"(?<![\d+])\+(?!7)\d{1,3}[\s\-]?\(?\d{2,4}\)?(?:[\s\-]?\d{2,4}){2,3}(?!\d)")
_PHONE_CTX_RE = re.compile(
    r"(?:тел\w*|моб\w*|phone|сот\w*|whatsapp|telegram|viber)\s*[:.\-–]?\s*"
    r"(\d{3}[\s\-]?\d{2}[\s\-]?\d{2}|\d{10})(?!\d)",
    FLAGS,
)

# Номера 8-800 / +7 800 — телефоны организаций, а не ПД клиента.
def _is_org_phone(value: str) -> bool:
    digits = digits_only(value)
    return digits.startswith("8800") or digits.startswith("7800")


def _group(m: re.Match[str]) -> list[tuple[int, int]]:
    return [(m.start(1), m.end(1))]


class CardDetector(Detector):
    types = frozenset({PDType.CARD_NUMBER, PDType.CARD_CVV, PDType.CARD_PIN, PDType.CARD_EXPIRY})
    needs_digits = True

    def detect(self, text: str) -> Iterator[Entity | None]:
        for m in _CARD_RE.finditer(text):
            digits = digits_only(m.group(1))
            if not 13 <= len(digits) <= 19:
                continue
            if luhn_valid(digits) or cue_before(text, m.start(), _CARD_CUE_RE, window=40):
                yield make_entity(PDType.CARD_NUMBER, _group(m), priority=82)
        for m in _CVV_RE.finditer(text):
            yield make_entity(PDType.CARD_CVV, _group(m), priority=85)
        for m in _PIN_RE.finditer(text):
            yield make_entity(PDType.CARD_PIN, _group(m), priority=85)
        for m in _EXPIRY_CTX_RE.finditer(text):
            yield make_entity(PDType.CARD_EXPIRY, _group(m), priority=80)
        for m in _EXPIRY_WEAK_CTX_RE.finditer(text):
            # «действует до» у скидки/акции — не срок карты; иначе маскируем без номера карты.
            if cue_before(text, m.start(), _DISCOUNT_CUE_RE, window=40):
                continue
            yield make_entity(PDType.CARD_EXPIRY, _group(m), priority=78)
        for m in _EXPIRY_BARE_RE.finditer(text):
            yield make_entity(
                PDType.CARD_EXPIRY, _group(m), priority=40, requires_any=frozenset({PDType.CARD_NUMBER})
            )


class InnDetector(Detector):
    types = frozenset({PDType.INN})
    needs_digits = True

    def detect(self, text: str) -> Iterator[Entity | None]:
        for m in _INN_CTX_RE.finditer(text):
            if cue_before(text, m.start(), _ORG_CUE_RE, window=40):
                continue
            yield make_entity(PDType.INN, _group(m), priority=77)
        # ИНН физлица без слова «ИНН» — только при корректной контрольной сумме.
        for m in _INN_BARE_RE.finditer(text):
            if inn_valid(m.group(1)):
                yield make_entity(PDType.INN, _group(m), priority=42)


class ContactDetector(Detector):
    types = frozenset({PDType.EMAIL, PDType.PHONE})

    def detect(self, text: str) -> Iterator[Entity | None]:
        if "@" in text:
            for m in _EMAIL_RE.finditer(text):
                yield make_entity(PDType.EMAIL, [(m.start(), m.end())], priority=90)
        for pattern in (_PHONE_RU_RE, _PHONE_INTL_RE):
            for m in pattern.finditer(text):
                if _is_org_phone(m.group(0)):
                    continue
                yield make_entity(PDType.PHONE, [(m.start(), m.end())], priority=65)
        for m in _PHONE_CTX_RE.finditer(text):
            if _is_org_phone(m.group(1)):
                continue
            yield make_entity(PDType.PHONE, _group(m), priority=64)
