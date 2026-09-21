"""Настройки сервиса из переменных окружения (секреты — только отсюда, не из кода)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True, slots=True)
class Settings:
    storage_backend: str
    redis_url: str
    mapping_ttl_seconds: int
    encryption_key: str
    token_secret: str
    systems_config: str
    system_header: str
    max_payload_chars: int
    max_payload_id_chars: int
    max_inflight: int
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            storage_backend=os.environ.get("STORAGE_BACKEND", "memory"),
            redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            mapping_ttl_seconds=_int("MAPPING_TTL_SECONDS", 3600),
            encryption_key=os.environ.get("ENCRYPTION_KEY", ""),
            token_secret=os.environ.get("TOKEN_SECRET", ""),
            systems_config=os.environ.get("SYSTEMS_CONFIG", "config/systems.yaml"),
            system_header=os.environ.get("SYSTEM_HEADER", "X-System-Id"),
            max_payload_chars=_int("MAX_PAYLOAD_CHARS", 1_000_000),
            max_payload_id_chars=_int("MAX_PAYLOAD_ID_CHARS", 256),
            max_inflight=_int("MAX_INFLIGHT", 512),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
