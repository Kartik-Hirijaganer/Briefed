"""MIME parser: provider payload → :class:`EmailMessage` (+ body) (plan §14 Phase 1).

Gmail exposes two payload shapes we consume:

1. ``format=raw`` — base64-URL-encoded ``message/rfc822`` bytes we feed
   to :mod:`email`'s :class:`BytesParser`. This gives full fidelity
   (multipart parts, attachments, List-Unsubscribe, encoded-word
   subjects, etc.).
2. ``format=metadata`` — header-only JSON. Used for bulk listing when we
   only need subject + from + date for a triage pass.

Both paths normalize into the same Pydantic models so everything
downstream speaks one vocabulary.

This module is a **100%-coverage target** per plan §20.1: every branch
(plain + multipart, quoted-reply trimming, encoded-word, List-Unsubscribe,
one-click) must be exercised by
:mod:`backend.tests.unit.test_gmail_parser`.
"""

from __future__ import annotations

import base64
import binascii
import re
from datetime import UTC, datetime
from email import message_from_bytes
from email.header import decode_header
from email.message import Message
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from typing import TYPE_CHECKING
from uuid import UUID

from app.core.ids import content_hash
from app.domain.providers import (
    EmailAddress,
    EmailBody,
    EmailMessage,
    RawMessage,
    UnsubscribeInfo,
)

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable


_EXCERPT_CHARS = 4000
"""Max characters retained in :attr:`EmailBody.plain_text_excerpt`."""

_QUOTED_REPLY_RE = re.compile(
    r"^(?:On .* wrote:|-----Original Message-----|>.+)$",
    re.MULTILINE,
)
"""Heuristic marker for the start of a quoted reply tail."""

_URL_RE = re.compile(r"<\s*([^<>,\s]+?)\s*>")
"""Matches angle-bracketed URLs in a ``List-Unsubscribe`` header."""


def _decode_base64_url(data: str) -> bytes:
    """Decode Gmail's base64-URL encoding (no padding) into bytes.

    Args:
        data: Base64-URL-encoded string from the Gmail API.

    Returns:
        The raw decoded bytes. A padding fix-up is applied before
        decoding so the input does not need to be pre-padded.
    """
    padding = 4 - (len(data) % 4)
    if padding != 4:
        data = data + ("=" * padding)
    try:
        return base64.urlsafe_b64decode(data.encode("ascii"))
    except (binascii.Error, ValueError):
        return b""


def _decode_header_text(raw: str | None) -> str:
    """Decode an RFC-2047 ``encoded-word`` header value.

    Handles mixed ``=?UTF-8?B?...?=`` / ``=?ISO-8859-1?Q?...?=`` fragments
    and falls back to the unmodified string when no encoding is declared.

    Args:
        raw: Raw header value (may be ``None``).

    Returns:
        The decoded string; empty when ``raw`` is ``None``.
    """
    if not raw:
        return ""
    decoded_parts: list[str] = []
    for value, charset in decode_header(raw):
        if isinstance(value, bytes):
            encoding = charset or "utf-8"
            try:
                decoded_parts.append(value.decode(encoding, errors="replace"))
            except LookupError:
                decoded_parts.append(value.decode("utf-8", errors="replace"))
        else:
            decoded_parts.append(value)
    return "".join(decoded_parts).strip()


def _parse_address(raw: str | None) -> EmailAddress | None:
    """Parse one ``From``/``To`` header value into :class:`EmailAddress`.

    Args:
        raw: Raw header value (may be ``None``).

    Returns:
        The parsed address, or ``None`` when the value was empty or
        unparseable.
    """
    if not raw:
        return None
    name, email = parseaddr(_decode_header_text(raw))
    if not email or "@" not in email:
        return None
    return EmailAddress(email=email, name=name.strip() or None)


def _parse_address_list(raw: str | None) -> tuple[EmailAddress, ...]:
    """Parse a comma-separated address list into a tuple of addresses.

    Args:
        raw: Raw header value (may be ``None``).

    Returns:
        A tuple of parsed addresses; empty when ``raw`` is missing or
        contained no valid addresses.
    """
    if not raw:
        return ()
    addresses: list[EmailAddress] = []
    for name, email in getaddresses([_decode_header_text(raw)]):
        if email and "@" in email:
            addresses.append(EmailAddress(email=email, name=name.strip() or None))
    return tuple(addresses)


