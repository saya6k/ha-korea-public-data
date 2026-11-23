"""KMA weather coordinator contracts; run with HA 2026.11+ and pytest installed."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import aiohttp

from custom_components.kr_public_data.airkorea import api as air_api
from custom_components.kr_public_data.kma_weather import coordinator as kma

_REGION = {"sido": "서울특별시", "name": "종로구", "nx": 60, "ny": 127}
_KEY = "서울특별시 종로구"
_OTHER = {"sido": "부산광역시", "name": "해운대구", "nx": 99, "ny": 75}


def _fetch(previous, forecast_ok=True, aux_ok=False):
    """forecast_ok=False fails 종로구 only (a second, healthy region keeps
    the cycle from counting as a total failure)."""
    c = object.__new__(kma.KMAWeatherCoordinator)
    c.data = previous
    c._regions = [_REGION] if forecast_ok else [_REGION, _OTHER]
    c._api_key = c._air_key = c._living_key = "k"
    c._air_station = "종로구"
    c._area_no = "1100000000"
    c._session = None
    aux = (AsyncMock(return_value={"o3Value": "0.05"}) if aux_ok
           else AsyncMock(side_effect=aiohttp.ClientError("down")))
    uv = (AsyncMock(return_value={"date": "2026112306", "h0": "4"}) if aux_ok
          else AsyncMock(side_effect=aiohttp.ClientError("down")))
    forecast = (AsyncMock(return_value=[]) if forecast_ok
                else AsyncMock(side_effect=[aiohttp.ClientError("down"), []]))
    with patch.object(kma, "fetch_vilage_forecast", forecast), \
            patch.object(kma, "parse_weather", return_value={"temperature": 3}), \
            patch.object(air_api, "fetch_realtime", aux), \
            patch.object(air_api, "fetch_uv_index", uv), \
            patch.object(kma.asyncio, "sleep", AsyncMock()):
        return asyncio.run(c._fetch())


def test_failed_aux_fetch_keeps_previous_ozone_and_uv():
    previous = {_KEY: {"temperature": 1, "ozone": 0.03, "uv_index": 5.0}}
    data = _fetch(previous)
    assert data[_KEY] == {"temperature": 3, "ozone": 0.03, "uv_index": 5.0}


def test_successful_aux_fetch_replaces_values():
    data = _fetch({_KEY: {"ozone": 0.03, "uv_index": 5.0}}, aux_ok=True)
    assert data[_KEY]["ozone"] == 0.05
    assert data[_KEY]["uv_index"] == 4.0


def test_failed_region_does_not_mutate_previous_data():
    previous = {_KEY: {"temperature": 1}}
    data = _fetch(previous, aux_ok=True, forecast_ok=False)
    # Previous forecast is kept for the failed region…
    assert data[_KEY]["temperature"] == 1
    assert data[_KEY]["ozone"] == 0.05
    # …but the dict entities still hold isn't written to.
    assert previous == {_KEY: {"temperature": 1}}
