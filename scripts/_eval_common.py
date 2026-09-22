"""Общие утилиты скриптов оценки точности (eval_gold, make_gold_template, format_matrix).

Находки получаются ровно тем же путём, что и POST /process для запроса без system_id
(app/core/processor.py, Processor._mask): DetectionEngine().detect(text, policy.pd_types,
policy.combinations) с политикой по умолчанию из config/systems.yaml. Это те же спаны,
которые идут в маску.
"""

from __future__ import annotations

import csv
from pathlib import Path

from app.core.engine import DetectionEngine
from app.core.policy import SystemPolicy, load_policies

REPO_ROOT = Path(__file__).resolve().parents[1]

# (тип ПД, [(start, end), ...]) — одна найденная сущность.
Finding = tuple[str, list[tuple[int, int]]]

_ENGINE = DetectionEngine()


def load_default_policy(repo_root: Path = REPO_ROOT) -> SystemPolicy:
    """Политика по умолчанию (system_id не передан) из config/systems.yaml."""
    return load_policies(repo_root / "config" / "systems.yaml").resolve(None)


def find_entities(text: str, policy: SystemPolicy) -> list[Finding]:
    """Находки как (тип, [спаны]) — те же спаны, что маскируются."""
    entities = _ENGINE.detect(text, policy.pd_types, policy.combinations)
    return [(e.pd_type.value, list(e.parts)) for e in entities]


def assert_outside_repo(path: Path) -> None:
    """Запрещает запись и чтение данных внутри репозитория: тексты не должны попасть в git."""
    resolved = path.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise SystemExit(f"путь внутри репозитория запрещён: {resolved}")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    """CSV с разделителем ";": UTF-8 (с BOM или без), при ошибке — cp1251 (сохранение из Excel)."""
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            with path.open(encoding=encoding, newline="") as fh:
                return list(csv.DictReader(fh, delimiter=";"))
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"не удалось прочитать CSV (ожидается UTF-8 или cp1251): {path}")
