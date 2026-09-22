"""Прогон фраз через DetectionEngine и сравнение с ожиданиями.

Печатает таблицу: фраза | найдено (тип: фрагменты) | ожидание | OK/MISS/FP.
Используется для диагностики пропусков ПД в коротких фразах датасета
(значения без контекста и с неверными контрольными суммами).

Запуск из корня репозитория: python -m scripts.probe_phrases
"""

from __future__ import annotations

from pathlib import Path

from app.core.engine import DetectionEngine
from app.core.policy import load_policies

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICIES = load_policies(REPO_ROOT / "config" / "systems.yaml")
POLICY = POLICIES.resolve(None)  # политика "default"

# Ожидание: список (тип, [части]) или None — ничего не должно быть найдено.
# Части — подстроки значения (метка остаётся открытой).
CASES: list[tuple[str, list[tuple[str, list[str]]] | None]] = [
    # --- Голые значения (весь текст = одно значение) ---------------------
    ("1234", [("pin", ["1234"])]),
    ("123", [("cvv", ["123"])]),
    ("12/27", [("card_expiry", ["12/27"])]),
    ("12/2027", [("card_expiry", ["12/2027"])]),
    ("01.01.1990", [("date", ["01.01.1990"])]),
    ("1990-01-15", [("date", ["1990-01-15"])]),
    ("15 марта 1990", [("date", ["15 марта 1990"])]),
    ("4509 123456", [("passport", ["4509", "123456"])]),
    ("45 09 123456", [("passport", ["45 09", "123456"])]),
    ("4509123456", [("passport", ["4509123456"])]),
    ("99 00 123456", [("passport", ["99 00", "123456"])]),
    ("77 АА 123456", [("driver_license", ["77 АА 123456"])]),
    ("230-005", [("department_code", ["230-005"])]),
    ("350000", [("address", ["350000"])]),
    ("123456789012", [("inn", ["123456789012"])]),
    ("1234567890", [("passport", ["1234567890"])]),
    ("1234 5678 9012 3456", [("card_number", ["1234 5678 9012 3456"])]),
    ("1234567890123456", [("card_number", ["1234567890123456"])]),
    ("+79161234567", [("phone", ["+79161234567"])]),
    ("8 916 123 45 67", [("phone", ["8 916 123 45 67"])]),
    ("ivan.petrov@mail.ru", [("email", ["ivan.petrov@mail.ru"])]),
    ("Иванов Иван Иванович", [("fio", ["Иванов Иван Иванович"])]),
    ("IVAN IVANOV", [("card_holder", ["IVAN IVANOV"])]),
    ("Россия", [("citizenship", ["Россия"])]),
    ("Украина", [("citizenship", ["Украина"])]),
    ("Российская Федерация", [("citizenship", ["Российская Федерация"])]),
    ("ГУ МВД России по г. Москве", [("passport_issuer", ["ГУ МВД России по г. Москве"])]),
    ("ОУФМС России по Краснодарскому краю", [("passport_issuer", ["ОУФМС России по Краснодарскому краю"])]),
    # --- С метками (неверные контрольные суммы, разные формы) -------------
    ("Срок действия: 12/27", [("card_expiry", ["12/27"])]),
    ("Действует до 05/28", [("card_expiry", ["05/28"])]),
    ("Срок действия карты 12.2027", [("card_expiry", ["12.2027"])]),
    ("CVV: 123", [("cvv", ["123"])]),
    ("CVC2 123", [("cvv", ["123"])]),
    ("код безопасности 123", [("cvv", ["123"])]),
    ("ПИН-код 1234", [("pin", ["1234"])]),
    ("PIN: 1234", [("pin", ["1234"])]),
    ("ИНН 123456789012", [("inn", ["123456789012"])]),
    ("Номер карты 1234 5678 9012 3456", [("card_number", ["1234 5678 9012 3456"])]),
    ("Гражданство: Россия", [("citizenship", ["Россия"])]),
    ("Гражданка России", [("citizenship", ["России"])]),
    ("гражданин Республики Казахстан", [("citizenship", ["Республики Казахстан"])]),
    ("Дата выдачи: 01.02.2015", [("passport_issue_date", ["01.02.2015"])]),
    ("Выдан ОВД района Хамовники г. Москвы", [("passport_issuer", ["ОВД района Хамовники г. Москвы"])]),
    ("Код подразделения 770-001", [("department_code", ["770-001"])]),
    ("Водительское удостоверение 77 АА 123456", [("driver_license", ["77 АА", "123456"])]),
    ("Дата рождения: 5 марта 1990 г.", [("birth_date", ["5 марта 1990"])]),
    ("Место рождения: гор. Москва", [("birth_place", ["Москва"])]),
    ("Место рождения — Краснодарский край, ст. Каневская", [("birth_place", ["Краснодарский край, ст. Каневская"])]),
    ("Имя держателя: IVANOV IVAN", [("card_holder", ["IVANOV IVAN"])]),
    ("Держатель: Ivan Petrov", [("card_holder", ["Ivan Petrov"])]),
    ("тел. 8(861)234-56-78", [("phone", ["8(861)234-56-78"])]),
    ("e-mail: a.b-c_d@sub.domain.ru", [("email", ["a.b-c_d@sub.domain.ru"])]),
    # --- Регистр и одиночные слова -----------------------------------------
    ("россия", [("citizenship", ["россия"])]),
    ("РОССИЯ", [("citizenship", ["РОССИЯ"])]),
    ("Российская федерация", [("citizenship", ["Российская федерация"])]),
    ("15 Марта 1990", [("date", ["15 Марта 1990"])]),
    ("15 МАРТА 1990", [("date", ["15 МАРТА 1990"])]),
    ("77 аа 123456", [("driver_license", ["77 аа 123456"])]),
    ("Иванов", [("fio", ["Иванов"])]),
    ("Иван", [("fio", ["Иван"])]),
    ("Ивановна", [("fio", ["Ивановна"])]),
    ("иванов", [("fio", ["иванов"])]),
    ("Москва", [("address", ["Москва"])]),
    ("краснодар", [("address", ["краснодар"])]),
    ("Санкт-Петербург", [("address", ["Санкт-Петербург"])]),
    ("Ivan Petrov", [("card_holder", ["Ivan Petrov"])]),
    ("ivan petrov", [("card_holder", ["ivan petrov"])]),
    # --- Ловушки — ничего не найдено --------------------------------------
    ("Александр Пушкин", None),
    ("Лев Толстой", None),
    ("2024", None),
    ("Спасибо", None),
    ("Отделение банка на ул. Ленина, д. 5", None),
    ("Тел. горячей линии 8 800 100-00-00", None),
    ("Пушкин", None),
    ("Толстой", None),
    ("магазин", None),
    ("VISA CARD", None),
    ("01.01.1799", None),
]


