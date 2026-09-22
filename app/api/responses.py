"""Общие вспомогательные функции для API-роутеров."""

from __future__ import annotations

import orjson
from fastapi.responses import Response


def json_response(body: dict[str, object], status: int = 200, headers: dict[str, str] | None = None) -> Response:
    return Response(orjson.dumps(body), status_code=status, media_type="application/json", headers=headers)
