"""Тесты демо-прокси /chat без реальной сети (поддельная LLM)."""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("STORAGE_BACKEND", "memory")

import yaml
from fastapi.testclient import TestClient

from app.core.chat_proxy import ChatProxy
from app.core.engine import DetectionEngine
from app.core.masking import Masker, MaskResult
from app.llm.client import LLMUnavailableError
from app.main import create_app
from app.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((REPO_ROOT / "tests" / "fixtures" / "span_reference.yaml").read_text(encoding="utf-8"))
CASE30 = next(c for c in CASES if c["id"] == 30)


class FakeLLM:
    """Поддельная LLM: запоминает messages, возвращает содержимое user-сообщения."""

    def __init__(self, response: str | None = None, error: Exception | None = None) -> None:
        self.messages: list[dict[str, str]] = []
        self.calls = 0
        self._response = response
        self._error = error

    async def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        self.messages.extend(messages)
        if self._error is not None:
            raise self._error
        if self._response is not None:
            return self._response
        return messages[-1]["content"]


class NoopMasker:
    """Маскер, возвращающий текст без изменений (для проверки защиты от утечки)."""

    def mask(self, text: str, entities, rules) -> MaskResult:
        return MaskResult(text=text, fragments=())


def _client(fake_llm: FakeLLM, masker: Masker | NoopMasker | None = None) -> tuple[TestClient, object]:
    app = create_app(Settings.from_env())
    client = TestClient(app)
    client.__enter__()
    app.state.chat_proxy = ChatProxy(
        DetectionEngine(), masker or Masker(os.urandom(32)), fake_llm
    )
    return client, app


def _close(client: TestClient) -> None:
    client.__exit__(None, None, None)


def test_no_pd_leaks_to_llm_for_case30() -> None:
    fake = FakeLLM()
    client, _ = _client(fake)
    try:
        response = client.post(
            "/chat", json={"message": CASE30["text"]}, headers={"X-System-Id": "llm-demo"}
        )
        assert response.status_code == 200
        sent = " ".join(m["content"] for m in fake.messages)
        for item in CASE30["expected"]:
            for part in item["parts"]:
                # Подстрока не должна остаться открытой как самостоятельный фрагмент
                # (без соседних букв/цифр), чтобы не ловить совпадения внутри токенов.
                assert not re.search(rf"(?<!\w){re.escape(part)}(?!\w)", sent), (
                    f"утечка {part!r} в сообщениях LLM"
                )
    finally:
        _close(client)


def test_answer_equals_original_for_case30() -> None:
    fake = FakeLLM()
    client, _ = _client(fake)
    try:
        response = client.post(
            "/chat", json={"message": CASE30["text"]}, headers={"X-System-Id": "llm-demo"}
        )
        assert response.status_code == 200
        assert response.json()["answer"] == CASE30["text"]
    finally:
        _close(client)


def test_no_pd_text_passes_through_unchanged() -> None:
    fake = FakeLLM()
    client, _ = _client(fake)
    try:
        text = "Александр Пушкин написал «Евгения Онегина»."
        response = client.post(
            "/chat", json={"message": text}, headers={"X-System-Id": "llm-demo"}
        )
        assert response.status_code == 200
        assert response.json()["sent_to_llm"] == text
    finally:
        _close(client)


def test_missing_system_header_forbidden() -> None:
    fake = FakeLLM()
    client, _ = _client(fake)
    try:
        response = client.post("/chat", json={"message": "привет"})
        assert response.status_code == 403
        assert fake.calls == 0
    finally:
        _close(client)


def test_unmask_disabled_system_forbidden() -> None:
    fake = FakeLLM()
    client, _ = _client(fake)
    try:
        response = client.post(
            "/chat", json={"message": "привет"}, headers={"X-System-Id": "analytics"}
        )
        assert response.status_code == 403
        assert fake.calls == 0
    finally:
        _close(client)


def test_llm_unavailable_returns_503_without_source() -> None:
    fake = FakeLLM(error=LLMUnavailableError("llm_down"))
    client, _ = _client(fake)
    try:
        response = client.post(
            "/chat", json={"message": CASE30["text"]}, headers={"X-System-Id": "llm-demo"}
        )
        assert response.status_code == 503
        assert CASE30["text"] not in response.text
    finally:
        _close(client)


def test_leak_guard_blocks_when_masker_noop() -> None:
    fake = FakeLLM()
    client, _ = _client(fake, masker=NoopMasker())
    try:
        response = client.post(
            "/chat", json={"message": CASE30["text"]}, headers={"X-System-Id": "llm-demo"}
        )
        assert response.status_code == 422
        assert fake.calls == 0
    finally:
        _close(client)
