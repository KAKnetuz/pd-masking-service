"""Черновик ручной разметки из захвата реальных входных текстов (ветка diag/capture).

Вход: --capture КАТАЛОГ с файлами samples-*.jsonl.
Выход: --out ПУТЬ.csv вне репозитория и рядом ПУТЬ.texts.jsonl (исходные тексты по id).

CSV (разделитель ";", UTF-8 с BOM): id;text;mask;trap;expected
    mask     — маска, которую вернул сервис (справочно);
    trap     — пусто, если сейчас ничего не найдено (разметить вручную: 1 или 0), иначе 0;
    expected — найденное сейчас, по одному значению на каждую часть сущности:
               "passport::4509 || passport::123456". Исправить вручную там, где неверно.
Сначала идут тексты без находок. Строки со словом DIAG-SMOKE (проверка захвата) пропускаются.

Запуск:
    python -m scripts.make_gold_template --capture <каталог> --out <gold.csv>
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from scripts._eval_common import Finding, assert_outside_repo, find_entities, load_default_policy

SMOKE_MARKER = "DIAG-SMOKE"


def read_samples(capture_dir: Path) -> dict[str, str]:
    """Уникальные тексты захвата → маска (первая встреченная). Битые строки пропускаются."""
    samples: dict[str, str] = {}
    for path in sorted(capture_dir.glob("samples-*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                text = item.get("text") if isinstance(item, dict) else None
                if isinstance(text, str) and SMOKE_MARKER not in text:
                    samples.setdefault(text, str(item.get("mask", "")))
    return samples


def expected_from_findings(text: str, findings: list[Finding]) -> str:
    """Каждая часть сущности — отдельное значение: служебные слова между частями не входят."""
    return " || ".join(f"{pd_type}::{text[s:e]}" for pd_type, spans in findings for s, e in spans)


def build_rows(samples: dict[str, str]) -> list[tuple[str, str, str, str]]:
    """(text, mask, trap, expected); сначала тексты без находок, внутри — по алфавиту."""
    policy = load_default_policy()
    rows = []
    for text, mask in samples.items():
        findings = find_entities(text, policy)
        trap = "0" if findings else ""
        rows.append((text, mask, trap, expected_from_findings(text, findings)))
    rows.sort(key=lambda r: (r[2] != "", r[0]))
    return rows


def write_outputs(out: Path, rows: list[tuple[str, str, str, str]]) -> None:
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["id", "text", "mask", "trap", "expected"])
        for idx, (text, mask, trap, expected) in enumerate(rows, start=1):
            writer.writerow([idx, text, mask, trap, expected])
    texts_path = out.with_name(out.stem + ".texts.jsonl")
    with texts_path.open("w", encoding="utf-8") as fh:
        for idx, (text, *_rest) in enumerate(rows, start=1):
            fh.write(json.dumps({"id": str(idx), "text": text}, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Черновик разметки из захвата")
    parser.add_argument("--capture", required=True, type=Path, help="каталог с samples-*.jsonl (вне репозитория)")
    parser.add_argument("--out", required=True, type=Path, help="CSV разметки (вне репозитория)")
    args = parser.parse_args(argv)

    assert_outside_repo(args.capture)
    assert_outside_repo(args.out)
    rows = build_rows(read_samples(args.capture))
    write_outputs(args.out, rows)
    without = sum(1 for row in rows if row[2] == "")
    print(f"unique={len(rows)} without_findings={without}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
