"""Матрица вариантов записи ПД по ТЗ 4.2 на синтетических данных (отчёт, не тест).

Для каждого типа ПД строятся фразы «метка + значение» по осям вариативности:
    A — регистр всей фразы (lower / UPPER / Title / случайный);
    B — пробелы: несколько подряд, неразрывный, табуляция (между меткой и значением и внутри значения);
    C — разделитель метка→значение (":", " ", "=", " — ", скобки, «ёлочки», кавычки);
    D — служебные слова между меткой и значением;
    E — форматы дат;
    F — запись номеров (слитно, пробелами, дефисами; «серия … номер …» в обоих порядках);
    G — положение значения в предложении.
Ожидается, что замаскированы все буквы и цифры значения, кроме служебных слов внутри него
(«г.», «ул.», «серия», «номер»), и ничего вне значения.
Статусы: full — всё значение замаскировано; partial — часть; none — ничего; over — замаскировано
что-то вне значения (метка или соседние слова). Ничего не чинит.

Запуск:
    python -m scripts.format_matrix
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from scripts._eval_common import Finding, find_entities, load_default_policy

AXES = "ABCDEFG"
FAILURES_PER_AXIS = 8
_WORD_RE = re.compile(r"\w+")
_MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
           "ноября", "декабря")
_MONTHS_SHORT = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
_DATE_WORDS = "двадцать первое апреля тысяча девятьсот восемьдесят пятого года"


def luhn_ok(number: str) -> bool:
    total = 0
    for idx, ch in enumerate(reversed(number)):
        digit = int(ch) * (2 if idx % 2 else 1)
        total += digit - 9 if digit > 9 else digit
    return total % 10 == 0


def make_card(prefix: str = "220012345678901") -> str:
    """16-значный номер карты, валидный по алгоритму Луна."""
    return next(prefix + str(d) for d in range(10) if luhn_ok(prefix + str(d)))


def _inn_digit(digits: str, coeffs: tuple[int, ...]) -> str:
    return str(sum(int(d) * c for d, c in zip(digits, coeffs, strict=True)) % 11 % 10)


def make_inn(base: str = "5001007322") -> str:
    """12-значный ИНН физлица с верными контрольными цифрами."""
    n11 = _inn_digit(base, (7, 2, 4, 10, 3, 5, 9, 4, 6, 8))
    n12 = _inn_digit(base + n11, (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8))
    return base + n11 + n12


_INN = make_inn()
_CARD = make_card()


@dataclass(frozen=True, slots=True)
class Spec:
    name: str
    labels: tuple[str, ...]
    value: str
    keep: frozenset[str] = frozenset()  # служебные слова внутри значения, их маскировать не нужно
    groups: tuple[str, ...] = ()  # группы цифр для оси F
    date: str = ""  # "full" | "expiry" — включает ось E
    series_number: bool = False  # «серия … номер …» на оси F


@dataclass(frozen=True, slots=True)
class Variant:
    axis: str
    name: str
    phrase: str
    start: int
    end: int
    keep: frozenset[str]


SPECS: tuple[Spec, ...] = (
    Spec("fio", ("ФИО", "клиент"), "Иванов Иван Иванович"),
    Spec("birth_date", ("дата рождения",), "15.03.1990", date="full"),
    Spec("birth_place", ("место рождения",), "г. Краснодар", keep=frozenset({"г"})),
    Spec("passport", ("паспорт",), "4509 123456", groups=("4509", "123456"), series_number=True),
    Spec("passport_issue_date", ("дата выдачи",), "20.05.2015", date="full"),
    Spec("passport_issuer", ("кем выдан", "орган выдачи"), "ГУ МВД России по Краснодарскому краю"),
    Spec("department_code", ("код подразделения",), "230-001", groups=("230", "001")),
    Spec("driver_license", ("водительское удостоверение", "ВУ"), "77 01 123456", groups=("77", "01", "123456"),
         series_number=True),
    Spec("citizenship", ("гражданство",), "Россия"),
    Spec("address", ("адрес",), "350000, г. Краснодар, ул. Красная, д. 10, кв. 5",
         keep=frozenset({"г", "ул", "д", "кв"})),
    Spec("email", ("e-mail", "почта"), "ivanov@mail.ru"),
    Spec("phone", ("телефон",), "+7 918 555-44-33", groups=("+7", "918", "555", "44", "33")),
    Spec("inn", ("ИНН",), _INN, groups=(_INN[:4], _INN[4:8], _INN[8:])),
    Spec("card_number", ("номер карты", "карта"), _CARD, groups=(_CARD[:4], _CARD[4:8], _CARD[8:12], _CARD[12:])),
    Spec("cvv", ("CVV", "cvc"), "123"),
    Spec("pin", ("пин-код", "PIN"), "1234"),
    Spec("card_holder", ("держатель карты",), "Иван Иванов"),
    Spec("card_holder_latin", ("держатель карты", "имя на карте"), "IVAN IVANOV"),
    Spec("card_expiry", ("срок действия",), "12/28", date="expiry"),
)

# Однозначно не ПД: ничего не должно маскироваться.
TRAPS: tuple[str, ...] = (
    "Александр Пушкин",
    "Лев Толстой",
    "Анна Каренина",
    "Иван Грозный",
    "Фёдор Достоевский",
    "Пётр Чайковский",
    "Юрий Гагарин",
    "Дмитрий Менделеев",
    "Стихи Пушкина мы учили в школе.",
    "Отделение банка находится по адресу: г. Москва, ул. Каланчевская, д. 27.",
    "Офис Альфа-Банка по адресу: г. Москва, ул. Тверская, д. 1",
    "Реквизиты организации: ИНН/КПП 7707083893/773601001, ОГРН 1027700132195.",
    "Сумма перевода 1 500,00 руб.",
    "Паспорт оформлен в 2015 году.",
    "Пин-код не пришёл.",
    "Срок действия акции истекает в конце квартала.",
    "Банк России",
    "Альфа-Банк",
    "Горячая линия 8 800 100-00-00",
    "Спасибо, всё понятно.",
    "Карта заблокирована.",
    "Серия фильмов закончилась.",
    "Номер заявки 123456 принят.",
    "Встреча назначена на 15 марта.",
    "Театр имени Чехова",
)


# --- построение вариантов ---------------------------------------------------------


def _variant(axis: str, name: str, before: str, value: str, after: str, keep: frozenset[str]) -> Variant:
    return Variant(axis, name, before + value + after, len(before), len(before) + len(value), keep)


def _random_case(text: str) -> str:
    return "".join(ch.upper() if i % 2 else ch.lower() for i, ch in enumerate(text))


_CASES: tuple[tuple[str, Callable[[str], str]], ...] = (
    ("lower", str.lower),
    ("upper", str.upper),
    ("title", str.title),
    ("random", _random_case),
)


def axis_a(spec: Spec, label: str) -> Iterator[Variant]:
    for name, fn in _CASES:
        before, value = fn(f"{label}: "), fn(spec.value)
        yield _variant("A", f"case:{name}", before, value, "", spec.keep)


def axis_b(spec: Spec, label: str) -> Iterator[Variant]:
    for name, gap in (("multi", "    "), ("nbsp", "\u00a0"), ("tab", "\t")):
        yield _variant("B", f"label-{name}", f"{label}{gap}", spec.value, "", spec.keep)
        if " " in spec.value:
            yield _variant("B", f"value-{name}", f"{label}: ", spec.value.replace(" ", gap), "", spec.keep)


_SEPARATORS = (("colon", ": ", ""), ("space", " ", ""), ("eq", "=", ""), ("dash", " — ", ""),
               ("paren", " (", ")"), ("guillemets", " «", "»"), ("quotes", ' "', '"'))


def axis_c(spec: Spec, label: str) -> Iterator[Variant]:
    for name, left, right in _SEPARATORS:
        yield _variant("C", f"sep:{name}", label + left, spec.value, right, spec.keep)


_SERVICE = (
    ("клиента:", " клиента: "),
    ("указан в анкете:", " указан в анкете: "),
    ("по документам", " по документам "),
)


def axis_d(spec: Spec, label: str) -> Iterator[Variant]:
    for name, words in _SERVICE:
        yield _variant("D", f"words:{name}", label + words, spec.value, "", spec.keep)


def _full_dates(value: str) -> tuple[tuple[str, str], ...]:
    day, month, year = (int(p) for p in value.split("."))
    d, m, y, yy = f"{day:02d}", f"{month:02d}", str(year), f"{year % 100:02d}"
    return (
        ("дд.мм.гггг", f"{d}.{m}.{y}"), ("мм.дд.гггг", f"{m}.{d}.{y}"), ("гггг.дд.мм", f"{y}.{d}.{m}"),
        ("гггг-мм-дд", f"{y}-{m}-{d}"), ("дд/мм/гггг", f"{d}/{m}/{y}"), ("дд мм гггг", f"{d} {m} {y}"),
        ("дд.мм.гг", f"{d}.{m}.{yy}"), ("дд/мм", f"{d}/{m}"), ("дд мм", f"{d} {m}"),
        ("д месяц гггг", f"{day} {_MONTHS[month - 1]} {y}"), ("д мес гггг", f"{day} {_MONTHS_SHORT[month - 1]} {y}"),
        ("д-мес-гг", f"{day}-{_MONTHS_SHORT[month - 1]}-{yy}"), ("д месяц", f"{day} {_MONTHS[month - 1]}"),
        ("словами", _DATE_WORDS),
    )


_EXPIRY = (("мм/гг", "12/28"), ("мм.гг", "12.28"), ("мм-гг", "12-28"), ("мм/гггг", "12/2028"))


def axis_e(spec: Spec, label: str) -> Iterator[Variant]:
    formats = _full_dates(spec.value) if spec.date == "full" else _EXPIRY
    keep = frozenset({"года"})
    for name, value in formats:
        yield _variant("E", f"date:{name}", f"{label}: ", value, "", keep)


def _series_number_variants(spec: Spec, label: str) -> Iterator[Variant]:
    series, number = " ".join(spec.groups[:-1]), spec.groups[-1]
    keep = frozenset({"серия", "номер"})
    for name, value in (
        ("серия-номер", f"серия {series} номер {number}"),
        ("номер-серия", f"номер {number} серия {series}"),
        ("серия:;номер:", f"серия: {series}; номер: {number}"),
    ):
        yield _variant("F", f"num:{name}", f"{label} ", value, "", keep)


def axis_f(spec: Spec, label: str) -> Iterator[Variant]:
    for name, sep in (("joined", ""), ("spaced", " "), ("hyphen", "-")):
        yield _variant("F", f"num:{name}", f"{label}: ", sep.join(spec.groups), "", spec.keep)
    if spec.series_number:
        yield from _series_number_variants(spec, label)


def axis_g(spec: Spec, label: str) -> Iterator[Variant]:
    yield _variant("G", "pos:start", f"{label}: ", spec.value, ", данные подтверждены.", spec.keep)
    yield _variant("G", "pos:middle", f"В анкете {label}: ", spec.value, ", данные подтверждены.", spec.keep)
    yield _variant("G", "pos:end", f"Данные подтверждены, {label}: ", spec.value, ".", spec.keep)


_AXIS_BUILDERS: dict[str, Callable[[Spec, str], Iterator[Variant]]] = {
    "A": axis_a, "B": axis_b, "C": axis_c, "D": axis_d, "E": axis_e, "F": axis_f, "G": axis_g,
}


def applicable_axes(spec: Spec) -> str:
    axes = "ABCDG"
    if spec.date:
        axes += "E"
    if spec.groups:
        axes += "F"
    return "".join(a for a in AXES if a in axes)


def variants_for(spec: Spec) -> Iterator[Variant]:
    for axis in applicable_axes(spec):
        for label in spec.labels:
            yield from _AXIS_BUILDERS[axis](spec, label)


# --- оценка варианта ---------------------------------------------------------------


def expected_positions(v: Variant) -> set[int]:
    """Буквы и цифры значения, кроме служебных слов из keep (без учёта регистра)."""
    value = v.phrase[v.start : v.end]
    skip = {v.start + i for m in _WORD_RE.finditer(value) if m.group(0).casefold() in v.keep
            for i in range(m.start(), m.end())}
    return {i for i in range(v.start, v.end) if v.phrase[i].isalnum() and i not in skip}


def masked_positions(phrase: str, findings: list[Finding]) -> set[int]:
    return {i for _, spans in findings for s, e in spans for i in range(s, e) if not phrase[i].isspace()}


def status(v: Variant, findings: list[Finding]) -> tuple[str, bool]:
    """(full | partial | none, замаскировано ли что-то вне значения)."""
    wanted = expected_positions(v)
    masked = masked_positions(v.phrase, findings)
    over = any(i < v.start or i >= v.end for i in masked)
    hit = len(wanted & masked)
    if hit == len(wanted):
        return "full", over
    return ("partial" if hit else "none"), over


def describe(phrase: str, findings: list[Finding]) -> str:
    if not findings:
        return "—"
    return "; ".join(f"{t}:" + "|".join(phrase[s:e] for s, e in spans) for t, spans in findings)


# --- отчёт ---------------------------------------------------------------------------


def run_matrix() -> tuple[dict[tuple[str, str], Counter[str]], list[tuple[str, str, str, str, str, str]]]:
    policy = load_default_policy()
    table: dict[tuple[str, str], Counter[str]] = {}
    failures: list[tuple[str, str, str, str, str, str]] = []
    for spec in SPECS:
        for v in variants_for(spec):
            findings = find_entities(v.phrase, policy)
            st, over = status(v, findings)
            cell = table.setdefault((spec.name, v.axis), Counter())
            cell[st] += 1
            cell["over"] += over
            if st != "full" or over:
                failures.append((v.axis, spec.name, v.name, st + ("+over" if over else ""), v.phrase,
                                 describe(v.phrase, findings)))
    return table, failures


def print_table(table: dict[tuple[str, str], Counter[str]]) -> None:
    print("type;axis;full;partial;none;over;total")
    totals: dict[str, Counter[str]] = {}
    for (name, axis), c in table.items():
        total = c["full"] + c["partial"] + c["none"]
        print(f"{name};{axis};{c['full']};{c['partial']};{c['none']};{c['over']};{total}")
        totals.setdefault(axis, Counter()).update(c)
    print("axis;full;total;share")
    for axis in AXES:
        c = totals.get(axis, Counter())
        total = c["full"] + c["partial"] + c["none"]
        if total:
            print(f"{axis};{c['full']};{total};{c['full'] / total:.0%}")


def print_failures(failures: list[tuple[str, str, str, str, str, str]]) -> None:
    print("axis;type;variant;status;phrase;found")
    shown: Counter[str] = Counter()
    for row in failures:
        if shown[row[0]] < FAILURES_PER_AXIS:
            shown[row[0]] += 1
            print(";".join(field.replace("\t", "\\t").replace("\u00a0", "<nbsp>") for field in row))


def print_traps() -> None:
    policy = load_default_policy()
    triggered = [(t, find_entities(t, policy)) for t in TRAPS]
    triggered = [(t, f) for t, f in triggered if f]
    print(f"traps_triggered={len(triggered)} of {len(TRAPS)}")
    for trap, findings in triggered:
        print(f"trap;{trap};{describe(trap, findings)}")


def main() -> int:
    table, failures = run_matrix()
    print_table(table)
    print_failures(failures)
    print_traps()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
