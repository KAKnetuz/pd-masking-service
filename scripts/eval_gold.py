"""Оценка точности маскирования на размеченном наборе (gold).

Вход — CSV разметки (разделитель ";", UTF-8 или cp1251):
    id;text;mask;trap;expected      (колонка mask — справочная, не используется)
    trap: 1 = ловушка (ПД нет), 0 = есть ПД, пусто = не размечено (строка пропускается).
    expected: значения через " || ", каждое — "тип::значение". Значение — точная подстрока
    текста, которую нужно замаскировать; составное ПД («серия 4509 номер 123456») —
    отдельными значениями: "passport::4509 || passport::123456".

Если рядом с CSV лежит файл <имя>.texts.jsonl (его пишет make_gold_template), тексты берутся
из него по id: Excel при сохранении портит числа и строки, начинающиеся с "+", "=", "-".

Классы значения:
    TP          — все символы значения (кроме пробелов) замаскированы сущностью того же типа;
    WRONG_TYPE  — замаскировано полностью, но тип другой;
    PARTIAL     — замаскирована часть символов;
    FN          — не замаскировано ничего;
    NOT_IN_TEXT — значения нет в тексте (ошибка разметки, в метрики не входит).
FP — замаскированный спан, не пересекающийся ни с одним ожидаемым значением (включая ловушки).

Запуск:
    python -m scripts.eval_gold --gold <gold.csv> --out <errors.csv> [--repo <каталог другой версии>]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from scripts._eval_common import Finding, assert_outside_repo, find_entities, load_default_policy, read_csv_rows

CLASSES = ("TP", "WRONG_TYPE", "PARTIAL", "FN")
NOT_IN_TEXT = "NOT_IN_TEXT"
FP_VALUE = "FP_VALUE"
TRAP_FP = "TRAP_FP"

# Находки другой версии кода (--repo) считаются в отдельном процессе, чтобы модули app
# двух версий не смешались. Наружу уходят только типы и спаны.
_REPO_FINDER = r"""
import json, sys
from pathlib import Path
from app.core.engine import DetectionEngine
from app.core.policy import load_policies
policy = load_policies(Path.cwd() / "config" / "systems.yaml").resolve(None)
engine = DetectionEngine()
texts = json.load(sys.stdin)
out = []
for text in texts:
    ents = engine.detect(text, policy.pd_types, policy.combinations)
    out.append([(e.pd_type.value, [list(p) for p in e.parts]) for e in ents])
