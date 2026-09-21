"""Модель найденной сущности ПД и реестр типов ПД."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PDType(str, Enum):
    """Типы персональных данных. Новый тип = новый элемент enum + детектор."""

    FIO = "fio"
    BIRTH_DATE = "birth_date"
    BIRTH_PLACE = "birth_place"
    PASSPORT = "passport"
    CITIZENSHIP = "citizenship"
    PASSPORT_ISSUER = "passport_issuer"
    DEPARTMENT_CODE = "department_code"
    PASSPORT_ISSUE_DATE = "passport_issue_date"
    DRIVER_LICENSE = "driver_license"
    ADDRESS = "address"
    EMAIL = "email"
    PHONE = "phone"
    INN = "inn"
    CARD_NUMBER = "card_number"
    CARD_CVV = "cvv"
    CARD_PIN = "pin"
    CARD_HOLDER = "card_holder"
    CARD_EXPIRY = "card_expiry"
    DATE = "date"
    # Дополнительные документы (бонус ТЗ)
    SNILS = "snils"
    FOREIGN_PASSPORT = "foreign_passport"
    MILITARY_ID = "military_id"
    BIRTH_CERTIFICATE = "birth_certificate"


ALL_PD_TYPES: frozenset[PDType] = frozenset(PDType)


@dataclass(frozen=True, slots=True)
class Entity:
    """Найденный фрагмент ПД.

    ``parts`` — интервалы, которые реально маскируются. Для «серия 4509 номер 123456»
    это два интервала с цифрами, служебные слова между ними не трогаются.
    ``requires_any`` — «слабая» сущность: сохраняется, только если в тексте найден
    хотя бы один из перечисленных типов (например, срок действия без номера карты).
    """

    pd_type: PDType
    parts: tuple[tuple[int, int], ...]
    priority: int = 50
    subtype: str = ""
    requires_any: frozenset[PDType] = field(default_factory=frozenset)

    @property
    def start(self) -> int:
        return self.parts[0][0]

    @property
    def end(self) -> int:
        return self.parts[-1][1]

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: Entity) -> bool:
        return self.start < other.end and other.start < self.end


def make_entity(
    pd_type: PDType,
    parts: list[tuple[int, int]] | tuple[tuple[int, int], ...],
    *,
    priority: int = 50,
    subtype: str = "",
    requires_any: frozenset[PDType] | None = None,
) -> Entity | None:
    """Создаёт сущность, отбрасывая пустые интервалы. None — если маскировать нечего."""
    clean = tuple(sorted((s, e) for s, e in parts if e > s))
    if not clean:
        return None
    return Entity(
        pd_type=pd_type,
        parts=clean,
        priority=priority,
        subtype=subtype,
        requires_any=requires_any or frozenset(),
    )
