"""Тесты клиентов LLM без реальной сети (транспорт подменяется MockTransport)."""

from __future__ import annotations

import ssl

import httpx
import pytest

from app.llm.client import (
    AlfaGenClient,
    LLMUnavailableError,
    StubLLMClient,
    build_llm_client,
)
from app.settings import Settings


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "storage_backend": "memory",
        "redis_url": "",
        "mapping_ttl_seconds": 60,
        "encryption_key": "",
        "token_secret": "",
        "systems_config": "config/systems.yaml",
        "system_header": "X-System-Id",
        "max_payload_chars": 1000,
        "max_payload_id_chars": 100,
        "max_inflight": 10,
        "log_level": "INFO",
        "llm_provider": "alfagen",
        "llm_base_url": "https://example.test/v1",
        "llm_model": "test-model",
        "llm_api_key": "test-key",
        "llm_timeout_seconds": 30,
        "llm_ca_bundle": "certs/russian_trusted_ca_chain.pem",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _client(handler: httpx.MockTransport) -> AlfaGenClient:
    settings = _settings()
    client = AlfaGenClient(settings)
    client._client = httpx.AsyncClient(
        transport=handler,
        verify=ssl.create_default_context(cafile=settings.llm_ca_bundle),
        timeout=settings.llm_timeout_seconds,
    )
    return client


def _stream_response() -> httpx.Response:
    body = (
        'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"!"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":null}}]}\n\n'
        "data: [DONE]\n\n"
    )
    return httpx.Response(200, text=body)


def test_stream_concatenates_delta_content() -> None:
    async def scenario() -> None:
        client = _client(httpx.MockTransport(lambda request: _stream_response()))
        result = await client.complete([{"role": "user", "content": "hi"}])
        assert result == "Hello!"

    import asyncio

    asyncio.run(scenario())


def test_http_400_raises_unavailable() -> None:
    async def scenario() -> None:
        client = _client(
            httpx.MockTransport(lambda request: httpx.Response(400, text="bad"))
        )
        with pytest.raises(LLMUnavailableError) as exc_info:
            await client.complete([{"role": "user", "content": "hi"}])
        assert exc_info.value.status_code == 400

    import asyncio

    asyncio.run(scenario())


def test_timeout_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    async def scenario() -> None:
        client = _client(httpx.MockTransport(handler))
        with pytest.raises(LLMUnavailableError):
            await client.complete([{"role": "user", "content": "hi"}])

    import asyncio

    asyncio.run(scenario())


def test_error_text_does_not_contain_sent_content() -> None:
    async def scenario() -> None:
        client = _client(
            httpx.MockTransport(lambda request: httpx.Response(400, text="bad"))
        )
        secret = "SUPER_SECRET_CONTENT"
        with pytest.raises(LLMUnavailableError) as exc_info:
            await client.complete([{"role": "user", "content": secret}])
        assert secret not in str(exc_info.value)

    import asyncio

    asyncio.run(scenario())


def test_stub_returns_last_message_content() -> None:
    async def scenario() -> None:
        client = StubLLMClient()
        result = await client.complete(
            [
                {"role": "user", "content": "первое"},
                {"role": "assistant", "content": "второе"},
            ]
        )
        assert result == "LLM-заглушка получила: второе"

    import asyncio

    asyncio.run(scenario())


def test_build_llm_client_selects_by_provider() -> None:
    assert isinstance(build_llm_client(_settings(llm_provider="alfagen")), AlfaGenClient)
    assert isinstance(build_llm_client(_settings(llm_provider="stub")), StubLLMClient)
