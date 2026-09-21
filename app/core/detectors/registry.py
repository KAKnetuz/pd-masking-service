"""Реестр детекторов. Новый детектор добавляется сюда одной строкой."""

from __future__ import annotations

from app.core.detectors.address import AddressDetector
from app.core.detectors.base import Detector
from app.core.detectors.dates import DateDetector
from app.core.detectors.documents import ExtraDocumentDetector, IdentityDocumentDetector, IssuanceDetector
from app.core.detectors.finance_contacts import CardDetector, ContactDetector, InnDetector
from app.core.detectors.fio import FioDetector


def default_detectors() -> tuple[Detector, ...]:
    return (
        ContactDetector(),
        CardDetector(),
        InnDetector(),
        IdentityDocumentDetector(),
        IssuanceDetector(),
        ExtraDocumentDetector(),
        DateDetector(),
        FioDetector(),
        AddressDetector(),
    )
