"""SSRF-hardened unsubscribe executor (ADR 0014).

Release 2 lets a user-initiated action actually unsubscribe — but only via the
sender-advertised ``List-Unsubscribe`` target Briefed already parsed, and only
when the sender supports RFC 8058 one-click over HTTPS. Every other case
(``http``-only one-click, non-one-click links, ``mailto:``) degrades to
``manual_required`` so the frontend can have the user finish in their browser.

Because the target URL is attacker-influenced data (a malicious sender can
advertise an internal address), the executor is deliberately network-hardened:

* scheme restricted to ``http`` / ``https`` (``data:`` / ``file:`` rejected);
* the host is resolved and **every** resolved address is rejected if it is
  private / loopback / link-local / reserved / CGNAT / multicast / metadata
  (IPv4 **and** IPv6, including IPv4-mapped) — validated **immediately before**
  the request to shrink the DNS-rebinding window;
* the caller passes an ``httpx.AsyncClient`` built with ``trust_env=False``
  (ignore proxy env) and ``follow_redirects=False`` (a 3xx to an internal
  address is a classic SSRF bypass — treated as a failure, never followed);
* the response body read is bounded so a hostile sender cannot exhaust memory.

Pinned-IP connect (resolve once, connect to that IP with the original ``Host``)
is noted in ADR 0014 as optional future hardening.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from app.core.logging import get_logger
from app.services.unsubscribe.parser import UnsubscribeAction

if TYPE_CHECKING:  # pragma: no cover
    import httpx


logger = get_logger(__name__)

_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})
"""Only plain HTTP(S) unsubscribe targets are ever contacted."""

_MAX_BODY_BYTES = 64 * 1024
"""Cap the response body read so a hostile sender cannot exhaust memory."""

_CGNAT_V4 = ipaddress.ip_network("100.64.0.0/10")
"""Carrier-grade NAT range — not flagged by ``is_private`` on older Pythons."""

ExecuteStatus = Literal["unsubscribed", "manual_required", "failed"]
"""Lifecycle outcome of an execute attempt."""

ExecutedVia = Literal["one_click", "none"]
"""How the unsubscribe was performed (``none`` for manual/failed)."""


class UnsafeUnsubscribeURLError(ValueError):
    """Raised when an unsubscribe URL fails the SSRF safety checks."""


class ExecuteOutcome(BaseModel):
    """Result of :func:`execute_unsubscribe`, crossing into the API layer.

    Attributes:
        status: Lifecycle outcome (``unsubscribed`` / ``manual_required`` /
            ``failed``).
        executed_via: ``one_click`` when Briefed sent the request itself,
            else ``none``.
        manual_url: The URL/``mailto:`` the user must open for
            ``manual_required``; ``None`` otherwise.
        error: Short machine-ish failure note for ``failed`` outcomes; ``None``
            otherwise.
        message: Human-readable summary suitable for the UI.
    """

    model_config = ConfigDict(frozen=True)

    status: ExecuteStatus = Field(..., description="Execute lifecycle outcome.")
    executed_via: ExecutedVia = Field(..., description="How the unsubscribe was performed.")
    manual_url: str | None = Field(default=None, description="URL the user must open, if manual.")
    error: str | None = Field(default=None, description="Failure note for failed outcomes.")
    message: str = Field(..., description="Human-readable summary for the UI.")


def validate_unsubscribe_url(url: str) -> None:
    """Reject an unsubscribe URL that is unsafe to contact (SSRF guard).

    The check is intentionally strict: scheme must be ``http`` / ``https``, the
    host must be a parseable ASCII hostname or IP literal, and **every**
    resolved address must be publicly routable.

    Args:
        url: Candidate ``List-Unsubscribe`` HTTP(S) target.

    Raises:
        UnsafeUnsubscribeURLError: When the scheme, host, or any resolved IP is
            disallowed (private/loopback/link-local/reserved/CGNAT/metadata),
            or the host is malformed / non-ASCII (IDN-suspicious).
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUnsubscribeURLError(f"scheme {scheme!r} is not allowed")

    host = parts.hostname
    if not host:
        raise UnsafeUnsubscribeURLError("missing host")
    if not host.isascii():
        raise UnsafeUnsubscribeURLError("non-ASCII (IDN-suspicious) host")

    for address in _resolve_addresses(host):
        if not _is_public_address(address):
            raise UnsafeUnsubscribeURLError(f"host resolves to non-public address {address!r}")


def _resolve_addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Return every IP the host maps to (the literal, or DNS-resolved set).

    Args:
        host: Hostname or IP literal extracted from the URL.

    Returns:
        Parsed IP addresses to classify.

    Raises:
        UnsafeUnsubscribeURLError: When the host cannot be resolved.
    """
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUnsubscribeURLError(f"host {host!r} did not resolve") from exc
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        sockaddr = info[4]
        try:
            addresses.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:  # pragma: no cover - getaddrinfo returns valid IPs
            raise UnsafeUnsubscribeURLError("resolved an unparseable address") from None
    if not addresses:  # pragma: no cover - getaddrinfo returns at least one
        raise UnsafeUnsubscribeURLError(f"host {host!r} did not resolve")
    return addresses


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return ``True`` only when ``address`` is a publicly routable host.

    Args:
        address: A resolved IP address.

    Returns:
        ``False`` for private/loopback/link-local/reserved/CGNAT/metadata
        (and IPv4-mapped IPv6 wrapping such addresses).
    """
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return _is_public_address(address.ipv4_mapped)
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        return False
    return not (isinstance(address, ipaddress.IPv4Address) and address in _CGNAT_V4)


