"""Стратегии маскирования и восстановление по фрагментам."""

from app.core.entities import PDType, make_entity
from app.core.masking import Masker, MaskRule, unmask_fragments

MASKER = Masker(b"s" * 32)


def _mask(text: str, pd_type: PDType, parts: list[tuple[int, int]], rule: MaskRule) -> str:
    entity = make_entity(pd_type, parts)
    assert entity is not None
    return MASKER.mask(text, [entity], {pd_type: rule}).text


def test_initials() -> None:
    text = "Иванов Иван Иванович"
    assert _mask(text, PDType.FIO, [(0, len(text))], MaskRule("initials")) == "И. И. И."


def test_partial_matches_contract_example() -> None:
    text = "4509 123456"
    rule = MaskRule("partial", keep_start=2, keep_end=2)
    assert _mask(text, PDType.PASSPORT, [(0, len(text))], rule) == "45** ****56"


def test_partial_keeps_words_between_parts() -> None:
    text = "45 09 номер 123456"
    rule = MaskRule("partial", keep_start=2, keep_end=2)
    assert _mask(text, PDType.PASSPORT, [(0, 5), (12, 18)], rule) == "45 ** номер ****56"


def test_short_value_fully_masked() -> None:
    assert _mask("123", PDType.CARD_CVV, [(0, 3)], MaskRule("partial", 2, 2)) == "***"


def test_email_and_token() -> None:
    email = "ivanov@mail.ru"
    assert _mask(email, PDType.EMAIL, [(0, len(email))], MaskRule("email")) == "i*****@mail.ru"
    token = _mask(email, PDType.EMAIL, [(0, len(email))], MaskRule("token"))
    assert token.startswith("[EMAIL_") and token == _mask(email, PDType.EMAIL, [(0, len(email))], MaskRule("token"))


def test_unmask_fragments_in_llm_answer() -> None:
    fragments = (("И. И. И.", "Иванов Иван Иванович"), ("45** ****56", "4509 123456"))
    answer = "Уважаемый И. И. И., паспорт 45** ****56 проверен."
    restored, count = unmask_fragments(answer, fragments)
    assert restored == "Уважаемый Иванов Иван Иванович, паспорт 4509 123456 проверен."
    assert count == 2
