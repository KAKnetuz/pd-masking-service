"""Матрица вариантов записи ПД по ТЗ 4.2 (отчёт, не pytest).

Для каждого типа ПД и каждой оси генерируются синтетические варианты записи
(метка + значение). Для каждого варианта проверяется, найдено ли значение
полностью / частично / не найдено (сопоставление как в eval_gold). Ничего не чинится.

Запуск:
    python -m scripts.format_matrix
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from scripts._eval_common import find_entities, load_default_policy
from scripts.eval_gold import match_value

_MONTHS_GEN = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]
_MONTHS_SHORT = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]

_DATE_WORDS = "пятнадцатое марта тысяча девятьсот девяностого года"

_AXES = ["A", "B", "C", "D", "E", "F", "G"]


@dataclass(frozen=True, slots=True)
class TypeSpec:
    pd_type: str
    labels: tuple[str, ...]
    value: str
    axes: frozenset[str]


def _valid_inn() -> str:
    rng = random.Random(42)
    coeffs_11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
    coeffs_12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
    while True:
        digits = [rng.randint(0, 9) for _ in range(10)]
        n11 = sum(d * int(c) for d, c in zip(digits, coeffs_11, strict=False)) % 11 % 10
        n12 = sum(d * int(c) for d, c in zip(digits, coeffs_12, strict=False)) % 11 % 10
        return "".join(map(str, digits)) + str(n11) + str(n12)


def _valid_card() -> str:
    rng = random.Random(7)
    while True:
        digits = [rng.randint(0, 9) for _ in range(15)]
        total = 0
        for idx, ch in enumerate(reversed(digits)):
            d = ch
            if idx % 2 == 1:
                d *= 2
                if d > 9:
                    d -= 9
            total += d
        check = (10 - total % 10) % 10
        return "".join(map(str, digits)) + str(check)


_INN = _valid_inn()
_CARD = _valid_card()

SPECS: list[TypeSpec] = [
    TypeSpec("fio", ("ФИО", "имя"), "Иванов Иван Иванович", frozenset("ABCDG")),
    TypeSpec("birth_date", ("дата рождения",), "15.03.1990", frozenset("ABCDEG")),
    TypeSpec("birth_place", ("место рождения",), "г. Краснодар", frozenset("ABCDG")),
    TypeSpec("passport", ("паспорт", "серия … номер …"), "4509 123456", frozenset("ABCDFG")),
    TypeSpec("passport_issue_date", ("дата выдачи",), "20.05.2015", frozenset("ABCDEG")),
    TypeSpec("passport_issuer", ("орган выдачи",), "ГУ МВД России по Краснодарскому краю", frozenset("ABCDG")),
    TypeSpec("department_code", ("код подразделения",), "230-001", frozenset("ABCDFG")),
    TypeSpec("driver_license", ("ВУ", "серия … номер …"), "77 01 123456", frozenset("ABCDFG")),
    TypeSpec("citizenship", ("гражданство",), "Россия", frozenset("ABCDG")),
    TypeSpec("address", ("адрес",), "350000, г. Краснодар, ул. Красная, д. 10, кв. 5", frozenset("ABCDG")),
    TypeSpec("email", ("e-mail",), "ivanov@mail.ru", frozenset("ABCDG")),
    TypeSpec("phone", ("телефон",), "+7 918 555-44-33", frozenset("ABCDFG")),
    TypeSpec("inn", ("ИНН",), _INN, frozenset("ABCDFG")),
    TypeSpec("card_number", ("номер карты",), _CARD, frozenset("ABCDFG")),
    TypeSpec("cvv", ("CVV",), "123", frozenset("ABCDG")),
    TypeSpec("pin", ("пин-код",), "1234", frozenset("ABCDG")),
    TypeSpec("card_holder", ("держатель карты",), "Иван Иванов", frozenset("ABCDG")),
    TypeSpec("card_expiry", ("срок действия",), "12/28", frozenset("ABCDEG")),
]

# Ловушки: ничего не должно маскироваться.
TRAPS: list[str] = [
    "Александр Пушкин",
    "Лев Толстой",
    "Анна Каренина",
    "Иван Грозный",
    "Фёдор Достоевский",
    "Пётр Чайковский",
    "Юрий Гагарин",
    "Дмитрий Менделеев",
    "Отделение банка на ул. Ленина, д. 5",
    "Офис Альфа-Банка по адресу: г. Москва, ул. Тверская, д. 1",
    "ИНН 7707083893",
    "КПП 770701001",
    "Сумма 1 500,00 руб.",
    "в 2015 году",
    "пин-код не пришёл",
    "срок действия карты истекает в конце месяца",
    "Банк России",
    "Альфа-Банк",
    "Горячая линия 8 800 100-00-00",
    "Пушкин",
    "Толстой",
    "Улица Пушкина, д. 10",
    "Памятник Ленину",
    "Магазин на Красной площади",
    "Театр имени Чехова",
    "01.01.1799",
    "2024",
    "Спасибо",
    "VISA CARD",
    "Гражданин Российской Федерации",
]


def _apply_case(text: str, mode: str) -> str:
    if mode == "lower":
        return text.lower()
    if mode == "upper":
        return text.upper()
    if mode == "title":
        return text.title()
    return "".join(ch.upper() if i % 3 == 0 else ch.lower() for i, ch in enumerate(text))


def _space_groups(value: str, sep: str) -> str:
    return value.replace(" ", sep)


def _regroup(value: str, sep: str) -> str:
    if " " in value:
        return value.replace(" ", sep)
    digits = "".join(ch for ch in value if ch.isdigit())
    return sep.join(digits[i : i + 4] for i in range(0, len(digits), 4))


def _split_series_number(value: str) -> tuple[str, str]:
    parts = value.rsplit(" ", 1)
    return parts[0], parts[1]


def _parse_date(value: str) -> tuple[int, int, int]:
    day, month, year = value.split(".")
    return int(day), int(month), int(year)


def _axis_case(spec: TypeSpec) -> list[tuple[str, str, str]]:
    variants: list[tuple[str, str, str]] = []
    for label in spec.labels:
        base = f"{label}: {spec.value}"
        for mode in ("lower", "upper", "title", "random"):
            variants.append((f"case:{mode}", _apply_case(base, mode), _apply_case(spec.value, mode)))
    return variants


def _axis_space(spec: TypeSpec) -> list[tuple[str, str, str]]:
    variants: list[tuple[str, str, str]] = []
    for label in spec.labels:
        variants.append(("space:one", f"{label} {spec.value}", spec.value))
        variants.append(("space:multi", f"{label}    {spec.value}", spec.value))
        variants.append(("space:nbsp", f"{label}\u00a0{spec.value}", spec.value))
        variants.append(("space:tab", f"{label}\t{spec.value}", spec.value))
        if " " in spec.value:
            for name, sep in (("value-multi", "    "), ("value-nbsp", "\u00a0"), ("value-tab", "\t")):
                spaced = _space_groups(spec.value, sep)
                variants.append((f"space:{name}", f"{label} {spaced}", spaced))
    return variants


def _axis_separator(spec: TypeSpec) -> list[tuple[str, str, str]]:
    variants: list[tuple[str, str, str]] = []
    for label in spec.labels:
        variants.append(("sep:colon", f"{label}: {spec.value}", spec.value))
        variants.append(("sep:space", f"{label} {spec.value}", spec.value))
        variants.append(("sep:eq", f"{label}={spec.value}", spec.value))
        variants.append(("sep:dash", f"{label} — {spec.value}", spec.value))
        variants.append(("sep:paren", f"{label} ({spec.value})", spec.value))
        variants.append(("sep:guillemet", f"{label} «{spec.value}»", spec.value))
        variants.append(("sep:quote", f'{label} "{spec.value}"', spec.value))
    return variants


def _axis_service_words(spec: TypeSpec) -> list[tuple[str, str, str]]:
    variants: list[tuple[str, str, str]] = []
    service = (("клиента", "клиента"), ("указан в анкете", "указан в анкете"), ("по документам", "по документам"))
    for label in spec.labels:
        for name, words in service:
            variants.append((f"svc:{name}", f"{label} {words} {spec.value}", spec.value))
    return variants


def _full_date_variants(spec: TypeSpec) -> list[tuple[str, str, str]]:
    day, month, year = _parse_date(spec.value)
    month_gen = _MONTHS_GEN[month - 1]
    month_short = _MONTHS_SHORT[month - 1]
    variants = [
        ("дд.мм.гггг", f"{day:02d}.{month:02d}.{year}", f"{day:02d}.{month:02d}.{year}"),
        ("мм.дд.гггг", f"{month:02d}.{day:02d}.{year}", f"{month:02d}.{day:02d}.{year}"),
        ("гггг.дд.мм", f"{year}.{day:02d}.{month:02d}", f"{year}.{day:02d}.{month:02d}"),
        ("гггг-мм-дд", f"{year}-{month:02d}-{day:02d}", f"{year}-{month:02d}-{day:02d}"),
        ("дд/мм/гггг", f"{day:02d}/{month:02d}/{year}", f"{day:02d}/{month:02d}/{year}"),
        ("дд мм гггг", f"{day:02d} {month:02d} {year}", f"{day:02d} {month:02d} {year}"),
        ("дд/мм", f"{day:02d}/{month:02d}", f"{day:02d}/{month:02d}"),
        ("дд мм", f"{day:02d} {month:02d}", f"{day:02d} {month:02d}"),
        ("15 марта 1990", f"{day} {month_gen} {year}", f"{day} {month_gen} {year}"),
        ("15 мар 1990", f"{day} {month_short} {year}", f"{day} {month_short} {year}"),
        ("15-мар-90", f"{day}-{month_short}-{year % 100:02d}", f"{day}-{month_short}-{year % 100:02d}"),
        ("словами", _DATE_WORDS, _DATE_WORDS),
    ]
    out: list[tuple[str, str, str]] = []
    for label in spec.labels:
        for name, value, value_in in variants:
            out.append((f"date:{name}", f"{label}: {value}", value_in))
    return out


def _expiry_date_variants(spec: TypeSpec) -> list[tuple[str, str, str]]:
    variants = [
        ("12/28", "12/28", "12/28"),
        ("12.28", "12.28", "12.28"),
        ("12-28", "12-28", "12-28"),
        ("12 28", "12 28", "12 28"),
        ("12/2028", "12/2028", "12/2028"),
    ]
    out: list[tuple[str, str, str]] = []
    for label in spec.labels:
        for name, value, value_in in variants:
            out.append((f"date:{name}", f"{label}: {value}", value_in))
    return out


def _axis_dates(spec: TypeSpec) -> list[tuple[str, str, str]]:
    if spec.pd_type == "card_expiry":
        return _expiry_date_variants(spec)
    return _full_date_variants(spec)


def _axis_numbers(spec: TypeSpec) -> list[tuple[str, str, str]]:
    variants: list[tuple[str, str, str]] = []
    for label in spec.labels:
        digits = "".join(ch for ch in spec.value if ch.isdigit())
        spaced = _regroup(spec.value, " ")
        hyphen = _regroup(spec.value, "-")
        variants.append(("num:joined", f"{label}: {digits}", digits))
        variants.append(("num:spaced", f"{label}: {spaced}", spaced))
        variants.append(("num:hyphen", f"{label}: {hyphen}", hyphen))
        if spec.pd_type in ("passport", "driver_license"):
            series, number = _split_series_number(spec.value)
            series_first = f"серия {series} номер {number}"
            number_first = f"номер {number} серия {series}"
            variants.append(("num:series-first", f"{label}: {series_first}", series_first))
            variants.append(("num:number-first", f"{label}: {number_first}", number_first))
    return variants


def _axis_position(spec: TypeSpec) -> list[tuple[str, str, str]]:
    variants: list[tuple[str, str, str]] = []
    for label in spec.labels:
        base = f"{label}: {spec.value}"
        variants.append(("pos:start", base, spec.value))
        variants.append(("pos:middle", f"Данные: {base}, подтверждены.", spec.value))
        variants.append(("pos:end", f"Данные подтверждены: {base}.", spec.value))
    return variants


_AXIS_GENERATORS = {
    "A": _axis_case,
    "B": _axis_space,
    "C": _axis_separator,
    "D": _axis_service_words,
    "E": _axis_dates,
    "F": _axis_numbers,
    "G": _axis_position,
}


def _variants_for_axis(spec: TypeSpec, axis: str) -> list[tuple[str, str, str]]:
    return _AXIS_GENERATORS[axis](spec)


def _classify(text: str, value: str, entities: list[tuple[str, list[tuple[int, int]]]]) -> str:
    coverage, _ = match_value(text, value, "", entities)
    if coverage == 0.0:
        return "none"
    if coverage < 1.0:
        return "partial"
    return "full"


def _fmt_found(text: str, entities: list[tuple[str, list[tuple[int, int]]]]) -> str:
    if not entities:
        return "—"
    return "; ".join(f"{t}: {text[spans[0][0]:spans[-1][1]]}" for t, spans in entities)


def _run_variants() -> dict[str, dict[str, tuple[int, int, list[tuple[str, str, str]]]]]:
    policy = load_default_policy()
    table: dict[str, dict[str, tuple[int, int, list[tuple[str, str, str]]]]] = {}
    for spec in SPECS:
        table[spec.pd_type] = {}
        for axis in _AXES:
            if axis not in spec.axes:
                continue
            variants = _variants_for_axis(spec, axis)
            full = 0
            failures: list[tuple[str, str, str]] = []
            for name, phrase, value in variants:
                entities = find_entities(phrase, policy)
                cls = _classify(phrase, value, entities)
                if cls == "full":
                    full += 1
                else:
                    failures.append((name, cls, _fmt_found(phrase, entities)))
            table[spec.pd_type][axis] = (full, len(variants), failures)
    return table


def _print_table(table: dict[str, dict[str, tuple[int, int, list[tuple[str, str, str]]]]]) -> None:
    print("type;axis;full;total")
    for pd_type in table:
        for axis in _AXES:
            if axis in table[pd_type]:
                full, total, _ = table[pd_type][axis]
                print(f"{pd_type};{axis};{full};{total}")


def _print_failures(table: dict[str, dict[str, tuple[int, int, list[tuple[str, str, str]]]]]) -> None:
    print("axis;type;variant;status;found")
    for axis in _AXES:
        shown = 0
        for pd_type in table:
            if axis not in table[pd_type]:
                continue
            _, _, failures = table[pd_type][axis]
            for name, cls, found in failures:
                if shown >= 5:
                    break
                print(f"{axis};{pd_type};{name};{cls};{found}")
                shown += 1
            if shown >= 5:
                break


def _run_traps() -> list[str]:
    policy = load_default_policy()
    triggered: list[str] = []
    for trap in TRAPS:
        if find_entities(trap, policy):
            triggered.append(trap)
    return triggered


def main() -> int:
    table = _run_variants()
    _print_table(table)
    _print_failures(table)
    triggered = _run_traps()
    print(f"traps_triggered={len(triggered)} of {len(TRAPS)}")
    for trap in triggered:
        print(f"trap:{trap}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
