"""News topics and their weights, used to rank headlines (see ``NewsFeeds.headlines``).

Each topic is a name, a weight (0..10) and a case-insensitive, word-bounded regex. ``general`` has
no keywords: its weight is the one an item gets when it matches nothing else. The owner re-weights
or extends the defaults with ``PERSONALAI_NEWS_TOPICS``. This module must not import
``agent.config`` (``Settings.from_env`` imports it to validate the setting at startup).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

GENERAL = "general"
MAX_WEIGHT = 10
MAX_TOPICS = 20
MAX_KEYWORDS = 20
MAX_KEYWORD_CHARS = 40
_NAME = re.compile(r"[a-z][a-z0-9_]{0,30}")
_WEIGHT = re.compile(r"[0-9]{1,2}")


@dataclass(frozen=True)
class Topic:
    name: str
    weight: int
    pattern: re.Pattern[str] | None  # None: matches nothing (the ``general`` fallback)


def _bounded(alternatives: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


_DEFAULT_KEYWORDS: dict[str, str] = {
    "ai": (
        r"ai|a\.i\.|artificial intelligence|llms?|large language models?|genai|generative ai"
        r"|chatgpt|gpt-?\d\w*|openai|anthropic|claude|gemini|llama|mistral|deepseek|qwen"
        r"|hugging ?face|machine learning|deep learning|neural networks?|foundation models?"
        r"|ai agents?|agi|copilot"
    ),
    "ai_infra": (
        r"gpus?|nvidia|data ?cent(?:er|re)s?|chips?|chipmakers?|semiconductors?|tsmc|amd|intel"
        r"|h100|h200|b200|gb200|blackwell|hopper|hbm|supercomputers?|tpus?|cuda|foundr(?:y|ies)"
        r"|ai infrastructure|compute"
    ),
    "tech": (
        r"technology|tech|software|startups?|apple|google|alphabet|microsoft|meta|amazon|aws"
        r"|cloud|cybersecurity|smartphones?|iphone|android|quantum|robotics?"
    ),
    "markets": (
        r"stocks?|shares|stock markets?|markets?|sensex|nifty|nasdaq|s&p ?500|dow jones"
        r"|wall street|earnings|ipos?|investors?|rally|sell-?offs?|bonds?|fed|interest rates?"
        r"|rbi|inflation|market cap|valuations?"
    ),
}
_DEFAULT_WEIGHTS: dict[str, int] = {"ai": 5, "ai_infra": 5, "tech": 3, "markets": 3, GENERAL: 1}


def default_topics() -> tuple[Topic, ...]:
    return tuple(
        Topic(
            name,
            weight,
            _bounded(_DEFAULT_KEYWORDS[name]) if name in _DEFAULT_KEYWORDS else None,
        )
        for name, weight in _DEFAULT_WEIGHTS.items()
    )


def _fail(reason: str) -> ValueError:
    return ValueError(f"PERSONALAI_NEWS_TOPICS: {reason}")


def _keywords(raw: str) -> re.Pattern[str]:
    words = [word.strip() for word in raw.split("|")]
    if not 1 <= len(words) <= MAX_KEYWORDS:
        raise _fail(f"a topic takes 1 to {MAX_KEYWORDS} keywords")
    if any(not 1 <= len(word) <= MAX_KEYWORD_CHARS for word in words):
        raise _fail(f"each keyword must be 1 to {MAX_KEYWORD_CHARS} characters")
    return _bounded("|".join(re.escape(word) for word in words))


def parse_news_topics(raw: str) -> tuple[Topic, ...]:
    """The default topics with the owner's changes applied.

    ``name=weight`` re-weights a default topic; ``name=weight:kw1|kw2`` adds a topic or replaces
    the keywords of an existing one. Keywords are plain words, not regular expressions. A weight
    of 0 hides the items that match the topic.
    """
    topics = {topic.name: topic for topic in default_topics()}
    seen: set[str] = set()
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        name, equals, rest = entry.partition("=")
        name = name.strip()
        if not equals or not _NAME.fullmatch(name):
            raise _fail("each entry must look like name=weight or name=weight:keyword|keyword")
        if name in seen:
            raise _fail("a topic name may appear only once")
        seen.add(name)
        weight_text, colon, keywords = rest.partition(":")
        weight_text = weight_text.strip()
        if not _WEIGHT.fullmatch(weight_text) or int(weight_text) > MAX_WEIGHT:
            raise _fail(f"a weight must be a whole number from 0 to {MAX_WEIGHT}")
        existing = topics.get(name)
        if colon:
            if name == GENERAL:
                raise _fail("the general topic has no keywords")
            pattern: re.Pattern[str] | None = _keywords(keywords)
        elif existing is None:
            raise _fail("a new topic needs keywords: name=weight:keyword|keyword")
        else:
            pattern = existing.pattern
        topics[name] = Topic(name, int(weight_text), pattern)
        if len(topics) > MAX_TOPICS:
            raise _fail(f"at most {MAX_TOPICS} topics are allowed")
    return tuple(topics.values())
