"""News feed fetching and parsing (RSS 2.0 and Atom).

Only URLs from ``Settings.news_feeds`` are ever fetched; the model's tool takes no URL. Redirects
stay on the same https host, bodies are size-capped while streaming, XML goes through
``defusedxml``, and the text that comes out is flattened (no markup, no links). Feed text is data
for the model only: no alert, deadline or background job reads it. Logs carry exception names.
Headlines are ranked by the owner's topic weights and then by freshness (see ``agent.news.topics``).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as safe_et
import httpx

from agent.config import validate_feed_url
from agent.connectors.gmail import html_to_text
from agent.core.clock import utcnow
from agent.core.textutil import one_line
from agent.news.topics import GENERAL, Topic, default_topics

log = logging.getLogger(__name__)

MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 2
MAX_ITEMS_PER_FEED = 50
CACHE_SECONDS = 15 * 60
TIMEOUT_SECONDS = 10
TITLE_CHARS = 200
SUMMARY_CHARS = 300
SOURCE_CHARS = 100
SUMMARY_MATCH_FACTOR = 0.6
UNKNOWN_AGE_HOURS = 48.0
HALF_LIFE_HOURS = 24.0
_REDIRECTS = frozenset({301, 302, 307, 308})
_ATOM = "{http://www.w3.org/2005/Atom}"


class FeedError(Exception):
    """A feed could not be fetched or parsed. Only the type name is ever logged."""


class FeedTooLarge(FeedError):
    pass


class FeedRedirectRefused(FeedError):
    pass


class FeedParseError(FeedError):
    pass


@dataclass(frozen=True)
class FeedItem:
    source: str
    title: str
    published: str | None
    summary: str
    topic: str = ""  # set when the item is ranked: the topic that gave it its weight


@dataclass(frozen=True)
class Feed:
    url: str
    title: str
    items: tuple[FeedItem, ...]


def _text(element: Element | None) -> str:
    return "".join(element.itertext()) if element is not None else ""


def _flat(raw: str, limit: int) -> str:
    """Plain one-line text: markup stripped (twice, for entity-encoded tags), no control chars."""
    stripped = html_to_text(html_to_text(raw))
    return one_line(stripped, limit)


def _date(raw: str) -> str | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        try:
            moment = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(UTC).isoformat()


def _child(parent: Element, *names: str) -> Element | None:
    for name in names:
        found = parent.find(name)
        if found is not None:
            return found
    return None


def parse_feed(url: str, data: bytes) -> Feed:
    host = urlsplit(url).hostname or ""
    try:
        root = safe_et.fromstring(data)
    except Exception:  # defusedxml raises its own types for forbidden constructs
        raise FeedParseError("not valid feed XML") from None
    tag = root.tag.rsplit("}", 1)[-1]
    items: list[FeedItem]
    if tag == "rss":
        channel = root.find("channel")
        if channel is None:
            raise FeedParseError("rss without a channel")
        title = _flat(_text(channel.find("title")), SOURCE_CHARS) or host
        items = [
            FeedItem(
                title,
                _flat(_text(item.find("title")), TITLE_CHARS),
                _date(_text(item.find("pubDate"))),
                _flat(_text(item.find("description")), SUMMARY_CHARS),
            )
            for item in channel.findall("item")[:MAX_ITEMS_PER_FEED]
        ]
    elif tag == "feed":
        title = _flat(_text(root.find(f"{_ATOM}title")), SOURCE_CHARS) or host
        items = [
            FeedItem(
                title,
                _flat(_text(entry.find(f"{_ATOM}title")), TITLE_CHARS),
                _date(_text(_child(entry, f"{_ATOM}published", f"{_ATOM}updated"))),
                _flat(_text(_child(entry, f"{_ATOM}summary", f"{_ATOM}content")), SUMMARY_CHARS),
            )
            for entry in root.findall(f"{_ATOM}entry")[:MAX_ITEMS_PER_FEED]
        ]
    else:
        raise FeedParseError("neither RSS nor Atom")
    return Feed(url, title, tuple(i for i in items if i.title))


class NewsFeeds:
    def __init__(
        self,
        urls: Sequence[str],
        *,
        topics: Sequence[Topic] | None = None,
        transport: httpx.BaseTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._urls = tuple(urls)
        self._topics = tuple(topics) if topics is not None else default_topics()
        self._now = now
        self._transport = transport
        self._monotonic = monotonic
        self._cache: dict[str, tuple[float, Feed]] = {}
        self._lock = threading.Lock()

    # --- fetching ---------------------------------------------------------------------------

    def fetch(self, url: str) -> Feed:
        """Download and parse one feed (never cached). Raises ``FeedError`` or ``httpx`` errors."""
        validate_feed_url(url)
        with httpx.Client(
            follow_redirects=False, timeout=TIMEOUT_SECONDS, transport=self._transport
        ) as client:
            return parse_feed(url, self._download(client, url))

    def _download(self, client: httpx.Client, url: str) -> bytes:
        host = urlsplit(url).hostname
        for _ in range(MAX_REDIRECTS + 1):
            with client.stream(
                "GET", url, headers={"Accept": "application/rss+xml, application/atom+xml, */*"}
            ) as response:
                if response.status_code in _REDIRECTS:
                    url = self._redirect_target(url, host, response.headers.get("location"))
                    continue
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BODY_BYTES:
                        raise FeedTooLarge("feed is larger than the size cap")
                return bytes(body)
        raise FeedRedirectRefused("too many redirects")

    @staticmethod
    def _redirect_target(url: str, host: str | None, location: str | None) -> str:
        if not location:
            raise FeedRedirectRefused("redirect without a location")
        target = urljoin(url, location)
        try:
            validate_feed_url(target)
        except ValueError:
            raise FeedRedirectRefused("redirect to a disallowed URL") from None
        if (urlsplit(target).hostname or "").lower() != (host or "").lower():
            raise FeedRedirectRefused("redirect to another host")
        return target

    def _load(self, url: str) -> Feed:
        now = self._monotonic()
        with self._lock:
            cached = self._cache.get(url)
        if cached is not None and now - cached[0] < CACHE_SECONDS:
            return cached[1]
        feed = self.fetch(url)
        with self._lock:
            self._cache[url] = (now, feed)
        return feed

    # --- reading ----------------------------------------------------------------------------

    @property
    def topic_names(self) -> tuple[str, ...]:
        return tuple(topic.name for topic in self._topics)

    def headlines(
        self, limit: int, source: str | None, topic: str | None = None
    ) -> tuple[list[FeedItem], list[str]]:
        """The best items across the feeds (or the ones matching ``source``), ranked by topic
        weight and freshness, and the hosts that could not be read. ``topic`` keeps only the items
        whose best-matching topic has that name."""
        items: list[FeedItem] = []
        unavailable: list[str] = []
        for url in self._urls:
            host = urlsplit(url).hostname or url
            try:
                feed = self._load(url)
            except Exception as exc:
                log.warning("news feed unavailable: %s", type(exc).__name__)
                if host not in unavailable:
                    unavailable.append(host)
                continue
            if source is None or _matches(source, feed.title, host):
                items.extend(feed.items)
        now = self._now()
        scored: list[tuple[float, FeedItem]] = []
        for item in items:
            weight, name = self._weigh(item)
            if weight <= 0 or (topic is not None and name != topic):
                continue
            score = weight * 0.5 ** (_age_hours(item.published, now) / HALF_LIFE_HOURS)
            scored.append((score, replace(item, topic=name)))
        scored.sort(key=lambda pair: pair[1].published or "", reverse=True)
        scored.sort(key=lambda pair: pair[0], reverse=True)  # stable: ties stay newest first
        return [item for _, item in scored[:limit]], unavailable

    def _weigh(self, item: FeedItem) -> tuple[float, str]:
        """The weight of the best topic for the item: a title match counts in full, a match only in
        the summary at ``SUMMARY_MATCH_FACTOR``. With no match the ``general`` weight applies."""
        best: tuple[float, str] | None = None
        general = 0
        for topic in self._topics:
            if topic.name == GENERAL:
                general = topic.weight
            if topic.pattern is None:
                continue
            if topic.pattern.search(item.title):
                weight = float(topic.weight)
            elif topic.pattern.search(item.summary):
                weight = topic.weight * SUMMARY_MATCH_FACTOR
            else:
                continue
            if best is None or weight > best[0]:
                best = (weight, topic.name)
        return best if best is not None else (float(general), GENERAL)


def _age_hours(published: str | None, now: datetime) -> float:
    if published is None:
        return UNKNOWN_AGE_HOURS
    try:
        moment = datetime.fromisoformat(published)
    except ValueError:
        return UNKNOWN_AGE_HOURS
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0.0, (now - moment).total_seconds() / 3600)


def _matches(source: str, title: str, host: str) -> bool:
    needle = source.strip().lower()
    return bool(needle) and (needle in title.lower() or needle in host.lower())
