"""Значения ПД после меток с вариативной записью (ТЗ 4.2).

Общие правила вместо шаблонов под отдельные фразы:
* разделитель между меткой и значением — любой из ":", "=", "—", "-", скобки, кавычки;
* между меткой и значением допускаются служебные слова («ПИН резервной карты: 3907»,
  «в поле CVV клиент указал код 517», «ИНН заявителя 500100732259»);
* метка может стоять после значения («введён код 517, но CVV не совпал»);
* регистр не важен.

Покрывает: ПИН, CVV, ИНН (в т.ч. группами цифр), код подразделения, орган выдачи паспорта,
ФИО после меток роли человека («Получатель перевода: Сидоров П.»), ФИО и номера, записанные
как всё сообщение («Мигель Гарсия», «45-09-123456»).
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from app.core.detectors.base import FLAGS, Detector, cue_before
from app.core.detectors.name_span import extend_person_span
from app.core.detectors.names_data import (
    CITIES,
    FAMOUS_SURNAME_RE,
    NOT_SURNAMES,
    PATRONYMIC_RE,
    SURNAME_RE,
    is_first_name,
)
from app.core.entities import Entity, PDType, make_entity

# Служебные слова между меткой и значением: до 4 слов без цифр, в пределах строки.
_GAP = r"(?:[^\d\n.;!?]{0,40}?)"
_SEP = r"[\s:=\-–—(«\"'“]*"

# --- ПИН и CVV ----------------------------------------------------------------------
_PIN_LABEL = r"(?:п\.?\s?и\.?\s?н(?:[\s.\-]*к\.?\s?о\.?\s?д\w*)?|\bpin(?:[\s\-]*(?:code|код\w*))?)(?![а-яёa-z])"
_CVV_LABEL = (
    r"(?:\bcvv\d?|\bcvc\d?|\bcvn|\bcav2|\bцвв|\bсививи|\bсивиси"
    r"|код\w*\s+(?:на\s+обороте|с\s+обратной\s+стороны|безопасности)(?:\s+карты)?)(?:[\s\-]*код\w*)?"
)
_PIN_RE = re.compile(r"(?<![а-яёa-z])" + _PIN_LABEL + _GAP + _SEP + r"(?<!\d)(\d{4,6})(?!\d)", FLAGS)
_CVV_RE = re.compile(_CVV_LABEL + _GAP + _SEP + r"(?<!\d)(\d{3})(?!\d)", FLAGS)
_CVV_AFTER_RE = re.compile(r"\bкод\w*\s+(\d{3})(?!\d)[^\d\n.]{0,30}?\b(?:cvv|cvc|цвв)", FLAGS)
# Всё сообщение — номер карты и короткий код за ним: «4276… 123» (CVV) / «4276… 1234» (ПИН).
_CARD_AND_CODE_RE = re.compile(r"^\s*(\d{16})\s+(\d{3,4})\s*$")

# --- ИНН, номера документов -------------------------------------------------------------
_INN_VALUE = r"(\d{4}[\s\-]\d{4}[\s\-]\d{4}|\d{12}|\d{10})(?![\d\-])"
_INN_RE = re.compile(r"\bинн\b(?!\s*/)" + _GAP + _SEP + r"(?<![\d\-])" + _INN_VALUE, FLAGS)
_ORG_CUE_RE = re.compile(
    r"организац|компани|контрагент|поставщик|юр\w*\s+лиц|\bооо\b|\bоао\b|\bзао\b|\bпао\b|\bао\b|\bип\b", FLAGS
)
_WHOLE_INN_RE = re.compile(r"^\s*(\d{4}[\s\-]\d{4}[\s\-]\d{4})\s*$")
_WHOLE_DOC_RE = re.compile(r"^\s*(\d{2}[\-/]\d{2}[\-/]\d{6}|\d{4}-\d{6})\s*$")
_SERIES_ONLY_RE = re.compile(r"\bсери[яи]\s*[:№]?\s*(\d{2}\s?\d{2})(?![\d\s]*(?:,\s*)?(?:номер|№)?\s*\d)", FLAGS)
_DEPT_RE = re.compile(r"код\w*\s+подразделени\w*" + _GAP + _SEP + r"(?<![\d\-])(\d{3}-\d{3})(?![\d\-])", FLAGS)

# --- Орган выдачи -----------------------------------------------------------------------
_AUTHORITY_RE = re.compile(
    r"(?<![А-ЯЁа-яёA-Za-z])(?:отдел\w*\s+)?(?:ТП\s+|МО\s+|ГУ\s+)?"
    r"(?:ОУФМС|УФМС|ФМС|ОВД|УВД|ГУВД|ОМВД|УМВД|МВД|OVD|UFMS)(?![А-ЯЁа-яёA-Za-z])"
    r"|(?<![А-ЯЁа-яё])(?:отдел\w*\s+(?:полиции|внутренних\s+дел|по\s+вопросам\s+миграции)"
    r"|паспортно-визов\w+\s+служб\w+|паспортн\w+\s+стол\w*)",
    FLAGS,
)
_ISSUER_CUE_RE = re.compile(r"выда|орган|кем\b|оформлен|паспорт", FLAGS)
# Метка органа выдачи: значение после неё — орган, даже без слов «ОВД», «УФМС».
_ISSUER_LABEL_RE = re.compile(
    r"(?:орган\w*,?\s+(?:выдачи|выдавш\w+)(?:\s+(?:паспорт|документ)\w*)?|кем\s+выдан\w*)\s*[:—\-]\s*", FLAGS
)
_ISSUER_TOKEN_RE = re.compile(r"«[^»\n]{1,40}»|\"[^\"\n]{1,40}\"|№\s?\d+|[A-Za-zА-ЯЁа-яё][A-Za-zА-ЯЁа-яё\-]*\.?|\d+|,")
_ISSUER_STOP = frozenset(
    """в с на и совпадает выдало выдал выдала выдан выдан выданный был была было подтвержден подтверждено
    код дата серия номер повторный ранее указан указано указанным прошлом году установленном""".split()
)
_ABBREVIATIONS = frozenset({"г.", "гор.", "обл.", "р-на.", "пос.", "с."})

# --- ФИО после метки роли человека ----------------------------------------------------------
_ROLE_LABEL_RE = re.compile(
    r"(?<![А-ЯЁа-яё])(?:получател\w*|отправител\w*|плательщик\w*|поручител\w*|соза[её]мщик\w*|за[её]мщик\w*"
    r"|вкладчик\w*|бенефициар\w*|наследник\w*|подписант\w*|доверенн\w+\s+лиц\w*|заявител\w*|закладател\w*"
    r"|подател\w*|владел\w*|держател\w*\s+счета|отчеств\w*|фамили\w*|клиент(?:ка)?(?:-[а-яё]+)?(?![а-яё]))"
    r"[^:\n\d«»]{0,40}?[»\"]?\s*(?:указан\w*\s*)?[:—]\s*",
    FLAGS,
)
_NAME_TOKEN_RE = re.compile(r"[A-Za-zА-ЯЁа-яё]+(?:['’\-/][A-Za-zА-ЯЁа-яё]+)*\.?")
# Слитное ФИО: «СидоровПётрАлексеевич», «СИДОРОВПЁТРАЛЕКСЕЕВИЧ» (оканчивается отчеством).
_CAMEL_NAME_RE = re.compile(
    r"^(?:[А-ЯЁ][а-яё]+){2,3}$|^(?:[А-ЯЁ]{9,}|[а-яё]{9,})(?<=(?:ОВИЧ|ЕВИЧ|ОВНА|ЕВНА|ович|евич|овна|евна))$"
)
_GEO_WORDS = frozenset(
    """федерация федерации республика республики эмираты штаты америки область край район город""".split()
)
_NOT_NAME_WORDS = frozenset(
    """ооо оао зао пао ао ип банк банка компания организация сумма счет счёт договор договору договора карта карты
    не указано указан нет отсутствует россия российская федерация рф москва назначение операция по""".split()
)
_MAX_NAME_TOKENS = 4
# «Клиент зарегистрирован по адресу: г. Сочи» — после метки адрес, а не имя.
_ADDRESS_CUE_RE = re.compile(r"адрес|прожива|зарегистр|прописан|место\s+", FLAGS)

# --- ФИО как всё сообщение ------------------------------------------------------------------
_TRAILING_NOTE_RE = re.compile(r"\s*\([^()]*\)\s*$")
_BARE_NAME_RE = re.compile(
    r"^(?:[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?|[A-Z][a-z]*['’][A-Z][a-z]+|[A-Z][a-z]+)"
    r"(?:\s+(?:[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?|[A-Z][a-z]*['’][A-Z][a-z]+|[A-Z][a-z]+)){1,2}$"
)
_BARE_STOP = frozenset(
    """банк банка россии россия альфа карта карты новый год добрый спасибо сити площадь улица проспект
    apple google samsung visa master mastercard card pay classic gold platinum world""".split()
)
# Латинские имя и фамилия в начале русской фразы: «Petrova Olga оплатила …».
_LATIN_LEAD_NAME_RE = re.compile(r"^\s*([A-Z][a-z]+\s+[A-Z][a-z]+)(?=\s+[а-яё])")

_PRIORITY_SECRET = 86
_PRIORITY_NUMBER = 79
_PRIORITY_ISSUER = 69
_PRIORITY_NAME = 67
_PRIORITY_BARE = 46
_PRIORITY_SERIES = 44


def _has_stop_word(value: str) -> bool:
    """Слово-исключение: организация, город, бренд или известный человек («Банк России», «Лев Толстой»)."""
    words = [w.lower() for w in re.split(r"[\s\-]+", value)]
    return any(w in _BARE_STOP or w in CITIES or FAMOUS_SURNAME_RE.match(w) for w in words)


def _group_entity(pd_type: PDType, m: re.Match[str], priority: int, idx: int = 1) -> Entity | None:
    return make_entity(pd_type, [m.span(idx)], priority=priority)


class ContextValueDetector(Detector):
    types = frozenset(
        {
            PDType.CARD_PIN,
            PDType.CARD_CVV,
            PDType.CARD_NUMBER,
            PDType.INN,
            PDType.PASSPORT,
            PDType.DEPARTMENT_CODE,
            PDType.PASSPORT_ISSUER,
            PDType.FIO,
        }
    )

    def detect(self, text: str) -> Iterator[Entity | None]:
        yield from self._card_secrets(text)
        yield from self._numbers(text)
        yield from self._issuers(text)
        yield from self._role_names(text)
        yield from self._bare_names(text)

    # --- ПИН, CVV ---
    @staticmethod
    def _card_secrets(text: str) -> Iterator[Entity | None]:
        for m in _PIN_RE.finditer(text):
            yield _group_entity(PDType.CARD_PIN, m, _PRIORITY_SECRET)
        for pattern in (_CVV_RE, _CVV_AFTER_RE):
            for m in pattern.finditer(text):
                yield _group_entity(PDType.CARD_CVV, m, _PRIORITY_SECRET)
        whole = _CARD_AND_CODE_RE.match(text)
        if whole:
            secret = PDType.CARD_CVV if len(whole.group(2)) == 3 else PDType.CARD_PIN
            yield _group_entity(PDType.CARD_NUMBER, whole, _PRIORITY_SECRET)
            yield _group_entity(secret, whole, _PRIORITY_SECRET, 2)

    # --- ИНН, документы, код подразделения ---
    @staticmethod
    def _numbers(text: str) -> Iterator[Entity | None]:
        for m in _INN_RE.finditer(text):
            if not cue_before(text, m.start(), _ORG_CUE_RE, window=40):
                yield _group_entity(PDType.INN, m, _PRIORITY_NUMBER)
        for pattern, pd_type in ((_WHOLE_INN_RE, PDType.INN), (_WHOLE_DOC_RE, PDType.PASSPORT)):
            m = pattern.match(text)
            if m:
                yield _group_entity(pd_type, m, _PRIORITY_NUMBER)
        for m in _SERIES_ONLY_RE.finditer(text):
            yield _group_entity(PDType.PASSPORT, m, _PRIORITY_SERIES)
        for m in _DEPT_RE.finditer(text):
            yield _group_entity(PDType.DEPARTMENT_CODE, m, _PRIORITY_NUMBER)

    # --- орган выдачи ---
    @staticmethod
    def _issuer_word_stops(word: str) -> bool:
        return word == "," or word.isdigit() or word.lower().rstrip(".") in _ISSUER_STOP

    @staticmethod
    def _sentence_end(word: str) -> bool:
        """Точка после слова — конец предложения, а не сокращение («г.», «обл.», «УФМС.»)."""
        return word.endswith(".") and word.lower() not in _ABBREVIATIONS and not word[:-1].isupper()

    @classmethod
    def _issuer_end(cls, text: str, start: int) -> int:
        """Конец названия органа: до стоп-слова, цифры, запятой, скобки или конца предложения."""
        end = start
        for tok in _ISSUER_TOKEN_RE.finditer(text, start):
            gap = text[end : tok.start()]
            if (tok.start() > start and (gap.strip() or len(gap) > 2)) or cls._issuer_word_stops(tok.group(0)):
                break
            if cls._sentence_end(tok.group(0)):
                end = tok.end() - 1
                break
            end = tok.end()
        return len(text[:end].rstrip(" .,"))

    def _issuers(self, text: str) -> Iterator[Entity | None]:
        for label in _ISSUER_LABEL_RE.finditer(text):
            end = self._issuer_end(text, label.end())
            if end - label.end() >= 3:
                yield make_entity(PDType.PASSPORT_ISSUER, [(label.end(), end)], priority=_PRIORITY_ISSUER)
        stripped = text.strip()
        for m in _AUTHORITY_RE.finditer(text):
            at_start = not text[: m.start()].strip()
            if not at_start and not cue_before(text, m.start(), _ISSUER_CUE_RE, window=60):
                continue
            if at_start and len(_TRAILING_NOTE_RE.sub("", stripped)) > 80:
                continue
            end = self._issuer_end(text, m.start())
            if end - m.start() >= 3:
                yield make_entity(PDType.PASSPORT_ISSUER, [(m.start(), end)], priority=_PRIORITY_ISSUER)

    # --- ФИО после метки роли ---
    @staticmethod
    def _strong_token(word: str) -> bool:
        """Инициал, имя, отчество, фамилия по морфологии или слитное ФИО."""
        core = word.rstrip(".")
        lower = core.lower()
        if len(core) == 1:
            return word.endswith(".")
        parts = [p for p in re.split(r"['’\-/]", lower) if p]
        by_dictionary = any(is_first_name(p) or PATRONYMIC_RE.match(p) for p in parts)
        by_surname = SURNAME_RE.match(lower) is not None and lower not in NOT_SURNAMES
        return by_dictionary or by_surname or _CAMEL_NAME_RE.match(core) is not None

    @classmethod
    def _name_token_ok(cls, word: str) -> bool:
        if len(word) > 2 and word.endswith("."):
            word = word[:-1]  # точка конца предложения, а не инициала
        core = word.rstrip(".")
        lower = core.lower()
        if not core or lower in _NOT_NAME_WORDS or FAMOUS_SURNAME_RE.match(lower):
            return False
        capitalized = len(core) > 1 and core[0].isupper() and not core.isupper() and not word.endswith(".")
        return capitalized or cls._strong_token(word)

    @classmethod
    def _weak_value(cls, tokens: list[re.Match[str]]) -> bool:
        """Нет ни одного слова из словаря/морфологии — нужны хотя бы два слова с заглавной."""
        words = [t.group(0) for t in tokens]
        only_initials = all(len(w.rstrip(".")) == 1 for w in words)  # «г.», «И.» — не ФИО
        has_strong = any(cls._strong_token(w) for w in words)
        few_or_geo = len(words) < 2 or any(w.lower().rstrip(".") in _GEO_WORDS for w in words)
        return only_initials or (not has_strong and few_or_geo)

    @classmethod
    def _name_tokens(cls, text: str, pos: int) -> list[re.Match[str]]:
        """Слова имени сразу после метки: до первого слова, не похожего на часть ФИО, или знака препинания."""
        tokens: list[re.Match[str]] = []
        for tok in _NAME_TOKEN_RE.finditer(text, pos):
            stop = text[pos : tok.start()].strip() or len(tokens) >= _MAX_NAME_TOKENS
            if stop or not cls._name_token_ok(tok.group(0)):
                break
            tokens.append(tok)
            pos = tok.end()
            if text[pos : pos + 1] in (",", ";", ":"):
                break
        return tokens

    def _role_names(self, text: str) -> Iterator[Entity | None]:
        for label in _ROLE_LABEL_RE.finditer(text):
            if _ORG_CUE_RE.search(label.group(0)) or _ADDRESS_CUE_RE.search(label.group(0)):
                continue
            tokens = self._name_tokens(text, label.end())
            if tokens and not self._weak_value(tokens):
                start, end = tokens[0].start(), tokens[-1].end()
                if text[end - 1] == "." and len(tokens[-1].group(0)) > 2:
                    end -= 1
                start, end = extend_person_span(text, start, end)
                yield make_entity(PDType.FIO, [(start, end)], priority=_PRIORITY_NAME)

    # --- ФИО как всё сообщение ---
    @staticmethod
    def _bare_names(text: str) -> Iterator[Entity | None]:
        value = _TRAILING_NOTE_RE.sub("", text.strip())
        if _BARE_NAME_RE.match(value) and len(value) <= 40 and not _has_stop_word(value):
            start = text.find(value)
            yield make_entity(PDType.FIO, [(start, start + len(value))], priority=_PRIORITY_BARE)
        m = _LATIN_LEAD_NAME_RE.match(text)
        if m and not _has_stop_word(m.group(1)):
            yield _group_entity(PDType.FIO, m, _PRIORITY_BARE)
