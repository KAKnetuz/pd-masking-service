"""Движок распознавания: запуск детекторов, разрешение пересечений, правила комбинаций."""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Mapping, Sequence

from app.core.detectors.base import Detector, text_has_digits
from app.core.detectors.registry import default_detectors
from app.core.entities import ALL_PD_TYPES, Entity, PDType

Combinations = Mapping[PDType, frozenset[PDType]]


class DetectionEngine:
    """Находит ПД в тексте. Не хранит состояние — безопасен для конкурентного вызова."""

    def __init__(self, detectors: Sequence[Detector] | None = None) -> None:
        self._detectors = tuple(detectors) if detectors is not None else default_detectors()

    def detect(
        self,
        text: str,
        enabled: frozenset[PDType] = ALL_PD_TYPES,
        combinations: Combinations | None = None,
    ) -> list[Entity]:
        if not text or not enabled:
            return []
        has_digits = text_has_digits(text)
        candidates = [
            entity
            for detector in self._detectors
            if detector.applicable(has_digits, enabled)
            for entity in detector.detect(text)
            if entity is not None and entity.pd_type in enabled
        ]
        accepted = self._resolve_overlaps(candidates)
        accepted = self._apply_requirements(accepted, combinations or {})
        return sorted(accepted, key=lambda e: e.start)

    @staticmethod
    def _resolve_overlaps(candidates: Iterable[Entity]) -> list[Entity]:
        """Жадный выбор: выше приоритет, затем длиннее. Пересекающиеся кандидаты отбрасываются."""
        ordered = sorted(candidates, key=lambda e: (-e.priority, -e.length, e.start))
        starts: list[int] = []
        chosen: list[Entity] = []
        for entity in ordered:
            idx = bisect.bisect_left(starts, entity.start)
            if idx > 0 and chosen[idx - 1].end > entity.start:
                continue
            if idx < len(chosen) and chosen[idx].start < entity.end:
                continue
            starts.insert(idx, entity.start)
            chosen.insert(idx, entity)
        return chosen

    @staticmethod
    def _apply_requirements(entities: list[Entity], combinations: Combinations) -> list[Entity]:
        """Слабые сущности и правила «маскировать только вместе с ...» (бонус ТЗ)."""

        def satisfied(entity: Entity, present: set[PDType]) -> bool:
            if entity.requires_any and not entity.requires_any & present:
                return False
            required = combinations.get(entity.pd_type)
            return not required or bool(required & present)

        kept = entities
        while True:
            present = {e.pd_type for e in kept}
            filtered = [e for e in kept if satisfied(e, present)]
            if len(filtered) == len(kept):
                return filtered
            kept = filtered
