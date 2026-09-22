"""Клиенты внешней LLM (AlfaGen) и заглушка без сети.

AlfaGen — OpenAI-совместимый API: POST {base}/chat/completions работает только
с ``stream: true``, ответ — SSE-поток строк ``data: {json}``, конец — ``data: [DONE]``.
Текст ответа — склейка ``choices[0].delta.content`` из всех чанков (content бывает null).

TLS проверяется по собственному CA-бандлу (сертификат сервера выпущен
"Russian Trusted Sub CA"); отключать проверку сертификата запрещено.
"""

from __future__ import annotations

import json
import ssl
from typing import Protocol

import httpx

from app.settings import Settings


class LLMUnavailableError(Exception):
    """LLM недоступна: сеть, таймаут, ответ не 200, битый поток.

    В тексте исключения нет содержимого запроса и ответа — только причина и код статуса.
    """

    def __init__(self, reason: str, status_code: int | None = None) -> None:
        self.reason = reason
        self.status_code = status_code
        if status_code is not None:
            super().__init__(f"{reason} (status={status_code})")
        else:
            super().__init__(reason)


class LLMClient(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> str: ...


class AlfaGenClient:
    """Клиент AlfaGen: один AsyncClient на процесс, SSE-поток, склейка delta.content."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.llm_base_url.rstrip("/")
        self._model = settings.llm_model
        self._api_key = settings.llm_api_key
        self._client = httpx.AsyncClient(
            verify=ssl.create_default_context(cafile=settings.llm_ca_bundle),
            timeout=settings.llm_timeout_seconds,
        )

    async def complete(self, messages: list[dict[str, str]]) -> str:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        payload = {"model": self._model, "messages": messages, "stream": True}
        url = f"{self._base_url}/chat/completions"
        try:
            async with self._client.stream(
                "POST", url, json=payload, headers=headers
            ) as response:
                if response.status_code != 200:
                    raise LLMUnavailableError("llm_http_error", response.status_code)
                return await self._read_stream(response)
        except LLMUnavailableError:
            raise
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise LLMUnavailableError(f"llm_transport_error: {type(exc).__name__}") from exc

    async def _read_stream(self, response: httpx.Response) -> str:
        parts: list[str] = []
        try:
            async for line in response.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise LLMUnavailableError("llm_bad_stream") from exc
                try:
                    content = chunk["choices"][0]["delta"].get("content")
                except (KeyError, IndexError, TypeError) as exc:
                    raise LLMUnavailableError("llm_bad_stream") from exc
                if content:
                    parts.append(content)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise LLMUnavailableError(f"llm_stream_error: {type(exc).__name__}") from exc
        return "".join(parts)

    async def aclose(self) -> None:
        await self._client.aclose()


class StubLLMClient:
    """Заглушка без сети: возвращает текст последнего сообщения."""

    async def complete(self, messages: list[dict[str, str]]) -> str:
        content = messages[-1]["content"] if messages else ""
        return f"LLM-заглушка получила: {content}"

    async def aclose(self) -> None:
        return None


def build_llm_client(settings: Settings) -> LLMClient:
    """Выбирает клиента по LLM_PROVIDER: "alfagen" или "stub"."""
    if settings.llm_provider == "alfagen":
        return AlfaGenClient(settings)
    return StubLLMClient()
