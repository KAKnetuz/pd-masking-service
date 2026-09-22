"""Тесты инструментов оценки точности (scripts/eval_gold, make_gold_template, format_matrix) на синтетике."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts._eval_common import REPO_ROOT, assert_outside_repo
from scripts.eval_gold import (
    GoldRow,
    classify_value,
    collect_errors,
    compute_metrics,
    match_value,
    parse_expected,
    parse_gold_row,
)
from scripts.format_matrix import SPECS, Variant, luhn_ok, make_card, make_inn, status, variants_for
from scripts.make_gold_template import expected_from_findings, read_samples

TEXT = "пин-код 1234"
PIN = [("pin", [(8, 12)])]


def _row(text: str, trap: int | None, *expected: tuple[str, str]) -> GoldRow:
    return GoldRow(id="1", text=text, trap=trap, expected=expected)


def test_parse_expected_separators_and_blanks() -> None:
    raw = "fio::Иванов Иван || passport::4509 ||  || broken || passport::123456 "
    assert parse_expected(raw) == (("fio", "Иванов Иван"), ("passport", "4509"), ("passport", "123456"))


def test_parse_gold_row_trap_values_and_text_override() -> None:
    row = parse_gold_row({"id": "7", "text": "испорчено Excel", "trap": "", "expected": ""}, {"7": "+7 918"})
    assert row.trap is None
    assert row.text == "+7 918"
    assert parse_gold_row({"id": "1", "text": "t", "trap": "1", "expected": ""}).trap == 1
    assert parse_gold_row({"id": "1", "text": "t", "trap": "0", "expected": ""}).trap == 0


def test_match_value_full_partial_none() -> None:
    assert match_value(TEXT, "1234", "pin", PIN) == (1.0, True)
    assert match_value(TEXT, "1234", "pin", [("pin", [(8, 10)])])[0] == 0.5
    assert match_value(TEXT, "1234", "pin", []) == (0.0, False)


def test_match_value_best_occurrence() -> None:
    assert match_value("1234 и 1234", "1234", "pin", [("pin", [(7, 11)])]) == (1.0, True)


def test_classify_value_classes() -> None:
    assert classify_value(TEXT, "1234", "pin", PIN) == "TP"
    assert classify_value(TEXT, "1234", "cvv", PIN) == "WRONG_TYPE"
    assert classify_value(TEXT, "1234", "pin", [("pin", [(8, 9)])]) == "PARTIAL"
    assert classify_value(TEXT, "1234", "pin", []) == "FN"
    assert classify_value(TEXT, "9999", "pin", PIN) == "NOT_IN_TEXT"


def test_recall_counts_wrong_type_in_denominator() -> None:
    rows = [_row(TEXT, 0, ("cvv", "1234"))]
    m = compute_metrics(rows, {"1": PIN})
    assert m.classes["WRONG_TYPE"] == 1
    assert m.recall == 0.0
    assert m.recall_any_type == 1.0


def test_trap_findings_count_as_fp_and_lower_precision() -> None:
    rows = [_row(TEXT, 0, ("pin", "1234")), GoldRow(id="2", text="Александр Пушкин", trap=1, expected=())]
    m = compute_metrics(rows, {"1": PIN, "2": [("fio", [(0, 16)])]})
    assert (m.traps, m.trap_fp, m.fp) == (1, 1, 1)
    assert m.precision == 0.5


def test_not_in_text_is_label_error_not_fn() -> None:
    m = compute_metrics([_row(TEXT, 0, ("pin", "9999"))], {"1": PIN})
    assert (m.not_in_text, m.classes["FN"], m.fn_text) == (1, 0, 0)


def test_unlabeled_rows_are_skipped() -> None:
    m = compute_metrics([_row(TEXT, None, ("pin", "1234"))], {"1": PIN})
    assert (m.skipped, m.labeled, m.values) == (1, 0, 0)


def test_char_metrics_and_perfect_text() -> None:
    m = compute_metrics([_row(TEXT, 0, ("pin", "1234"))], {"1": [("pin", [(3, 12)])]})
    assert m.perfect_text == 1
    assert m.recall_chars == 1.0
    assert m.overmask_chars == 0.5


def test_collect_errors_kinds() -> None:
    rows = [
        _row("серия 4509 номер 123456", 0, ("passport", "4509"), ("passport", "123456")),
        GoldRow(id="2", text="Лев Толстой", trap=1, expected=()),
    ]
    findings = {"1": [("passport", [(6, 10)]), ("fio", [(0, 5)])], "2": [("fio", [(0, 11)])]}
    kinds = sorted(e.kind for e in collect_errors(rows, findings))
    assert kinds == ["FN_VALUE", "FP_VALUE", "TRAP_FP"]


def test_expected_from_findings_splits_parts() -> None:
    text = "серия 4509 номер 123456"
    assert expected_from_findings(text, [("passport", [(6, 10), (17, 23)])]) == "passport::4509 || passport::123456"


def test_read_samples_dedup_skips_smoke_and_broken(tmp_path: Path) -> None:
    lines = [
        json.dumps({"text": "a", "mask": "*"}),
        json.dumps({"text": "a", "mask": "другая"}),
        json.dumps({"text": "DIAG-SMOKE b", "mask": ""}),
        "не json",
    ]
    (tmp_path / "samples-1.jsonl").write_text("\n".join(lines), encoding="utf-8")
    assert read_samples(tmp_path) == {"a": "*"}


def test_assert_outside_repo() -> None:
    with pytest.raises(SystemExit):
        assert_outside_repo(REPO_ROOT / "gold.csv")
    assert_outside_repo(REPO_ROOT.parent / "gold.csv")


def test_synthetic_numbers_are_valid() -> None:
    assert luhn_ok(make_card())
    assert not luhn_ok("4276123456789010")
    assert make_inn("5001007322") == "500100732259"


def test_status_ignores_keep_words_and_detects_overmask() -> None:
    v = Variant("F", "num", "паспорт серия 4509 номер 123456", 8, 31, frozenset({"серия", "номер"}))
    assert status(v, [("passport", [(14, 18), (25, 31)])]) == ("full", False)
    assert status(v, [("passport", [(0, 31)])]) == ("full", True)
    assert status(v, [("passport", [(14, 18)])]) == ("partial", False)


def test_variants_keep_value_offsets() -> None:
    for spec in SPECS:
        for v in variants_for(spec):
            assert 0 <= v.start < v.end <= len(v.phrase), (spec.name, v.name)
