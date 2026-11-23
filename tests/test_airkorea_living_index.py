"""AirKorea living-index (UV/대기정체) contracts; run with HA 2026.11+ and pytest installed."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant.helpers import llm

from custom_components.kr_public_data.airkorea import coordinator as coord_mod
from custom_components.kr_public_data.airkorea.coordinator import AirKoreaCoordinator
from custom_components.kr_public_data.airkorea.sensor import UVIndexSensor
from custom_components.kr_public_data.llm.airkorea_tool import GetAirQualityTool


def _fetch(stations, sido="서울"):
    c = object.__new__(AirKoreaCoordinator)
    c.data = None
    c._api_key = c._living_key = "k"
    c._stations = stations
    c._station_sido = {st["stationName"]: st.get("sido") or sido for st in stations}
    c._session = None
    uv = AsyncMock(side_effect=lambda _s, _k, area: {"h0": area[:2]})
    with patch.object(coord_mod, "fetch_realtime", AsyncMock(return_value={})), \
            patch.object(coord_mod, "fetch_forecast", AsyncMock(return_value=[{}])), \
            patch.object(coord_mod, "fetch_uv_index", uv), \
            patch.object(coord_mod, "fetch_air_stagnation", AsyncMock(return_value={})):
        return asyncio.run(c._fetch()), uv


def test_living_index_uses_each_stations_sido():
    data, uv = _fetch([{"sido": "서울", "stationName": "종로구"},
                       {"sido": "서울", "stationName": "중구"},
                       {"sido": "부산", "stationName": "광복동"}])
    # One call per 시도, not per station; 11…/26… are 서울/부산 area codes.
    assert uv.await_count == 2
    assert data["uv"] == {"종로구": {"h0": "11"}, "중구": {"h0": "11"}, "광복동": {"h0": "26"}}


def test_legacy_stations_fall_back_to_entry_sido():
    data, _ = _fetch([{"stationName": "광복동"}], sido="부산")
    assert data["uv"] == {"광복동": {"h0": "26"}}


def test_uv_sensor_reads_its_own_station():
    coordinator = SimpleNamespace(data={"uv": {"종로구": {"h0": "3"}, "광복동": {"h0": "8"}}})
    sensor = SimpleNamespace(coordinator=coordinator, _station="광복동")
    with patch("custom_components.kr_public_data.airkorea.sensor.datetime") as dt:
        dt.now.return_value = SimpleNamespace(hour=0)
        assert UVIndexSensor.native_value.fget(sensor) == 8


def test_tool_summarises_only_a_shared_uv_value():
    station = {"dataTime": "2026-11-23 22:00", "pm25Grade": "2"}
    data = {"stations": {"종로구": station, "광복동": station}, "forecast": [],
            "uv": {"종로구": {"h0": "3"}, "광복동": {"h0": "8"}}, "stagnation": {}}
    entry = SimpleNamespace(runtime_data={"coordinator": SimpleNamespace(data=data)})
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_entry=lambda _: entry))
    tool = GetAirQualityTool(hass, "test")

    def call(**args):
        return asyncio.run(tool.async_call(
            hass, llm.ToolInput(tool_name=tool.name, tool_args=args), None)).data

    both = call()
    assert both["uv_index"] is None
    assert {s["station"]: s["uv_index"] for s in both["stations"]} == {"종로구": "3", "광복동": "8"}
    assert call(station_name="광복동")["uv_index"] == "8"
