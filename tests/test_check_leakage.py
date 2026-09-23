"""Тесты проверки утечки выборки в репозиторий (scripts/check_leakage.py) на синтетике."""

from __future__ import annotations

from scripts.check_leakage import WINDOW, area, find_leaks, normalize, windows


def test_normalize_collapses_spaces_and_case() -> None:
    assert normalize("  Серия   4510\tНОМЕР 654321 ") == "серия 4510 номер 654321"


def test_windows_short_and_long() -> None:
    assert windows("abc") == {"abc"}
    assert len(windows("x" * (WINDOW + 5))) == 1
    assert len(windows("".join(chr(1072 + i % 32) for i in range(WINDOW + 3)))) == 4


def test_find_leaks_full_partial_and_min_chars() -> None:
    long_text = "Клиент оформил заявку на перевыпуск карты в отделении банка сегодня утром"
    texts = {"1": "Короткий", "2": long_text, "3": "Совсем другой длинный текст про погоду и прогулки в парке"}
    files = {
        "app/x.py": normalize("# пример: " + long_text),
        "tests/y.py": normalize(long_text[5:60]),
    }
    matches = find_leaks(texts, files, min_chars=20)
    assert ("full", "2", "app/x.py") in matches
    assert ("partial", "2", "tests/y.py") in matches
    assert all(text_id not in ("1", "3") for _, text_id, _ in matches)


def test_area() -> None:
    assert area("app/core/engine.py") == "app"
    assert area("tests/test_api.py") == "tests"
    assert area("README.md") == "other"
