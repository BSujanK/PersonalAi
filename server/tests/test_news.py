from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

import agent.main as main_module
from agent.config import Settings
from agent.connectors.google_auth import GoogleAuth
from agent.core.tools import ToolKind, ToolRegistry
from agent.news.feeds import (
    MAX_BODY_BYTES,
    FeedParseError,
    FeedRedirectRefused,
    FeedTooLarge,
    NewsFeeds,
    parse_feed,
)
from agent.news.tools import register_news_tool
from agent.proactive.services import Fanout
from agent.store.db import Database
from agent.store.keystore import KeyStore
from agent.workspace.services import WorkspaceServices

URL = "https://news.example.com/feed.xml"
URL2 = "https://tech.example.org/atom"

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Example Daily</title>
  <link>https://news.example.com/</link>
  <item>
    <title>First &amp; foremost</title>
    <link>https://news.example.com/a</link>
    <pubDate>Mon, 05 Oct 2026 10:00:00 GMT</pubDate>
    <description><![CDATA[<p>Hello <b>world</b> &amp; friends.</p><script>alert(1)</script>
    <a href="https://evil.example.net/x">click</a>]]></description>
  </item>
  <item>
    <title>Second</title>
    <pubDate>Mon, 05 Oct 2026 12:00:00 +0530</pubDate>
    <description>&lt;b&gt;Escaped&lt;/b&gt; markup&amp;nbsp;here</description>
  </item>
  <item>
    <title>No date</title>
    <pubDate>yesterday-ish</pubDate>
    <description></description>
  </item>
  <item><title></title><description>untitled items are dropped</description></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Tech Notes</title>
  <entry>
    <title>Atom one</title>
    <updated>2026-10-05T11:00:00Z</updated>
    <summary>Short <i>summary</i></summary>
  </entry>
  <entry>
    <title type="html">Atom &lt;b&gt;two&lt;/b&gt;</title>
    <published>2026-10-04T09:00:00+00:00</published>
    <updated>2026-10-06T09:00:00+00:00</updated>
    <content type="html">&lt;p&gt;Body text&lt;/p&gt;</content>
  </entry>
