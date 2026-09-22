"""Распознавание ПД: позитивные и негативные примеры по всем категориям ТЗ."""

from app.core.engine import DetectionEngine
from app.core.entities import PDType

ENGINE = DetectionEngine()

POSITIVE = [
    (PDType.FIO, "Клиент Иванов Иван Иванович просит справку", "Иванов Иван Иванович"),
    (PDType.FIO, "иванов иван иванович просит справку", "иванов иван иванович"),
    (PDType.FIO, "Документы подписал Петров П.П.", "Петров П.П."),
    (PDType.FIO, "Звонила Мария Сидорова", "Мария Сидорова"),
    (PDType.PASSPORT, "паспорт 4509 123456", "4509 123456"),
    (PDType.PASSPORT, "серия 45 09 номер 123456", "45 09 номер 123456"),
    (PDType.DRIVER_LICENSE, "водительское удостоверение 77 АВ 123456", "77 АВ 123456"),
    (PDType.DEPARTMENT_CODE, "код подразделения 770-001", "770-001"),
    (PDType.PASSPORT_ISSUER, "выдан ОВД района Хамовники г. Москвы 12.03.2010", "ОВД района Хамовники г. Москвы"),
    (PDType.PASSPORT_ISSUE_DATE, "дата выдачи 03.12.2010", "03.12.2010"),
    (PDType.BIRTH_DATE, "Дата рождения: 12 марта 1990 г.", "12 марта 1990"),
    (PDType.BIRTH_DATE, "дата рождения 1990.12.03", "1990.12.03"),
    (PDType.BIRTH_PLACE, "место рождения: г. Нижний Новгород", "Нижний Новгород"),
    (PDType.CITIZENSHIP, "Гражданство: Российская Федерация", "Российская Федерация"),
    (PDType.EMAIL, "почта Ivan.Petrov@Mail.RU", "Ivan.Petrov@Mail.RU"),
    (PDType.PHONE, "тел. 8 916 123-45-67", "8 916 123-45-67"),
    (PDType.PHONE, "+7 (916) 123-45-67", "+7 (916) 123-45-67"),
    (PDType.INN, "ИНН 500100732259", "500100732259"),
    (PDType.CARD_NUMBER, "карта 4276 1234 5678 9010", "4276 1234 5678 9010"),
    (PDType.CARD_CVV, "CVV 123", "123"),
    (PDType.CARD_PIN, "пин-код 1234", "1234"),
    (PDType.CARD_HOLDER, "Держатель карты: IVAN IVANOV", "IVAN IVANOV"),
    (PDType.CARD_EXPIRY, "срок действия 12/27", "12/27"),
    (PDType.SNILS, "СНИЛС 112-233-445 95", "112-233-445 95"),
]

NEGATIVE = [
    "Александр Пушкин написал «Евгения Онегина».",
    "Встреча с поэтом Александром Сергеевичем Пушкиным",
    "Отделение банка находится по адресу г. Москва, ул. Тверская, д. 7",
    "Заказ 1234 доставлен 5 штук",
    "Роман Толстого «Война и мир»",
]


def _found(text: str) -> list[tuple[PDType, str]]:
    return [(e.pd_type, text[e.start : e.end]) for e in ENGINE.detect(text)]


def test_positive_cases() -> None:
    for pd_type, text, expected in POSITIVE:
        assert (pd_type, expected) in _found(text), f"{pd_type.value}: {text!r} -> {_found(text)}"


def test_negative_cases() -> None:
    for text in NEGATIVE:
        assert _found(text) == [], f"ложное срабатывание: {text!r} -> {_found(text)}"


def test_address_components() -> None:
    text = "Адрес: 123456, г. Москва, ул. Ленина, д. 5, кв. 12"
    values = [v for t, v in _found(text) if t is PDType.ADDRESS]
    assert values == ["123456", "Москва", "Ленина", "5", "12"]


def test_weak_entities_need_context() -> None:
    assert _found("Скидка действует до 12/27") == []
    assert (PDType.CARD_EXPIRY, "12/27") in _found("карта 4276 1234 5678 9010 12/27")


def test_text_date_trailing_words_excluded() -> None:
    """Слова-хвосты «года/год/г./г.р.» не входят в фрагмент даты."""
    assert _found("Она родилась 12 марта 1990 года в Москве.") == [
        (PDType.BIRTH_DATE, "12 марта 1990")
    ]
    assert _found("Дата рождения 12 марта 1990 г.") == [(PDType.BIRTH_DATE, "12 марта 1990")]
    assert _found("05.11.1985 г.р.") == [(PDType.BIRTH_DATE, "05.11.1985")]


def test_combination_rule() -> None:
    rules = {PDType.CARD_PIN: frozenset({PDType.CARD_NUMBER})}
    assert ENGINE.detect("пин-код 1234", combinations=rules) == []
    text = "карта 4276 1234 5678 9010, пин-код 1234"
    assert PDType.CARD_PIN in {e.pd_type for e in ENGINE.detect(text, combinations=rules)}


def test_large_text_is_fast() -> None:
    import time

    chunk = "Клиент Иванов Иван Иванович, паспорт 4509 123456, тел. +7 916 123-45-67. Обычный текст запроса. "
    text = chunk * 4000  # ~ 400 тыс. символов ≈ 100 тыс. токенов
    started = time.perf_counter()
    entities = ENGINE.detect(text)
    assert len(entities) >= 12000
    assert time.perf_counter() - started < 10