def _parse_internal_date_from_headers(date_header: str | None) -> datetime | None:
    """Parse an RFC-2822 ``Date`` header into a UTC datetime.

    Args:
        date_header: Raw ``Date:`` header value.

    Returns:
        A UTC-aware :class:`datetime`, or ``None`` when unparseable.
    """
    if not date_header:
        return None
    try:
        parsed = parsedate_to_datetime(date_header)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_list_unsubscribe(
    header: str | None,
    post_header: str | None,
) -> UnsubscribeInfo | None:
    """Split ``List-Unsubscribe`` into HTTP URLs + mailto + one-click flag.

    Args:
        header: Raw ``List-Unsubscribe`` value (may be ``None``).
        post_header: Raw ``List-Unsubscribe-Post`` value (may be ``None``).

    Returns:
        A populated :class:`UnsubscribeInfo`, or ``None`` when the header
        was absent/unparseable.
    """
    if not header:
        return None
    matches = _URL_RE.findall(header)
    http_urls: list[str] = []
    mailto: str | None = None
    for raw_entry in matches:
        entry = raw_entry.strip()
        if entry.lower().startswith("mailto:"):
            mailto = entry
        elif entry.lower().startswith(("http://", "https://")):
            http_urls.append(entry)
    if not http_urls and not mailto:
        return None
    one_click = bool(
        post_header and "one-click" in post_header.lower(),
    )
    return UnsubscribeInfo(
        http_urls=tuple(http_urls),
        mailto=mailto,
        one_click=one_click,
    )


def _walk_parts(message: Message) -> Iterable[Message]:
    """Yield every non-multipart part of a potentially multipart message.

    Args:
        message: Parsed :class:`email.message.Message`.

    Yields:
        Leaf parts (those without further multipart children).
    """
    if message.is_multipart():
        for part in message.walk():
            if part is message or part.is_multipart():
                continue
            yield part
    else:
        yield message


def _extract_plain_text(message: Message) -> str:
    """Extract a best-effort plain-text body from a MIME tree.

    Preference order:
    1. First ``text/plain`` leaf.
    2. First ``text/html`` leaf stripped of tags.

    Args:
        message: Parsed MIME message.

    Returns:
        The decoded body text; empty string when no textual part exists.
    """
    plain: str = ""
    html: str = ""
    for part in _walk_parts(message):
        ctype = part.get_content_type()
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes | bytearray):
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            decoded = payload.decode(charset, errors="replace")
        except LookupError:
            decoded = payload.decode("utf-8", errors="replace")
        if ctype == "text/plain" and not plain:
            plain = decoded
        elif ctype == "text/html" and not html:
            html = decoded
    if plain:
        return plain
    if html:
        return re.sub(r"<[^>]+>", " ", html)
    return ""


def _trim_quoted_reply(text: str) -> tuple[str, bool]:
    """Strip a quoted-reply tail when one is detected.

    Args:
        text: Decoded plain text.

    Returns:
        A ``(trimmed, was_trimmed)`` pair. ``was_trimmed`` is ``True``
        when we actually cut something off.
    """
    match = _QUOTED_REPLY_RE.search(text)
    if not match:
        return text, False
    head = text[: match.start()].rstrip()
    return head, bool(head)


def _extract_html(message: Message) -> str | None:
    """Return the first ``text/html`` body decoded to a Python str.

    Args:
        message: Parsed MIME message.

    Returns:
        The decoded HTML, or ``None`` when absent.
    """
    for part in _walk_parts(message):
        if part.get_content_type() != "text/html":
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes | bytearray):
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except LookupError:
            return payload.decode("utf-8", errors="replace")
    return None


