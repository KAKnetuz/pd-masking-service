"""Демо-прокси /chat: маскирование → LLM → демаскирование.

Цепочка «система-потребитель → маскирование → LLM → демаскирование → потребитель».
Соответствие «метка → оригинал» живёт только в памяти на время запроса и не
сохраняется в хранилище.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field

from app.core.engine import DetectionEngine
from app.core.masking import Masker, unmask_fragments
from app.core.policy import SystemPolicy

_SYSTEM_PROMPT = (
    "Ты ассистент банка. Персональные данные в тексте заменены метками вида "
    "[ТИП_xxxxxx]. Сохраняй метки в ответе без изменений и не пытайся их расшифровать."
)


class LeakBlockedError(Exception):
    """Маскирование не гарантировало отсутствие ПД — запрос в LLM не отправляется."""


@dataclass(frozen=True, slots=True)
class ChatResult:
    sent_to_llm: str
    llm_answer: str
    answer: str
    pd_types: dict[str, int] = field(default_factory=dict)
    llm_ms: float = 0.0


class ChatProxy:
    def __init__(self, engine: DetectionEngine, masker: Masker, llm_client) -> None:
        self._engine = engine
        self._masker = masker
        self._llm = llm_client

    async def handle(self, message: str, policy: SystemPolicy) -> ChatResult:
        # a) найти сущности ПД в исходном сообщении по политике.
        entities = self._engine.detect(message, policy.pd_types, policy.combinations)

        # b) замаскировать, сохранить фрагменты «метка → оригинал».
        masked = self._masker.mask(message, entities, policy.rules)

        # c) защита от утечки: повторный детект на замаскированном тексте.
        leaked = self._engine.detect(masked.text, policy.pd_types, policy.combinations)
        if leaked:
            raise LeakBlockedError

        # d) отправить в LLM.
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": masked.text},
        ]
        started = time.perf_counter()
        llm_answer = await self._llm.complete(messages)
        llm_ms = (time.perf_counter() - started) * 1000

        # e) демаскировать ответ модели по фрагментам.
        answer, _ = unmask_fragments(llm_answer, masked.fragments)

        # f) результат.
        counts = Counter(e.pd_type.value for e in entities)
        return ChatResult(
            sent_to_llm=masked.text,
            llm_answer=llm_answer,
            answer=answer,
            pd_types=dict(counts),
            llm_ms=llm_ms,
        )
