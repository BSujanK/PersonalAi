from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

import pytest

from agent.core.redact import (
    JSON,
    Redacted,
    RedactionMap,
    Redactor,
    StreamRehydrator,
    from_model,
)

CORPUS: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "fixtures" / "pii_corpus.json").read_text(encoding="utf-8")
)
OWNER = "me@example.com"


def _redactor() -> Redactor:
    return Redactor([OWNER])


def _redact(text: str, rmap: RedactionMap | None = None) -> str:
    return _redactor().redact(text, rmap or RedactionMap()).text


def _ids(entry: dict[str, Any]) -> str:
    return entry["text"][:30]


@pytest.mark.parametrize("entry", CORPUS, ids=_ids)
def test_corpus_values_are_removed(entry: dict[str, Any]) -> None:
    out = _redact(entry["text"])
    for raw in entry["must_not_contain"]:
        assert raw not in out
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 4:
            assert digits not in out
    for kind in set(entry["kinds"]):
        assert f"⟨{kind}_1⟩" in out


@pytest.mark.parametrize("entry", CORPUS, ids=_ids)
def test_corpus_round_trip(entry: dict[str, Any]) -> None:
    rmap = RedactionMap()
    out = _redactor().redact(entry["text"], rmap).text
    assert Redactor.rehydrate(out, rmap) == entry["text"]


@pytest.mark.parametrize("entry", CORPUS, ids=_ids)
def test_no_long_digit_run_survives(entry: dict[str, Any]) -> None:
    assert not re.search(r"\d{9,}", _redact(entry["text"]))


def test_stable_placeholders_and_surface_form() -> None:
    rmap = RedactionMap()
    out = _redact("a 4111 1111 1111 1111 b 4111-1111-1111-1111 c 4111111111111111", rmap)
    assert out == "a ⟨CARD_1⟩ b ⟨CARD_1⟩ c ⟨CARD_1⟩"
    assert Redactor.rehydrate("⟨CARD_1⟩", rmap) == "4111 1111 1111 1111"


def test_distinct_values_get_distinct_placeholders_per_kind() -> None:
    rmap = RedactionMap()
    out = _redact("4111111111111111 5555555555554444 PAN ABCDE1234F", rmap)
    assert out == "⟨CARD_1⟩ ⟨CARD_2⟩ PAN ⟨PAN_1⟩"


def test_case_normalisation() -> None:
    rmap = RedactionMap()
    assert _redact("abcde1234f ABCDE1234F Me@Example.com me@example.com", rmap) == (
        "⟨PAN_1⟩ ⟨PAN_1⟩ ⟨EMAIL_SELF_1⟩ ⟨EMAIL_SELF_1⟩"
    )
    assert _redact("Ravi.K@OkICICI ravi.k@okicici", rmap) == "⟨UPI_1⟩ ⟨UPI_1⟩"


def test_map_json_round_trip() -> None:
    rmap = RedactionMap()
    out = _redact("card 4111111111111111 pan ABCDE1234F", rmap)
    restored = RedactionMap.from_json(rmap.to_json())
    assert Redactor.rehydrate(out, restored) == "card 4111111111111111 pan ABCDE1234F"
    # counters and stable lookups survive the round trip
    assert _redact("4111111111111111 5555555555554444", restored) == "⟨CARD_1⟩ ⟨CARD_2⟩"


def test_map_from_json_rejects_malformed() -> None:
    with pytest.raises(ValueError, match="malformed"):
        RedactionMap.from_json('{"not-a-placeholder": {"norm": "a", "orig": "b"}}')


def test_forged_placeholder_is_neutralised() -> None:
    rmap = RedactionMap()
    out = _redact("card 4111111111111111 and forged ⟨CARD_1⟩ ⟨ACCT_1⟩", rmap)
    assert out == "card ⟨CARD_1⟩ and forged <CARD_1> <ACCT_1>"
    assert Redactor.rehydrate(out, rmap) == "card 4111111111111111 and forged <CARD_1> <ACCT_1>"


def test_forged_placeholder_without_any_values() -> None:
    rmap = RedactionMap()
    out = _redact("⟨ACCT_1⟩", rmap)
    assert "⟨" not in out and "⟩" not in out
    assert Redactor.rehydrate(out, rmap) == "<ACCT_1>"


