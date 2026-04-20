"""Integration test for the API Lambda handler (plan §14 Phase 0).

Exercises :data:`app.lambda_api.mangum_handler` with a Lambda Function
URL event and asserts that ``/health`` returns a 200 response body. This
matches the plan's Phase 0 exit-criteria case:

    integration — Lambda invoke returns `/health` 200 under SnapStart.

SnapStart itself is an AWS-runtime capability — we cannot reproduce the
restore cycle locally, but this test confirms that the handler is
SnapStart-safe because (a) all init happens at module import time,
(b) :func:`~app.lambda_api.mangum_handler` is a plain callable with no
per-invocation async loop setup.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app import __version__
from app.lambda_api import mangum_handler


@pytest.fixture(scope="module")
def function_url_health_event() -> dict[str, Any]:
    """Return a minimal Lambda Function URL (v2) event hitting ``GET /health``.

    Shape lifted directly from the AWS docs
    (``payloadFormatVersion: 2.0``); only the fields Mangum reads are
    populated so the test is not coupled to future AWS additions.
    """
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": "/health",
        "rawQueryString": "",
        "headers": {
            "accept": "application/json",
            "host": "xxxxxx.lambda-url.us-east-1.on.aws",
        },
        "requestContext": {
            "accountId": "anonymous",
            "apiId": "xxxxxx",
            "domainName": "xxxxxx.lambda-url.us-east-1.on.aws",
            "domainPrefix": "xxxxxx",
            "http": {
                "method": "GET",
                "path": "/health",
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "pytest",
            },
            "requestId": "test-request-id",
            "routeKey": "$default",
            "stage": "$default",
            "time": "01/Jan/2026:00:00:00 +0000",
            "timeEpoch": 1_735_689_600_000,
        },
        "isBase64Encoded": False,
    }


def test_lambda_api_health_returns_200(
    function_url_health_event: dict[str, Any],
) -> None:
    """Mangum-wrapped FastAPI app returns 200 ``{status: ok}`` for ``/health``.

    This is the Phase 0 integration exit-criteria test.
    """
    response = mangum_handler(function_url_health_event, None)

    assert response["statusCode"] == 200, response
    body = json.loads(response["body"])
    assert body["status"] == "ok"
    assert body["version"] == __version__
