"""Детекторы документов, удостоверяющих личность, и реквизитов их выдачи."""

from __future__ import annotations

import re
from collections.abc import Iterator

from app.core.detectors.base import FLAGS, Detector, cue_before, digits_only, snils_valid
from app.core.entities import Entity, PDType, make_entity

# --- Паспорт РФ и водительское удостоверение -------------------------------
_SERIES = r"(\d{2}[ \t]{0,20}(?:\d{2}|[А-ЯЁA-Z]{2}))"
_NUMBER = r"(\d{6})(?!\d)"
_BETWEEN = r"[\s,\-№:]*(?:номер|ном\.|№|н\.)?\s*[:№]?\s*"

_SERIES_NUMBER_RE = re.compile(r"серия\s*[:№]?\s*" + _SERIES + _BETWEEN + _NUMBER, FLAGS)
_PASSPORT_CTX_RE = re.compile(
    r"(?:паспорт\w*|серия\s+и\s+номер|удостоверени\w+\s+личности|\bдул\b)[^\d\n]{0,40}?"
    r"(?<!\d)(\d{2}\s?\d{2})" + _BETWEEN + _NUMBER,
    FLAGS,
)
_PASSPORT_BARE_SPACED_RE = re.compile(r"(?<![\d\-])(\d{2}\s\d{2})\s(\d{6})(?![\d\-])")
_PASSPORT_BARE_RE = re.compile(r"(?<![\d\-+])(\d{4})\s(\d{6})(?![\d\-])")

_DRIVER_CTX_RE = re.compile(
    r"(?:водительск\w*(?:\s+удостоверени\w*)?|\bв/у\b|\bву\b|вод\.\s*уд\.?|\bправ[аео]?\b"
    r"|driver'?s?\s+licen[cs]e)[^\d\n]{0,40}?(?<![\dА-ЯЁA-Z])" + _SERIES + _BETWEEN + _NUMBER,
    FLAGS,
)
_DRIVER_CUE_RE = re.compile(r"водительск|\bв/у\b|\bву\b|вод\.\s*уд|\bправ[аео]?\b|driver", FLAGS)

# --- Реквизиты выдачи ---------------------------------------------------------
_DEPT_CODE_RE = re.compile(
    r"(?:код\w*\s+подразделени\w*|код\w*\s+подр\.|к/п|к\.\s?п\.)\s*[:№\-–]?\s*(\d{3}[\s\-]?\d{3})(?!\d)", FLAGS
)
_DEPT_CODE_BARE_RE = re.compile(r"(?<![\d\-])(\d{3}-\d{3})(?![\d\-])")

_ISSUER_START_RE = re.compile(
    r"(?:кем\s+выдан\w*|выдан[аоы]?(?![а-яё])|орган\w*,?\s+выдавш\w+(?:\s+(?:паспорт|документ)\w*)?"
    r"|issued\s+by)\s*[:\-–]?\s*",
    FLAGS,
)
_ISSUER_AUTHORITY_RE = re.compile(
    r"мвд|фмс|овд|увд|уфмс|оуфмс|омвд|отдел|\bгу\b|\bтп\b|гибдд|полиц|управлени|паспортн|\bмо\b|рэо",
    FLAGS,
)
_ISSUER_STOP_RE = re.compile(
    r"[;\n]|,?\s*(?:дата\s+выдачи|код\w*\s+подразделени|к/п\b)"
    r"|,?\s*\d{1,2}[./]\d{1,2}[./]\d{2,4}|,\s*\d"
    r"|(?<![\s.][А-Яа-яЁё])(?<![\s.][А-Яа-яЁё]{2})\.\s+(?-i:[А-ЯЁ])|\.\s*$",
    FLAGS,
)

_COUNTRIES = (
    r"РФ|Росси[ияйю]|Российск\w+\s+Федераци\w+|российск\w+|русск\w+"
    r"|(?:Республик[аи]\s+)?Беларусь|Белоруссии|белорусск\w+|Украин[аыеу]|украинск\w+"
    r"|(?:Республик[аи]\s+)?Казахстан\w*|казахстанск\w+|(?:Республик[аи]\s+)?Узбекистан\w*|узбекск\w+"
    r"|(?:Республик[аи]\s+)?Таджикистан\w*|таджикск\w+"
    r"|(?:Республик[аи]\s+)?Кыргызстан\w*|Кыргызской\s+Республики|Киргизи[ия]|киргизск\w+"
    r"|(?:Республик[аи]\s+)?Армени[ияю]|армянск\w+"
    r"|(?:Республик[аи]\s+)?Азербайджан\w*|азербайджанск\w+|Грузи[ия]|грузинск\w+"
    r"|(?:Республик[аи]\s+)?Молдов[аыу]|Молдави[ия]|Туркменистан\w*"
    r"|Германи[ия]|США|Кита[йя]|КНР|Турци[ия]|Израил[ья]|Латви[ия]|Литв[аы]|Эстони[ия]|Франци[ия]"
    r"|Итали[ия]|Великобритани[ия]|Инди[ия]|Вьетнам\w*|Серби[ия]|Польш[аи]|Абхази[ия]"
)
_CITIZENSHIP_RE = re.compile(
    r"(?:гражданств\w*|подданств\w*|гражданин\w*|гражданк\w*|citizenship|nationality)"
    r"\s*[:\-–—=(«\"]?\s*(" + _COUNTRIES + r")(?![А-Яа-яЁё])",
    FLAGS,
)

