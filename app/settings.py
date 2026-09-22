"""Настройки сервиса из переменных окружения (секреты — только отсюда, не из кода)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


@dataclass(frozen=True, slots=True)
class Settings:
    storage_backend: str
    redis_url: str
    redis_timeout_seconds: float
    redis_max_connections: int
    mapping_ttl_seconds: int
    encryption_key: str
    token_secret: str
    systems_config: str
    system_header: str
    max_payload_chars: int
    max_payload_id_chars: int
    max_inflight: int
    log_level: str
    llm_provider: str
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_timeout_seconds: int
    llm_ca_bundle: str

    def __repr__(self) -> str:
        return self._public_repr()

    def __str__(self) -> str:
        return self._public_repr()

    def _public_repr(self) -> str:
        """repr/str без секретов: ключ LLM не показывается."""
        fields = {
            "storage_backend": self.storage_backend,
            "redis_url": self.redis_url,
            "redis_timeout_seconds": self.redis_timeout_seconds,
            "redis_max_connections": self.redis_max_connections,
            "mapping_ttl_seconds": self.mapping_ttl_seconds,
            "systems_config": self.systems_config,
            "system_header": self.system_header,
            "max_payload_chars": self.max_payload_chars,
            "max_payload_id_chars": self.max_payload_id_chars,
            "max_inflight": self.max_inflight,
            "log_level": self.log_level,
            "llm_provider": self.llm_provider,
            "llm_base_url": self.llm_base_url,
            "llm_model": self.llm_model,
            "llm_timeout_seconds": self.llm_timeout_seconds,
            "llm_ca_bundle": self.llm_ca_bundle,
        }
        return f"Settings({fields!r})"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            storage_backend=os.environ.get("STORAGE_BACKEND", "memory"),
            redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            redis_timeout_seconds=_float("REDIS_TIMEOUT_SECONDS", 2.0),
            redis_max_connections=_int("REDIS_MAX_CONNECTIONS", 128),
            mapping_ttl_seconds=_int("MAPPING_TTL_SECONDS", 3600),
            encryption_key=os.environ.get("ENCRYPTION_KEY", ""),
            token_secret=os.environ.get("TOKEN_SECRET", ""),
            systems_config=os.environ.get("SYSTEMS_CONFIG", "config/systems.yaml"),
            system_header=os.environ.get("SYSTEM_HEADER", "X-System-Id"),
            max_payload_chars=_int("MAX_PAYLOAD_CHARS", 1_000_000),
            max_payload_id_chars=_int("MAX_PAYLOAD_ID_CHARS", 256),
            max_inflight=_int("MAX_INFLIGHT", 64),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            llm_provider=os.environ.get("LLM_PROVIDER", "stub"),
            llm_base_url=os.environ.get(
                "LLM_BASE_URL", "https://alfagen.alfabank.ru/continue-dev/v1"
            ),
            llm_model=os.environ.get("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash-0731"),
            llm_api_key=os.environ.get("LLM_API_KEY", ""),
            llm_timeout_seconds=_int("LLM_TIMEOUT_SECONDS", 30),
            llm_ca_bundle=os.environ.get(
                "LLM_CA_BUNDLE", "certs/russian_trusted_ca_chain.pem"
            ),
        )
