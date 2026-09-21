"""Стратегии маскирования.

Вид маски задаётся в ``config/systems.yaml`` для каждого типа ПД и каждой системы,
поэтому формат можно подстроить под эталон без изменения кода.

* ``initials``  — «Иванов Иван Иванович» → «И. И. И.»
* ``partial``   — «4509 123456» → «45** ****56» (оставить keep_start/keep_end символов)
* ``full``      — все буквы и цифры → «*», разделители сохраняются
* ``email``     — «ivanov@mail.ru» → «i*****@mail.ru»
* ``token``     — «[FIO_3f2a1c]»: стабильный токен (HMAC), удобен для LLM
* ``redact``    — «[ПАСПОРТ]»: метка типа
* ``synthetic`` — правдоподобная замена того же формата (бонус ТЗ)
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.core.entities import Entity, PDType

_LETTERS_RE = re.compile(r"[A-Za-zА-ЯЁа-яё]+")

STRATEGIES = frozenset({"initials", "partial", "full", "email", "token", "redact", "synthetic"})

_LABELS: dict[PDType, str] = {
    PDType.FIO: "ФИО",
    PDType.BIRTH_DATE: "ДАТА_РОЖДЕНИЯ",
    PDType.BIRTH_PLACE: "МЕСТО_РОЖДЕНИЯ",
    PDType.PASSPORT: "ПАСПОРТ",
    PDType.CITIZENSHIP: "ГРАЖДАНСТВО",
    PDType.PASSPORT_ISSUER: "ОРГАН_ВЫДАЧИ",
    PDType.DEPARTMENT_CODE: "КОД_ПОДРАЗДЕЛЕНИЯ",
    PDType.PASSPORT_ISSUE_DATE: "ДАТА_ВЫДАЧИ",
    PDType.DRIVER_LICENSE: "ВУ",
    PDType.ADDRESS: "АДРЕС",
    PDType.EMAIL: "EMAIL",
    PDType.PHONE: "ТЕЛЕФОН",
    PDType.INN: "ИНН",
    PDType.CARD_NUMBER: "НОМЕР_КАРТЫ",
    PDType.CARD_CVV: "CVV",
    PDType.CARD_PIN: "PIN",
    PDType.CARD_HOLDER: "ДЕРЖАТЕЛЬ_КАРТЫ",
    PDType.CARD_EXPIRY: "СРОК_КАРТЫ",
    PDType.DATE: "ДАТА",
    PDType.SNILS: "СНИЛС",
    PDType.FOREIGN_PASSPORT: "ЗАГРАНПАСПОРТ",
    PDType.MILITARY_ID: "ВОЕННЫЙ_БИЛЕТ",
    PDType.BIRTH_CERTIFICATE: "СВИДЕТЕЛЬСТВО_О_РОЖДЕНИИ",
}

_FAKE_SURNAMES = ("Смирнов", "Кузнецов", "Попов", "Соколов", "Лебедев", "Новиков", "Морозов", "Волков")
_FAKE_NAMES = ("Алексей", "Дмитрий", "Сергей", "Андрей", "Михаил", "Николай", "Олег", "Павел")
_FAKE_PATRONYMICS = ("Петрович", "Сергеевич", "Андреевич", "Олегович", "Павлович", "Игоревич")


@dataclass(frozen=True, slots=True)
class MaskRule:
    strategy: str = "full"
    keep_start: int = 0
    keep_end: int = 0
    char: str = "*"

    def __post_init__(self) -> None:
        if self.strategy not in STRATEGIES:
            raise ValueError(f"Неизвестная стратегия маскирования: {self.strategy}")
        if len(self.char) != 1:
            raise ValueError("Символ маски должен быть одним символом")
        if self.keep_start < 0 or self.keep_end < 0:
            raise ValueError("keep_start/keep_end не могут быть отрицательными")


DEFAULT_RULE = MaskRule()


@dataclass(frozen=True, slots=True)
class MaskResult:
    text: str
    #: Пары (маска фрагмента, исходный фрагмент) — для демаскирования изменённого текста.
    fragments: tuple[tuple[str, str], ...]


class Masker:
    def __init__(self, secret: bytes) -> None:
        self._secret = secret

    def mask(self, text: str, entities: Sequence[Entity], rules: Mapping[PDType, MaskRule]) -> MaskResult:
        chunks: list[str] = []
        fragments: list[tuple[str, str]] = []
        pos = 0
        for entity in entities:
            rule = rules.get(entity.pd_type, DEFAULT_RULE)
            replacement = self._apply(text, entity, rule)
            chunks.append(text[pos : entity.start])
            chunks.append(replacement)
            fragments.append((replacement, text[entity.start : entity.end]))
            pos = entity.end
        chunks.append(text[pos:])
        return MaskResult(text="".join(chunks), fragments=tuple(fragments))

    # --- стратегии ------------------------------------------------------
    def _apply(self, text: str, entity: Entity, rule: MaskRule) -> str:
        span = text[entity.start : entity.end]
        strategy = rule.strategy
        if strategy == "initials":
            words = _LETTERS_RE.findall(span)
            return " ".join(f"{w[0]}." for w in words) if words else self._chars(text, entity, rule)
        if strategy == "email" and "@" in span:
            local, _, domain = span.partition("@")
            return local[:1] + rule.char * (len(local) - 1) + "@" + domain
        if strategy == "token":
            return f"[{entity.pd_type.value.upper()}_{self._digest(entity.pd_type, span)[:6]}]"
        if strategy == "redact":
            return f"[{_LABELS.get(entity.pd_type, entity.pd_type.value.upper())}]"
        if strategy == "synthetic":
            return self._synthetic(entity, span)
        return self._chars(text, entity, rule)

    @staticmethod
    def _chars(text: str, entity: Entity, rule: MaskRule) -> str:
        """Посимвольная маска внутри ``parts``; разделители и служебные слова между частями сохраняются."""
        base = entity.start
        chars = list(text[entity.start : entity.end])
        positions = [
            i - base for start, end in entity.parts for i in range(start, end) if text[i].isalnum()
        ]
        keep_start, keep_end = (rule.keep_start, rule.keep_end) if rule.strategy == "partial" else (0, 0)
        if len(positions) <= keep_start + keep_end:
            keep_start = keep_end = 0
        for idx, pos in enumerate(positions):
            if idx < keep_start or idx >= len(positions) - keep_end:
                continue
            chars[pos] = rule.char
        return "".join(chars)

    def _synthetic(self, entity: Entity, span: str) -> str:
        digest = self._digest(entity.pd_type, span)
        seed = int(digest, 16)
        if entity.pd_type in (PDType.FIO, PDType.CARD_HOLDER):
            words = len(_LETTERS_RE.findall(span)) or 1
            pool = (
                _FAKE_SURNAMES[seed % len(_FAKE_SURNAMES)],
                _FAKE_NAMES[(seed >> 8) % len(_FAKE_NAMES)],
                _FAKE_PATRONYMICS[(seed >> 16) % len(_FAKE_PATRONYMICS)],
            )
            return " ".join(pool[: min(words, 3)])
        if entity.pd_type is PDType.EMAIL:
            return f"user{digest[:6]}@example.com"
        out = []
        for idx, ch in enumerate(span):
            if ch.isdigit():
                out.append(str(int(digest[idx % len(digest)], 16) % 10))
            elif ch.isalpha():
                out.append("X" if ch.isupper() else "x")
            else:
                out.append(ch)
        return "".join(out)

    def _digest(self, pd_type: PDType, value: str) -> str:
        return hmac.new(self._secret, f"{pd_type.value}:{value}".encode(), hashlib.sha256).hexdigest()


def unmask_fragments(text: str, fragments: Sequence[tuple[str, str]]) -> tuple[str, int]:
    """Восстанавливает исходные значения в произвольном тексте (например, в ответе LLM).

    Длинные маски заменяются первыми, чтобы короткая маска не «съела» часть длинной.
    Возвращает текст и количество выполненных замен.
    """
    replaced = 0
    for masked, original in sorted(set(fragments), key=lambda f: -len(f[0])):
        if masked == original or masked not in text:
            continue
        count = text.count(masked)
        text = text.replace(masked, original)
        replaced += count
    return text, replaced