_BIRTH_PLACE_TOKEN = r"(?:(?:гор|пос|пгт|дер|ст|обл|респ|г|с|д)\.|ст-ца|[А-ЯЁа-яё][А-ЯЁа-яё\-]*)"
_BIRTH_PLACE_VALUE = (
    r"[А-ЯЁа-яё][А-ЯЁа-яё\-]*"
    r"(?:(?:\s+|,\s*)" + _BIRTH_PLACE_TOKEN + r"){0,5}"
)
_BIRTH_PLACE_PREFIX = (
    r"(?:(?:г\.|гор\.|город|с\.|село|пос\.|посёлок|поселок|пгт\.?|д\.|дер\.|деревня|ст-ца|станица)\s*)?"
)
_BIRTH_PLACE_RE = re.compile(
    r"(?:место\s+рождения|родил(?:ся|ась)\s+в(?![а-яё])|уроже?н(?:ец|ка)|\bм\.\s?р\.|place\s+of\s+birth)"
    r"\s*[:\-–—]?\s*" + _BIRTH_PLACE_PREFIX + r"(" + _BIRTH_PLACE_VALUE + r")",
    FLAGS,
)
_BIRTH_PLACE_VALUE_RE = re.compile(_BIRTH_PLACE_PREFIX + r"(" + _BIRTH_PLACE_VALUE + r")", FLAGS)
_BIRTH_PLACE_WORD_RE = re.compile(r"[А-ЯЁа-яё\-]+")
_BIRTH_PLACE_TAIL_STOP = frozenset({"в", "на", "и", "году", "года", "г", "гг", "паспорт", "дата"})
# Слова, которые продолжают название места («Сочи, Краснодарский край», «Московская область»).
_BIRTH_PLACE_GEO_WORDS = frozenset(
    {"область", "обл", "край", "края", "район", "района", "республика", "респ", "округ", "г", "гор", "город",
     "с", "село", "пос", "посёлок", "поселок", "пгт", "д", "дер", "деревня", "ст", "станица"}
)
_COLON_AFTER_LABEL_RE = re.compile(r"[^:\d\n]{0,60}:\s*")

# --- Дополнительные документы (бонус ТЗ) -------------------------------------
_SNILS_RE = re.compile(r"(?<![\d\-])(\d{3}[-\s]?\d{3}[-\s]?\d{3}[-\s]?\d{2})(?![\d\-])")
_SNILS_CUE_RE = re.compile(r"снилс|страхов\w*\s+номер|страхов\w*\s+свидетельств", FLAGS)
_FOREIGN_PASSPORT_RE = re.compile(
    r"(?:загран\w*(?:\s+паспорт\w*)?|заграничн\w+\s+паспорт\w*|passport\s+(?:no\.?|number|№))"
    r"[^\d\n]{0,30}?(?<!\d)(\d{2})\s?№?\s?(\d{7})(?!\d)",
    FLAGS,
)
_MILITARY_ID_RE = re.compile(
    r"военн\w+\s+билет\w*[^\n\d]{0,20}?(?<![А-ЯЁA-Z])([А-ЯЁ]{2})\s?№?\s?(\d{7})(?!\d)", FLAGS
)
_BIRTH_CERT_RE = re.compile(
    r"свидетельств\w+\s+о\s+рождении[^\n]{0,20}?(?<![A-ZА-ЯЁ])([IVXLC]{1,4}|[1І]{1,3})[\s\-]?"
    r"([А-ЯЁ]{2})\s?№?\s?(\d{6})(?!\d)",
    FLAGS,
)


def _groups(m: re.Match[str], *idx: int) -> list[tuple[int, int]]:
    return [(m.start(i), m.end(i)) for i in idx]


def _doc_type(text: str, pos: int) -> PDType:
    return PDType.DRIVER_LICENSE if cue_before(text, pos, _DRIVER_CUE_RE, window=60) else PDType.PASSPORT


