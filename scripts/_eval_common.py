"""Общие утилиты для скриптов оценки точности (eval_gold, make_gold_template, format_matrix).

Находки получаются ровно тем же путём, что и POST /process для system_id по умолчанию:
DetectionEngine().detect(text, policy.pd_types, policy.combinations), где policy —
политика "default" из config/systems.yaml. Это те же спаны, которые идут в маску.
"""

from __future__ import annotations

from pathlib import Path

from app.core.engine import DetectionEngine
from app.core.policy import SystemPolicy, load_policies

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_default_policy(repo_root: Path = REPO_ROOT) -> SystemPolicy:
    """Политика "default" из config/systems.yaml указанного репозитория."""
    return load_policies(repo_root / "config" / "systems.yaml").resolve(None)


def find_entities(text: str, policy: SystemPolicy) -> list[tuple[str, list[tuple[int, int]]]]:
    """Находки как (тип, [спаны]) — те же спаны, что маскируются."""
    engine = DetectionEngine()
    entities = engine.detect(text, policy.pd_types, policy.combinations)
    return [(e.pd_type.value, list(e.parts)) for e in entities]


def assert_outside_repo(path: Path) -> None:
    """Запрещает запись внутрь репозитория: данные клиента не должны попадать в git."""
    resolved = path.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise SystemExit(f"путь вывода внутри репозитория запрещён: {resolved}")