def parse_message(
    raw: RawMessage,
    *,
    account_id: UUID,
) -> tuple[EmailMessage, EmailBody]:
    """Parse a :class:`RawMessage` into (:class:`EmailMessage`, :class:`EmailBody`).

    When ``raw.raw_mime`` is set, the full MIME tree is walked; when only
    ``raw.header_map`` is populated (metadata-format payloads) the parser
    still returns a valid pair — with empty body — so downstream code can
    operate uniformly.

    Args:
        raw: The provider payload (either raw MIME or header-map).
        account_id: ``connected_accounts.id`` to stamp onto the result.

    Returns:
        A ``(metadata, body)`` pair ready for persistence.
    """
    headers: dict[str, str] = dict(raw.header_map)
    mime: Message | None = None
    if raw.raw_mime:
        mime = message_from_bytes(raw.raw_mime)
        for key in mime:
            if key not in headers:
                value = mime.get(key)
                if value is not None:
                    headers[key] = value

    subject = _decode_header_text(headers.get("Subject"))
    from_addr = _parse_address(headers.get("From")) or EmailAddress(
        email="unknown@invalid.example",
        name=None,
    )
    to_addrs = _parse_address_list(headers.get("To"))
    cc_addrs = _parse_address_list(headers.get("Cc"))

    list_unsubscribe = _parse_list_unsubscribe(
        headers.get("List-Unsubscribe"),
        headers.get("List-Unsubscribe-Post"),
    )

    internal_date = datetime.fromtimestamp(raw.internal_date_ms / 1000.0, tz=UTC)
    if raw.internal_date_ms == 0:
        parsed_date = _parse_internal_date_from_headers(headers.get("Date"))
        if parsed_date is not None:
            internal_date = parsed_date

    body_text: str = ""
    html_body: str | None = None
    quoted_trimmed = False
    if mime is not None:
        body_text = _extract_plain_text(mime)
        body_text, quoted_trimmed = _trim_quoted_reply(body_text)
        html_body = _extract_html(mime)

    excerpt = body_text[:_EXCERPT_CHARS]

    digest = content_hash(
        subject=subject,
        from_addr=from_addr.email,
        internal_date_ms=raw.internal_date_ms,
        snippet=raw.snippet,
    )

    metadata = EmailMessage(
        account_id=account_id,
        message_id=raw.message_id,
        thread_id=raw.thread_id,
        internal_date=internal_date,
        from_addr=from_addr,
        to_addrs=to_addrs,
        cc_addrs=cc_addrs,
        subject=subject,
        snippet=raw.snippet,
        labels=raw.label_ids,
        list_unsubscribe=list_unsubscribe,
        content_hash=digest,
        size_bytes=raw.size_bytes,
    )

    body = EmailBody(
        message_id=raw.message_id,
        plain_text_excerpt=excerpt,
        html_sanitized=html_body,
        quoted_text_removed=quoted_trimmed,
        language=headers.get("Content-Language"),
        size_bytes=raw.size_bytes,
    )
    return metadata, body


def raw_from_gmail_full(
    payload: dict[str, object],
) -> RawMessage:
    """Build :class:`RawMessage` from a Gmail ``format=full|raw`` API payload.

    Args:
        payload: JSON-decoded response from ``users.messages.get``.

    Returns:
        A populated :class:`RawMessage` ready for :func:`parse_message`.

    Raises:
        ValueError: If ``payload`` lacks a required top-level field.
    """
    message_id = str(payload.get("id") or "")
    thread_id = str(payload.get("threadId") or "")
    if not message_id or not thread_id:
        raise ValueError("payload missing id/threadId")

    internal_raw = payload.get("internalDate")
    internal_ms = int(str(internal_raw)) if internal_raw is not None else 0
    size_raw = payload.get("sizeEstimate") or 0
    size_bytes = int(str(size_raw))
    snippet = str(payload.get("snippet") or "")

    label_ids_raw = payload.get("labelIds") or ()
    label_ids: tuple[str, ...] = ()
    if isinstance(label_ids_raw, list | tuple):
        label_ids = tuple(str(item) for item in label_ids_raw)

    raw_mime: bytes | None = None
    raw_field = payload.get("raw")
    if isinstance(raw_field, str) and raw_field:
        raw_mime = _decode_base64_url(raw_field)

    headers_list: list[dict[str, str]] = []
    payload_body = payload.get("payload")
    if isinstance(payload_body, dict):
        for entry in payload_body.get("headers") or ():
            if isinstance(entry, dict):
                headers_list.append({str(k): str(v) for k, v in entry.items()})
    header_map = {h.get("name", ""): h.get("value", "") for h in headers_list}

    return RawMessage(
        message_id=message_id,
        thread_id=thread_id,
        internal_date_ms=internal_ms,
        size_bytes=size_bytes,
        raw_mime=raw_mime,
        label_ids=label_ids,
        header_map=header_map,
        snippet=snippet,
    )
