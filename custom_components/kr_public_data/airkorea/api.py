"""AirKorea API client - V5 for living index."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from custom_components.kr_public_data.exceptions import (
    KrTransientError,
    raise_for_gateway_error,
    raise_for_result_code,
)
from custom_components.kr_public_data.utils import KST

from . import FORECAST_URL, REALTIME_URL, STATION_URL, group_stations

_LOGGER = logging.getLogger(__name__)


async def fetch_stations_by_sido(
    session: aiohttp.ClientSession, api_key: str
) -> dict[str, list[str]]:
    """전국 측정소 목록(측정소정보 API) → {시도 축약명: 측정소명 목록}.

    addr 파라미터는 부분 문자열 검색이라('광주'가 경기 광주시까지 잡음) 전체를
    한 번에 받아 주소로 분류한다. 이 API는 대기오염정보와 별도 활용신청이
    필요하므로, 실패하면 예외를 던져 호출자가 STATIONS_BY_SIDO로 폴백하게 한다.
    """
    params = {"serviceKey": api_key, "returnType": "json",
              "numOfRows": "1000", "pageNo": "1"}
    async with session.get(STATION_URL, params=params,
                           timeout=aiohttp.ClientTimeout(total=15)) as r:
        text = await r.text()
        raise_for_gateway_error(text)
        if r.status != 200:
            raise KrTransientError(f"AirKorea station list HTTP {r.status}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise KrTransientError(f"AirKorea station list: not JSON: {text[:120]}") from err
    header = data.get("response", {}).get("header", {})
    rc = header.get("resultCode")
    if rc != "00":
        raise_for_result_code(rc, header.get("resultMsg", ""))
        raise KrTransientError(
            f"AirKorea station list resultCode {rc}: {header.get('resultMsg', '')}")
    items = data.get("response", {}).get("body", {}).get("items", [])
    if isinstance(items, dict):
        items = [items]
    grouped = group_stations(items)
    if not grouped:
        raise KrTransientError("AirKorea station list: no stations")
    return grouped


async def fetch_realtime(
    session: aiohttp.ClientSession, api_key: str, station_name: str
) -> dict[str, Any]:
    params = {"serviceKey": api_key, "returnType": "json", "numOfRows": "1",
              "pageNo": "1", "stationName": station_name, "dataTerm": "DAILY",
              "ver": "1.5"}
    async with session.get(REALTIME_URL, params=params,
                           timeout=aiohttp.ClientTimeout(total=15)) as r:
        text = await r.text()
        raise_for_gateway_error(text)
        if r.status != 200:
            raise KrTransientError(f"AirKorea realtime HTTP {r.status}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise KrTransientError(f"AirKorea realtime: not JSON: {text[:120]}") from err
    header = data.get("response", {}).get("header", {})
    rc = header.get("resultCode")
    if rc == "03":  # NO_DATA
        return {}
    if rc != "00":
        raise_for_result_code(rc, header.get("resultMsg", ""))
        raise KrTransientError(
            f"AirKorea realtime resultCode {rc}: {header.get('resultMsg', '')}")
    items = data.get("response", {}).get("body", {}).get("items", [])
    if isinstance(items, dict):
        items = [items]
    return items[0] if items else {}


async def fetch_forecast(session: aiohttp.ClientSession, api_key: str) -> list[dict]:
    params = {"serviceKey": api_key, "returnType": "json", "numOfRows": "10",
              "pageNo": "1", "searchDate": datetime.now(KST).strftime("%Y-%m-%d")}
    async with session.get(FORECAST_URL, params=params,
                           timeout=aiohttp.ClientTimeout(total=15)) as r:
        text = await r.text()
        raise_for_gateway_error(text)
        if r.status != 200:
            raise KrTransientError(f"AirKorea forecast HTTP {r.status}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise KrTransientError(f"AirKorea forecast: not JSON: {text[:120]}") from err
    header = data.get("response", {}).get("header", {})
    rc = header.get("resultCode")
    if rc == "03":  # NO_DATA
        return []
    if rc != "00":
        raise_for_result_code(rc, header.get("resultMsg", ""))
        raise KrTransientError(
            f"AirKorea forecast resultCode {rc}: {header.get('resultMsg', '')}")
    items = data.get("response", {}).get("body", {}).get("items", [])
    if isinstance(items, dict):
        items = [items]
    return items


async def _fetch_living_v4(
    session: aiohttp.ClientSession, api_key: str, url: str, area_no: str
) -> dict[str, Any]:
    """Fetch V5 living index. time = YYYYMMDDHH, issued at 06/18 KST."""
    now = datetime.now(KST)
    # Try current issue time, then previous
    base_h = 18 if now.hour >= 18 else 6
    attempts = [
        now.strftime("%Y%m%d") + f"{base_h:02d}",
    ]
    if base_h == 6:
        attempts.append((now - timedelta(days=1)).strftime("%Y%m%d") + "18")
    else:
        attempts.append(now.strftime("%Y%m%d") + "06")

    for time_str in attempts:
        params = {"serviceKey": api_key, "dataType": "JSON",
                  "areaNo": area_no, "time": time_str,
                  "numOfRows": "10", "pageNo": "1"}
        try:
            async with session.get(url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    _LOGGER.debug("Living V5 HTTP %s for time=%s", r.status, time_str)
                    continue
                text = await r.text()
            data = json.loads(text)
            header = data.get("response", {}).get("header", {})
            rc = header.get("resultCode", "")
            if rc == "00":
                items = data.get("response", {}).get("body", {}).get("items", {})
                if isinstance(items, dict):
                    items = items.get("item", [])
                if isinstance(items, dict):
                    items = [items]
                if isinstance(items, list) and items:
                    _LOGGER.debug("Living V5 OK: time=%s keys=%s", time_str,
                                  [k for k in items[0] if items[0].get(k)])
                    return items[0]
            else:
                _LOGGER.debug("Living V5 error: time=%s code=%s msg=%s",
                              time_str, rc, header.get("resultMsg", ""))
        except Exception as e:
            _LOGGER.debug("Living V5 exception: %s", e)
    return {}


async def fetch_uv_index(
    session: aiohttp.ClientSession, api_key: str, area_code: str
) -> dict[str, Any]:
    from . import UV_IDX_URL
    return await _fetch_living_v4(session, api_key, UV_IDX_URL, area_code)


async def fetch_air_stagnation(
    session: aiohttp.ClientSession, api_key: str, area_code: str
) -> dict[str, Any]:
    from . import AIR_STAG_URL
    return await _fetch_living_v4(session, api_key, AIR_STAG_URL, area_code)
