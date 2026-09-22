"""Отладочная форма текста: без содержимого, только при включённом флаге."""

from __future__ import annotations

import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.observability.shape import MAX_SHAPE_CHARS, text_shape
from app.settings import Settings


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Срок действия: 12/27", "срок действия: 99/99"),
        ("Иванов Иван", "Аааааа Аааа"),
        ("IVAN petrov", "XXXX xxxxxx"),
        ("Добрый день!", "Аааааа аааа!"),
        ("Паспорт серия 4509 № 123456", "паспорт серия 9999 № 999999"),
        ("ПИН-код 1234", "пин-код 9999"),
        ("Гражданство: Россия", "гражданство: Аааааа"),
    ],
)
def test_text_shape(text: str, expected: str) -> None:
    assert text_shape(text) == expected


def test_text_shape_is_truncated() -> None:
    assert len(text_shape("x" * 500)) == MAX_SHAPE_CHARS


def _events(output: str) -> list[dict]:
    events = []
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def _run(capsys: pytest.CaptureFixture[str], debug: bool, payload: str, payload_id: str) -> list[dict]:
    settings = dataclasses.replace(Settings.from_env(), debug_shapes=debug, storage_backend="memory")
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post("/process", json={"payload": payload, "payload_id": payload_id})
        assert response.status_code == 200
    return _events(capsys.readouterr().out)


def test_shape_logged_when_enabled_and_no_pd(capsys: pytest.CaptureFixture[str]) -> None:
    events = _run(capsys, True, "Добрый день!", "shape-on-1")
    shapes = [e for e in events if e.get("event") == "no_pd_shape"]
    assert len(shapes) == 1
    assert shapes[0]["shape"] == "Аааааа аааа!"
    assert "Добрый" not in json.dumps(events, ensure_ascii=False)


def test_shape_not_logged_when_disabled(capsys: pytest.CaptureFixture[str]) -> None:
    events = _run(capsys, False, "Добрый день!", "shape-off-1")
    assert not [e for e in events if e.get("event") == "no_pd_shape"]


def test_shape_not_logged_when_pd_found(capsys: pytest.CaptureFixture[str]) -> None:
    events = _run(capsys, True, "Паспорт 4509 123456.", "shape-pd-1")
    assert not [e for e in events if e.get("event") == "no_pd_shape"]
