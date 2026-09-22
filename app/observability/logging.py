"""Структурированные JSON-логи без персональных данных.

В лог попадают только поля из белого списка (идентификаторы, типы ПД, длины,
время). Текст запроса и ответа не логируется никогда — даже при ошибках.
"""

from __future__ import annotations

import json
import logging
import sys
import time

_ALLOWED_FIELDS = (
    "request_id",
    "payload_id_hash",
    "system_id",
    "direction",
    "status",
    "latency_ms",
    "chars",
    "tokens",
    "pd_types",
    "entities",
    "llm_ms",
    "operation",
    "error",
    "storage",
    "workers",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for name in _ALLOWED_FIELDS:
            value = getattr(record, name, None)
            if value is not None:
                entry[name] = value
        if record.exc_info and record.exc_info[0] is not None:
            # Только тип исключения: сообщение может содержать фрагмент входных данных.
            entry["exception"] = record.exc_info[0].__name__
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Логи доступа uvicorn содержат только путь, но отключаем их ради производительности.
    logging.getLogger("uvicorn.access").disabled = True
