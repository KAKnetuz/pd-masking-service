"""Реестр детекторов. Новый детектор добавляется сюда одной строкой."""

from __future__ import annotations

from app.core.detectors.address import AddressDetector
from app.core.detectors.base import Detector
from app.core.detectors.context_values import ContextValueDetector
from app.core.detectors.dates import DateDetector
from app.core.detectors.documents import ExtraDocumentDetector, IdentityDocumentDetector, IssuanceDetector
from app.core.detectors.finance_contacts import CardDetector, ContactDetector, InnDetector
from app.core.detectors.fio import FioDetector
from app.core.detectors.labelled import LabelledValueDetector
from app.core.detectors.standalone import StandaloneValueDetector


def default_detectors() -> tuple[Detector, ...]:
    return (
        StandaloneValueDetector(),
        ContactDetector(),
        CardDetector(),
        InnDetector(),
        IdentityDocumentDetector(),
        IssuanceDetector(),
        ExtraDocumentDetector(),
        DateDetector(),
        FioDetector(),
        AddressDetector(),
        LabelledValueDetector(),
        ContextValueDetector(),
    )
