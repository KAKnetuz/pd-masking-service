"""Защита от перегрузки: лимит одновременных запросов на воркер → 429 + Retry-After.

Чистый ASGI-middleware (без BaseHTTPMiddleware) — минимальные накладные расходы.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from app.observability.metrics import INFLIGHT, REJECTED

_BODY_429 = b'{"detail":"too many requests"}'


class InflightLimitMiddleware:
    def __init__(self, app: ASGIApp, max_inflight: int) -> None:
        self._app = app
        self._max = max_inflight
        self._inflight = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != "/process":
            await self._app(scope, receive, send)
            return
        if self._inflight >= self._max:
            REJECTED.labels("overload").inc()
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [(b"content-type", b"application/json"), (b"retry-after", b"1")],
                }
            )
            await send({"type": "http.response.body", "body": _BODY_429})
            return
        self._inflight += 1
        INFLIGHT.inc()
        try:
            await self._app(scope, receive, send)
        finally:
            self._inflight -= 1
            INFLIGHT.dec()
