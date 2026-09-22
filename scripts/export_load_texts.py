"""Export load-test texts from span_reference.yaml into ASCII-safe load/texts.json.

Reads tests/fixtures/span_reference.yaml (UTF-8) and writes load/texts.json with
ensure_ascii=True so the output contains only ASCII (Cyrillic is escaped as
\\uXXXX) and cannot be corrupted by encoding issues.

Run from repo root: python -m scripts.export_load_texts
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_PATH = REPO_ROOT / "tests" / "fixtures" / "span_reference.yaml"
OUTPUT_PATH = REPO_ROOT / "load" / "texts.json"

# Short samples: one PD type per phrase (ids 1, 4, 9, 10, 16, 18, 19, 20, 22, 23, 26, 27, 28).
SHORT_IDS = {1, 4, 9, 10, 16, 18, 19, 20, 22, 23, 26, 27, 28}
COMPLEX_ID = 30


def _has_pd(case: dict) -> bool:
    return bool(case.get("expected"))


def main() -> None:
    cases = yaml.safe_load(FIXTURES_PATH.read_text(encoding="utf-8")) or []
    by_id = {case["id"]: case for case in cases}

    short = [
        {"text": by_id[i]["text"], "has_pd": _has_pd(by_id[i])}
        for i in sorted(SHORT_IDS)
    ]
    complex_case = by_id[COMPLEX_ID]
    complex_item = {"text": complex_case["text"], "has_pd": _has_pd(complex_case)}

    payload = {"short": short, "complex": complex_item}
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
