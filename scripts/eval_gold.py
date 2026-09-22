"""Оценка точности маскирования на размеченном наборе (gold).

Вход — CSV разметки (utf-8-sig, разделитель ";"):
    id;text;trap;expected
    trap: 1 = ловушка (ПД нет), 0 = есть ПД, пусто = не размечено (пропускается).
    expected: список "тип::значение" через " || ".

Находки получаются тем же путём, что POST /process для system_id по умолчанию
(DetectionEngine().detect с политикой "default"). Сопоставление значений и метрики —
по ПРОМТ 26, часть 2.1.

Запуск:
    python -m scripts.eval_gold --gold <файл.csv> --out <ошибки.csv> [--repo <каталог>]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from scripts._eval_common import (
    assert_outside_repo,
    find_entities,
    load_default_policy,
)

# Подпроцесс для другой версии кода (--repo): находки в JSON через stdout, только спаны и типы.
_REPO_FINDER = r"""
import json, sys
from pathlib import Path
from app.core.engine import DetectionEngine
from app.core.policy import load_policies
repo = Path.cwd()
policy = load_policies(repo / "config" / "systems.yaml").resolve(None)
engine = DetectionEngine()
data = json.load(sys.stdin)
out = {}
for idx, text in enumerate(data["texts"]):
    ents = engine.detect(text, policy.pd_types, policy.combinations)
    out[idx] = [(e.pd_type.value, list(e.parts)) for e in ents]