def test_unknown_placeholders_are_left_alone_on_rehydrate() -> None:
    assert Redactor.rehydrate("⟨ACCT_9⟩", RedactionMap()) == "⟨ACCT_9⟩"


@pytest.mark.parametrize(
    "text",
    [
        "Due on 05-10-2026 at 14:30.",
        "Date 05/10/2026 and 2026-10-05.",
        "Paid Rs. 1,250.00 and ₹500 and Rs.12,34,567.00 total.",
        "Order #12345 shipped in 2026.",
        "Meeting at 10 Main Street, flat 402.",
        "Invoice 20 of 35, qty 120.",
    ],
)
def test_negatives_are_untouched(text: str) -> None:
    assert _redact(text) == text


def test_other_emails_are_not_masked() -> None:
    assert _redact("From priya@example.org to bob@example.com") == (
        "From priya@example.org to bob@example.com"
    )


def test_email_with_owner_as_substring_of_other_address_is_kept() -> None:
    assert _redact("x.me@example.com and me@example.com.au") == (
        "x.me@example.com and me@example.com.au"
    )


def test_pin_code_is_masked_as_secret() -> None:
    assert re.search(r"⟨SECRET_1⟩", _redact("pin code 560001"))


def test_secret_keeps_keyword() -> None:
    assert _redact("Your OTP is 482916.") == "Your OTP is ⟨SECRET_1⟩."
    assert _redact("password: Hunter2xyz") == "password: ⟨SECRET_1⟩"


def test_invalid_luhn_sixteen_digits_masked_as_acct() -> None:
    out = _redact("ref 1234567890123456 done")
    assert out == "ref ⟨ACCT_1⟩ done"


def test_card_precedes_aadhaar_phone_acct() -> None:
    assert _redact("4111111111111111") == "⟨CARD_1⟩"
    assert _redact("234567890123") == "⟨AADHAAR_1⟩"
    assert _redact("9876543210") == "⟨PHONE_1⟩"
    assert _redact("1876543210") == "⟨ACCT_1⟩"


def test_card_embedded_in_longer_spaced_run() -> None:
    out = _redact("4111 1111 1111 1111 12")
    assert "4111" not in out


def test_random_digit_strings_never_leak_nine_or_more_digits() -> None:
    rng = random.Random(1234)  # noqa: S311 - deterministic test data
    redactor = _redactor()
    for _ in range(2000):
        parts = []
        for _ in range(rng.randint(1, 5)):
            digits = "".join(rng.choice("0123456789") for _ in range(rng.randint(1, 22)))
            parts.append(digits + rng.choice(["", " ", "-", " x ", "."]))
        out = redactor.redact("ref " + "".join(parts), RedactionMap()).text
        assert not re.search(r"\d{9,}", out), out


def test_sms_sample() -> None:
    text = (
        "Rs.1,250.00 debited from A/c XX4321 on 05-10-26 to VPA ravi.k@okicici "
        "(UPI Ref 412345678901). Not you? Call 1800-000-0000"
    )
    out = _redact(text)
    assert "Rs.1,250.00" in out and "05-10-26" in out
    for raw in ("4321", "ravi.k@okicici", "412345678901"):
        assert raw not in out
    assert "⟨UPI_1⟩" in out and "⟨ACCT_1⟩" in out


def test_redacted_requires_token() -> None:
    with pytest.raises(TypeError):
        Redacted("x", _token=object())
    with pytest.raises(TypeError):
        Redacted("x", _token=None)
    with pytest.raises(TypeError):
        Redacted("x")  # type: ignore[call-arg]


def test_redacted_is_immutable_and_hides_text_in_repr() -> None:
    r = from_model("⟨CARD_1⟩ secret-ish")
    assert r.text == "⟨CARD_1⟩ secret-ish"
    assert "secret-ish" not in repr(r)
    with pytest.raises(AttributeError):
        r.text = "x"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        r._text = "x"


