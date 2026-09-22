"""Тесты чистых функций scripts.eval_gold на синтетике (без файлов вне tests/)."""

from __future__ import annotations

from scripts.eval_gold import (
    GoldRow,
    classify_value,
    collect_errors,
    compute_metrics,
    match_value,
    parse_gold_row,
)


def test_parse_gold_row_with_separators() -> None:
    expected = "fio::Иванов Иван || passport::4509 123456"
    row = parse_gold_row({"id": "1", "text": "текст", "trap": "0", "expected": expected})
    assert row.id == "1"
    assert row.trap == 0
    assert row.expected == (("fio", "Иванов Иван"), ("passport", "4509 123456"))


def test_parse_gold_row_trap_empty() -> None:
    row = parse_gold_row({"id": "2", "text": "текст", "trap": "", "expected": ""})
    assert row.trap is None
    assert row.expected == ()


def test_match_value_full() -> None:
    text = "пин-код 1234"
    entities = [("pin", [(8, 12)])]
    coverage, type_ok = match_value(text, "1234", "pin", entities)
    assert coverage == 1.0
    assert type_ok is True


def test_match_value_partial() -> None:
    text = "пин-код 1234"
    entities = [("pin", [(8, 10)])]
    coverage, _ = match_value(text, "1234", "pin", entities)
    assert 0.0 < coverage < 1.0


def test_match_value_not_found() -> None:
    text = "пин-код 1234"
    coverage, _ = match_value(text, "1234", "pin", [])
    assert coverage == 0.0


def test_match_value_multiple_occurrences() -> None:
    text = "1234 и 1234"
    entities = [("pin", [(0, 4)])]
    coverage, type_ok = match_value(text, "1234", "pin", entities)
    assert coverage == 1.0
    assert type_ok is True


def test_classify_wrong_type() -> None:
    text = "1234"
    entities = [("cvv", [(0, 4)])]
    assert classify_value(text, "1234", "pin", entities) == "WRONG_TYPE"


def test_compute_metrics_fp_outside_expected() -> None:
    rows = [GoldRow(id="1", text="пин-код 1234", trap=0, expected=(("pin", "1234"),))]
    findings = {"пин-код 1234": [("pin", [(8, 12)]), ("cvv", [(0, 3)])]}
    m = compute_metrics(rows, findings)
    assert m.tp == 1
    assert m.fp == 1
    assert m.pd_texts == 1
    assert m.perfect_text == 1


def test_collect_errors_trap_fp() -> None:
    rows = [GoldRow(id="2", text="пин-код 1234", trap=1, expected=())]
    findings = {"пин-код 1234": [("pin", [(8, 12)])]}
    errors = collect_errors(rows, findings)
    assert len(errors) == 1
    assert errors[0].kind == "TRAP_FP"
    assert errors[0].id == "2"


def test_compute_metrics_fn_text() -> None:
    rows = [GoldRow(id="3", text="пин-код 1234", trap=0, expected=(("pin", "1234"),))]
    findings = {"пин-код 1234": []}
    m = compute_metrics(rows, findings)
    assert m.fn == 1
    assert m.fn_text == 1
    assert m.perfect_text == 0
