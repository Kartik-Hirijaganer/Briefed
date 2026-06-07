"""Unit tests for the SSRF-hardened unsubscribe executor (ADR 0014).

The validator is exercised directly across a sweep of unsafe targets; the
decision tree is exercised with ``respx`` using **public IP literals** so no
real DNS is involved on the happy path.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.services.unsubscribe.executor import (
    UnsafeUnsubscribeURLError,
    execute_unsubscribe,
    validate_unsubscribe_url,
)
from app.services.unsubscribe.parser import UnsubscribeAction

# A real, publicly routable address (example.com) — passes the SSRF guard
# without a DNS lookup because it is an IP literal.
_PUBLIC_URL = "https://93.184.216.34/unsub"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/u",  # IPv4 loopback
        "https://10.0.0.1/u",  # private 10/8
        "https://172.16.0.1/u",  # private 172.16/12
        "https://192.168.1.1/u",  # private 192.168/16
        "https://169.254.169.254/u",  # link-local + cloud metadata
        "https://100.64.0.1/u",  # CGNAT 100.64/10
        "http://0.0.0.0/u",  # unspecified
        "https://[::1]/u",  # IPv6 loopback
        "https://[fc00::1]/u",  # IPv6 unique-local (private)
        "https://[fe80::1]/u",  # IPv6 link-local
        "https://[::ffff:10.0.0.1]/u",  # IPv4-mapped private
        "ftp://example.com/u",  # disallowed scheme
        "data:text/plain,hello",  # data: scheme
        "file:///etc/passwd",  # file: scheme
        "https:///nohost",  # missing host
        "http://exámple.com/u",  # non-ASCII / IDN-suspicious
    ],
)
def test_validator_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(UnsafeUnsubscribeURLError):
        validate_unsubscribe_url(url)


def test_validator_rejects_localhost_hostname() -> None:
    # "localhost" resolves to a loopback address via DNS.
    with pytest.raises(UnsafeUnsubscribeURLError):
        validate_unsubscribe_url("http://localhost/u")


def test_validator_rejects_unresolvable_host() -> None:
    with pytest.raises(UnsafeUnsubscribeURLError):
        validate_unsubscribe_url("http://does-not-exist.invalid/u")


def test_validator_allows_public_ip_literal() -> None:
    # Should not raise.
    validate_unsubscribe_url(_PUBLIC_URL)


@respx.mock
async def test_one_click_https_2xx_unsubscribed() -> None:
    route = respx.post(_PUBLIC_URL).mock(return_value=httpx.Response(200))
    action = UnsubscribeAction(http_urls=(_PUBLIC_URL,), one_click=True)
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
        outcome = await execute_unsubscribe(action, http_client=client, timeout=5.0)
    assert route.called
    assert outcome.status == "unsubscribed"
    assert outcome.executed_via == "one_click"
    assert outcome.manual_url is None


@respx.mock
@pytest.mark.parametrize("status_code", [403, 404, 500, 503])
async def test_one_click_non_2xx_failed(status_code: int) -> None:
    respx.post(_PUBLIC_URL).mock(return_value=httpx.Response(status_code))
    action = UnsubscribeAction(http_urls=(_PUBLIC_URL,), one_click=True)
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
        outcome = await execute_unsubscribe(action, http_client=client, timeout=5.0)
    assert outcome.status == "failed"
    assert outcome.executed_via == "none"


@respx.mock
async def test_non_one_click_url_is_manual_required() -> None:
    action = UnsubscribeAction(http_urls=(_PUBLIC_URL,), one_click=False)
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
        outcome = await execute_unsubscribe(action, http_client=client, timeout=5.0)
    assert outcome.status == "manual_required"
    assert outcome.manual_url == _PUBLIC_URL
    # No HTTP request is made for the manual path.
    assert respx.calls.call_count == 0


@respx.mock
async def test_http_only_one_click_is_manual_required() -> None:
    # one_click advertised but only an http:// URL → not eligible for the
    # automated POST; surface it for the user instead.
    http_url = "http://93.184.216.34/unsub"
    action = UnsubscribeAction(http_urls=(http_url,), one_click=True)
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
        outcome = await execute_unsubscribe(action, http_client=client, timeout=5.0)
    assert outcome.status == "manual_required"
    assert outcome.manual_url == http_url
    assert respx.calls.call_count == 0


@respx.mock
async def test_mailto_only_is_manual_required() -> None:
    action = UnsubscribeAction(mailto="mailto:unsub@sender.example", one_click=True)
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
        outcome = await execute_unsubscribe(action, http_client=client, timeout=5.0)
    assert outcome.status == "manual_required"
    assert outcome.manual_url == "mailto:unsub@sender.example"
    assert respx.calls.call_count == 0


@respx.mock
async def test_one_click_to_private_address_is_blocked() -> None:
    private_url = "https://10.0.0.5/unsub"
    route = respx.post(private_url).mock(return_value=httpx.Response(200))
    action = UnsubscribeAction(http_urls=(private_url,), one_click=True)
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
        outcome = await execute_unsubscribe(action, http_client=client, timeout=5.0)
    assert outcome.status == "failed"
    assert outcome.error == "ssrf_blocked"
    # The request is never sent.
    assert not route.called


@respx.mock
async def test_redirect_to_private_is_not_followed() -> None:
    respx.post(_PUBLIC_URL).mock(
        return_value=httpx.Response(302, headers={"Location": "http://10.0.0.1/evil"}),
    )
    action = UnsubscribeAction(http_urls=(_PUBLIC_URL,), one_click=True)
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
        outcome = await execute_unsubscribe(action, http_client=client, timeout=5.0)
    # A 3xx is not a 2xx and is never followed → failed, no second request.
    assert outcome.status == "failed"
    assert respx.calls.call_count == 1


@respx.mock
async def test_oversized_body_is_bounded_and_still_succeeds() -> None:
    respx.post(_PUBLIC_URL).mock(return_value=httpx.Response(200, content=b"x" * 200_000))
    action = UnsubscribeAction(http_urls=(_PUBLIC_URL,), one_click=True)
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
        outcome = await execute_unsubscribe(action, http_client=client, timeout=5.0)
    assert outcome.status == "unsubscribed"


@respx.mock
async def test_no_actionable_target_fails() -> None:
    action = UnsubscribeAction()
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
        outcome = await execute_unsubscribe(action, http_client=client, timeout=5.0)
    assert outcome.status == "failed"
    assert outcome.error == "no_actionable_target"
