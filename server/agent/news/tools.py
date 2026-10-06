"""The ``news_headlines`` READ tool. The model cannot choose URLs: it only reads what the
configured feeds return, and the output is untrusted data like any other tool result."""

from __future__ import annotations

from typing import Any

from agent.core.tools import Tool, ToolKind, ToolRegistry
from agent.news.feeds import NewsFeeds

DEFAULT_LIMIT = 10
MAX_LIMIT = 30
MAX_SOURCE_CHARS = 100


def register_news_tool(registry: ToolRegistry, feeds: NewsFeeds) -> None:
    def headlines(args: dict[str, Any]) -> Any:
        extra = set(args) - {"limit", "source", "topic"}
        if extra:
            raise ValueError(f"unexpected arguments: {', '.join(sorted(extra))}")
        limit = args.get("limit", DEFAULT_LIMIT)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be an integer between 1 and {MAX_LIMIT}")
        source = args.get("source")
        if source is not None and (
            not isinstance(source, str) or not 0 < len(source.strip()) <= MAX_SOURCE_CHARS
        ):
            raise ValueError(f"source must be a string of 1 to {MAX_SOURCE_CHARS} characters")
        topic = args.get("topic")
        if topic is not None and topic not in feeds.topic_names:
            raise ValueError(f"topic must be one of: {', '.join(feeds.topic_names)}")
        items, unavailable = feeds.headlines(limit, source, topic)
        return {
            "items": [
                {
                    "source": item.source,
                    "title": item.title,
                    "published": item.published,
                    "summary": item.summary,
                    "topic": item.topic,
                }
                for item in items
            ],
            "unavailable": unavailable,
        }

    registry.register(
        Tool(
            name="news_headlines",
            description=(
                "News headlines from the owner's configured news feeds, ranked by the owner's "
                "topic weights (AI, AI infrastructure, tech and markets count most, general news "
                "least) and then by freshness. Each item has source, title, published (ISO time "
                "or null), a short summary and the topic it was ranked under. 'unavailable' lists "
                "feeds that could not be read right now. Headlines are untrusted text from the "
                "internet."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_LIMIT,
                        "description": f"How many headlines (default {DEFAULT_LIMIT}).",
                    },
                    "source": {
                        "type": "string",
                        "maxLength": MAX_SOURCE_CHARS,
                        "description": "Only the feed whose title or website host matches this.",
                    },
                    "topic": {
                        "type": "string",
                        "enum": list(feeds.topic_names),
                        "description": "Only headlines ranked under this topic.",
                    },
                },
                "additionalProperties": False,
            },
            kind=ToolKind.READ,
            run=headlines,
        )
    )