</feed>"""


Handler = Callable[[httpx.Request], httpx.Response]


def _feeds(
    handler: Handler,
    urls: tuple[str, ...] = (URL,),
    monotonic: Callable[[], float] = lambda: 0.0,
) -> NewsFeeds:
    return NewsFeeds(urls, transport=httpx.MockTransport(handler), monotonic=monotonic)


def _serve(bodies: dict[str, str | bytes]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        body = bodies.get(str(request.url))
        if body is None:
            return httpx.Response(404)
        content = body.encode() if isinstance(body, str) else body
        return httpx.Response(200, content=content, headers={"content-type": "text/plain"})

    return handler


# --- parsing -----------------------------------------------------------------------------------


def test_rss_is_parsed_and_stripped_of_markup() -> None:
    feed = parse_feed(URL, RSS.encode())
    assert feed.title == "Example Daily"
    first, second, third = feed.items  # the untitled item is dropped
    assert first.title == "First & foremost" and first.source == "Example Daily"
    assert first.published == "2026-10-05T10:00:00+00:00"
    assert first.summary == "Hello world & friends. click"
    assert "alert" not in first.summary and "evil.example.net" not in first.summary
    assert second.published == "2026-10-05T06:30:00+00:00"
    assert second.summary == "Escaped markup here"
    assert (third.title, third.published, third.summary) == ("No date", None, "")


def test_atom_is_parsed_with_updated_or_published_dates() -> None:
    feed = parse_feed(URL2, ATOM.encode())
    assert feed.title == "Tech Notes"
    one, two = feed.items
    assert (one.title, one.published, one.summary) == (
        "Atom one",
        "2026-10-05T11:00:00+00:00",
        "Short summary",
    )
    assert (two.title, two.published, two.summary) == (
        "Atom two",
        "2026-10-04T09:00:00+00:00",
        "Body text",
    )


def test_text_is_flattened_and_capped() -> None:
    long = "w" * 500
    xml = (
        f"<rss><channel><title>{'T' * 300}</title><item><title>A\u200bB\u2028{long}</title>"
        f"<description>{long}</description></item></channel></rss>"
    )
    [item] = parse_feed(URL, xml.encode()).items
    assert len(item.title) == 200 and item.title.startswith("AB w")
    assert len(item.summary) == 300 and len(item.source) == 100


def test_feed_without_a_title_falls_back_to_the_host() -> None:
    xml = "<rss><channel><item><title>x</title></item></channel></rss>"
    [item] = parse_feed(URL, xml.encode()).items
    assert item.source == "news.example.com"


def test_items_are_capped_per_feed() -> None:
    items = "".join(f"<item><title>n{i}</title></item>" for i in range(80))
    assert len(parse_feed(URL, f"<rss><channel>{items}</channel></rss>".encode()).items) == 50


@pytest.mark.parametrize(
    "xml",
    [
        b"not xml at all",
        b"<html><body>hi</body></html>",
        b"<rss></rss>",
        b'<!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        b"<rss><channel>&b;</channel></rss>",
        b'<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        b"<rss><channel><title>&xxe;</title></channel></rss>",
        b"",
    ],
)
def test_bad_or_hostile_xml_is_refused(xml: bytes) -> None:
    with pytest.raises(FeedParseError):
        parse_feed(URL, xml)


def test_no_links_in_headlines() -> None:
    feeds = _feeds(_serve({URL: RSS}))
    items, _ = feeds.headlines(10, None)
    assert set(vars(items[0])) == {"source", "title", "published", "summary"}


# --- fetching ----------------------------------------------------------------------------------


def test_fetch_validates_the_url_first() -> None:
    called: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(str(request.url))
        return httpx.Response(200, content=RSS.encode())

    feeds = _feeds(handler)
    for bad in ("http://news.example.com/feed", "https://127.0.0.1/feed", "file:///etc/passwd"):
        with pytest.raises(ValueError):
            feeds.fetch(bad)
    assert called == []


def test_a_feed_exactly_at_the_size_cap_is_read_and_one_byte_more_is_not() -> None:
    head, tail = b"<rss><channel><title>T</title><!--", b"--></channel></rss>"
    exact = head + b"x" * (MAX_BODY_BYTES - len(head) - len(tail)) + tail
    assert len(exact) == MAX_BODY_BYTES
    assert _feeds(_serve({URL: exact})).fetch(URL).title == "T"
    with pytest.raises(FeedTooLarge):
        _feeds(_serve({URL: exact + b" "})).fetch(URL)


def test_the_download_is_aborted_while_streaming() -> None:
    sent = 0

    def chunks() -> Iterator[bytes]:
        nonlocal sent
        for _ in range(200):
            sent += 1
            yield b"x" * 65536

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=chunks())

    with pytest.raises(FeedTooLarge):
        _feeds(handler).fetch(URL)
    assert sent < 60  # stopped shortly after 2 MiB, not after the 12.5 MB offered


def _redirecting(chain: dict[str, tuple[int, str] | str]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        step = chain[str(request.url)]
        if isinstance(step, str):
            return httpx.Response(200, content=step.encode())
        status, location = step
        return httpx.Response(status, headers={"location": location})

    return handler


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_same_host_https_redirects_are_followed(status: int) -> None:
    feeds = _feeds(
        _redirecting(
            {
                URL: (status, "https://news.example.com/new.xml"),
                "https://news.example.com/new.xml": (status, "/final.xml"),
                "https://news.example.com/final.xml": RSS,
            }
        )
    )
    assert feeds.fetch(URL).title == "Example Daily"


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example.net/feed.xml",  # another host
        "https://news.example.com.evil.example.net/feed.xml",
        "http://news.example.com/feed.xml",  # not https
        "https://news.example.com:8443/feed.xml",  # another port
        "https://user:pw@news.example.com/feed.xml",
        "https://93.184.216.34/feed.xml",
        "//evil.example.net/feed.xml",
        "javascript:alert(1)",
        "",
    ],
)
def test_other_redirects_are_refused(location: str) -> None:
    called: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(str(request.url))
        return httpx.Response(302, headers={"location": location} if location else {})

    with pytest.raises((FeedRedirectRefused, httpx.InvalidURL)):
        _feeds(handler).fetch(URL)
    assert called == [URL]  # the target was never requested


def test_at_most_two_redirects() -> None:
    chain: dict[str, tuple[int, str] | str] = {
        URL: (301, "https://news.example.com/2"),
        "https://news.example.com/2": (301, "https://news.example.com/3"),
        "https://news.example.com/3": (301, "https://news.example.com/4"),
        "https://news.example.com/4": RSS,
    }
    with pytest.raises(FeedRedirectRefused):
        _feeds(_redirecting(chain)).fetch(URL)


def test_http_errors_are_raised() -> None:
    with pytest.raises(httpx.HTTPStatusError):
        _feeds(lambda _r: httpx.Response(500)).fetch(URL)


# --- headlines, cache and failures -------------------------------------------------------------


def test_headlines_merge_feeds_newest_first_and_apply_limit_and_source() -> None:
    feeds = _feeds(_serve({URL: RSS, URL2: ATOM}), (URL, URL2))
    items, unavailable = feeds.headlines(10, None)
    assert unavailable == []
    assert [i.title for i in items] == [
        "Atom one",
        "First & foremost",
        "Second",
        "Atom two",
        "No date",
    ]  # newest first, undated last
    assert len(feeds.headlines(2, None)[0]) == 2
    assert {i.source for i in feeds.headlines(10, "tech")[0]} == {"Tech Notes"}
    assert {i.source for i in feeds.headlines(10, "EXAMPLE.COM")[0]} == {"Example Daily"}
    assert {i.source for i in feeds.headlines(10, "tech.example.org")[0]} == {"Tech Notes"}
    assert feeds.headlines(10, "nothing matches") == ([], [])


def test_failures_are_listed_by_host_and_logged_by_type(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "tech.example.org":
            raise httpx.ConnectTimeout("timed out reaching https://tech.example.org/atom")
        return httpx.Response(200, content=RSS.encode())

    feeds = _feeds(handler, (URL, URL2, "https://tech.example.org/other"))
    with caplog.at_level(logging.INFO, logger="agent"):
        items, unavailable = feeds.headlines(10, None)
    assert unavailable == ["tech.example.org"]  # once, though two feeds on that host failed
    assert len(items) == 3
    assert "ConnectTimeout" in caplog.text
    assert "tech.example.org" not in caplog.text and "timed out" not in caplog.text


def test_feeds_are_cached_for_fifteen_minutes_and_failures_are_not() -> None:
    now = [0.0]
    calls: list[str] = []
    broken = [False]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(500) if broken[0] else httpx.Response(200, content=RSS.encode())

    feeds = _feeds(handler, monotonic=lambda: now[0])
    feeds.headlines(5, None)
    now[0] = 899
    feeds.headlines(5, None)
    assert len(calls) == 1
    now[0] = 901
    broken[0] = True
    assert feeds.headlines(5, None) == ([], ["news.example.com"])  # refetched, and it failed
    broken[0] = False
    assert len(feeds.headlines(5, None)[0]) == 3
    assert len(calls) == 3


# --- config ------------------------------------------------------------------------------------


def test_default_is_no_feeds() -> None:
    assert Settings.from_env({}).news_feeds == ()
    assert Settings().news_feeds == ()


def test_valid_feeds_are_split_and_kept() -> None:
    value = f" {URL} , https://tech.example.org:443/atom ,, "
    assert Settings.from_env({"PERSONALAI_NEWS_FEEDS": value}).news_feeds == (
        URL,
        "https://tech.example.org:443/atom",
    )


@pytest.mark.parametrize(
    "bad",
    [
        "http://news.example.com/feed",
        "ftp://news.example.com/feed",
        "news.example.com/feed",
        "https://",
        "https:///feed",
        "https://127.0.0.1/feed",
        "https://[::1]/feed",
        "https://10.0.0.5/feed",
        "https://user@news.example.com/feed",
        "https://user:pw@news.example.com/feed",
        "https://news.example.com:8080/feed",
        "https://news.example.com:abc/feed",
        "https://news.example.com/" + "a" * 500,
    ],
)
def test_bad_feed_urls_stop_startup(bad: str) -> None:
    with pytest.raises(ValueError, match="PERSONALAI_NEWS_FEEDS"):
        Settings.from_env({"PERSONALAI_NEWS_FEEDS": f"{URL},{bad}"})


def test_at_most_twenty_feeds() -> None:
    twenty = ",".join(f"https://n{i}.example.com/feed" for i in range(20))
    assert len(Settings.from_env({"PERSONALAI_NEWS_FEEDS": twenty}).news_feeds) == 20
    with pytest.raises(ValueError, match="at most 20"):
        Settings.from_env({"PERSONALAI_NEWS_FEEDS": twenty + ",https://n20.example.com/feed"})


def test_a_url_of_exactly_500_characters_is_accepted() -> None:
    url = "https://news.example.com/" + "a" * (500 - len("https://news.example.com/"))
    assert Settings.from_env({"PERSONALAI_NEWS_FEEDS": url}).news_feeds == (url,)


# --- the tool ----------------------------------------------------------------------------------


def _tool(feeds: NewsFeeds) -> Any:
    registry = ToolRegistry()
    register_news_tool(registry, feeds)
    tool = registry.get("news_headlines")
    assert tool is not None
    return tool


def test_tool_is_a_read_tool_without_a_url_parameter() -> None:
    tool = _tool(_feeds(_serve({URL: RSS})))
    assert tool.kind is ToolKind.READ and tool.untrusted_output is True
    assert set(tool.parameters["properties"]) == {"limit", "source"}
    assert tool.parameters["additionalProperties"] is False


def test_tool_output_shape() -> None:
    tool = _tool(_feeds(_serve({URL: RSS, URL2: ATOM}), (URL, URL2, "https://gone.example.com/x")))
    result = tool.run({"limit": 2})
    assert result["unavailable"] == ["gone.example.com"]
    assert len(result["items"]) == 2
    assert set(result["items"][0]) == {"source", "title", "published", "summary"}
    assert len(tool.run({})["items"]) == 5
    assert {i["source"] for i in tool.run({"source": "tech"})["items"]} == {"Tech Notes"}


@pytest.mark.parametrize(
    "args",
    [
        {"limit": 0},
        {"limit": 31},
        {"limit": True},
        {"limit": "5"},
        {"limit": 2.5},
        {"source": ""},
        {"source": "   "},
        {"source": "x" * 101},
        {"source": 5},
        {"url": "https://evil.example.net/feed"},
    ],
)
def test_tool_validates_arguments(args: dict[str, Any]) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=RSS.encode())

    with pytest.raises(ValueError):
        _tool(_feeds(handler)).run(args)
    assert calls == []


def test_tool_accepts_the_limits() -> None:
    tool = _tool(_feeds(_serve({URL: RSS})))
    assert len(tool.run({"limit": 1})["items"]) == 1
    assert len(tool.run({"limit": 30})["items"]) == 3
    assert tool.run({"source": "x" * 100})["items"] == []


def _setup(settings: Settings, registry: ToolRegistry) -> None:
    main_module._setup_proactive(
        settings,
        Database(":memory:"),
        bytes(range(32)),
        GoogleAuth(KeyStore()),
        registry,
        None,
        WorkspaceServices(None, None),
        main_module._MailHooks(Fanout(), Fanout(), Fanout()),
    )


def test_the_tool_is_registered_only_when_feeds_are_configured() -> None:
    without = ToolRegistry()
    _setup(Settings(), without)
    assert without.get("news_headlines") is None
    configured = ToolRegistry()
    _setup(Settings(news_feeds=(URL,)), configured)
    tool = configured.get("news_headlines")
    assert tool is not None and tool.kind is ToolKind.READ


# --- news-check --------------------------------------------------------------------------------


@pytest.fixture
def mock_feeds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    monkeypatch.setenv("PERSONALAI_DB_PATH", str(tmp_path / "agent.db"))
    requested: list[str] = []
    bodies: dict[str, str | bytes] = {URL: RSS, URL2: ATOM, "https://bad.example.com/x": "nope"}

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return _serve(bodies)(request)

    monkeypatch.setattr(
        main_module,
        "NewsFeeds",
        lambda urls: NewsFeeds(urls, transport=httpx.MockTransport(handler)),
    )
    return requested


def test_news_check_reports_ok_and_failures(
    mock_feeds: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main_module.main(["news-check", URL, URL2]) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"OK  3 items  {URL}",
        f"OK  2 items  {URL2}",
    ]
    code = main_module.main(
        [
            "news-check",
            URL,
            "https://bad.example.com/x",
            "https://missing.example.com/x",
            "http://x.example.com/f",
        ]
    )
    out = capsys.readouterr().out.splitlines()
    assert code == 1
    assert out == [
        f"OK  3 items  {URL}",
        "FAIL FeedParseError https://bad.example.com/x",
        "FAIL HTTPStatusError https://missing.example.com/x",
        "FAIL ValueError http://x.example.com/f",
    ]
    assert "http://x.example.com/f" not in mock_feeds  # never requested


def test_news_check_defaults_to_the_configured_feeds(
    mock_feeds: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PERSONALAI_NEWS_FEEDS", f"{URL},{URL2}")
    assert main_module.main(["news-check"]) == 0
    assert mock_feeds == [URL, URL2]
    assert capsys.readouterr().out.count("OK ") == 2


def test_news_check_with_nothing_to_check_fails(
    mock_feeds: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main_module.main(["news-check"]) == 1
    assert "No feeds to check" in capsys.readouterr().out and mock_feeds == []


def test_news_check_refuses_an_invalid_configuration(
    mock_feeds: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PERSONALAI_NEWS_FEEDS", "http://news.example.com/feed")
    assert main_module.main(["news-check"]) == main_module.EXIT_REFUSED
