"""LLM result contracts; run with HA 2026.10+ and pytest installed."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from homeassistant.helpers import llm

from custom_components.kr_public_data.const import DOMAIN
from custom_components.kr_public_data.llm.kma_weather_tool import GetKMAWeatherForecastTool
from custom_components.kr_public_data.llm.safety_alert_tool import GetSafetyAlertsTool
from custom_components.kr_public_data.llm.tools import TOOLS_BY_ETYPE
from custom_components.kr_public_data.llm.transit_tool import GetSubwayArrivalsTool


def _hass(store):
    """Minimal hass whose only config entry carries `store` as runtime_data."""
    entry = None if store is None else SimpleNamespace(runtime_data=store)
    return SimpleNamespace(
        config_entries=SimpleNamespace(async_get_entry=lambda _entry_id: entry))


def test_all_tools_report_missing_data_as_errors():
    hass = _hass(None)
    for factories in TOOLS_BY_ETYPE.values():
        for factory in factories:
            tool = factory(hass, "test")
            result = asyncio.run(
                tool.async_call(
                    hass, llm.ToolInput(tool_name=tool.name, tool_args={"range": "week"}), None
                )
            )
            assert isinstance(result, llm.ToolResult), tool.name
            assert result.error, tool.name
            assert result.data["error"], tool.name
            assert tool.name.startswith(f"{DOMAIN}__"), tool.name
            assert tool.integration == DOMAIN
            assert tool.title
            assert tool.annotations == llm.ToolAnnotations(
                read_only=True, destructive=False, idempotent=True, open_world=False
            )


def test_empty_alerts_are_success_with_featured_image():
    store = {
        "coordinators": {"seoul": SimpleNamespace(data={"alerts": []})},
        "regions": [{"code": "seoul", "name": "Seoul"}],
    }
    hass = _hass(store)
    tool = GetSafetyAlertsTool(hass, "test")
    result = asyncio.run(
        tool.async_call(hass, llm.ToolInput(tool_name=tool.name, tool_args={}), None)
    )
    assert not result.error
    assert result.data["total_active"] == 0
    assert result.data["results"] == []
    assert result.data["featured_image"].startswith("data:image/svg+xml;base64,")


def test_weather_preserves_native_card_payload():
    store = {
        "coordinator": SimpleNamespace(
            data={
                "Seoul": {
                    "daily_forecasts": [{"datetime": "2026-09-29", "temperature": 20}],
                    "temperature": 21,
                }
            }
        )
    }
    hass = _hass(store)
    tool = GetKMAWeatherForecastTool(hass, "test")
    result = asyncio.run(
        tool.async_call(hass, llm.ToolInput(tool_name=tool.name, tool_args={"range": "week"}), None)
    )
    assert isinstance(result, llm.ToolResult)
    assert not result.error
    assert result.data["source"] == "kma"
    assert result.data["forecast"]
    assert result.data["current_temperature"] == "21°C"


def _two_region_weather():
    data = {name: {"daily_forecasts": [{"datetime": "2026-09-29", "temperature": t}],
                   "temperature": t}
            for name, t in (("서울특별시 종로구", 1), ("부산광역시 해운대구", 9))}
    hass = _hass({"coordinator": SimpleNamespace(data=data)})
    tool = GetKMAWeatherForecastTool(hass, "test")

    def call(**args):
        return asyncio.run(tool.async_call(
            hass, llm.ToolInput(tool_name=tool.name, tool_args={"range": "week", **args}), None))
    return call


def test_weather_resolves_region_by_partial_name():
    call = _two_region_weather()
    assert call(region_name="해운대구").data["region"] == "부산광역시 해운대구"
    assert call(region_name="부산 해운대구").data["region"] == "부산광역시 해운대구"
    assert call(region_name="서울특별시 종로구").data["region"] == "서울특별시 종로구"


def test_weather_rejects_unconfigured_region():
    result = _two_region_weather()(region_name="대구 수성구")
    assert result.error
    assert "서울특별시 종로구" in result.data["error"]
    assert "부산광역시 해운대구" in result.data["error"]


def test_weather_asks_which_region_when_ambiguous():
    result = _two_region_weather()()
    assert result.error
    assert "부산광역시 해운대구" in result.data["error"]


def _subway(*stations):
    coords = {s: SimpleNamespace(data={"상행_1002": []}) for s in stations}
    hass = _hass({"subway_coords": coords})
    tool = GetSubwayArrivalsTool(hass, "test")

    def call(**args):
        return asyncio.run(tool.async_call(
            hass, llm.ToolInput(tool_name=tool.name, tool_args=args), None))
    return call


def test_subway_single_station_needs_no_name():
    assert _subway("강남")().data["station"] == "강남"


def test_subway_matches_name_with_station_suffix():
    assert _subway("강남", "역삼")(station="역삼역").data["station"] == "역삼"


def test_subway_asks_which_station_when_ambiguous():
    result = _subway("강남", "역삼")()
    assert result.error
    assert "역삼" in result.data["error"]


def test_subway_lists_stations_for_unknown_name():
    result = _subway("강남", "역삼")(station="잠실")
    assert result.error
    assert "강남" in result.data["error"]
