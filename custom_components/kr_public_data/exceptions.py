"""Shared exception hierarchy for API error classification.

Coordinators (see resilience.py) map these onto HA behavior:
KrAuthError → reauth flow, KrQuotaError → poll pause until midnight KST,
KrTransientError / anything else → stale-keep with tolerance.
"""
from __future__ import annotations

import re


class KrApiError(Exception):
    """Base error for all kr_public_data API failures."""


class KrAuthError(KrApiError):
    """Credentials or service key rejected — needs user action."""


class KrQuotaError(KrApiError):
    """Daily request quota exceeded — resets at midnight KST."""


class KrTransientError(KrApiError):
    """Intermittent failure (TLS reset, timeout, 5xx, bad payload)."""


# The data.go.kr gateway answers key/quota problems itself, before the
# service sees the request, with an ``OpenAPI_ServiceResponse`` envelope
# (HTTP 401/403/429, same shape in JSON and XML) instead of the service's own
# ``response.header``. Verified live 2026-11-17: an unregistered key returns
# HTTP 403 + returnReasonCode 30.
_GATEWAY_CODE = re.compile(r'returnReasonCode"?\s*[:>]\s*"?(\d+)')
_GATEWAY_MSG = re.compile(r'returnAuthMsg"?\s*[:>]\s*"?([^"<]*)')


def raise_for_gateway_error(text: str) -> None:
    """Raise KrAuthError/KrQuotaError for a data.go.kr gateway envelope.

    Call it on the raw body before any HTTP-status check, so a rejected key
    reaches the reauth flow instead of being retried as a transient error.
    """
    if "OpenAPI_ServiceResponse" not in text:
        return
    code = _GATEWAY_CODE.search(text)
    msg = _GATEWAY_MSG.search(text)
    raise_for_result_code(code.group(1) if code else None, msg.group(1) if msg else "")


def raise_for_result_code(code: str | None, msg: str = "") -> None:
    """Map 공공데이터포털 standard result codes to typed errors.

    22 = LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS (daily quota),
    30/31/32 = service key unregistered / expired / wrong domain.
    Anything else (including 00/03) is left to the caller.
    """
    if code == "22":
        raise KrQuotaError(f"daily quota exceeded: {msg}")
    if code in ("30", "31", "32"):
        raise KrAuthError(f"service key rejected (code {code}): {msg}")
