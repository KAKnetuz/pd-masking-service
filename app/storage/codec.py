"""Сериализация и шифрование записей (AES-256-GCM).

ПД в хранилище лежат только в зашифрованном виде. Ключ передаётся через
переменную окружения ENCRYPTION_KEY и никогда не пишется в логи.
"""

from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.storage.base import MappingRecord

_NONCE_SIZE = 12


def decode_key(raw: str) -> bytes:
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise ValueError("ENCRYPTION_KEY должен быть base64 от 32 байт")
    return key


class RecordCodec:
    def __init__(self, key: bytes) -> None:
        self._aead = AESGCM(key)

    def encode(self, key: str, record: MappingRecord) -> bytes:
        payload = json.dumps(
            {"o": record.original, "m": record.masked, "f": record.fragments},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        nonce = os.urandom(_NONCE_SIZE)
        # payload_id — associated data: запись нельзя «подставить» под чужой ключ.
        return nonce + self._aead.encrypt(nonce, payload, key.encode())

    def decode(self, key: str, blob: bytes) -> MappingRecord:
        nonce, ciphertext = blob[:_NONCE_SIZE], blob[_NONCE_SIZE:]
        data = json.loads(self._aead.decrypt(nonce, ciphertext, key.encode()))
        return MappingRecord(
            original=data["o"],
            masked=data["m"],
            fragments=tuple((m, o) for m, o in data.get("f", ())),
        )
