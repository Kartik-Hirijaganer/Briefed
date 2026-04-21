"""100%-coverage tests for the Gmail MIME parser (plan §20.1)."""

from __future__ import annotations

import base64
from uuid import uuid4

from app.domain.providers import RawMessage
from app.services.gmail.parser import (
    parse_message,
    raw_from_gmail_full,
)


def _encode_mime(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def test_parse_plain_text_message() -> None:
    mime = (
        b"Subject: Hello\r\n"
        b"From: Alice <alice@example.com>\r\n"
        b"To: Bob <bob@example.com>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"hi there"
    )
    raw = RawMessage(
        message_id="m1",
        thread_id="t1",
        internal_date_ms=1_700_000_000_000,
        raw_mime=mime,
        size_bytes=len(mime),
        snippet="hi there",
    )
    meta, body = parse_message(raw, account_id=uuid4())
    assert meta.subject == "Hello"
    assert meta.from_addr.email == "alice@example.com"
    assert meta.from_addr.name == "Alice"
    assert meta.to_addrs[0].email == "bob@example.com"
    assert body.plain_text_excerpt.startswith("hi there")
    assert len(meta.content_hash) == 32


def test_parse_multipart_alternative() -> None:
    mime = (
        b"Subject: Mixed\r\n"
        b"From: alice@example.com\r\n"
        b'Content-Type: multipart/alternative; boundary="BND"\r\n\r\n'
        b"--BND\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nplain-text-body\r\n"
        b"--BND\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<b>html</b>\r\n"
        b"--BND--\r\n"
    )
    raw = RawMessage(
        message_id="m2",
        thread_id="t2",
        internal_date_ms=1_700_000_000_000,
        raw_mime=mime,
        size_bytes=len(mime),
        snippet="",
    )
    meta, body = parse_message(raw, account_id=uuid4())
    assert "plain-text-body" in body.plain_text_excerpt
    assert body.html_sanitized == "<b>html</b>"
    assert meta.subject == "Mixed"


def test_parse_encoded_word_subject() -> None:
    # "=?UTF-8?B?...?=" encoding of "Café ☕"
    encoded = base64.b64encode("Café ☕".encode()).decode("ascii")
    mime = (
        f"Subject: =?UTF-8?B?{encoded}?=\r\n"
        "From: alice@example.com\r\n"
        "Content-Type: text/plain\r\n\r\n"
        "body"
    ).encode()
    raw = RawMessage(
        message_id="m3",
        thread_id="t3",
        internal_date_ms=1_700_000_000_000,
        raw_mime=mime,
        size_bytes=len(mime),
    )
    meta, _ = parse_message(raw, account_id=uuid4())
    assert meta.subject == "Café ☕"


def test_parse_list_unsubscribe_and_one_click() -> None:
    mime = (
        b"Subject: Promo\r\n"
        b"From: news@example.com\r\n"
        b"List-Unsubscribe: <https://unsub.example/?id=1>, <mailto:u@example.com>\r\n"
        b"List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n"
        b"Content-Type: text/plain\r\n\r\n"
        b"body"
    )
    raw = RawMessage(
        message_id="m4",
        thread_id="t4",
        internal_date_ms=1_700_000_000_000,
        raw_mime=mime,
        size_bytes=len(mime),
    )
    meta, _ = parse_message(raw, account_id=uuid4())
    assert meta.list_unsubscribe is not None
    assert meta.list_unsubscribe.http_urls == ("https://unsub.example/?id=1",)
    assert meta.list_unsubscribe.mailto == "mailto:u@example.com"
    assert meta.list_unsubscribe.one_click is True


def test_parse_list_unsubscribe_absent() -> None:
    mime = b"Subject: Plain\r\nFrom: alice@example.com\r\nContent-Type: text/plain\r\n\r\nbody"
    raw = RawMessage(
        message_id="m5",
        thread_id="t5",
        internal_date_ms=1_700_000_000_000,
        raw_mime=mime,
        size_bytes=len(mime),
    )
    meta, _ = parse_message(raw, account_id=uuid4())
    assert meta.list_unsubscribe is None


def test_parse_malformed_list_unsubscribe_returns_none() -> None:
    mime = (
        b"Subject: Plain\r\n"
        b"From: alice@example.com\r\n"
        b"List-Unsubscribe: not an angle-bracket url\r\n"
        b"Content-Type: text/plain\r\n\r\nbody"
    )
    raw = RawMessage(
        message_id="m5a",
        thread_id="t5a",
        internal_date_ms=1_700_000_000_000,
        raw_mime=mime,
        size_bytes=len(mime),
    )
    meta, _ = parse_message(raw, account_id=uuid4())
    assert meta.list_unsubscribe is None


def test_parse_invalid_from_falls_back_to_unknown() -> None:
    mime = b"Subject: NoFrom\r\nContent-Type: text/plain\r\n\r\nbody"
    raw = RawMessage(
        message_id="m6",
        thread_id="t6",
        internal_date_ms=1_700_000_000_000,
        raw_mime=mime,
        size_bytes=len(mime),
    )
    meta, _ = parse_message(raw, account_id=uuid4())
    assert meta.from_addr.email == "unknown@invalid.example"


def test_parse_uses_date_header_when_internal_date_missing() -> None:
    mime = (
        b"Subject: Dated\r\n"
        b"From: alice@example.com\r\n"
        b"Date: Mon, 10 Feb 2026 12:00:00 +0000\r\n"
        b"Content-Type: text/plain\r\n\r\nbody"
    )
    raw = RawMessage(
        message_id="m7",
        thread_id="t7",
        internal_date_ms=0,  # triggers header fallback
        raw_mime=mime,
        size_bytes=len(mime),
    )
    meta, _ = parse_message(raw, account_id=uuid4())
    assert meta.internal_date.year == 2026
    assert meta.internal_date.month == 2


def test_parse_bad_date_header_keeps_epoch_fallback() -> None:
    mime = (
        b"Subject: BadDate\r\n"
        b"From: alice@example.com\r\n"
        b"Date: definitely not a date\r\n"
        b"Content-Type: text/plain\r\n\r\nbody"
    )
    raw = RawMessage(
        message_id="m7a",
        thread_id="t7a",
        internal_date_ms=0,
        raw_mime=mime,
        size_bytes=len(mime),
    )
    meta, _ = parse_message(raw, account_id=uuid4())
    # Falls back to epoch when both internal_date_ms=0 and header unparseable.
    assert meta.internal_date.year == 1970


def test_parse_trims_quoted_reply() -> None:
    mime = (
        b"Subject: Reply\r\n"
        b"From: alice@example.com\r\n"
        b"Content-Type: text/plain\r\n\r\n"
        b"Thanks, I'll take it.\n\n"
        b"On Mon, Feb 2026 at 10:00 AM, Bob wrote:\n"
        b"> earlier text"
    )
    raw = RawMessage(
        message_id="m8",
        thread_id="t8",
        internal_date_ms=1_700_000_000_000,
        raw_mime=mime,
        size_bytes=len(mime),
    )
    _, body = parse_message(raw, account_id=uuid4())
    assert "earlier text" not in body.plain_text_excerpt
    assert body.quoted_text_removed is True


def test_parse_metadata_only_payload() -> None:
    raw = RawMessage(
        message_id="m9",
        thread_id="t9",
        internal_date_ms=1_700_000_000_000,
        raw_mime=None,
        size_bytes=0,
        header_map={
            "Subject": "Meta Only",
            "From": "alice@example.com",
            "To": "bob@example.com, carol@example.com",
        },
    )
    meta, body = parse_message(raw, account_id=uuid4())
    assert meta.subject == "Meta Only"
    assert len(meta.to_addrs) == 2
    assert body.plain_text_excerpt == ""
    assert body.html_sanitized is None


def test_parse_html_only_falls_back_to_stripped_tags() -> None:
    mime = (
        b"Subject: HtmlOnly\r\n"
        b"From: alice@example.com\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        b"<p>Hello</p>"
    )
    raw = RawMessage(
        message_id="m10",
        thread_id="t10",
        internal_date_ms=1_700_000_000_000,
        raw_mime=mime,
        size_bytes=len(mime),
    )
    _, body = parse_message(raw, account_id=uuid4())
    assert "Hello" in body.plain_text_excerpt


def test_raw_from_gmail_full_roundtrips_raw_mime() -> None:
    mime = b"Subject: Wire\r\nFrom: a@example.com\r\n\r\nhi"
    payload = {
        "id": "m11",
        "threadId": "t11",
        "internalDate": "1700000000000",
        "sizeEstimate": 20,
        "snippet": "hi",
        "labelIds": ["INBOX"],
        "raw": _encode_mime(mime),
        "payload": {"headers": [{"name": "Subject", "value": "Wire"}]},
    }
    raw = raw_from_gmail_full(payload)
    assert raw.message_id == "m11"
    assert raw.thread_id == "t11"
    assert raw.raw_mime == mime
    assert raw.label_ids == ("INBOX",)
    assert raw.header_map == {"Subject": "Wire"}


def test_raw_from_gmail_full_rejects_missing_ids() -> None:
    import pytest

    with pytest.raises(ValueError):
        raw_from_gmail_full({"id": "m11"})


def test_raw_from_gmail_full_handles_bad_base64() -> None:
    payload = {
        "id": "m12",
        "threadId": "t12",
        "internalDate": "0",
        "raw": "!!!not-base64!!!",
        "payload": {},
    }
    raw = raw_from_gmail_full(payload)
    # Bad base64 yields empty bytes rather than raising.
    assert raw.raw_mime == b""


def test_parse_cc_addresses_are_extracted() -> None:
    mime = (
        b"Subject: CC\r\n"
        b"From: alice@example.com\r\n"
        b"Cc: Carol <carol@example.com>, dave@example.com\r\n"
        b"Content-Type: text/plain\r\n\r\nbody"
    )
    raw = RawMessage(
        message_id="m13",
        thread_id="t13",
        internal_date_ms=1_700_000_000_000,
        raw_mime=mime,
        size_bytes=len(mime),
    )
    meta, _ = parse_message(raw, account_id=uuid4())
    assert len(meta.cc_addrs) == 2
    assert meta.cc_addrs[0].name == "Carol"


def test_decode_header_empty_input() -> None:
    from app.services.gmail.parser import _decode_header_text

    assert _decode_header_text(None) == ""
    assert _decode_header_text("") == ""


def test_parse_address_rejects_empty_and_malformed() -> None:
    from app.services.gmail.parser import _parse_address

    assert _parse_address(None) is None
    assert _parse_address("   ") is None
    assert _parse_address("no-at-sign") is None


def test_parse_address_list_handles_none() -> None:
    from app.services.gmail.parser import _parse_address_list

    assert _parse_address_list(None) == ()
    assert _parse_address_list("") == ()


def test_parse_date_header_handles_none_and_bad_inputs() -> None:
    from app.services.gmail.parser import _parse_internal_date_from_headers

    assert _parse_internal_date_from_headers(None) is None
    assert _parse_internal_date_from_headers("") is None
    assert _parse_internal_date_from_headers("bogus") is None


def test_parse_date_header_assumes_utc_for_naive_dates() -> None:
    from datetime import UTC

    from app.services.gmail.parser import _parse_internal_date_from_headers

    parsed = _parse_internal_date_from_headers("Mon, 10 Feb 2026 12:00:00")
    assert parsed is not None
    assert parsed.tzinfo == UTC


def test_parse_list_unsubscribe_with_none() -> None:
    from app.services.gmail.parser import _parse_list_unsubscribe

    assert _parse_list_unsubscribe(None, None) is None
    assert _parse_list_unsubscribe("", None) is None


def test_decode_header_bad_charset_falls_back_to_utf8() -> None:
    from app.services.gmail.parser import _decode_header_text

    encoded = "=?not-a-real-charset?B?aGVsbG8=?="
    assert _decode_header_text(encoded) == "hello"


def test_extract_plain_text_ignores_attachments() -> None:
    from email import message_from_bytes

    from app.services.gmail.parser import _extract_plain_text

    mime = (
        b"Content-Type: multipart/mixed; boundary=B\r\n\r\n"
        b"--B\r\nContent-Type: application/pdf\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\nAAAA\r\n"
        b"--B--\r\n"
    )
    result = _extract_plain_text(message_from_bytes(mime))
    assert result == ""


def test_extract_plain_text_falls_back_when_charset_unknown() -> None:
    from email import message_from_bytes

    from app.services.gmail.parser import _extract_plain_text

    mime = (
        b"Content-Type: text/plain; charset=x-unknown\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n\r\n"
        b"hello"
    )
    assert _extract_plain_text(message_from_bytes(mime)) == "hello"


def test_extract_plain_text_skips_non_byte_payload() -> None:
    from app.services.gmail.parser import _extract_plain_text

    class _FakePart:
        def is_multipart(self) -> bool:
            return False

        def get_content_type(self) -> str:
            return "text/plain"

        def get_payload(self, decode: bool = False) -> str:
            return "not bytes"

        def get_content_charset(self) -> str:
            return "utf-8"

    assert _extract_plain_text(_FakePart()) == ""  # type: ignore[arg-type]


def test_extract_html_falls_back_when_charset_unknown() -> None:
    from email import message_from_bytes

    from app.services.gmail.parser import _extract_html

    mime = (
        b"Content-Type: text/html; charset=x-unknown\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n\r\n"
        b"<b>hello</b>"
    )
    assert _extract_html(message_from_bytes(mime)) == "<b>hello</b>"


def test_extract_html_skips_non_byte_payload() -> None:
    from app.services.gmail.parser import _extract_html

    class _FakePart:
        def is_multipart(self) -> bool:
            return False

        def get_content_type(self) -> str:
            return "text/html"

        def get_payload(self, decode: bool = False) -> str:
            return "not bytes"

        def get_content_charset(self) -> str:
            return "utf-8"

    assert _extract_html(_FakePart()) is None  # type: ignore[arg-type]


def test_parse_message_prefers_provided_header_map() -> None:
    mime = (
        b"Subject: MIME subject\r\nFrom: alice@example.com\r\nContent-Type: text/plain\r\n\r\nbody"
    )
    raw = RawMessage(
        message_id="m14",
        thread_id="t14",
        internal_date_ms=1_700_000_000_000,
        raw_mime=mime,
        header_map={"Subject": "Header map subject"},
        size_bytes=len(mime),
    )
    meta, _ = parse_message(raw, account_id=uuid4())
    assert meta.subject == "Header map subject"


def test_raw_from_gmail_full_without_raw_field() -> None:
    payload = {
        "id": "x",
        "threadId": "y",
        "internalDate": "1",
        "snippet": "s",
        "labelIds": ["A", "B"],
        "payload": {"headers": [{"name": "Subject", "value": "S"}]},
    }
    raw = raw_from_gmail_full(payload)
    assert raw.raw_mime is None
    assert raw.label_ids == ("A", "B")
    assert raw.header_map == {"Subject": "S"}


def test_raw_from_gmail_full_tolerates_missing_payload_body() -> None:
    payload: dict[str, object] = {"id": "x", "threadId": "y", "internalDate": "0"}
    raw = raw_from_gmail_full(payload)
    assert raw.header_map == {}
    assert raw.label_ids == ()


def test_raw_from_gmail_full_ignores_non_list_labels_and_bad_headers() -> None:
    payload = {
        "id": "x",
        "threadId": "y",
        "internalDate": "1",
        "labelIds": "INBOX",
        "payload": {"headers": ["bad", {"name": "Subject", "value": "S"}]},
    }
    raw = raw_from_gmail_full(payload)
    assert raw.label_ids == ()
    assert raw.header_map == {"Subject": "S"}