class IdentityDocumentDetector(Detector):
    types = frozenset({PDType.PASSPORT, PDType.DRIVER_LICENSE})
    needs_digits = True

    def detect(self, text: str) -> Iterator[Entity | None]:
        for m in _DRIVER_CTX_RE.finditer(text):
            yield make_entity(PDType.DRIVER_LICENSE, _groups(m, 1, 2), priority=76)
        for m in _PASSPORT_CTX_RE.finditer(text):
            yield make_entity(PDType.PASSPORT, _groups(m, 1, 2), priority=74)
        for m in _SERIES_NUMBER_RE.finditer(text):
            yield make_entity(_doc_type(text, m.start()), _groups(m, 1, 2), priority=73)
        for pattern in (_PASSPORT_BARE_SPACED_RE, _PASSPORT_BARE_RE):
            for m in pattern.finditer(text):
                yield make_entity(_doc_type(text, m.start()), _groups(m, 1, 2), priority=45)


class IssuanceDetector(Detector):
    """Код подразделения, орган выдачи, гражданство, место рождения."""

    types = frozenset(
        {PDType.DEPARTMENT_CODE, PDType.PASSPORT_ISSUER, PDType.CITIZENSHIP, PDType.BIRTH_PLACE}
    )

    def detect(self, text: str) -> Iterator[Entity | None]:
        for m in _DEPT_CODE_RE.finditer(text):
            yield make_entity(PDType.DEPARTMENT_CODE, _groups(m, 1), priority=72)
        for m in _DEPT_CODE_BARE_RE.finditer(text):
            yield make_entity(
                PDType.DEPARTMENT_CODE,
                _groups(m, 1),
                priority=30,
                requires_any=frozenset({PDType.PASSPORT, PDType.PASSPORT_ISSUER}),
            )
        yield from self._issuers(text)
        for m in _CITIZENSHIP_RE.finditer(text):
            yield make_entity(PDType.CITIZENSHIP, _groups(m, 1), priority=70)
        yield from self._birth_places(text)

    @staticmethod
    def _issuers(text: str) -> Iterator[Entity | None]:
        for m in _ISSUER_START_RE.finditer(text):
            start = m.end()
            if not _ISSUER_AUTHORITY_RE.search(text, start, min(len(text), start + 30)):
                continue
            window_end = min(len(text), start + 200)
            stop = _ISSUER_STOP_RE.search(text, start, window_end)
            end = stop.start() if stop else window_end
            end = start + len(text[start:end].rstrip(" ,."))
            if end - start >= 3:
                yield make_entity(PDType.PASSPORT_ISSUER, [(start, end)], priority=66)

    @staticmethod
    def _birth_place_words(text: str, start: int, end: int) -> list[re.Match[str]]:
        """Слова значения: первое слово и следующие за ним слова с заглавной или географические."""
        words = list(_BIRTH_PLACE_WORD_RE.finditer(text, start, end))
        kept = words[:1]
        for w in words[1:]:
            word = w.group(0)
            if word.lower() in _BIRTH_PLACE_GEO_WORDS or (word[0].isupper() and kept[0].group(0)[0].isupper()):
                kept.append(w)
            else:
                break
        while kept and kept[-1].group(0).lower() in _BIRTH_PLACE_TAIL_STOP | {"область", "край", "района"}:
            kept.pop()
        return kept

    @classmethod
    def _birth_places(cls, text: str) -> Iterator[Entity | None]:
        for m in _BIRTH_PLACE_RE.finditer(text):
            start, end = m.start(1), m.end(1)
            colon = None if ":" in m.group(0) else _COLON_AFTER_LABEL_RE.match(text, start)
            if colon:
                # «Место рождения бенефициара по договору: г. Алма-Ата» — значение после двоеточия.
                value = _BIRTH_PLACE_VALUE_RE.match(text, colon.end())
                if not value:
                    continue
                start, end = value.span(1)
            words = cls._birth_place_words(text, start, end)
            if words:
                yield make_entity(PDType.BIRTH_PLACE, [(words[0].start(), words[-1].end())], priority=72)


class ExtraDocumentDetector(Detector):
    """СНИЛС, загранпаспорт, военный билет, свидетельство о рождении."""

    types = frozenset(
        {PDType.SNILS, PDType.FOREIGN_PASSPORT, PDType.MILITARY_ID, PDType.BIRTH_CERTIFICATE}
    )
    needs_digits = True

    def detect(self, text: str) -> Iterator[Entity | None]:
        for m in _SNILS_RE.finditer(text):
            has_cue = cue_before(text, m.start(), _SNILS_CUE_RE, window=40)
            if has_cue or ("-" in m.group(1) and snils_valid(digits_only(m.group(1)))):
                yield make_entity(PDType.SNILS, _groups(m, 1), priority=68)
        for m in _FOREIGN_PASSPORT_RE.finditer(text):
            yield make_entity(PDType.FOREIGN_PASSPORT, _groups(m, 1, 2), priority=78)
        for m in _MILITARY_ID_RE.finditer(text):
            yield make_entity(PDType.MILITARY_ID, _groups(m, 1, 2), priority=78)
        for m in _BIRTH_CERT_RE.finditer(text):
            yield make_entity(PDType.BIRTH_CERTIFICATE, _groups(m, 1, 2, 3), priority=78)