json.dump(out, sys.stdout, ensure_ascii=False)
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
    tp: int = 0
    partial: int = 0
    fn: int = 0
    wrong_type: int = 0
    fp: int = 0
    precision: float = 0.0
    recall: float = 0.0
    recall_no_type: float = 0.0
    recall_chars: float = 0.0
    overmask_chars: float = 0.0
    type_breakdown: dict[str, tuple[int, int, int]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ErrorRow:
    id: str
    kind: str
    pd_type: str
    expected: str
    found: str
    text: str


Findings = dict[str, list[tuple[str, list[tuple[int, int]]]]]


def parse_gold_row(row: dict[str, str]) -> GoldRow:
    """Разбирает одну строку CSV разметки в GoldRow."""
    trap_raw = str(row.get("trap", "")).strip()
    trap = None if trap_raw == "" else (1 if trap_raw == "1" else 0)
    expected: list[tuple[str, str]] = []
    for item in str(row.get("expected", "")).split("||"):
        item = item.strip()
        if not item:
            continue
        pd_type, _, value = item.partition("::")
        expected.append((pd_type.strip(), value.strip()))
    return GoldRow(
        id=str(row.get("id", "")).strip(),
        text=str(row.get("text", "")),
        trap=trap,
        expected=tuple(expected),
    )


def _non_space_positions(text: str, start: int, end: int) -> list[int]:
    return [i for i in range(start, end) if not text[i].isspace()]


def match_value(
    text: str, value: str, expected_type: str, entities: list[tuple[str, list[tuple[int, int]]]]
) -> tuple[float, bool]:
    """Покрытие значения спанами: (доля не-пробельных символов, совпал ли тип).

    Значение ищется по всем вхождениям в text; берётся лучшее покрытие.
    """
    best_coverage = 0.0
    best_type_ok = False
    start = 0
    while True:
        idx = text.find(value, start)
        if idx == -1:
            break
        occ_end = idx + len(value)
        positions = _non_space_positions(text, idx, occ_end)
        if positions:
            covered = 0
            covering_type: str | None = None
            for pos in positions:
                for etype, spans in entities:
                    if any(s <= pos < e for s, e in spans):
                        covered += 1
                        covering_type = etype
                        break
            coverage = covered / len(positions)
            if coverage > best_coverage:
                best_coverage = coverage
                best_type_ok = coverage == 1.0 and covering_type == expected_type
        start = idx + 1
    return best_coverage, best_type_ok


def classify_value(text: str, value: str, expected_type: str, entities: list[tuple[str, list[tuple[int, int]]]]) -> str:
    """Классификация значения: TP / PARTIAL / FN / WRONG_TYPE."""
    coverage, type_ok = match_value(text, value, expected_type, entities)
    if coverage == 0.0:
        return "FN"
    if coverage < 1.0:
        return "PARTIAL"
    return "TP" if type_ok else "WRONG_TYPE"


def _expected_occurrences(text: str, expected: tuple[tuple[str, str], ...]) -> list[tuple[int, int]]:
    occurrences: list[tuple[int, int]] = []
    for _, value in expected:
        start = 0
        while True:
            idx = text.find(value, start)
            if idx == -1:
                break
            occurrences.append((idx, idx + len(value)))
            start = idx + 1
    return occurrences


def _masked_positions(text: str, entities: list[tuple[str, list[tuple[int, int]]]]) -> set[int]:
    positions: set[int] = set()
    for _, spans in entities:
        for s, e in spans:
            positions.update(i for i in range(s, e) if not text[i].isspace())
    return positions


def _expected_positions(text: str, expected: tuple[tuple[str, str], ...]) -> set[int]:
    positions: set[int] = set()
    for _, value in expected:
        start = 0
        while True:
            idx = text.find(value, start)
            if idx == -1:
                break
            positions.update(i for i in range(idx, idx + len(value)) if not text[i].isspace())
            start = idx + 1
    return positions


def _count_text_metrics(m: Metrics, rows: list[GoldRow], findings: Findings) -> None:
    m.labeled = sum(1 for r in rows if r.trap is not None)
    m.skipped = sum(1 for r in rows if r.trap is None)
    traps = [r for r in rows if r.trap == 1]
    m.traps = len(traps)
    m.pd_texts = sum(1 for r in rows if r.trap == 0)
    m.trap_fp = sum(1 for r in traps if findings.get(r.text))


def _bump_type_breakdown(m: Metrics, etype: str, cls: str) -> None:
    bd = m.type_breakdown.setdefault(etype, [0, 0, 0])
    if cls == "TP":
        bd[0] += 1
    elif cls == "PARTIAL":
        bd[1] += 1
    else:
        bd[2] += 1


def _count_value(
    m: Metrics, text: str, etype: str, value: str, entities: list[tuple[str, list[tuple[int, int]]]]
) -> str:
    cls = classify_value(text, value, etype, entities)
    if cls == "TP":
        m.tp += 1
    elif cls == "PARTIAL":
        m.partial += 1
    elif cls == "WRONG_TYPE":
        m.wrong_type += 1
    else:
        m.fn += 1
    _bump_type_breakdown(m, etype, cls)
    return cls


def _count_value_metrics(m: Metrics, rows: list[GoldRow], findings: Findings) -> None:
    for r in rows:
        if r.trap != 0:
            continue
        entities = findings.get(r.text, [])
        occurrences = _expected_occurrences(r.text, r.expected)
        row_any_found = False
        row_all_tp = True
        for etype, value in r.expected:
            cls = _count_value(m, r.text, etype, value, entities)
            row_any_found = row_any_found or cls != "FN"
            row_all_tp = row_all_tp and cls == "TP"
        if not row_any_found:
            m.fn_text += 1
        if row_all_tp and r.expected:
            m.perfect_text += 1
        for _, spans in entities:
            for s, e in spans:
                if not any(s < oe and os < e for os, oe in occurrences):
                    m.fp += 1


def _count_char_metrics(m: Metrics, rows: list[GoldRow], findings: Findings) -> None:
    expected_chars = 0
    expected_masked = 0
    masked_chars = 0
    overmask = 0
    for r in rows:
        if r.trap != 0:
            continue
        entities = findings.get(r.text, [])
        masked = _masked_positions(r.text, entities)
        expected_pos = _expected_positions(r.text, r.expected)
        expected_chars += len(expected_pos)
        expected_masked += len(expected_pos & masked)
        masked_chars += len(masked)
        overmask += len(masked - expected_pos)
    m.recall_chars = expected_masked / expected_chars if expected_chars else 0.0
    m.overmask_chars = overmask / masked_chars if masked_chars else 0.0


def _finalize_metrics(m: Metrics) -> None:
    denom = m.tp + m.partial + m.fn
    m.precision = m.tp / (m.tp + m.fp) if (m.tp + m.fp) else 0.0
    m.recall = m.tp / denom if denom else 0.0
    tp_no_type = m.tp + m.wrong_type
    m.recall_no_type = tp_no_type / (tp_no_type + m.partial + m.fn) if (tp_no_type + m.partial + m.fn) else 0.0


def compute_metrics(rows: list[GoldRow], findings_by_text: Findings) -> Metrics:
    """Считает метрики по размеченным строкам и находкам."""
    m = Metrics()
    _count_text_metrics(m, rows, findings_by_text)
    _count_value_metrics(m, rows, findings_by_text)
    _count_char_metrics(m, rows, findings_by_text)
    _finalize_metrics(m)
    return m


def _trap_errors(r: GoldRow, entities: list[tuple[str, list[tuple[int, int]]]]) -> list[ErrorRow]:
    errors: list[ErrorRow] = []
    for etype, spans in entities:
        for s, e in spans:
            errors.append(ErrorRow(r.id, "TRAP_FP", etype, "", r.text[s:e], r.text))
    return errors


def _value_errors(r: GoldRow, entities: list[tuple[str, list[tuple[int, int]]]]) -> list[ErrorRow]:
    errors: list[ErrorRow] = []
    for etype, value in r.expected:
        cls = classify_value(r.text, value, etype, entities)
        if cls == "FN":
            errors.append(ErrorRow(r.id, "FN_VALUE", etype, value, "", r.text))
        elif cls == "PARTIAL":
            errors.append(ErrorRow(r.id, "PARTIAL", etype, value, "", r.text))
        elif cls == "WRONG_TYPE":
            errors.append(ErrorRow(r.id, "WRONG_TYPE", etype, value, _span_text(r.text, entities, value), r.text))
    return errors


def _fp_errors(
    r: GoldRow, entities: list[tuple[str, list[tuple[int, int]]]], occurrences: list[tuple[int, int]]
) -> list[ErrorRow]:
    errors: list[ErrorRow] = []
    for etype, spans in entities:
        for s, e in spans:
            if not any(s < oe and os < e for os, oe in occurrences):
                errors.append(ErrorRow(r.id, "FP_VALUE", etype, "", r.text[s:e], r.text))
    return errors


def collect_errors(rows: list[GoldRow], findings_by_text: Findings) -> list[ErrorRow]:
    """Список ошибок для CSV: FN_VALUE, PARTIAL, FP_VALUE, TRAP_FP, WRONG_TYPE."""
    errors: list[ErrorRow] = []
    for r in rows:
        entities = findings_by_text.get(r.text, [])
        if r.trap == 1:
            errors.extend(_trap_errors(r, entities))
            continue
        if r.trap is None:
            continue
        errors.extend(_value_errors(r, entities))
        errors.extend(_fp_errors(r, entities, _expected_occurrences(r.text, r.expected)))
    return errors


def _span_text(text: str, entities: list[tuple[str, list[tuple[int, int]]]], value: str) -> str:
    """Текст спана, покрывающего значение (для WRONG_TYPE)."""
    idx = text.find(value)
    if idx == -1:
        return ""
    for _, spans in entities:
        for s, e in spans:
            if s <= idx < e:
                return text[s:e]
    return ""


def _load_gold(path: Path) -> list[GoldRow]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        return [parse_gold_row(row) for row in reader]


def _current_findings(texts: list[str]) -> dict[str, list[tuple[str, list[tuple[int, int]]]]]:
    policy = load_default_policy()
    return {text: find_entities(text, policy) for text in texts}


def _repo_findings(repo: Path, texts: list[str]) -> dict[str, list[tuple[str, list[tuple[int, int]]]]]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo)
    proc = subprocess.run(
        [sys.executable, "-c", _REPO_FINDER],
        cwd=str(repo),
        env=env,
        input=json.dumps({"texts": texts}),
        capture_output=True,
        text=True,
        check=True,
    )
    raw = json.loads(proc.stdout)
    return {texts[int(idx)]: [(t, [tuple(sp) for sp in spans]) for t, spans in items] for idx, items in raw.items()}


