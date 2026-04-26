"""Header-sweep tests for the Phase 5 List-Unsubscribe parser.

Plan §14 Phase 5 exit criteria: *"unit — List-Unsubscribe parser
across 20 header variants"*. Each case below is one distinct shape
we have seen in real-world marketing / ESP headers; the matrix
covers RFC 2369 (angle-bracketed URLs, mailto) and RFC 8058
(one-click POST) behaviour plus the tolerant fallbacks.
"""

from __future__ import annotations

import pytest

from app.services.unsubscribe.parser import (
    UnsubscribeAction,
    parse_list_unsubscribe,
)


@pytest.mark.parametrize(
    ("header", "post_header", "expected_urls", "expected_mailto", "expected_one_click"),
    [
        # 1 — canonical mailto + https
        (
            "<mailto:unsub@x.example>, <https://x.example/unsub?u=1>",
            None,
            ("https://x.example/unsub?u=1",),
            "mailto:unsub@x.example",
            False,
        ),
        # 2 — https only
        ("<https://a.example/u>", None, ("https://a.example/u",), None, False),
        # 3 — mailto only
        ("<mailto:bye@a.example>", None, (), "mailto:bye@a.example", False),
        # 4 — one-click via RFC 8058
        (
            "<https://a.example/u>",
            "List-Unsubscribe=One-Click",
            ("https://a.example/u",),
            None,
            True,
        ),
        # 5 — one-click with whitespace variations in the post header
        (
            "<https://a.example/u>",
            "  List-Unsubscribe  =  One-Click  ",
            ("https://a.example/u",),
            None,
            True,
        ),
        # 6 — case-insensitive post header
        (
            "<https://a.example/u>",
            "list-unsubscribe=ONE-CLICK",
            ("https://a.example/u",),
            None,
            True,
        ),
        # 7 — multiple https + mailto (first mailto wins)
        (
            "<mailto:m1@x.example>, <mailto:m2@x.example>, <https://x.example/u>",
            None,
            ("https://x.example/u",),
            "mailto:m1@x.example",
            False,
        ),
        # 8 — http (not https) is still surfaced
        ("<http://legacy.example/u>", None, ("http://legacy.example/u",), None, False),
        # 9 — mixed http + https preserves order
        (
            "<http://a.example/u>, <https://a.example/u>",
            None,
            ("http://a.example/u", "https://a.example/u"),
            None,
            False,
        ),
        # 10 — newline inside header + between entries
        (
            "<mailto:x@y.example>,\n  <https://y.example/u>",
            None,
            ("https://y.example/u",),
            "mailto:x@y.example",
            False,
        ),
        # 11 — URL with commas + querystring (brackets anchor the split)
        (
            "<https://x.example/u?a=1,2,3&b=q%20z>",
            None,
            ("https://x.example/u?a=1,2,3&b=q%20z",),
            None,
            False,
        ),
        # 12 — empty string
        ("", None, None, None, False),
        # 13 — whitespace-only
        ("   \t\n  ", None, None, None, False),
        # 14 — bogus scheme ignored, https kept
        (
            "<ftp://nope.example/u>, <https://ok.example/u>",
            None,
            ("https://ok.example/u",),
            None,
            False,
        ),
        # 15 — no brackets → whitespace/comma fallback
        (
            "https://a.example/u, mailto:u@a.example",
            None,
            ("https://a.example/u",),
            "mailto:u@a.example",
            False,
        ),
        # 16 — duplicates de-duplicated by case-insensitive equality
        (
            "<HTTPS://X.EXAMPLE/U>, <https://x.example/u>",
            None,
            ("HTTPS://X.EXAMPLE/U",),
            None,
            False,
        ),
        # 17 — one-click signalled but header is only mailto (still captured)
        (
            "<mailto:unsub@x.example>",
            "List-Unsubscribe=One-Click",
            (),
            "mailto:unsub@x.example",
            True,
        ),
        # 18 — https with spaces padding the brackets
        (
            "   <   https://a.example/u   >   ",
            None,
            ("https://a.example/u",),
            None,
            False,
        ),
        # 19 — trailing semicolons on a bracketless entry
        (
            "https://a.example/u;",
            None,
            ("https://a.example/u",),
            None,
            False,
        ),
        # 20 — three URLs retained in order
        (
            "<https://a.example/1>, <https://a.example/2>, <https://a.example/3>",
            None,
            (
                "https://a.example/1",
                "https://a.example/2",
                "https://a.example/3",
            ),
            None,
            False,
        ),
        # 21 — missing scheme entry silently dropped
        (
            "<not-a-url>, <https://x.example/u>",
            None,
            ("https://x.example/u",),
            None,
            False,
        ),
        # 22 — one-click post header without the directive → not one-click
        (
            "<https://a.example/u>",
            "Something-Else=Value",
            ("https://a.example/u",),
            None,
            False,
        ),
    ],
)
def test_parse_list_unsubscribe_matrix(
    header: str,
    post_header: str | None,
    expected_urls: tuple[str, ...] | None,
    expected_mailto: str | None,
    expected_one_click: bool,
) -> None:
    action = parse_list_unsubscribe(header, post_header)
    if expected_urls is None and expected_mailto is None:
        assert action is None
        return
    assert isinstance(action, UnsubscribeAction)
    assert action.http_urls == (expected_urls or ())
    assert action.mailto == expected_mailto
    assert action.one_click is expected_one_click


def test_preferred_url_prefers_https() -> None:
    action = parse_list_unsubscribe(
        "<http://a.example/u>, <https://b.example/u>, <mailto:x@y.example>",
    )
    assert action is not None
    assert action.preferred_url == "https://b.example/u"


def test_preferred_url_falls_back_to_mailto() -> None:
    action = parse_list_unsubscribe("<mailto:x@y.example>")
    assert action is not None
    assert action.preferred_url == "mailto:x@y.example"


def test_preferred_url_falls_back_to_http_when_no_https() -> None:
    action = parse_list_unsubscribe("<http://a.example/u>")
    assert action is not None
    assert action.preferred_url == "http://a.example/u"


def test_has_any_action_reflects_content() -> None:
    assert parse_list_unsubscribe("<https://a.example/u>") is not None
    assert parse_list_unsubscribe(None) is None


def test_none_and_blank_headers_return_none() -> None:
    assert parse_list_unsubscribe(None) is None
    assert parse_list_unsubscribe("") is None
    assert parse_list_unsubscribe("   ") is None


def test_url_length_cap_rejects_oversize_entries() -> None:
    too_long = "https://a.example/" + ("x" * 2100)
    action = parse_list_unsubscribe(f"<{too_long}>")
    assert action is None


def test_entry_count_cap_truncates() -> None:
    header = ", ".join(f"<https://a.example/{i}>" for i in range(20))
    action = parse_list_unsubscribe(header)
    assert action is not None
    assert len(action.http_urls) == 16
