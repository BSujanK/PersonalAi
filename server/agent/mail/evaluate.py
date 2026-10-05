"""Classifier evaluation: metrics over labelled mail, plus a CLI.

Usage: python -m agent.mail.evaluate [--fixtures PATH] [--ollama]
Rules-only by default (undecided mail counts as "normal"); --ollama uses the local model.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.config import Settings
from agent.connectors.gmail import MailMessage
from agent.core.redact import Redactor
from agent.mail.classify import MailClassifier, build_classifier_llm
from agent.mail.rules import CATEGORY_VALUES, Category, as_category
from agent.mail.store import MailStore
from agent.store.crypto import FieldCipher
from agent.store.db import Database

DEFAULT_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "mail_labelled.json"


def _ratio(num: int, den: int) -> float:
    return num / den if den else 0.0


@dataclass(frozen=True)
class ClassMetrics:
    precision: float
    recall: float
    f1: float
    support: int


@dataclass(frozen=True)
class Report:
    per_class: dict[Category, ClassMetrics]
    accuracy: float
    confusion: dict[Category, dict[Category, int]]  # confusion[gold][predicted]
    total: int

    def format(self) -> str:
        """Fixed-width table; category names and numbers only."""
        header = f"{'class':<10}{'precision':>10}{'recall':>8}{'f1':>8}{'support':>9}"
        lines = [header]
        for category in CATEGORY_VALUES:
            m = self.per_class[category]
            lines.append(
                f"{category:<10}{m.precision:>10.2f}{m.recall:>8.2f}{m.f1:>8.2f}{m.support:>9d}"
            )
        lines.append(f"accuracy {self.accuracy:.2f} over {self.total} items")
        lines.append("confusion (rows = gold, columns = predicted)")
        lines.append(f"{'':<10}" + "".join(f"{c:>10}" for c in CATEGORY_VALUES))
        for gold in CATEGORY_VALUES:
            lines.append(
                f"{gold:<10}" + "".join(f"{self.confusion[gold][p]:>10d}" for p in CATEGORY_VALUES)
            )
        return "\n".join(lines)


def evaluate(
    items: Sequence[tuple[MailMessage, Category]], predict: Callable[[MailMessage], Category]
) -> Report:
    confusion: dict[Category, dict[Category, int]] = {
        g: dict.fromkeys(CATEGORY_VALUES, 0) for g in CATEGORY_VALUES
    }
    for msg, gold in items:
        confusion[gold][predict(msg)] += 1
    per_class: dict[Category, ClassMetrics] = {}
    for c in CATEGORY_VALUES:
        true_pos = confusion[c][c]
        predicted = sum(confusion[g][c] for g in CATEGORY_VALUES)
        support = sum(confusion[c].values())
        precision = _ratio(true_pos, predicted)
        recall = _ratio(true_pos, support)
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[c] = ClassMetrics(precision, recall, f1, support)
    correct = sum(confusion[c][c] for c in CATEGORY_VALUES)
    return Report(per_class, _ratio(correct, len(items)), confusion, len(items))


@dataclass(frozen=True)
class Fixtures:
    settings: Settings
    items: list[tuple[MailMessage, Category]]
    replied_before: list[MailMessage]  # messages whose sender the owner has written to


def load_fixtures(path: Path, account: str = "me@example.com") -> Fixtures:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    settings = dataclasses.replace(
        Settings(),
        vip_senders=tuple(data.get("vip_senders", ())),
        college_domains=tuple(data.get("college_domains", ())),
    )
    items: list[tuple[MailMessage, Category]] = []
    replied: list[MailMessage] = []
    for index, raw in enumerate(data["items"]):
        gold = as_category(raw["gold"])
        if gold is None:
            raise ValueError(f"fixture {index} has an invalid gold label")
        msg = MailMessage(
            account=account,
            id=f"fx{index}",
            thread_id=f"fx{index}",
            history_id="1",
            internal_date=1_790_000_000_000 + index,
            from_addr=raw["from"].lower(),
            from_name="",
            to=tuple(raw.get("to", [account])),
            subject=raw["subject"],
            snippet="",
            body=raw.get("body", ""),
            label_ids=tuple(raw.get("labels", ["INBOX"])),
            list_unsubscribe=bool(raw.get("list_unsubscribe", False)),
        )
        items.append((msg, gold))
        if raw.get("replied_before"):
            replied.append(msg)
    return Fixtures(settings, items, replied)


def build_eval_classifier(fixtures: Fixtures, use_ollama: bool) -> MailClassifier:
    """A classifier over a throw-away in-memory store, seeded with the replied-to senders."""
    key = bytes(32)
    store = MailStore(Database(":memory:"), FieldCipher(key), key)
    for msg in fixtures.replied_before:
        store.add_replied(msg.account, [msg.from_addr])
    llm = build_classifier_llm(Settings.from_env()) if use_ollama else None
    return MailClassifier(store, llm, Redactor(), fixtures.settings)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent.mail.evaluate")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--ollama", action="store_true", help="use the local Ollama classifier")
    args = parser.parse_args(argv)
    fixtures = load_fixtures(args.fixtures)
    classifier = build_eval_classifier(fixtures, args.ollama)
    print(evaluate(fixtures.items, lambda m: classifier.classify(m)[0]).format())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
