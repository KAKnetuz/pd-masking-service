"""Черновик ручной разметки из захвата реальных входных текстов.

Вход: --capture КАТАЛОГ (файлы samples-*.jsonl из ветки diag/capture).
Выход: --out ПУТЬ.csv (вне репозитория), формат как в eval_gold:
    id;text;trap;expected

Для каждого уникального текста находки считаются текущим кодом тем же путём, что
POST /process для system_id по умолчанию. Если что-то найдено — trap=0 и expected
из найденного; иначе trap пусто и expected пусто. Сначала тексты без находок.

Запуск:
    python -m scripts.make_gold_template --capture <каталог> --out <файл.csv>
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from scripts._eval_common import assert_outside_repo, find_entities, load_default_policy


def _read_texts(capture_dir: Path) -> list[str]:
    texts: list[str] = []
    for path in sorted(capture_dir.glob("samples-*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    texts.append(json.loads(line)["text"])
                except (json.JSONDecodeError, KeyError):
                    continue
    return texts


def _value_for(text: str, spans: list[tuple[int, int]]) -> str:
    return text[spans[0][0] : spans[-1][1]]


def _build_rows(texts: list[str]) -> list[tuple[str, str, str]]:
    policy = load_default_policy()
    rows: list[tuple[str, str, str]] = []
    for text in texts:
        findings = find_entities(text, policy)
        if findings:
            expected = " || ".join(f"{t}::{_value_for(text, spans)}" for t, spans in findings)
            rows.append((text, "0", expected))
        else:
            rows.append((text, "", ""))
    rows.sort(key=lambda r: (r[1] != "", r[0]))
    return rows


def _write_csv(path: Path, rows: list[tuple[str, str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["id", "text", "trap", "expected"])
        for idx, (text, trap, expected) in enumerate(rows, start=1):
            writer.writerow([idx, text, trap, expected])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Черновик разметки из захвата")
    parser.add_argument("--capture", required=True, type=Path, help="каталог с samples-*.jsonl")
    parser.add_argument("--out", required=True, type=Path, help="CSV разметки (вне репозитория)")
    args = parser.parse_args(argv)

    assert_outside_repo(args.out)
    texts = _read_texts(args.capture)
    unique = list(dict.fromkeys(texts))
    rows = _build_rows(unique)
    _write_csv(args.out, rows)
    without = sum(1 for _, trap, _ in rows if trap == "")
    print(f"total={len(texts)} unique={len(unique)} without_findings={without}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