def _found(text: str) -> list[tuple[str, list[str]]]:
    engine = DetectionEngine()
    entities = engine.detect(text, POLICY.pd_types, POLICY.combinations)
    return [
        (entity.pd_type.value, [text[start:end] for start, end in entity.parts])
        for entity in entities
    ]


def _fmt(found: list[tuple[str, list[str]]]) -> str:
    if not found:
        return "—"
    return "; ".join(f"{t}: {', '.join(parts)}" for t, parts in found)


def _fmt_expected(expected: list[tuple[str, list[str]]] | None) -> str:
    if expected is None:
        return "ничего"
    return "; ".join(f"{t}: {', '.join(parts)}" for t, parts in expected)


def main() -> None:
    ok = miss = fp = 0
    print(f"{'фраза':<42}{'найдено':<52}{'ожидание':<40}статус")
    print("-" * 150)
    for text, expected in CASES:
        found = _found(text)
        status = (
            ("OK" if not found else "FP") if expected is None else "OK" if found == expected else "MISS"
        )
        if status == "OK":
            ok += 1
        elif status == "MISS":
            miss += 1
        else:
            fp += 1
        print(f"{text:<42}{_fmt(found):<52}{_fmt_expected(expected):<40}{status}")
    print("-" * 150)
    print(f"Итого: OK={ok}  MISS={miss}  FP={fp}  (всего {len(CASES)})")


if __name__ == "__main__":
    main()
