"""Проверка утечки выборки в код: встречаются ли тексты размеченной выборки в файлах репозитория.

Для каждого текста выборки длиной от --min-chars символов ищется в каждом файле из `git ls-files`:
    * весь текст целиком (full);
    * любой фрагмент из WINDOW символов подряд (partial) — ловит частичное копирование.
Сравнение без учёта регистра, пробелы схлопываются. Короткие тексты («Иванов», «4509 123456») не
проверяются: это стандартные тестовые значения, они есть в проекте и без выборки.
Печатаются только числа, id текстов и пути к файлам; сами тексты выборки не выводятся.

Запуск:
    python -m scripts.check_leakage --gold <разметка.csv> [--min-chars 20]
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections import Counter
from pathlib import Path

from scripts._eval_common import REPO_ROOT, assert_outside_repo
from scripts.eval_gold import load_gold

WINDOW = 40
_SPACES_RE = re.compile(r"\s+")

Match = tuple[str, str, str]  # (вид совпадения, id текста, файл)


def normalize(text: str) -> str:
    return _SPACES_RE.sub(" ", text).strip().casefold()


def windows(text: str, size: int = WINDOW) -> set[str]:
    """Все фрагменты длины size (для текстов не длиннее size — сам текст)."""
    if len(text) <= size:
        return {text}
    return {text[i : i + size] for i in range(len(text) - size + 1)}


def tracked_files(repo: Path) -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True, text=True, check=True).stdout
    return [repo / line for line in out.splitlines() if line]


def read_normalized(path: Path) -> str | None:
    try:
        return normalize(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, OSError):
        return None


def find_leaks(texts: dict[str, str], files: dict[str, str], min_chars: int) -> list[Match]:
    """Совпадения текстов выборки (не короче min_chars) с содержимым файлов."""
    matches: list[Match] = []
    for text_id, raw in texts.items():
        text = normalize(raw)
        if len(text) < min_chars:
            continue
        for name, content in files.items():
            if text in content:
                matches.append(("full", text_id, name))
            elif len(text) > WINDOW and any(w in content for w in windows(text)):
                matches.append(("partial", text_id, name))
    return matches


def area(name: str) -> str:
    """Область файла: код распознавания, тесты, скрипты или прочее."""
    top = name.replace("\\", "/").split("/", 1)[0]
    return top if top in ("app", "tests", "scripts") else "other"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Нет ли текстов выборки в файлах репозитория")
    parser.add_argument("--gold", required=True, type=Path, help="CSV разметки (вне репозитория)")
    parser.add_argument("--min-chars", type=int, default=20, help="минимальная длина проверяемого текста")
    args = parser.parse_args(argv)

    assert_outside_repo(args.gold)
    texts = {row.id: row.text for row in load_gold(args.gold)}
    files: dict[str, str] = {}
    for path in tracked_files(REPO_ROOT):
        content = read_normalized(path)
        if content is not None:
            files[path.relative_to(REPO_ROOT).as_posix()] = content
    checked = sum(1 for t in texts.values() if len(normalize(t)) >= args.min_chars)
    matches = find_leaks(texts, files, args.min_chars)
    print(f"texts={len(texts)} checked={checked} min_chars={args.min_chars} files={len(files)} window={WINDOW}")
    by_area = Counter((area(name), kind) for kind, _, name in matches)
    for zone in ("app", "tests", "scripts", "other"):
        print(f"{zone}: full={by_area[(zone, 'full')]} partial={by_area[(zone, 'partial')]}")
    for kind, text_id, name in matches:
        print(f"{kind};text_id={text_id};file={name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
