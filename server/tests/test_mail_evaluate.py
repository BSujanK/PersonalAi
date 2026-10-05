from __future__ import annotations

import pytest

from agent.connectors.gmail import MailMessage
from agent.mail.evaluate import (
    DEFAULT_FIXTURES,
    build_eval_classifier,
    evaluate,
    load_fixtures,
    main,
)
from agent.mail.rules import Category


def _m(i: int) -> MailMessage:
    return MailMessage("a", f"m{i}", "t", "1", i, "x@example.com", "", (), "s", "", "b", (), False)


def test_metric_math_on_hand_computed_case() -> None:
    # gold:  important important important normal normal promo
    # pred:  important important normal    normal important promo
    gold: list[Category] = ["important", "important", "important", "normal", "normal", "promo"]
    pred: list[Category] = ["important", "important", "normal", "normal", "important", "promo"]
    items = [(_m(i), g) for i, g in enumerate(gold)]
    report = evaluate(items, lambda m: pred[int(m.id[1:])])
    imp = report.per_class["important"]
    assert (imp.precision, imp.recall, imp.support) == (
        pytest.approx(2 / 3),
        pytest.approx(2 / 3),
        3,
    )
    assert imp.f1 == pytest.approx(2 / 3)
    nor = report.per_class["normal"]
    assert (nor.precision, nor.recall) == (pytest.approx(0.5), pytest.approx(0.5))
    assert report.per_class["promo"].f1 == 1.0
    spam = report.per_class["spam"]
    assert (spam.precision, spam.recall, spam.f1, spam.support) == (0.0, 0.0, 0.0, 0)
    assert report.accuracy == pytest.approx(4 / 6)
    assert report.confusion["important"]["normal"] == 1
    assert report.confusion["normal"]["important"] == 1
    assert report.total == 6
    table = report.format()
    assert "important" in table and "0.67" in table and "accuracy 0.67 over 6 items" in table


def test_empty_input_does_not_divide_by_zero() -> None:
    report = evaluate([], lambda m: "normal")
    assert report.accuracy == 0.0 and report.total == 0


def test_rules_only_pipeline_on_fixture_set(capsys: pytest.CaptureFixture[str]) -> None:
    fixtures = load_fixtures(DEFAULT_FIXTURES)
    assert len(fixtures.items) >= 40
    classifier = build_eval_classifier(fixtures, use_ollama=False)
    decided: list[tuple[MailMessage, Category]] = []
    results: dict[str, tuple[Category, str]] = {}
    for msg, gold in fixtures.items:
        category, _source, reason, _text = classifier.classify(msg)
        results[msg.id] = (category, reason)
        if reason != "llm_unavailable":
            decided.append((msg, gold))
    full = evaluate(fixtures.items, lambda m: results[m.id][0])
    on_decided = evaluate(decided, lambda m: results[m.id][0])
    with capsys.disabled():
        print("\nRules-only report, all items (undecided -> normal)")
        print(full.format())
        print("\nRules-only report, rule-decided items only")
        print(on_decided.format())
    assert len(decided) >= 25
    for category, metrics in on_decided.per_class.items():
        if metrics.support:
            assert metrics.precision >= 0.9, category


def test_tricky_fixtures_behave_as_designed() -> None:
    fixtures = load_fixtures(DEFAULT_FIXTURES)
    classifier = build_eval_classifier(fixtures, use_ollama=False)
    outcome = {m.subject: classifier.classify(m)[:3] for m, _ in fixtures.items}
    assert outcome["Exam season sale: 30% off notebooks"][0] == "promo"
    assert outcome["Campus drive notice"][2] == "college_domain"
    assert outcome["Hello"][2] == "llm_unavailable"  # injection mail is not decided by rules
    assert outcome["Verify your account now"][2] == "llm_unavailable"


def test_cli_prints_a_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "accuracy" in capsys.readouterr().out
