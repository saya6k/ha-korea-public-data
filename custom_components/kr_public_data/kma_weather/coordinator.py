"""KMA Weather coordinator - fetches forecast + O3 + UV in sync."""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.kr_public_data.exceptions import KrTransientError
from custom_components.kr_public_data.resilience import ResilientCoordinator
from custom_components.kr_public_data.utils import KST

from . import KMA_SCAN_INTERVAL, region_key
from .api import fetch_vilage_forecast, parse_weather

_LOGGER = logging.getLogger(__name__)

# Small randomized delay between sequential 공공데이터포털 calls in one _fetch()
# cycle, so back-to-back requests (forecast/O3/UV, or multiple regions) don't
# bunch up against the gateway's per-second rate limit.
_REQUEST_JITTER = (0.2, 0.5)


def _uv_offset(uv: dict[str, Any], now: datetime) -> int:
    """3-hour field offset (h0, h3, …) matching ``now``.

    The living-index fields count hours from the bulletin's issue time
    (``date``, YYYYMMDDHH KST — 06 or 18), not from midnight.
    """
    try:
        issued = datetime.strptime(str(uv.get("date", "")), "%Y%m%d%H").replace(tzinfo=KST)
    except ValueError:
        return 0
    hours = int((now - issued).total_seconds() // 3600)
    return max(hours // 3 * 3, 0)


class KMAWeatherCoordinator(ResilientCoordinator):
    stale_tolerance = 4

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry,
                 api_key: str, regions: list[dict[str, Any]],
                 air_api_key: str = "", air_station: str = "",
                 living_api_key: str = "", area_no: str = "") -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name="kma_weather",
                         update_interval=timedelta(seconds=KMA_SCAN_INTERVAL))
        self._api_key = api_key
        self._regions = regions
        self._air_key = air_api_key or api_key
        self._air_station = air_station
        self._living_key = living_api_key or api_key
        self._area_no = area_no
        self._session = async_get_clientsession(hass)

    async def _fetch(self) -> dict[str, Any]:
        result = {}
        previous = self.data or {}
        region_failures = 0
        last_err: Exception | None = None
        session = self._session
        # 1. Fetch weather forecast per region
        for i, reg in enumerate(self._regions):
            if i:
                await asyncio.sleep(random.uniform(*_REQUEST_JITTER))
            name = region_key(reg)
            try:
                items = await fetch_vilage_forecast(
                    session, self._api_key, reg["nx"], reg["ny"])
                result[name] = parse_weather(items)
            except Exception as e:
                region_failures += 1
                last_err = e
                _LOGGER.warning("KMA weather %s: %s", name, e)
                # Keep the previous forecast for this region instead of
                # blanking the weather entity.
                result[name] = previous.get(name, {})

        if self._regions and region_failures == len(self._regions):
            raise KrTransientError(f"KMA: all region forecasts failed: {last_err}")

        # 2. Fetch O3 from AirKorea (same session, same update cycle)
        if self._air_station:
            await asyncio.sleep(random.uniform(*_REQUEST_JITTER))
            try:
                from custom_components.kr_public_data.airkorea.api import fetch_realtime
                air = await fetch_realtime(session, self._air_key, self._air_station)
                if air:
                    o3 = air.get("o3Value")
                    if o3 and o3 != "-":
                        for region in result.values():
                            region["ozone"] = float(o3)
            except Exception as e:
                _LOGGER.debug("KMA O3 fetch: %s", e)

        # 3. Fetch UV index from Living Weather V5 (same session)
        if self._area_no:
            await asyncio.sleep(random.uniform(*_REQUEST_JITTER))
            try:
                from custom_components.kr_public_data.airkorea.api import fetch_uv_index
                uv = await fetch_uv_index(session, self._living_key, self._area_no)
                if uv:
                    h = _uv_offset(uv, datetime.now(KST))
                    for field in [f"h{h}", "h0"]:
                        val = uv.get(field)
                        if val and str(val).strip():
                            try:
                                uv_val = float(val)
                                for region in result.values():
                                    region["uv_index"] = uv_val
                                break
                            except (ValueError, TypeError):
                                pass
            except Exception as e:
                _LOGGER.debug("KMA UV fetch: %s", e)

        return result
