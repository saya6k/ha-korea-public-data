"""AirKorea station-list contracts; run with HA 2026.11+ and pytest installed."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from custom_components.kr_public_data import config_flow
from custom_components.kr_public_data.airkorea import (
    SIDO_AREA_CODE,
    STATIONS_BY_SIDO,
    group_stations,
    station_sido,
)
from custom_components.kr_public_data.exceptions import KrAuthError


def test_station_sido_normalizes_address_forms():
    assert station_sido("부산광역시 중구 광복로 1") == "부산"
    assert station_sido("부산 중구 광복로 1") == "부산"
    assert station_sido("경기도 광주시 경안동") == "경기"
    assert station_sido("강원특별자치도 춘천시") == "강원"
    assert station_sido("충청남도 공주시") == "충남"
    # 광주·전남 통합: 자치구는 옛 광주광역시, 시군은 전남.
    assert station_sido("전남광주통합특별시 북구 우산동") == "광주"
    assert station_sido("전남광주통합특별시 여수시 문수동") == "전남"
    assert station_sido("") == ""


def test_group_stations_buckets_by_sido_and_sorts():
    items = [
        {"stationName": "광복동", "addr": "부산광역시 중구"},
        {"stationName": "대연동", "addr": "부산 남구"},
        {"stationName": "경안동", "addr": "경기도 광주시"},
        {"stationName": "서석동", "addr": "전남광주통합특별시 동구"},
        {"stationName": "", "addr": "서울 중구"},
    ]
    assert group_stations(items) == {
        "부산": ["광복동", "대연동"], "광주": ["서석동"], "경기": ["경안동"]}


def test_builtin_table_is_unambiguous():
    # The realtime API looks stations up by name alone.
    names = [s for v in STATIONS_BY_SIDO.values() for s in v]
    assert len(names) == len(set(names))
    assert set(STATIONS_BY_SIDO) == set(SIDO_AREA_CODE)


def test_flow_uses_live_list_when_available():
    live = {"서울": ["종로구"]}
    with patch.object(config_flow, "async_get_clientsession"), patch(
            "custom_components.kr_public_data.airkorea.api.fetch_stations_by_sido",
            AsyncMock(return_value=live)):
        assert asyncio.run(config_flow._air_stations_by_sido(None, "k")) is live


def test_flow_falls_back_when_station_api_is_not_subscribed():
    with patch.object(config_flow, "async_get_clientsession"), patch(
            "custom_components.kr_public_data.airkorea.api.fetch_stations_by_sido",
            AsyncMock(side_effect=KrAuthError("SERVICE_KEY_IS_NOT_REGISTERED_ERROR"))):
        assert asyncio.run(config_flow._air_stations_by_sido(None, "k")) is STATIONS_BY_SIDO
