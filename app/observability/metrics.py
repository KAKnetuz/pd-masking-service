"""Метрики Prometheus: Latency, RPS, TPS (ТЗ 4.4).

RPS = rate(pd_requests_total[1m]), TPS = rate(pd_tokens_total[1m]),
latency — гистограмма pd_request_duration_seconds (P50/P95/P99 через histogram_quantile).
В метках только типы и статусы — никаких значений ПД.
При нескольких воркерах используется multiprocess-режим (PROMETHEUS_MULTIPROC_DIR).
"""

from __future__ import annotations

import os

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)

REQUESTS = Counter("pd_requests_total", "Обработанные запросы", ["direction", "status"])
LATENCY = Histogram(
    "pd_request_duration_seconds",
    "Время обработки запроса",
    ["direction"],
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
TOKENS = Counter("pd_tokens_total", "Обработанные токены (оценка: 1 токен ≈ 4 символа)", ["direction"])
PD_FOUND = Counter("pd_entities_total", "Найденные сущности ПД", ["pd_type"])
REJECTED = Counter("pd_rejected_total", "Отклонённые запросы", ["reason"])
STORE_DEGRADED = Counter("pd_store_degraded_total", "Переключения на резервное хранилище")
INFLIGHT = Gauge("pd_inflight_requests", "Запросы в обработке", multiprocess_mode="livesum")
LLM_LATENCY = Histogram(
    "pd_llm_duration_seconds",
    "Время вызова внешней LLM",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)
LLM_ERRORS = Counter("pd_llm_errors_total", "Ошибки внешней LLM", ["reason"])


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def render_metrics() -> tuple[bytes, str]:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry), CONTENT_TYPE_LATEST
    return generate_latest(), CONTENT_TYPE_LATEST