def _print_metrics(m: Metrics) -> None:
    print("labeled;skipped")
    print(f"{m.labeled};{m.skipped}")
    print("traps;trap_fp")
    print(f"{m.traps};{m.trap_fp}")
    print("pd_texts;fn_text;perfect_text")
    print(f"{m.pd_texts};{m.fn_text};{m.perfect_text}")
    print("tp;partial;fn;wrong_type;fp")
    print(f"{m.tp};{m.partial};{m.fn};{m.wrong_type};{m.fp}")
    print("precision;recall;recall_no_type")
    print(f"{m.precision:.4f};{m.recall:.4f};{m.recall_no_type:.4f}")
    print("recall_chars;overmask_chars")
    print(f"{m.recall_chars:.4f};{m.overmask_chars:.4f}")
    print("type;tp;partial;fn")
    for pd_type in sorted(m.type_breakdown):
        tp, partial, fn = m.type_breakdown[pd_type]
        print(f"{pd_type};{tp};{partial};{fn}")


def _write_errors(path: Path, errors: list[ErrorRow]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["id", "kind", "type", "expected", "found", "text"])
        for err in errors:
            writer.writerow([err.id, err.kind, err.pd_type, err.expected, err.found, err.text])


def _print_side_by_side(before: Metrics, after: Metrics) -> None:
    print("metric;before;after")
    for name in ("labeled", "skipped", "traps", "trap_fp", "pd_texts", "fn_text", "perfect_text",
                 "tp", "partial", "fn", "wrong_type", "fp"):
        print(f"{name};{getattr(before, name)};{getattr(after, name)}")
    for name in ("precision", "recall", "recall_no_type", "recall_chars", "overmask_chars"):
        print(f"{name};{getattr(before, name):.4f};{getattr(after, name):.4f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Оценка точности на размеченном наборе")
    parser.add_argument("--gold", required=True, type=Path, help="CSV разметки (вне репозитория)")
    parser.add_argument("--out", required=True, type=Path, help="CSV ошибок (вне репозитория)")
    parser.add_argument("--repo", type=Path, default=None, help="корень другой версии кода (git worktree)")
    args = parser.parse_args(argv)

    assert_outside_repo(args.out)
    assert_outside_repo(args.gold)
    rows = _load_gold(args.gold)
    texts = [r.text for r in rows]

    after = compute_metrics(rows, _current_findings(texts))
    errors = collect_errors(rows, _current_findings(texts))
    _write_errors(args.out, errors)

    if args.repo is not None:
        before = compute_metrics(rows, _repo_findings(args.repo, texts))
        _print_side_by_side(before, after)
    else:
        _print_metrics(after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