async def execute_unsubscribe(
    action: UnsubscribeAction,
    *,
    http_client: httpx.AsyncClient,
    timeout: float,
) -> ExecuteOutcome:
    """Execute (or surface) the unsubscribe described by ``action``.

    Decision tree (ADR 0014):

    * one-click **and** an HTTPS URL → POST ``List-Unsubscribe=One-Click``;
      2xx → ``unsubscribed`` (``one_click``), non-2xx → ``failed``;
    * has a URL but not one-click-over-HTTPS → ``manual_required`` + the URL;
    * ``mailto:`` only → ``manual_required`` + the ``mailto:`` (no
      ``gmail.send`` scope, so Briefed never sends the email itself);
    * nothing actionable → ``failed``.

    Args:
        action: Normalized ``List-Unsubscribe`` payload for the sender.
        http_client: Caller-owned client built with ``trust_env=False`` and
            ``follow_redirects=False``.
        timeout: Per-request timeout in seconds.

    Returns:
        The :class:`ExecuteOutcome` to persist + return to the client.
    """
    one_click_url = _one_click_url(action)
    if one_click_url is not None:
        return await _attempt_one_click(one_click_url, http_client=http_client, timeout=timeout)

    manual_url = action.preferred_url
    if manual_url is not None:
        return ExecuteOutcome(
            status="manual_required",
            executed_via="none",
            manual_url=manual_url,
            error=None,
            message="Open the unsubscribe link to finish — this sender does not support one-click.",
        )

    return ExecuteOutcome(
        status="failed",
        executed_via="none",
        manual_url=None,
        error="no_actionable_target",
        message="This sender did not advertise an unsubscribe action.",
    )


def _one_click_url(action: UnsubscribeAction) -> str | None:
    """Return the HTTPS URL eligible for an automated one-click POST.

    Args:
        action: Normalized unsubscribe payload.

    Returns:
        The first HTTPS URL when the sender advertised RFC 8058 one-click,
        else ``None`` (HTTP-only one-click is intentionally excluded).
    """
    if not action.one_click:
        return None
    for url in action.http_urls:
        if url.lower().startswith("https://"):
            return url
    return None


async def _attempt_one_click(
    url: str,
    *,
    http_client: httpx.AsyncClient,
    timeout: float,
) -> ExecuteOutcome:
    """Validate, then POST a one-click unsubscribe to ``url``.

    Args:
        url: Validated-on-entry HTTPS one-click target.
        http_client: Caller-owned non-redirecting client.
        timeout: Per-request timeout in seconds.

    Returns:
        ``unsubscribed`` on 2xx, ``failed`` on SSRF rejection / non-2xx /
        transport error.
    """
    import httpx  # deferred import keeps module load SnapStart-friendly

    # Validate immediately before the request to shrink the rebinding window.
    try:
        await asyncio.to_thread(validate_unsubscribe_url, url)
    except UnsafeUnsubscribeURLError as exc:
        logger.warning("unsubscribe.execute.blocked", reason=str(exc))
        return ExecuteOutcome(
            status="failed",
            executed_via="none",
            manual_url=None,
            error="ssrf_blocked",
            message="The unsubscribe target was blocked by Briefed's safety checks.",
        )

    try:
        async with http_client.stream(
            "POST",
            url,
            data={"List-Unsubscribe": "One-Click"},
            timeout=timeout,
            follow_redirects=False,
        ) as response:
            await _drain_bounded(response)
            status_code = response.status_code
    except httpx.HTTPError as exc:
        logger.warning("unsubscribe.execute.transport_error", error=str(exc))
        return ExecuteOutcome(
            status="failed",
            executed_via="none",
            manual_url=None,
            error="request_failed",
            message="Could not reach the sender's unsubscribe endpoint.",
        )

    if 200 <= status_code < 300:
        return ExecuteOutcome(
            status="unsubscribed",
            executed_via="one_click",
            manual_url=None,
            error=None,
            message="Unsubscribed via the sender's one-click endpoint.",
        )
    return ExecuteOutcome(
        status="failed",
        executed_via="none",
        manual_url=None,
        error=f"http_{status_code}",
        message="The sender's unsubscribe endpoint rejected the request.",
    )


async def _drain_bounded(response: httpx.Response) -> None:
    """Read at most :data:`_MAX_BODY_BYTES` of the response, then stop.

    Args:
        response: An open streaming response.
    """
    read = 0
    async for chunk in response.aiter_bytes():
        read += len(chunk)
        if read >= _MAX_BODY_BYTES:
            break


__all__ = [
    "ExecuteOutcome",
    "ExecuteStatus",
    "ExecutedVia",
    "UnsafeUnsubscribeURLError",
    "execute_unsubscribe",
    "validate_unsubscribe_url",
]