json.dump(out, sys.stdout)
"""


@dataclass(frozen=True, slots=True)
class GoldRow:
    id: str
    text: str
    trap: int | None  # None = не размечено
    expected: tuple[tuple[str, str], ...]  # (тип, значение)


@dataclass(slots=True)
class Metrics:
    labeled: int = 0
    skipped: int = 0
    traps: int = 0
    trap_fp: int = 0
    pd_texts: int = 0
    fn_text: int = 0
    perfect_text: int = 0
    classes: Counter[str] = field(default_factory=Counter)
    not_in_text: int = 0
    fp: int = 0
    expected_chars: int = 0
    expected_masked: int = 0
    masked_chars: int = 0
    overmask: int = 0
    by_type: dict[str, Counter[str]] = field(default_factory=dict)

    @property
    def values(self) -> int:
        return sum(self.classes[c] for c in CLASSES)

    @property
    def precision(self) -> float:
        tp = self.classes["TP"] + self.classes["WRONG_TYPE"]
        return tp / (tp + self.fp) if tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.classes["TP"] / self.values if self.values else 0.0

    @property
    def recall_any_type(self) -> float:
        tp = self.classes["TP"] + self.classes["WRONG_TYPE"]
        return tp / self.values if self.values else 0.0

    @property
    def recall_chars(self) -> float:
        return self.expected_masked / self.expected_chars if self.expected_chars else 0.0

    @property
    def overmask_chars(self) -> float:
        return self.overmask / self.masked_chars if self.masked_chars else 0.0


@dataclass(frozen=True, slots=True)
class ErrorRow:
    id: str
    kind: str
    pd_type: str
    expected: str
    found: str
    text: str


# --- разбор разметки ----------------------------------------------------------


def parse_expected(raw: str) -> tuple[tuple[str, str], ...]:
    """"тип::значение || тип::значение" → ((тип, значение), ...). Пробелы по краям значения не значимы."""
    items: list[tuple[str, str]] = []
    for item in raw.split("||"):
        pd_type, sep, value = item.strip().partition("::")
        if sep and value.strip():
            items.append((pd_type.strip(), value.strip()))
    return tuple(items)


def parse_trap(raw: str) -> int | None:
    value = raw.strip()
    if value == "":
        return None
    return 1 if value == "1" else 0


def parse_gold_row(row: dict[str, str], texts_by_id: dict[str, str] | None = None) -> GoldRow:
    """Одна строка CSV → GoldRow. Текст берётся из texts_by_id, если он там есть."""
    row_id = str(row.get("id") or "").strip()
    text = str(row.get("text") or "")
    if texts_by_id and row_id in texts_by_id:
        text = texts_by_id[row_id]
    return GoldRow(
        id=row_id,
        text=text,
        trap=parse_trap(str(row.get("trap") or "")),
        expected=parse_expected(str(row.get("expected") or "")),
    )


# --- сопоставление -------------------------------------------------------------


def occurrences(text: str, value: str) -> list[tuple[int, int]]:
    """Все вхождения value в text (с перекрытием)."""
    found: list[tuple[int, int]] = []
    start = text.find(value)
    while value and start != -1:
        found.append((start, start + len(value)))
        start = text.find(value, start + 1)
    return found


def _type_at(pos: int, findings: list[Finding]) -> str | None:
    for pd_type, spans in findings:
        if any(s <= pos < e for s, e in spans):
            return pd_type
    return None


def _coverage(text: str, start: int, end: int, findings: list[Finding]) -> tuple[float, set[str]]:
    positions = [i for i in range(start, end) if not text[i].isspace()]
    types = [_type_at(i, findings) for i in positions]
    covered = [t for t in types if t is not None]
    share = len(covered) / len(positions) if positions else 0.0
    return share, set(covered)


def match_value(text: str, value: str, expected_type: str, findings: list[Finding]) -> tuple[float, bool]:
    """Лучшее покрытие значения по всем вхождениям: (доля символов без пробелов, тип совпал)."""
    best = (0.0, False)
    for start, end in occurrences(text, value):
        share, types = _coverage(text, start, end, findings)
        type_ok = share == 1.0 and types == {expected_type}
        if (share, type_ok) > best:
            best = (share, type_ok)
    return best


def classify_value(text: str, value: str, expected_type: str, findings: list[Finding]) -> str:
    """TP / WRONG_TYPE / PARTIAL / FN / NOT_IN_TEXT."""
    if not occurrences(text, value):
        return NOT_IN_TEXT
    share, type_ok = match_value(text, value, expected_type, findings)
    if share == 0.0:
        return "FN"
    if share < 1.0:
        return "PARTIAL"
    return "TP" if type_ok else "WRONG_TYPE"


def expected_spans(row: GoldRow) -> list[tuple[int, int]]:
    return [span for _, value in row.expected for span in occurrences(row.text, value)]


def extra_spans(row: GoldRow, findings: list[Finding]) -> list[tuple[str, tuple[int, int]]]:
    """Замаскированные спаны, не пересекающиеся ни с одним ожидаемым значением."""
    wanted = expected_spans(row)
    return [
        (pd_type, (s, e))
        for pd_type, spans in findings
        for s, e in spans
        if not any(s < we and ws < e for ws, we in wanted)
    ]


# --- метрики -------------------------------------------------------------------


def _non_space(text: str, spans: list[tuple[int, int]]) -> set[int]:
    return {i for s, e in spans for i in range(s, e) if not text[i].isspace()}


def _count_chars(m: Metrics, row: GoldRow, findings: list[Finding]) -> None:
    masked = _non_space(row.text, [span for _, spans in findings for span in spans])
    wanted = _non_space(row.text, expected_spans(row))
    m.expected_chars += len(wanted)
    m.expected_masked += len(wanted & masked)
    m.masked_chars += len(masked)
    m.overmask += len(masked - wanted)


def _count_values(m: Metrics, row: GoldRow, findings: list[Finding]) -> None:
    classes = []
    for pd_type, value in row.expected:
        cls = classify_value(row.text, value, pd_type, findings)
        if cls == NOT_IN_TEXT:
            m.not_in_text += 1
            continue
        classes.append(cls)
        m.classes[cls] += 1
        m.by_type.setdefault(pd_type, Counter())[cls] += 1
    if classes and all(c == "FN" for c in classes):
        m.fn_text += 1
    if classes and all(c == "TP" for c in classes):
        m.perfect_text += 1


def _count_row(m: Metrics, row: GoldRow, findings: list[Finding]) -> None:
    m.fp += len(extra_spans(row, findings))
    _count_chars(m, row, findings)
    if row.trap == 1:
        m.traps += 1
        m.trap_fp += 1 if findings else 0
        return
    m.pd_texts += 1
    _count_values(m, row, findings)


def compute_metrics(rows: list[GoldRow], findings_by_id: dict[str, list[Finding]]) -> Metrics:
    """Метрики по размеченным строкам. findings_by_id: id строки → находки."""
    m = Metrics()
    for row in rows:
        if row.trap is None:
            m.skipped += 1
            continue
        m.labeled += 1
        _count_row(m, row, findings_by_id.get(row.id, []))
    return m


# --- список ошибок -------------------------------------------------------------


def _found_text(text: str, value: str, findings: list[Finding]) -> str:
    """Замаскированные фрагменты внутри первого вхождения значения."""
    spans = occurrences(text, value)
    if not spans:
        return ""
    start, end = spans[0]
    parts = [text[max(s, start) : min(e, end)] for _, sp in findings for s, e in sp if s < end and start < e]
    return " | ".join(parts)


def _value_errors(row: GoldRow, findings: list[Finding]) -> list[ErrorRow]:
    errors = []
    for pd_type, value in row.expected:
        cls = classify_value(row.text, value, pd_type, findings)
        if cls == "TP":
            continue
        kind = cls if cls in (NOT_IN_TEXT, "PARTIAL", "WRONG_TYPE") else "FN_VALUE"
        errors.append(ErrorRow(row.id, kind, pd_type, value, _found_text(row.text, value, findings), row.text))
    return errors


def collect_errors(rows: list[GoldRow], findings_by_id: dict[str, list[Finding]]) -> list[ErrorRow]:
    """Ошибки для CSV: FN_VALUE, PARTIAL, WRONG_TYPE, NOT_IN_TEXT, FP_VALUE, TRAP_FP."""
    errors: list[ErrorRow] = []
    for row in rows:
        if row.trap is None:
            continue
        findings = findings_by_id.get(row.id, [])
        kind = TRAP_FP if row.trap == 1 else FP_VALUE
        for pd_type, (s, e) in extra_spans(row, findings):
            errors.append(ErrorRow(row.id, kind, pd_type, "", row.text[s:e], row.text))
        if row.trap == 0:
            errors.extend(_value_errors(row, findings))
    return errors


# --- ввод-вывод ------------------------------------------------------------------


def _texts_path(gold: Path) -> Path:
    return gold.with_name(gold.stem + ".texts.jsonl")


def load_texts(path: Path) -> dict[str, str]:
    texts: dict[str, str] = {}
    if not path.exists():
        return texts
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                item = json.loads(line)
                texts[str(item["id"])] = item["text"]
    return texts


def load_gold(path: Path) -> list[GoldRow]:
    texts = load_texts(_texts_path(path))
    return [parse_gold_row(row, texts) for row in read_csv_rows(path)]


def current_findings(rows: list[GoldRow]) -> dict[str, list[Finding]]:
    policy = load_default_policy()
    return {row.id: find_entities(row.text, policy) for row in rows}


def repo_findings(repo: Path, rows: list[GoldRow]) -> dict[str, list[Finding]]:
    env = {**os.environ, "PYTHONPATH": str(repo)}
    proc = subprocess.run(
        [sys.executable, "-c", _REPO_FINDER],
        cwd=str(repo),
        env=env,
        input=json.dumps([row.text for row in rows]),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    raw = json.loads(proc.stdout)
    return {
        row.id: [(t, [(s, e) for s, e in spans]) for t, spans in items] for row, items in zip(rows, raw, strict=True)
    }


def _summary(m: Metrics) -> list[tuple[str, str]]:
    return [
        ("labeled", str(m.labeled)),
        ("skipped (trap пусто)", str(m.skipped)),
        ("traps", str(m.traps)),
        ("trap_fp (ловушки с находкой)", str(m.trap_fp)),
        ("pd_texts", str(m.pd_texts)),
        ("fn_text (ничего не найдено)", str(m.fn_text)),
        ("perfect_text (всё TP)", str(m.perfect_text)),
        *((f"values {c}", str(m.classes[c])) for c in CLASSES),
        ("not_in_text (ошибки разметки)", str(m.not_in_text)),
        ("fp spans", str(m.fp)),
        ("precision", f"{m.precision:.4f}"),
        ("recall", f"{m.recall:.4f}"),
        ("recall_any_type", f"{m.recall_any_type:.4f}"),
        ("recall_chars", f"{m.recall_chars:.4f}"),
        ("overmask_chars", f"{m.overmask_chars:.4f}"),
    ]


def _type_lines(m: Metrics) -> list[str]:
    lines = ["type;TP;WRONG_TYPE;PARTIAL;FN"]
    for pd_type in sorted(m.by_type):
        counts = m.by_type[pd_type]
        lines.append(";".join([pd_type, *(str(counts[c]) for c in CLASSES)]))
    return lines


def print_report(after: Metrics, before: Metrics | None = None) -> None:
    if before is None:
        print("metric;value")
        for name, value in _summary(after):
            print(f"{name};{value}")
    else:
        print("metric;before;after")
        for (name, old), (_, new) in zip(_summary(before), _summary(after), strict=True):
            print(f"{name};{old};{new}")
        print("--- before ---")
        print("\n".join(_type_lines(before)))
        print("--- after ---")
    print("\n".join(_type_lines(after)))


def write_errors(path: Path, errors: list[ErrorRow]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["id", "kind", "type", "expected", "found", "text"])
        for err in errors:
            writer.writerow([err.id, err.kind, err.pd_type, err.expected, err.found, err.text])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Оценка точности на размеченном наборе")
    parser.add_argument("--gold", required=True, type=Path, help="CSV разметки (вне репозитория)")
    parser.add_argument("--out", required=True, type=Path, help="CSV ошибок (вне репозитория)")
    parser.add_argument("--repo", type=Path, default=None, help="корень другой версии кода (git worktree)")
    args = parser.parse_args(argv)

    assert_outside_repo(args.gold)
    assert_outside_repo(args.out)
    rows = load_gold(args.gold)
    findings = current_findings(rows)
    after = compute_metrics(rows, findings)
    write_errors(args.out, collect_errors(rows, findings))
    before = compute_metrics(rows, repo_findings(args.repo, rows)) if args.repo else None
    print_report(after, before)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
