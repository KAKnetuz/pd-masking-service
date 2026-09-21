"""Детектор адресов.

Адрес разбирается на компоненты (страна, индекс, регион, город, улица, дом, корпус,
квартира). Маскируются только значения, служебные слова («ул.», «д.») сохраняются —
так LLM понимает, что речь об адресе (сохранение смысла, ТЗ 2).

Соседние компоненты объединяются в цепочку. Одиночный компонент без адресного
контекста не маскируется (меньше ложных срабатываний). Цепочка после слов
«отделение», «офис банка», «банкомат» — адрес организации, а не ПД.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from app.core.detectors.base import FLAGS, Detector, cue_before
from app.core.entities import Entity, PDType, make_entity

_NB = r"(?<![А-Яа-яЁё])"  # граница слова для кириллицы

_COMPONENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "country",
        re.compile(
            r"(?-i:(Россия|Российская\s+Федерация|РФ|Беларусь|Казахстан))"
            r"(?=\s*,\s*(?:\d{6}|г\.|город|обл|респ|(?-i:[А-ЯЁ])))",
            FLAGS,
        ),
    ),
    ("index", re.compile(r"(?:индекс\w*\s*[:\-]?\s*)?(?<!\d)(\d{6})(?!\d)(?=\s*,)", FLAGS)),
    (
        "region",
        re.compile(
            _NB + r"([А-ЯЁа-яё\-]+(?:ая|ой|ий|ский|ской|ская))\s+"
            r"(?:обл\.?|област\w*|кра[йяю]\b|автономн\w+\s+округ\w*)",
            FLAGS,
        ),
    ),
    (
        "region",
        re.compile(_NB + r"(?:респ\.|республик\w*)\s+((?-i:[А-ЯЁ])[а-яё\-]+(?:\s+(?-i:[А-ЯЁ])[а-яё]+)?)", FLAGS),
    ),
    ("district", re.compile(_NB + r"([А-ЯЁа-яё\-]+(?:ий|ый|ой|ский|ской|ого))\s+(?:р-н|район\w*)", FLAGS)),
    (
        "city",
        re.compile(
            _NB + r"(?:г\.|гор\.|город\w*|пгт\.?|пос\.|посёлок|поселок|с\.|село|дер\.|деревн\w+|ст-ца|станиц\w+)"
            r"\s*([А-ЯЁа-яё][А-ЯЁа-яё\-]*(?:\s+(?-i:[А-ЯЁ])[а-яё\-]+)?)",
            FLAGS,
        ),
    ),
    (
        "street",
        re.compile(
            _NB + r"(?:ул\.|улиц\w*|пр-т|пр-кт|просп\.|проспект\w*|пер\.|переул\w*|б-р|бул\.|бульвар\w*"
            r"|ш\.|шоссе|наб\.|набережн\w*|пл\.|площад\w*|проезд\w*|мкр\.?|микрорайон\w*|туп\.|тупик\w*"
            r"|алле[яи]|линия|тракт)\s*"
            r"((?:\d{1,3}(?:-?(?:я|й|го|ая|ой))?\s+)?[А-ЯЁа-яё][А-ЯЁа-яё\-]*(?:\s+(?-i:[А-ЯЁ0-9])[А-ЯЁа-яё\-]*){0,2})",
            FLAGS,
        ),
    ),
    (
        "street",
        re.compile(
            r"(?-i:([А-ЯЁ][а-яё]+(?:ая|ий|ой|ый)))\s+"
            r"(?:улица|ул\.|проспект|пер\.|переулок|шоссе|бульвар|набережная|площадь)",
            FLAGS,
        ),
    ),
    (
        "house",
        re.compile(
            _NB + r"(?:д\.|дом\w*|вл\.|влад\.|владени\w+)\s*№?\s*"
            r"(\d{1,4}[А-Яа-яA-Za-z]?(?:\s?/\s?\d{1,4}[А-Яа-я]?)?)(?!\d)",
            FLAGS,
        ),
    ),
    (
        "building",
        re.compile(
            _NB + r"(?:корп\.|корпус\w*|к\.|стр\.|строени\w+|лит\.|литер\w*)\s*"
            r"(\d{1,3}[А-Яа-я]?|[А-ЯЁ])(?![\dА-Яа-яЁё])",
            FLAGS,
        ),
    ),
    (
        "flat",
        re.compile(
            _NB + r"(?:кв\.|квартир\w*|кв\b|оф\.|офис\w*|комн\.|комнат\w*|пом\.|помещени\w+)\s*№?\s*"
            r"(\d{1,5}[А-Яа-я]?)(?!\d)",
            FLAGS,
        ),
    ),
)

_CITIES = frozenset(
    """
    москва санкт-петербург новосибирск екатеринбург казань челябинск самара омск ростов-на-дону
    уфа красноярск воронеж пермь волгоград краснодар саратов тюмень тольятти ижевск барнаул ульяновск
    иркутск хабаровск ярославль владивосток махачкала томск оренбург кемерово новокузнецк рязань астрахань
    пенза липецк киров чебоксары калининград тула курск сочи ставрополь севастополь симферополь минск
    алматы астана ташкент бишкек ереван баку тбилиси
    """.split()
) | {"нижний новгород"}
_LOCALITY_RE = re.compile(r"(?-i:[А-ЯЁ][а-яё]+(?:-на-[А-ЯЁ][а-яё]+|-[А-ЯЁ][а-яё]+|\s+Новгород)?)")

_GAP_RE = re.compile(r"[\s,;]{0,4}")

# Адрес организации (отделения банка и т.п.) — не персональные данные.
_ORG_CUE_RE = re.compile(
    r"отделени\w*|филиал\w*|банкомат\w*|терминал\w*|\bдо\s+«|доп(?:олнительн\w*)?\.?\s+офис\w*"
    r"|офис\w*\s+(?:банка|компании|продаж|обслуживани)|альфа-?\s?банк\w*|\bбанк\w*"
    r"|пункт\w*\s+выдачи|магазин\w*|\bтц\b|торгов\w+\s+центр\w*|ресторан\w*|кафе|музе\w*|театр\w*",
    FLAGS,
)
# Адресный контекст клиента: позволяет маскировать даже одиночный компонент.
_PERSONAL_CUE_RE = re.compile(
    r"прожива\w*|зарегистр\w*|регистраци\w*|адрес\w*|живу|живёт|живет|прописк\w*|прописан\w*"
    r"|место\s+жительства|доставк\w*|по\s+месту",
    FLAGS,
)


@dataclass(slots=True)
class _Component:
    kind: str
    start: int
    end: int
    value: tuple[int, int]


def _gap_ok(text: str, start: int, end: int) -> bool:
    return start <= end and _GAP_RE.fullmatch(text, start, end) is not None


class AddressDetector(Detector):
    types = frozenset({PDType.ADDRESS})

    def detect(self, text: str) -> Iterator[Entity | None]:
        components = self._components(text)
        if not components:
            return
        components = self._add_localities(text, components)
        for chain in self._chains(text, components):
            if cue_before(text, chain[0].start, _ORG_CUE_RE, window=80):
                continue
            if len(chain) < 2 and not cue_before(text, chain[0].start, _PERSONAL_CUE_RE, window=60):
                continue
            for comp in chain:
                yield make_entity(PDType.ADDRESS, [comp.value], priority=50, subtype=comp.kind)

    @staticmethod
    def _components(text: str) -> list[_Component]:
        found: list[_Component] = []
        for kind, pattern in _COMPONENT_PATTERNS:
            for m in pattern.finditer(text):
                value = m.group(1).rstrip(" -")
                if value:
                    found.append(_Component(kind, m.start(), m.end(), (m.start(1), m.start(1) + len(value))))
        # Убираем вложенные совпадения («к.» внутри «кв.»), оставляя более длинные.
        found.sort(key=lambda c: (c.start, -(c.end - c.start)))
        result: list[_Component] = []
        for comp in found:
            if result and comp.start < result[-1].end:
                continue
            result.append(comp)
        return result

    @staticmethod
    def _add_localities(text: str, components: list[_Component]) -> list[_Component]:
        """Город без «г.» внутри адреса: «123456, Москва, ул. Ленина»."""
        extra: list[_Component] = []
        for m in _LOCALITY_RE.finditer(text):
            if m.group(0).lower() not in _CITIES:
                continue
            if any(c.start <= m.start() < c.end for c in components):
                continue
            if any(_gap_ok(text, m.end(), c.start) or _gap_ok(text, c.end, m.start()) for c in components):
                extra.append(_Component("city", m.start(), m.end(), (m.start(), m.end())))
        return sorted(components + extra, key=lambda c: c.start)

    @staticmethod
    def _chains(text: str, components: list[_Component]) -> list[list[_Component]]:
        chains: list[list[_Component]] = []
        for comp in components:
            if chains and _gap_ok(text, chains[-1][-1].end, comp.start):
                chains[-1].append(comp)
            else:
                chains.append([comp])
        return chains
