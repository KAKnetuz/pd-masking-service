"""Profile per-detector and full-pipeline performance on load texts.

Reads load/texts.json (complex sentence + short phrases), builds a long text by
repeating the complex sentence until at least 20000 chars, then times each
detector from the registry separately, plus the full DetectionEngine.detect cycle
and Masker.mask on the long text.

Run from repo root: python -m scripts.profile_detectors
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from app.core.detectors.registry import default_detectors
from app.core.engine import DetectionEngine
from app.core.masking import Masker

REPO_ROOT = Path(__file__).resolve().parents[1]
TEXTS_PATH = REPO_ROOT / "load" / "texts.json"

LONG_MIN_CHARS = 20_000
COMPLEX_REPS = 200
LONG_REPS = 10


def build_long_text(complex_text: str) -> str:
    text = ""
    while len(text) < LONG_MIN_CHARS:
        text += complex_text + " "
    return text


def avg_ms(call, reps: int) -> float:
    """Average wall-clock time of `call()` over `reps` runs, in milliseconds."""
    start = time.perf_counter()
    for _ in range(reps):
        call()
    return (time.perf_counter() - start) / reps * 1000.0


def main() -> None:
    payload = json.loads(TEXTS_PATH.read_text(encoding="utf-8"))
    complex_text = payload["complex"]["text"]
    long_text = build_long_text(complex_text)

    detectors = default_detectors()
    engine = DetectionEngine(detectors)
    masker = Masker(os.urandom(32))

    # Per-detector timing: same call the engine makes (detector.detect(text)).
    # detect() may return a lazy generator, so materialize it to actually run it.
    rows: list[tuple[str, float, float]] = []
    for detector in detectors:
        name = type(detector).__name__
        complex_ms = avg_ms(lambda d=detector: list(d.detect(complex_text)), COMPLEX_REPS)
        long_ms = avg_ms(lambda d=detector: list(d.detect(long_text)), LONG_REPS)
        rows.append((name, complex_ms, long_ms))

    rows.sort(key=lambda r: r[2], reverse=True)
    total_long_ms = sum(r[2] for r in rows)

    print(f"Texts: complex {len(complex_text)} chars, long {len(long_text)} chars")
    print(f"Detector reps: complex x{COMPLEX_REPS}, long x{LONG_REPS}")
    print()
    header = f"{'detector':<28}{'ms complex':>12}{'ms long':>12}{'share of sum, %':>18}"
    print(header)
    print("-" * len(header))
    for name, complex_ms, long_ms in rows:
        share = long_ms / total_long_ms * 100 if total_long_ms else 0.0
        print(f"{name:<28}{complex_ms:>12.3f}{long_ms:>12.3f}{share:>17.2f}%")

    # Full pipeline measurements.
    print()
    print("Full pipeline:")
    detect_complex_ms = avg_ms(lambda: engine.detect(complex_text), COMPLEX_REPS)
    detect_long_ms = avg_ms(lambda: engine.detect(long_text), LONG_REPS)
    entities_long = engine.detect(long_text)
    mask_long_ms = avg_ms(lambda: masker.mask(long_text, entities_long, {}), LONG_REPS)
    print(f"  DetectionEngine.detect complex: {detect_complex_ms:.3f} ms")
    print(f"  DetectionEngine.detect long:    {detect_long_ms:.3f} ms")
    print(f"  Masker.mask long:               {mask_long_ms:.3f} ms")


if __name__ == "__main__":
    main()
