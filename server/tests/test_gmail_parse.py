from __future__ import annotations

import base64

import pytest

from agent.connectors.gmail import MalformedMessage, html_to_text, parse_message
from tests.fakes_gmail import b64, make_resource


def test_parses_headers_recipients_and_flags() -> None:
    res = make_resource(
        "m1",
        from_='"Alice Example" <Alice@Example.com>',
        to="Bob <bob@example.com>, carol@example.org",
        cc="dave@example.com",
        subject="=?UTF-8?B?SGVsbG8g4pyT?=",
        extra_headers={"list-unsubscribe": "<mailto:u@example.com>"},
    )
    msg = parse_message("me@example.com", res)
    assert msg.from_addr == "alice@example.com"
    assert msg.from_name == "Alice Example"
    assert msg.to == ("bob@example.com", "carol@example.org", "dave@example.com")
    assert msg.subject == "Hello ✓"
    assert msg.list_unsubscribe is True
    assert msg.label_ids == ("INBOX", "UNREAD")
    assert msg.internal_date == 1_790_000_000_000


def test_headers_are_case_insensitive() -> None:
    res = make_resource("m1")
    for header in res["payload"]["headers"]:
        header["name"] = header["name"].upper()
    assert parse_message("a", res).subject == "Hello"


def test_prefers_plain_over_html_and_falls_back_to_html() -> None:
    both = make_resource("m1", body="plain text", html="<p>html text</p>")
    assert parse_message("a", both).body == "plain text"
    res = make_resource("m2", html="<style>p{}</style><p>Hi &amp; bye</p><script>x()</script>")
    res["payload"]["parts"] = [res["payload"]["parts"][1]]
    assert parse_message("a", res).body == "Hi & bye"


def test_nested_parts_charset_and_padding() -> None:
    latin = "caf\xe9".encode("latin-1")
    data = base64.urlsafe_b64encode(latin).decode().rstrip("=")
    res = make_resource("m1")
    res["payload"]["parts"] = [
        {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "Content-Type", "value": 'text/plain; charset="iso-8859-1"'}
                    ],
                    "body": {"data": data},
                },
                {
                    "mimeType": "text/plain",
                    "filename": "a.txt",
                    "body": {"data": b64("attachment"), "attachmentId": "x"},
                },
            ],
        }
    ]
    assert parse_message("a", res).body == "caf\xe9"


def test_unknown_charset_and_body_cap() -> None:
    res = make_resource("m1", body="x" * 150_000)
    res["payload"]["parts"][0]["headers"] = [
        {"name": "Content-Type", "value": "text/plain; charset=nonsense"}
    ]
    assert len(parse_message("a", res).body) == 100_000


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.pop("id"),
        lambda r: r.update(internalDate="soon"),
        lambda r: r.update(payload="nope"),
        lambda r: r.update(labelIds="INBOX"),
        lambda r: r["payload"]["parts"].__setitem__(
            0, {"mimeType": "text/plain", "body": {"data": "a"}}
        ),
    ],
)
def test_malformed_resources_raise(mutate: object) -> None:
    res = make_resource("m1")
    mutate(res)  # type: ignore[operator]
    with pytest.raises(MalformedMessage):
        parse_message("a", res)


def test_html_to_text_blocks_and_entities() -> None:
    assert html_to_text("<div>a</div><div>b &lt;c&gt;</div>") == "a\n\nb <c>"