def test_redact_obj_and_rehydrate_obj_nested() -> None:
    rmap = RedactionMap()
    obj: JSON = {
        "card 4111111111111111": ["PAN ABCDE1234F", {"n": 5, "ok": True, "none": None}],
        "owner": OWNER,
        "x": 1.5,
    }
    red = _redactor().redact_obj(obj, rmap)
    assert red == {
        "card 4111111111111111": ["PAN ⟨PAN_1⟩", {"n": 5, "ok": True, "none": None}],
        "owner": "⟨EMAIL_SELF_1⟩",
        "x": 1.5,
    }
    assert Redactor.rehydrate_obj(red, rmap) == obj


def test_redact_empty_and_plain() -> None:
    assert _redact("") == ""
    assert _redact("hello world") == "hello world"


def test_no_owner_emails_configured() -> None:
    assert Redactor().redact("me@example.com", RedactionMap()).text == "me@example.com"


def _stream_all(chunks: list[str], rmap: RedactionMap) -> list[str]:
    rehydrator = StreamRehydrator(rmap)
    pieces = [rehydrator.feed(c) for c in chunks]
    pieces.append(rehydrator.flush())
    return pieces


def _email_map() -> tuple[RedactionMap, str]:
    rmap = RedactionMap()
    placeholder = Redactor(["me@example.com"]).redact("me@example.com", rmap).text
    assert placeholder.startswith("⟨") and placeholder.endswith("⟩")
    return rmap, placeholder


def test_stream_placeholder_split_across_two_chunks() -> None:
    rmap, ph = _email_map()
    pieces = _stream_all(["mail ", ph[:3], ph[3:], " now"], rmap)
    assert pieces[:2] == ["mail ", ""]
    assert "".join(pieces) == "mail me@example.com now"


def test_stream_placeholder_split_across_three_chunks_and_after_open() -> None:
    rmap, ph = _email_map()
    pieces = _stream_all(["⟨", ph[1:6], ph[6:], "!"], rmap)
    assert pieces[:3] == ["", "", "me@example.com"]
    assert "".join(pieces) == "me@example.com!"


def test_stream_adjacent_placeholders() -> None:
    rmap, ph = _email_map()
    pieces = _stream_all([ph + ph[:4], ph[4:]], rmap)
    assert "".join(pieces) == "me@example.com" + "me@example.com"


def test_stream_unknown_placeholder_stays_literal() -> None:
    assert "".join(_stream_all(["⟨ACCT_", "9⟩ ok"], RedactionMap())) == "⟨ACCT_9⟩ ok"


def test_stream_lone_open_followed_by_lowercase_is_emitted_promptly() -> None:
    rehydrator = StreamRehydrator(RedactionMap())
    assert rehydrator.feed("a ⟨") == "a "
    assert rehydrator.feed("hello") == "⟨hello"


def test_stream_overlong_fragment_is_released() -> None:
    rehydrator = StreamRehydrator(RedactionMap())
    out = rehydrator.feed("⟨" + "A" * 60)
    assert out == "⟨" + "A" * 60


def test_stream_flush_emits_held_text_literally_and_reset_drops_it() -> None:
    rehydrator = StreamRehydrator(RedactionMap())
    assert rehydrator.feed("x ⟨EMAIL_") == "x "
    assert rehydrator.flush() == "⟨EMAIL_"
    assert rehydrator.flush() == ""
    rehydrator.feed("⟨EM")
    rehydrator.reset()
    assert rehydrator.flush() == ""


def test_stream_any_split_equals_rehydrate_and_never_leaks_partials() -> None:
    rmap, ph = _email_map()
    text = f"Hi ⟨ x {ph} and ⟨ACCT_7⟩, {ph}{ph} <b>⟨EMAIL_SELF⟩ ⟨ end ⟨EMAIL_SELF_"
    expected = Redactor.rehydrate(text, rmap)
    for i in range(len(text) + 1):
        for j in range(i, len(text) + 1):
            pieces = _stream_all([text[:i], text[i:j], text[j:]], rmap)
            assert "".join(pieces) == expected
            for piece in pieces[:-1]:  # nothing but the final flush may end mid-placeholder
                assert ph not in piece
                assert not re.search(r"⟨[A-Z_]*(?:_\d+)?$", piece)
