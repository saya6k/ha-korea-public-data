"""Opinet client contracts; run with HA 2026.11+ and pytest installed."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from custom_components.kr_public_data.fuel.api import fetch_low_price


def test_low_price_filters_by_area():
    response = MagicMock(status=200)

    async def text():
        return "<RESULT></RESULT>"
    response.text = text
    session = MagicMock()
    session.get.return_value.__aenter__.return_value = response

    asyncio.run(fetch_low_price(session, "k", "01", "B027"))
    params = session.get.call_args.kwargs["params"]
    # Opinet ignores `sido` and returns the nationwide ranking.
    assert params["area"] == "01"
    assert "sido" not in params
