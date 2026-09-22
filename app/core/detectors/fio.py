"""Детектор ФИО и имени держателя карты.

1. Токенизация кириллических слов и классификация: имя (словарь), отчество
   и фамилия (морфология), слово с заглавной буквы.
2. Устойчивые сочетания: Ф+И+О, И+О+Ф, И+О, Ф+И, И+Ф, фамилия + инициалы.
3. Контекстные триггеры («клиент», «ФИО:», «заёмщик»): 2–3 слова после них.
4. Исключения: известные люди (Пушкин, Толстой) и «имени/улица/памятник» перед именем.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from app.core.detectors.base import FLAGS, Detector, cue_before
from app.core.detectors.name_span import extend_person_span
from app.core.detectors.names_data import (
    FAMOUS_SURNAME_RE,
    NOT_SURNAMES,
    PATRONYMIC_RE,
    SURNAME_RE,
    is_first_name,
)
from app.core.entities import Entity, PDType, make_entity

_WORD_RE = re.compile(r"[А-ЯЁа-яё]+(?:-[А-ЯЁа-яё]+)?")

_CUE_RE = re.compile(
    r"(?:\bфио|клиент\w*|заё?мщик\w*|заявител\w*|получател\w*|отправител\w*|пациент\w*"
    r"|абонент\w*|владел\w*|гражданин\w*|гражданк\w*|\bгр\.|господин\w*|госпож\w*|\bг-н|\bг-жа"
    r"|уважаем\w+|плательщик\w*|вкладчик\w*|поручител\w*|наследник\w*|подписант\w*"
    r"|представител\w*)\s*[:\-–—]?\s*$",
    FLAGS,
)

# Контекст, при котором имя — не ПД клиента: улицы, памятники, культура, история.
_NON_PD_CUE_RE = re.compile(
    r"(?:\bимени|\bим\.|\bулиц\w*|\bул\.|проспект\w*|\bпр-т|\bпл\.|площад\w*|переул\w*|бульвар\w*"
    r"|памятник\w*|музе\w*|поэт\w*|писател\w*|композитор\w*|художник\w*|философ\w*"
    r"|учён\w*|учен\w*|стих\w*|произведени\w*|повест\w*|классик\w*|царь|импер\w*"
    r"|полковод\w*|актёр\w*|актер\w*|режиссёр\w*|режиссер\w*|\bтеатр\w*|\bметро\b|\bстанци\w*)"
    r"\s*[«\"]?\s*$",
    FLAGS,
)

# Сильный контекст: при нём даже «известная» фамилия считается ПД клиента.
_STRONG_CUE_RE = re.compile(
    r"клиент|заё?мщик|\bфио\b|заявител|держател|получател|паспорт|плательщик|вкладчик", FLAGS
)

_INITIALS_AFTER_RE = re.compile(
    r"([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)\s+([А-ЯЁ])\.\s?([А-ЯЁ])(?:\.|(?![А-ЯЁа-яё]))"
)
_INITIALS_BEFORE_RE = re.compile(
    r"(?<![А-Яа-яЁё])([А-ЯЁ])\.\s?([А-ЯЁ])\.\s?([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)"
)

_HOLDER_CUE_RE = re.compile(
    r"(?:держател\w*(?:\s+карты)?|имя\s+держателя(?:\s+карты)?|имя\s+(?:и\s+фамилия\s+)?на\s+карте"
    r"|владел\w*\s+карты|эмбосс\w*\s+имя|card\s*holder(?:\s+name)?|name\s+on\s+card)\s*[:\-–—]?\s*[«\"]?"
    r"([A-Za-zА-ЯЁа-яё][A-Za-zА-ЯЁа-яё'-]+(?:\s+[A-Za-zА-ЯЁа-яё][A-Za-zА-ЯЁа-яё'-]+){1,2})",
    FLAGS,
)
_HOLDER_WORD_RE = re.compile(r"[A-Za-zА-ЯЁа-яё'-]+")
_HOLDER_STOPWORDS = frozenset({"карты", "номер", "срок", "cvv", "cvc", "пин", "pin", "код"})
# Служебные слова сразу после метки: «Имя держателя указано как: …» — это не имя.
_HOLDER_LEAD_STOPWORDS = frozenset(
    {"указано", "указан", "указана", "как", "это", "является", "записано", "значится", "оформлена", "оформлено"}
)

# Латинское имя заглавными рядом с номером карты: «IVAN IVANOV». Слабая сущность.
_LATIN_HOLDER_RE = re.compile(r"(?<![A-Za-z])([A-Z]{2,})\s+([A-Z]{2,})(?![A-Za-z])")
_LATIN_STOPWORDS = frozenset(
    {"CVV", "CVC", "PIN", "VISA", "MASTERCARD", "MIR", "MAESTRO", "VALID", "THRU", "EXP", "CARD",
     "BANK", "NUMBER", "HOLDER", "NAME", "UNIONPAY", "AMEX", "CODE", "DATE", "LLM", "API", "PDF"}
)

# Слова с заглавной буквы, которые не бывают частью ФИО («гражданин Российской Федерации»).
_NOT_NAME_WORDS = frozenset(
    """
    российской федерации россии рф республики республика беларусь белоруссии казахстана казахстан
    украины украина узбекистана таджикистана кыргызстана киргизии армении азербайджана грузии
    молдовы германии сша китая банка банк альфа москвы москва санкт петербурга
    """.split()
)


def _holder_word_ok(word: str) -> bool:
    """Слово похоже на часть имени держателя: латиница, словарь имён/фамилий или «Слово с заглавной»."""
    lower = word.lower()
    by_dictionary = is_first_name(lower) or PATRONYMIC_RE.match(lower) is not None
    by_surname = SURNAME_RE.match(lower) is not None and lower not in NOT_SURNAMES
    return word.isascii() or by_dictionary or by_surname or (word[0].isupper() and not word.isupper())


@dataclass(slots=True)
class _Token:
    start: int
    end: int
    text: str
    lower: str
    capitalized: bool
    first: bool
    patronymic: bool
    surname: bool


def _tokenize(text: str) -> list[_Token]:
    tokens = []
    for m in _WORD_RE.finditer(text):
        word = m.group(0)
        lower = word.lower()
        tokens.append(
            _Token(
                start=m.start(),
                end=m.end(),
                text=word,
                lower=lower,
                capitalized=word[0].isupper() and not (len(word) > 1 and word.isupper()),
                first=is_first_name(lower),
                patronymic=PATRONYMIC_RE.match(lower) is not None,
                surname=SURNAME_RE.match(lower) is not None and lower not in NOT_SURNAMES,
            )
        )
    return tokens


def _adjacent(text: str, left: _Token, right: _Token) -> bool:
    gap = text[left.end : right.start]
    return 0 < len(gap) <= 3 and gap.isspace()


def _is_surname(tok: _Token, strict: bool) -> bool:
    if tok.surname:
        return True
    # Фамилия без типичного суффикса («Ким», «Шмидт») — только с заглавной и рядом с отчеством.
    if _CUE_RE.search(tok.text + " "):
        return False
    return not strict and tok.capitalized and not tok.first and not tok.patronymic


def _match_run(run: list[_Token]) -> int:
    """Длина распознанного ФИО в начале ``run`` (0 — не ФИО)."""
    if len(run) >= 3:
        a, b, c = run[:3]
        if _is_surname(a, strict=False) and b.first and c.patronymic:
            return 3
        if a.first and b.patronymic and _is_surname(c, strict=False):
            return 3
    if len(run) >= 2:
        a, b = run[:2]
        if a.first and b.patronymic:
            return 2
        if _is_surname(a, strict=True) and b.first:
            return 2
        if a.first and _is_surname(b, strict=True):
            return 2
    return 0


class FioDetector(Detector):
    types = frozenset({PDType.FIO, PDType.CARD_HOLDER})

    def detect(self, text: str) -> Iterable[Entity | None]:
        tokens = _tokenize(text)
        candidates = [
            *self._by_morphology(text, tokens),
            *self._by_initials(text),
            *self._by_cue(text, tokens),
            *self._card_holders(text),
        ]
        kept = [e for e in candidates if e is not None and not self._is_excluded(text, e)]
        return [self._extend(text, e) for e in kept]

    @staticmethod
    def _extend(text: str, entity: Entity) -> Entity | None:
        if entity.pd_type is not PDType.FIO or len(entity.parts) != 1:
            return entity
        start, end = extend_person_span(text, entity.start, entity.end)
        if (start, end) == (entity.start, entity.end):
            return entity
        return make_entity(PDType.FIO, [(start, end)], priority=entity.priority)

    @staticmethod
    def _by_morphology(text: str, tokens: list[_Token]) -> Iterator[Entity | None]:
        i, n = 0, len(tokens)
        while i < n:
            run = [tokens[i]]
            j = i + 1
            while j < n and len(run) < 3 and _adjacent(text, run[-1], tokens[j]):
                run.append(tokens[j])
                j += 1
            size = _match_run(run)
            if size:
                yield make_entity(PDType.FIO, [(run[0].start, run[size - 1].end)], priority=60)
                i += size
            else:
                i += 1

    @staticmethod
    def _by_initials(text: str) -> Iterator[Entity | None]:
        for pattern in (_INITIALS_AFTER_RE, _INITIALS_BEFORE_RE):
            for m in pattern.finditer(text):
                yield make_entity(PDType.FIO, [(m.start(), m.end())], priority=62)

    @staticmethod
    def _by_cue(text: str, tokens: list[_Token]) -> Iterator[Entity | None]:
        for idx, tok in enumerate(tokens):
            if not cue_before(text, tok.start, _CUE_RE, window=40):
                continue
            if _CUE_RE.search(tok.text + " "):
                continue
            run = [tok]
            k = idx + 1
            while k < len(tokens) and len(run) < 3 and _adjacent(text, run[-1], tokens[k]):
                nxt = tokens[k]
                if not (nxt.capitalized or nxt.first or nxt.patronymic or nxt.surname):
                    break
                run.append(nxt)
                k += 1
            if len(run) < 2:
                # Одиночная фамилия после подсказки («Клиент Сидоров», «клиент сидоров»).
                if (
                    len(run) == 1
                    and run[0].surname
                    and not run[0].first
                    and not run[0].patronymic
                    and run[0].lower not in _NOT_NAME_WORDS
                ):
                    yield make_entity(PDType.FIO, [(run[0].start, run[0].end)], priority=58)
                continue
            if any(t.lower in _NOT_NAME_WORDS for t in run):
                continue
            if all(t.capitalized for t in run) or any(t.first or t.patronymic for t in run):
                yield make_entity(PDType.FIO, [(run[0].start, run[-1].end)], priority=58)

    @staticmethod
    def _card_holders(text: str) -> Iterator[Entity | None]:
        for m in _HOLDER_CUE_RE.finditer(text):
            words = list(_HOLDER_WORD_RE.finditer(text, m.start(1), m.end(1)))
            while words and words[-1].group(0).lower() in _HOLDER_STOPWORDS:
                words.pop()
            while words and words[0].group(0).lower() in _HOLDER_LEAD_STOPWORDS:
                words.pop(0)
            while words and not _holder_word_ok(words[-1].group(0)):
                words.pop()
            if any(not _holder_word_ok(w.group(0)) for w in words):
                continue
            if len(words) >= 2:
                yield make_entity(PDType.CARD_HOLDER, [(words[0].start(), words[-1].end())], priority=80)
        for m in _LATIN_HOLDER_RE.finditer(text):
            if m.group(1) in _LATIN_STOPWORDS or m.group(2) in _LATIN_STOPWORDS:
                continue
            yield make_entity(
                PDType.CARD_HOLDER,
                [(m.start(), m.end())],
                priority=55,
                requires_any=frozenset({PDType.CARD_NUMBER}),
            )

    @staticmethod
    def _is_excluded(text: str, entity: Entity) -> bool:
        if entity.pd_type is PDType.CARD_HOLDER:
            return False
        # Имя в кавычках — название произведения, организации и т.п.: «Евгений Онегин».
        if entity.start > 0 and text[entity.start - 1] in "«\"'„“":
            return True
        if cue_before(text, entity.start, _NON_PD_CUE_RE, window=30):
            return True
        words = [w.lower() for w in _WORD_RE.findall(text[entity.start : entity.end])]
        if any(FAMOUS_SURNAME_RE.match(w) for w in words):
            return not cue_before(text, entity.start, _STRONG_CUE_RE, window=40)
        return False
