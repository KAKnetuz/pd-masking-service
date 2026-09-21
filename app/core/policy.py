"""Настройки систем-потребителей (config/systems.yaml).

Для каждой системы задаются: доступ (enabled), перечень типов ПД, разрешено ли
демаскирование, вид маски по типам и правила комбинаций. Конфиг проверяется при
старте: ошибка в имени типа или стратегии не даст сервису запуститься с неверными правилами.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.core.entities import ALL_PD_TYPES, PDType
from app.core.masking import MaskRule


class SystemNotAllowedError(Exception):
    """Система неизвестна или отключена."""


@dataclass(frozen=True, slots=True)
class SystemPolicy:
    system_id: str
    enabled: bool
    pd_types: frozenset[PDType]
    unmask_allowed: bool
    rules: Mapping[PDType, MaskRule]
    combinations: Mapping[PDType, frozenset[PDType]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PolicyRegistry:
    default_system: str
    systems: Mapping[str, SystemPolicy]

    def resolve(self, system_id: str | None) -> SystemPolicy:
        key = system_id or self.default_system
        policy = self.systems.get(key)
        if policy is None or not policy.enabled:
            raise SystemNotAllowedError(key)
        return policy


def _pd_type(name: str) -> PDType:
    try:
        return PDType(name)
    except ValueError as exc:
        raise ValueError(f"Неизвестный тип ПД в конфиге: {name!r}") from exc


def _pd_types(raw: Any) -> frozenset[PDType]:
    if raw in (None, "all"):
        return ALL_PD_TYPES
    return frozenset(_pd_type(name) for name in raw)


def _rules(raw: Mapping[str, Any] | None) -> dict[PDType, MaskRule]:
    return {_pd_type(name): MaskRule(**(spec or {})) for name, spec in (raw or {}).items()}


def _combinations(raw: Mapping[str, Any] | None) -> dict[PDType, frozenset[PDType]]:
    return {_pd_type(name): frozenset(_pd_type(t) for t in req) for name, req in (raw or {}).items()}


def parse_policies(data: Mapping[str, Any]) -> PolicyRegistry:
    base_rules = _rules(data.get("masking"))
    systems: dict[str, SystemPolicy] = {}
    for system_id, spec in (data.get("systems") or {}).items():
        spec = spec or {}
        systems[system_id] = SystemPolicy(
            system_id=system_id,
            enabled=bool(spec.get("enabled", True)),
            pd_types=_pd_types(spec.get("pd_types", "all")),
            unmask_allowed=bool(spec.get("unmask", True)),
            rules={**base_rules, **_rules(spec.get("masking"))},
            combinations=_combinations(spec.get("require_combination")),
        )
    default_system = str(data.get("default_system", "default"))
    if default_system not in systems:
        raise ValueError(f"default_system {default_system!r} не описана в systems")
    return PolicyRegistry(default_system=default_system, systems=systems)


def load_policies(path: str | Path) -> PolicyRegistry:
    with Path(path).open(encoding="utf-8") as fh:
        return parse_policies(yaml.safe_load(fh) or {})
