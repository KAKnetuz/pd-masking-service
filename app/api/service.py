"""Служебные эндпоинты: /health (живость), /ready (готовность), /metrics (Prometheus)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.api.responses import json_response
from app.observability.metrics import render_metrics

router = APIRouter()


@router.get("/health")
async def health() -> Response:
    return json_response({"status": "ok"})


@router.get("/ready")
async def ready(request: Request) -> Response:
    state = request.app.state
    store_ok = await state.store.ping()
    body = {"status": "ok" if store_ok else "degraded", "storage": state.settings.storage_backend, "store_ok": store_ok}
    # Деградация не делает сервис неготовым: запросы обслуживает резервное хранилище.
    return json_response(body)


@router.get("/metrics")
async def metrics() -> Response:
    payload, content_type = render_metrics()
    return Response(payload, media_type=content_type)
