"""HTTP-контракт POST /process (FastAPI TestClient, хранилище в памяти)."""

import os

os.environ.setdefault("STORAGE_BACKEND", "memory")

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

SOURCE = "Клиент Иванов Иван Иванович, паспорт 4509 123456"


def _client() -> TestClient:
    return TestClient(create_app(Settings.from_env()))


def test_process_contract_roundtrip() -> None:
    with _client() as client:
        masked = client.post("/process", json={"payload": SOURCE, "payload_id": "api-1"})
        assert masked.status_code == 200
        assert set(masked.json()) == {"result"}
        restored = client.post("/process", json={"payload": masked.json()["result"], "payload_id": "api-1"})
        assert restored.json() == {"result": SOURCE}


def test_validation_error_does_not_echo_payload() -> None:
    with _client() as client:
        response = client.post("/process", json={"payload": SOURCE})
        assert response.status_code == 400
        assert "Иванов" not in response.text


def test_unknown_system_forbidden() -> None:
    with _client() as client:
        response = client.post(
            "/process", json={"payload": SOURCE, "payload_id": "api-2"}, headers={"X-System-Id": "legacy-crm"}
        )
        assert response.status_code == 403


def test_service_endpoints() -> None:
    with _client() as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/ready").status_code == 200
        assert b"pd_requests_total" in client.get("/metrics").content


def test_log_hashes_payload_id(capsys) -> None:
    """В логе обработанного запроса нет исходного payload_id, есть payload_id_hash."""
    import hashlib
    import json

    payload_id = "secret-payload-id-123"
    with _client() as client:
        client.post("/process", json={"payload": SOURCE, "payload_id": payload_id})
    captured = capsys.readouterr().out
    processed = [
        json.loads(line)
        for line in captured.splitlines()
        if '"event": "processed"' in line
    ]
    assert processed, "не найден лог 'processed'"
    record = processed[-1]
    assert record["payload_id_hash"] == hashlib.sha256(payload_id.encode()).hexdigest()[:16]
    assert "payload_id" not in record
